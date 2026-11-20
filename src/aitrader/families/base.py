"""Strategy family definitions.

A *family* is a parameterised signal generator. Entry, exit, stop-loss, take-profit,
trailing, time-exit and position-sizing parameters are optimised **together** as one
parameter vector, so risk management is part of every strategy rather than bolted on.

The same family code is used by:
  * the hyperoptable research strategies (ft/strategies/Fam*.py), and
  * the live multi-sleeve host strategy (ft/strategies/AIPortfolio.py),
so what is validated is exactly what trades.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from aitrader import indicators as ta


@dataclass(frozen=True)
class Param:
    name: str
    kind: str  # "int" | "float"
    low: float
    high: float
    default: float
    space: str  # "buy" (entry) or "sell" (exit/risk)
    decimals: int = 2

    def clip(self, v: float) -> float:
        v = min(max(float(v), self.low), self.high)
        return int(round(v)) if self.kind == "int" else round(v, self.decimals)


# Exit + risk parameters shared by every family (all optimised jointly with entries).
EXIT_PARAMS: tuple[Param, ...] = (
    Param("sl_atr", "float", 1.0, 4.0, 2.0, "sell", 1),  # initial stop distance in ATRs
    Param("tp_rr", "float", 1.0, 5.0, 2.0, "sell", 1),  # take profit in multiples of stop
    Param("trail_rr", "float", 0.5, 3.0, 1.5, "sell", 1),  # start trailing at this R
    Param("trail_atr", "float", 1.0, 4.0, 2.5, "sell", 1),  # trailing distance in ATRs
    Param("max_hold", "int", 12, 168, 72, "sell"),  # time exit (bars)
    Param("conv_w", "float", 0.0, 1.0, 0.5, "sell", 2),  # sizing: weight on signal conviction
)

ATR_LEN = 14

SignalFn = Callable[[pd.DataFrame, dict], pd.DataFrame]


@dataclass(frozen=True)
class Family:
    name: str
    title: str
    description: str
    entry_params: tuple[Param, ...]
    signal_fn: SignalFn
    affinity: str = "trend"  # which market-scan score suits this family: trend | revert
    params: tuple[Param, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", tuple(self.entry_params) + EXIT_PARAMS)

    # ------------------------------------------------------------------
    def defaults(self) -> dict[str, float]:
        return {p.name: p.clip(p.default) for p in self.params}

    def normalize(self, params: dict | None) -> dict[str, float]:
        """Fill missing values with defaults and clip to the valid range."""
        out = self.defaults()
        for p in self.params:
            if params and p.name in params and params[p.name] is not None:
                out[p.name] = p.clip(params[p.name])
        return out

    def space(self, overrides: dict | None = None) -> dict[str, tuple[float, float]]:
        """Search space, optionally narrowed/shifted by learnings (clipped to hard bounds)."""
        out = {}
        for p in self.params:
            lo, hi = p.low, p.high
            if overrides and p.name in overrides:
                olo, ohi = overrides[p.name]
                lo, hi = max(p.low, float(olo)), min(p.high, float(ohi))
                if hi <= lo:
                    lo, hi = p.low, p.high
            out[p.name] = (lo, hi)
        return out

    def perturb(self, params: dict, rel: float, rng: random.Random) -> dict[str, float]:
        """Random neighbour: each param moved by up to ±rel of its range."""
        out = {}
        for p in self.params:
            span = (p.high - p.low) * rel
            out[p.name] = p.clip(params.get(p.name, p.default) + rng.uniform(-span, span))
        return out

    def populate(self, df: pd.DataFrame, params: dict) -> pd.DataFrame:
        """Add indicator + signal columns. Always produces:
        atr, long_sig, short_sig, exit_long_sig, exit_short_sig, conviction (0.5..1.5)."""
        p = self.normalize(params)
        df = df.copy()
        df["atr"] = ta.atr(df, ATR_LEN)
        sig = self.signal_fn(df, p)
        for col in ("long_sig", "short_sig", "exit_long_sig", "exit_short_sig"):
            s = sig[col] if col in sig else pd.Series(False, index=df.index)
            df[col] = s.fillna(False).astype(bool)
        conv = sig["conviction"] if "conviction" in sig else pd.Series(1.0, index=df.index)
        df["conviction"] = conv.fillna(1.0).clip(0.5, 1.5)
        # never signal while ATR is undefined (warm-up)
        warm = df["atr"].isna() | (df["atr"] <= 0)
        df.loc[warm, ["long_sig", "short_sig"]] = False
        return df
