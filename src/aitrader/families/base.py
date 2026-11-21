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
    Param("max_hold", "int", 12, 500, 72, "sell"),  # time exit (bars of the strategy's timeframe)
    Param("be_rr", "float", 0.3, 2.0, 1.0, "sell", 2),  # move stop to break-even at this R
    Param("lock_rr", "float", 0.5, 3.0, 1.5, "sell", 2),  # start the profit ratchet at this R
    Param("lock_frac", "float", 0.0, 0.8, 0.4, "sell", 2),  # share of best open profit that is locked
    # what a careful trader adds (all off by default; research decides whether they pay):
    Param("tp_near", "float", 0.0, 0.95, 0.0, "sell", 2),  # >0: once this share of the way to TP was reached …
    Param("tp_lock", "float", 0.5, 0.95, 0.75, "sell", 2),  # … lock this share of the best open profit
    Param("event_lock", "int", 0, 2, 0, "sell"),  # lock half the profit 2 h (1) / 8 h (2) before US CPI/jobs/Fed
    Param("vol_shock", "int", 0, 3, 0, "sell"),  # trail from the best price once ATR ≥ 1.6× / 2× / 2.5× the entry ATR
    # Strategy Lab exits, exactly as the owner's engine trades them (strategies found by the
    # screener/autopilot): ATR stop + optional R take profit + optional chandelier trail from
    # entry on the current ATR – no break-even, no ratchet. Never searched (pinned to 0).
    Param("exit_mode", "int", 0, 1, 0, "sell"),   # 0 = system exits, 1 = Strategy Lab exits
    Param("lab_tp", "float", 0.0, 10.0, 0.0, "sell", 2),    # take profit in R (0 = none)
    Param("lab_trail", "float", 0.0, 6.0, 0.0, "sell", 2),  # chandelier trail in current ATRs (0 = none)
    Param("conv_w", "float", 0.0, 1.0, 0.5, "sell", 2),  # sizing: weight on signal conviction
)

# Structural "genes" shared by all families: hyperopt switches them on/off, so research
# discovers new strategy variants (e.g. trend-filtered mean reversion, low-vol breakouts),
# not just new numbers for a fixed recipe.
GENE_PARAMS: tuple[Param, ...] = (
    Param("htf_trend", "int", 0, 1, 0, "buy"),  # 1 = trade only with the higher-timeframe trend
    Param("htf_len", "int", 100, 400, 200, "buy"),  # EMA length (1h bars) defining that trend
    Param("vol_regime", "int", 0, 2, 0, "buy"),  # 0 any, 1 only high-vol, 2 only low-vol regime
    # market context a human trader keeps in mind (aitrader.context); like the genes above
    # they only remove entries, and only research decides whether that helps
    Param("session", "int", 0, 4, 0, "buy"),      # 0 any, 1 Asia, 2 Europe, 3 US hours, 4 Europe or US
    Param("no_weekend", "int", 0, 1, 0, "buy"),   # 1 = no entries on Saturday/Sunday (UTC)
    Param("event_guard", "int", 0, 2, 0, "buy"),  # 1 = none ±2 h around US CPI/jobs/Fed, 2 = ±12 h
)
CONTEXT_GENES = ("session", "no_weekend", "event_guard")
EXIT_GENES = ("tp_near", "event_lock", "vol_shock")  # careful-trader exits, searched like the context genes
LAB_EXIT = ("exit_mode", "lab_tp", "lab_trail")      # Strategy Lab exits: only for imported configurations

ATR_LEN = 14
VOL_WINDOW = 500

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
        object.__setattr__(self, "params", tuple(self.entry_params) + GENE_PARAMS + EXIT_PARAMS)

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
                if hi < lo:  # lo == hi pins a parameter (e.g. a structural gene)
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

    @staticmethod
    def _apply_genes(df: pd.DataFrame, p: dict) -> None:
        if int(p.get("htf_trend", 0)) == 1:
            htf = ta.ema(df["close"], int(p.get("htf_len", 200)))
            up = (df["close"] > htf) & (htf > htf.shift(24))
            dn = (df["close"] < htf) & (htf < htf.shift(24))
            df["long_sig"] &= up.fillna(False)
            df["short_sig"] &= dn.fillna(False)
        regime = int(p.get("vol_regime", 0))
        if regime:
            atr_pct = df["atr"] / df["close"]
            med = atr_pct.rolling(VOL_WINDOW, min_periods=100).median()
            ok = (atr_pct > med) if regime == 1 else (atr_pct <= med)
            ok = ok.fillna(False)
            df["long_sig"] &= ok
            df["short_sig"] &= ok
        ctx = [int(p.get(k, 0)) for k in CONTEXT_GENES]
        if any(ctx):
            from aitrader.context import entry_filter
            ok = entry_filter(df, *ctx)
            if ok is not None:
                df["long_sig"] &= ok.to_numpy()
                df["short_sig"] &= ok.to_numpy()

    def variant(self, params: dict) -> str:
        """Human-readable strategy variant, e.g. 'donchian_breakout +HTF-trend(200) +low-vol'."""
        p = self.normalize(params)
        parts = [self.name]
        if int(p["htf_trend"]) == 1:
            parts.append(f"+HTF-trend({int(p['htf_len'])})")
        parts.append({0: "", 1: "+high-vol", 2: "+low-vol"}[int(p["vol_regime"])])
        parts.append({0: "", 1: "+Asia-hours", 2: "+Europe-hours", 3: "+US-hours", 4: "+EU/US-hours"}[int(p["session"])])
        parts.append("+no-weekend" if int(p["no_weekend"]) else "")
        parts.append({0: "", 1: "+event-guard", 2: "+event-day-guard"}[int(p["event_guard"])])
        return " ".join(x for x in parts if x)

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
        self._apply_genes(df, p)
        conv = sig["conviction"] if "conviction" in sig else pd.Series(1.0, index=df.index)
        df["conviction"] = conv.fillna(1.0).clip(0.5, 1.5)
        # never signal while ATR is undefined (warm-up)
        warm = df["atr"].isna() | (df["atr"] <= 0)
        df.loc[warm, ["long_sig", "short_sig"]] = False
        return df
