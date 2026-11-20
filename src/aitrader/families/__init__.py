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


# ------------------------------------------------------- time-series momentum (TSMOM)
def _tsmom(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Classic time-series momentum (Moskowitz/Ooi/Pedersen), vol-normalised: the L-hour
    return measured in units of its own volatility. One of the best-documented effects in
    futures markets, including crypto perps."""
    L = int(p["lookback"])
    ret = np.log(df["close"]).diff()
    vol = ret.rolling(int(p["vol_len"]), min_periods=48).std()
    z = np.log(df["close"] / df["close"].shift(L)) / (vol * np.sqrt(L)).replace(0, np.nan)
    k, ex = p["z_entry"], p["z_exit"]
    fast = ta.ema(df["close"], int(p["confirm_len"]))
    up_x = ta.crossed_above(df["close"], fast)
    dn_x = ta.crossed_below(df["close"], fast)
    long_sig = ((z > k) & (z.shift(1) <= k)) | ((z > k) & up_x)
    short_sig = ((z < -k) & (z.shift(1) >= -k)) | ((z < -k) & dn_x)
    return pd.DataFrame(
        {
            "long_sig": long_sig,
            "short_sig": short_sig,
            "exit_long_sig": z < ex,
            "exit_short_sig": z > -ex,
            "conviction": 0.5 + z.abs() / (k + 1.0),
        }
    )


TSMOM = Family(
    name="tsmom",
    title="Time-series momentum (vol-scaled)",
    description="Trades the sign of the multi-day return measured in volatility units (3–21 day lookbacks), "
                "re-entering on short-term confirmation; exits when momentum fades.",
    entry_params=(
        Param("lookback", "int", 72, 504, 240, "buy"),
        Param("vol_len", "int", 72, 336, 168, "buy"),
        Param("z_entry", "float", 0.3, 2.0, 0.8, "buy", 2),
        Param("z_exit", "float", -0.5, 0.6, 0.0, "buy", 2),
        Param("confirm_len", "int", 6, 48, 20, "buy"),
    ),
    signal_fn=_tsmom,
    affinity="trend",
)


# -------------------------------------------------- funding-rate crowding (contrarian)
def _funding_reversal(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Perpetual funding as a crowding gauge: when funding is extreme versus its own
    history, the paying side is crowded. Fade it once price confirms (EMA cross).
    Needs a 'funding' column (merged by the strategy); without it there are no signals."""
    if "funding" not in df or df["funding"].isna().all():
        f = pd.Series(False, index=df.index)
        return pd.DataFrame({"long_sig": f, "short_sig": f, "exit_long_sig": f, "exit_short_sig": f,
                             "conviction": pd.Series(1.0, index=df.index)})
    fr = df["funding"].astype(float).ffill()
    w = int(p["fund_window"])
    z = (fr - fr.rolling(w, min_periods=w // 3).mean()) / fr.rolling(w, min_periods=w // 3).std().replace(0, np.nan)
    k = p["fund_z"]
    fast = ta.ema(df["close"], int(p["confirm_len"]))
    crowd_long, crowd_short = z > k, z < -k
    hot = crowd_long.rolling(int(p["memory"]), min_periods=1).max().astype(bool)
    cold = crowd_short.rolling(int(p["memory"]), min_periods=1).max().astype(bool)
    return pd.DataFrame(
        {
            "long_sig": cold & ta.crossed_above(df["close"], fast),
            "short_sig": hot & ta.crossed_below(df["close"], fast),
            "exit_long_sig": z > k / 2,
            "exit_short_sig": z < -k / 2,
            "conviction": 0.5 + z.abs() / (k + 1.0),
        }
    )


FUNDING = Family(
    name="funding_reversal",
    title="Funding-rate crowding reversal",
    description="Fades extreme perpetual funding (crowded longs/shorts) after an EMA price confirmation.",
    entry_params=(
        Param("fund_window", "int", 168, 1440, 720, "buy"),
        Param("fund_z", "float", 1.0, 3.0, 1.8, "buy", 2),
        Param("memory", "int", 4, 48, 16, "buy"),
        Param("confirm_len", "int", 6, 48, 20, "buy"),
    ),
    signal_fn=_funding_reversal,
    affinity="revert",
)


# ------------------------------------------------- z-score reversion (statistical stretch)
def _zscore_revert(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Distance of price from its N-bar mean in standard deviations. Buys a stretch below
    -k sigma, sells above +k sigma, exits once price has reverted to -/+ exit sigma.
    (Owner's Strategy Lab idea, now searched across the whole universe and timeframes.)"""
    n = int(p["window"])
    mean = df["close"].rolling(n, min_periods=n).mean()
    sd = df["close"].rolling(n, min_periods=n).std().replace(0, np.nan)
    z = (df["close"] - mean) / sd
    k, x = p["z_entry"], p["z_exit"]
    return pd.DataFrame(
        {
            "long_sig": ta.crossed_below(z, -k),
            "short_sig": ta.crossed_above(z, k),
            "exit_long_sig": z >= -x,
            "exit_short_sig": z <= x,
            "conviction": z.abs() / k,
        }
    )


ZSCORE = Family(
    name="zscore_revert",
    title="Z-score reversion to the mean",
    description="Fades statistical stretches: enters when price is k standard deviations away from its N-bar "
                "mean, exits when it has reverted to the exit level.",
    entry_params=(
        Param("window", "int", 50, 400, 200, "buy"),
        Param("z_entry", "float", 2.0, 4.0, 3.0, "buy", 2),
        Param("z_exit", "float", 0.0, 2.5, 1.0, "buy", 2),
    ),
    signal_fn=_zscore_revert,
    affinity="revert",
)


FAMILIES: dict[str, Family] = {f.name: f for f in (TREND_EMA, MEANREV_BB, DONCHIAN, SQUEEZE, TSMOM, FUNDING, ZSCORE)}
# families researched on 15m as well as 1h (short-horizon ideas; funding needs 1h alignment)
MULTI_TF = {"zscore_revert", "meanrev_bb", "squeeze_momentum"}
NEEDS_FUNDING = {"funding_reversal"}

# Freqtrade strategy class name used for hyperopting each family.
RESEARCH_CLASS: dict[str, str] = {
    "trend_ema": "FamTrendEma",
    "meanrev_bb": "FamMeanRevBB",
    "donchian_breakout": "FamDonchian",
    "squeeze_momentum": "FamSqueeze",
    "tsmom": "FamTsmom",
    "funding_reversal": "FamFunding",
    "zscore_revert": "FamZscore",
}


def get_family(name: str) -> Family:
    try:
        return FAMILIES[name]
    except KeyError as e:
        raise ValueError(f"unknown family {name!r}; known: {sorted(FAMILIES)}") from e


__all__ = ["EXIT_PARAMS", "FAMILIES", "NEEDS_FUNDING", "RESEARCH_CLASS", "Family", "Param", "get_family"]
