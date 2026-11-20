"""Registry of strategy families."""

from __future__ import annotations

import numpy as np
import pandas as pd

from aitrader import indicators as ta
from aitrader.families.base import EXIT_PARAMS, Family, Param


# --------------------------------------------------------------------------- trend
def _trend_ema(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    fast = ta.ema(df["close"], p["fast"])
    slow = ta.ema(df["close"], p["slow"])
    a = ta.adx(df, 14)["adx"]
    r = ta.rsi(df["close"], 14)
    up = (fast > slow) & (df["close"] > slow) & (a > p["adx_min"])
    dn = (fast < slow) & (df["close"] < slow) & (a > p["adx_min"])
    pb = p["pullback_rsi"]
    long_sig = up & (ta.crossed_above(fast, slow) | ta.crossed_above(r, pb))
    short_sig = dn & (ta.crossed_below(fast, slow) | ta.crossed_below(r, 100 - pb))
    return pd.DataFrame(
        {
            "long_sig": long_sig,
            "short_sig": short_sig,
            "exit_long_sig": ta.crossed_below(fast, slow),
            "exit_short_sig": ta.crossed_above(fast, slow),
            "conviction": a / (p["adx_min"] * 1.5),
        }
    )


TREND_EMA = Family(
    name="trend_ema",
    title="EMA trend + pullback",
    description="Trades EMA crossovers and RSI pullbacks in the direction of an ADX-confirmed trend.",
    entry_params=(
        Param("fast", "int", 8, 30, 20, "buy"),
        Param("slow", "int", 40, 150, 80, "buy"),
        Param("adx_min", "float", 15.0, 35.0, 22.0, "buy", 1),
        Param("pullback_rsi", "float", 35.0, 55.0, 45.0, "buy", 1),
    ),
    signal_fn=_trend_ema,
    affinity="trend",
)


# ------------------------------------------------------------------- mean reversion
def _meanrev_bb(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    bb = ta.bollinger(df["close"], int(p["bb_len"]), p["bb_k"])
    r = ta.rsi(df["close"], 14)
    a = ta.adx(df, 14)["adx"]
    calm = a < p["adx_max"]
    atr = ta.atr(df, 14)
    long_sig = (df["close"] < bb["bb_lower"]) & (r < p["rsi_low"]) & calm
    short_sig = (df["close"] > bb["bb_upper"]) & (r > 100 - p["rsi_low"]) & calm
    depth = ((bb["bb_lower"] - df["close"]).clip(lower=0) + (df["close"] - bb["bb_upper"]).clip(lower=0))
    return pd.DataFrame(
        {
            "long_sig": long_sig,
            "short_sig": short_sig,
            "exit_long_sig": df["close"] >= bb["bb_mid"],
            "exit_short_sig": df["close"] <= bb["bb_mid"],
            "conviction": 0.75 + depth / atr.replace(0, np.nan),
        }
    )


MEANREV_BB = Family(
    name="meanrev_bb",
    title="Bollinger mean reversion",
    description="Fades closes outside Bollinger bands with RSI extremes, only in low-ADX (ranging) regimes.",
    entry_params=(
        Param("bb_len", "int", 14, 40, 20, "buy"),
        Param("bb_k", "float", 1.5, 3.0, 2.2, "buy", 1),
        Param("rsi_low", "float", 15.0, 35.0, 28.0, "buy", 1),
        Param("adx_max", "float", 15.0, 35.0, 25.0, "buy", 1),
    ),
    signal_fn=_meanrev_bb,
    affinity="revert",
)


# ------------------------------------------------------------------------ breakout
def _donchian(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    dc = ta.donchian_prev(df, int(p["dc_len"]))
    ex = ta.donchian_prev(df, int(p["exit_len"]))
    vol_ratio = df["volume"] / ta.sma(df["volume"], 20).replace(0, np.nan)
    vol_ok = vol_ratio > p["vol_mult"]
    return pd.DataFrame(
        {
            "long_sig": (df["close"] > dc["dc_high"]) & vol_ok,
            "short_sig": (df["close"] < dc["dc_low"]) & vol_ok,
            "exit_long_sig": df["close"] < ex["dc_low"],
            "exit_short_sig": df["close"] > ex["dc_high"],
            "conviction": vol_ratio / (p["vol_mult"] * 1.5),
        }
    )


DONCHIAN = Family(
    name="donchian_breakout",
    title="Donchian volume breakout",
    description="Enters on closes beyond the N-bar channel with above-average volume; turtle-style channel exit.",
    entry_params=(
        Param("dc_len", "int", 20, 120, 48, "buy"),
        Param("exit_len", "int", 10, 60, 24, "buy"),
        Param("vol_mult", "float", 1.0, 2.5, 1.3, "buy", 1),
    ),
    signal_fn=_donchian,
    affinity="trend",
)


# ------------------------------------------------------------------ squeeze release
def _squeeze(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    bb = ta.bollinger(df["close"], 20, 2.0)
    kc = ta.keltner(df, 20, p["kc_mult"])
    squeeze_on = (bb["bb_upper"] < kc["kc_upper"]) & (bb["bb_lower"] > kc["kc_lower"])
    fired = squeeze_on.shift(1, fill_value=False) & ~squeeze_on
    recent = fired.rolling(int(p["window"]), min_periods=1).max().astype(bool)
    mom = df["close"] - ta.sma(df["close"], int(p["mom_len"]))
    trend = ta.ema(df["close"], int(p["trend_len"]))
    atr = ta.atr(df, 14)
    rising = mom > mom.shift(1)
    return pd.DataFrame(
        {
            "long_sig": recent & (mom > 0) & rising & (df["close"] > trend),
            "short_sig": recent & (mom < 0) & ~rising & (df["close"] < trend),
            "exit_long_sig": (mom < 0) & (mom.shift(1) >= 0),
            "exit_short_sig": (mom > 0) & (mom.shift(1) <= 0),
            "conviction": 0.5 + mom.abs() / atr.replace(0, np.nan),
        }
    )


SQUEEZE = Family(
    name="squeeze_momentum",
    title="Volatility squeeze release",
    description="Bollinger-inside-Keltner compression; trades the release in the momentum direction with a trend filter.",
    entry_params=(
        Param("kc_mult", "float", 1.0, 2.0, 1.5, "buy", 2),
        Param("window", "int", 1, 6, 3, "buy"),
        Param("mom_len", "int", 10, 40, 20, "buy"),
        Param("trend_len", "int", 50, 200, 100, "buy"),
    ),
    signal_fn=_squeeze,
    affinity="trend",
)


FAMILIES: dict[str, Family] = {f.name: f for f in (TREND_EMA, MEANREV_BB, DONCHIAN, SQUEEZE)}

# Freqtrade strategy class name used for hyperopting each family.
RESEARCH_CLASS: dict[str, str] = {
    "trend_ema": "FamTrendEma",
    "meanrev_bb": "FamMeanRevBB",
    "donchian_breakout": "FamDonchian",
    "squeeze_momentum": "FamSqueeze",
}


def get_family(name: str) -> Family:
    try:
        return FAMILIES[name]
    except KeyError as e:
        raise ValueError(f"unknown family {name!r}; known: {sorted(FAMILIES)}") from e


__all__ = ["EXIT_PARAMS", "FAMILIES", "RESEARCH_CLASS", "Family", "Param", "get_family"]
