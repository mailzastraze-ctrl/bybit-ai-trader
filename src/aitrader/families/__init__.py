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
        Param("window", "int", 10, 400, 200, "buy"),
        Param("z_entry", "float", 1.0, 4.0, 3.0, "buy", 2),
        Param("z_exit", "float", 0.0, 2.5, 1.0, "buy", 2),
    ),
    signal_fn=_zscore_revert,
    affinity="revert",
)


# ------------------- families ported from the owner's Bybit Strategy Lab (same logic)
def _sig(long_sig, short_sig, exit_long, exit_short, conviction=None, index=None) -> pd.DataFrame:
    return pd.DataFrame({"long_sig": long_sig, "short_sig": short_sig, "exit_long_sig": exit_long,
                         "exit_short_sig": exit_short,
                         "conviction": conviction if conviction is not None else pd.Series(1.0, index=index)})


def _supertrend(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    st = ta.supertrend(df, int(p["st_len"]), p["st_mult"])["st_dir"]
    up = (st == 1) & (st.shift(1) == -1)
    dn = (st == -1) & (st.shift(1) == 1)
    return _sig(up, dn, dn, up, index=df.index)


SUPERTREND = Family(
    name="supertrend", title="SuperTrend flip",
    description="Trend following: enters when the ATR-band SuperTrend flips direction, exits on the opposite flip.",
    entry_params=(Param("st_len", "int", 5, 50, 10, "buy"), Param("st_mult", "float", 1.0, 6.0, 3.0, "buy", 2)),
    signal_fn=_supertrend, affinity="trend")


def _macd_cross(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    fast = int(p["macd_fast"])
    m = ta.macd(df["close"], fast, fast + int(p["macd_gap"]), int(p["macd_signal"]))
    up, dn = ta.crossed_above(m["macd"], m["signal"]), ta.crossed_below(m["macd"], m["signal"])
    zero = int(p["macd_zero"]) == 1
    return _sig(up & ((m["macd"] > 0) | (not zero)), dn & ((m["macd"] < 0) | (not zero)), dn, up,
                0.75 + (m["hist"].abs() / df["close"] * 200).clip(0, 0.75), index=df.index)


MACD = Family(
    name="macd_cross", title="MACD signal cross",
    description="MACD line crossing its signal line; optional zero-line filter (longs only above zero).",
    entry_params=(Param("macd_fast", "int", 4, 30, 12, "buy"), Param("macd_gap", "int", 1, 76, 14, "buy"),
                  Param("macd_signal", "int", 3, 20, 9, "buy"), Param("macd_zero", "int", 0, 1, 0, "buy")),
    signal_fn=_macd_cross, affinity="trend")


def _adx_di(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    a = ta.adx(df, int(p["di_len"]))
    up, dn = ta.crossed_above(a["plus_di"], a["minus_di"]), ta.crossed_below(a["plus_di"], a["minus_di"])
    strong = a["adx"] > p["adx_thr"]
    return _sig(up & strong, dn & strong, dn, up, a["adx"] / (p["adx_thr"] * 1.5), index=df.index)


ADX_DI = Family(
    name="adx_di", title="ADX + DI trend strength",
    description="+DI/-DI crossovers taken only when ADX shows a strong enough trend; exit on the opposite cross.",
    entry_params=(Param("di_len", "int", 7, 30, 14, "buy"), Param("adx_thr", "float", 10.0, 40.0, 25.0, "buy", 1)),
    signal_fn=_adx_di, affinity="trend")


def _hull_turn(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    h = ta.hma(df["close"], int(p["hma_len"]))
    up = (h > h.shift(1)) & (h.shift(1) <= h.shift(2))
    dn = (h < h.shift(1)) & (h.shift(1) >= h.shift(2))
    return _sig(up, dn, dn, up, index=df.index)


HULL = Family(
    name="hull_turn", title="Hull MA turn",
    description="Fast, low-lag trend following: long when the Hull moving average turns up, short when it turns down.",
    entry_params=(Param("hma_len", "int", 10, 200, 55, "buy"),),
    signal_fn=_hull_turn, affinity="trend")


def _rsi_revert(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    x = ta.rsi(df["close"], int(p["rsi_len"]))
    lo, hi = p["rsi_lower"], 100.0 - p["rsi_lower"]
    trend = int(p["rsi_trend"])
    tr = ta.sma(df["close"], trend) if trend >= 20 else None
    ok_l = (df["close"] > tr) if tr is not None else True
    ok_s = (df["close"] < tr) if tr is not None else True
    return _sig(ta.crossed_above(x, lo) & ok_l, ta.crossed_below(x, hi) & ok_s,
                x >= 50 + p["rsi_exit"], x <= 50 - p["rsi_exit"], index=df.index)


RSI_REVERT = Family(
    name="rsi_revert", title="RSI reversion",
    description="Long when RSI leaves the oversold zone upwards, exit at the exit level; shorts mirrored. "
                "Optional SMA trend filter (0 = off).",
    entry_params=(Param("rsi_len", "int", 2, 40, 14, "buy"), Param("rsi_lower", "float", 10.0, 45.0, 30.0, "buy", 1),
                  Param("rsi_exit", "float", -10.0, 30.0, 5.0, "buy", 1), Param("rsi_trend", "int", 0, 400, 0, "buy")),
    signal_fn=_rsi_revert, affinity="revert")


def _stoch_cross(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    s = ta.stoch(df, int(p["stoch_k"]), int(p["stoch_smooth"]), int(p["stoch_d"]))
    up, dn = ta.crossed_above(s["k"], s["d"]), ta.crossed_below(s["k"], s["d"])
    lo = p["stoch_lo"]
    return _sig(up & (s["k"] < lo + 10), dn & (s["k"] > 100 - lo - 10), dn, up, index=df.index)


STOCH = Family(
    name="stoch_cross", title="Stochastic reversal",
    description="%K crossing %D inside the oversold (long) / overbought (short) zone; exit on the opposite cross.",
    entry_params=(Param("stoch_k", "int", 5, 30, 14, "buy"), Param("stoch_smooth", "int", 1, 5, 3, "buy"),
                  Param("stoch_d", "int", 2, 6, 3, "buy"), Param("stoch_lo", "float", 10.0, 35.0, 20.0, "buy", 1)),
    signal_fn=_stoch_cross, affinity="revert")


def _ema_cross(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    f, sl = ta.ema(df["close"], int(p["ema_fast"])), ta.ema(df["close"], int(p["ema_slow"]))
    if int(p["ema_fast"]) >= int(p["ema_slow"]):
        no = pd.Series(False, index=df.index)
        return _sig(no, no, no, no, index=df.index)
    up, dn = ta.crossed_above(f, sl), ta.crossed_below(f, sl)
    t = int(p["ema_trend"])
    tr = ta.ema(df["close"], t) if t >= 20 else None
    return _sig(up & ((df["close"] > tr) if tr is not None else True), dn & ((df["close"] < tr) if tr is not None else True),
                dn, up, index=df.index)


EMA_CROSS = Family(
    name="ema_cross", title="EMA crossover",
    description="Fast EMA crossing the slow EMA, optionally only in the direction of a long EMA trend (0 = off).",
    entry_params=(Param("ema_fast", "int", 3, 60, 12, "buy"), Param("ema_slow", "int", 10, 200, 26, "buy"),
                  Param("ema_trend", "int", 0, 400, 0, "buy")),
    signal_fn=_ema_cross, affinity="trend")


def _bb_revert(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    b = ta.bollinger(df["close"], int(p["br_len"]), p["br_mult"])
    c = df["close"]
    return _sig(ta.crossed_below(c, b["bb_lower"]), ta.crossed_above(c, b["bb_upper"]),
                c >= b["bb_mid"], c <= b["bb_mid"], index=df.index)


BB_REVERT = Family(
    name="bb_revert", title="Bollinger band reversion (plain)",
    description="Buys a close below the lower band, sells one above the upper band; exits at the middle line.",
    entry_params=(Param("br_len", "int", 10, 60, 20, "buy"), Param("br_mult", "float", 1.0, 3.5, 2.0, "buy", 2)),
    signal_fn=_bb_revert, affinity="revert")


def _turtle(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    e, x = int(p["tt_entry"]), int(p["tt_exit"])
    hi = df["high"].rolling(e, min_periods=e).max().shift(1)
    lo = df["low"].rolling(e, min_periods=e).min().shift(1)
    xhi = df["high"].rolling(x, min_periods=x).max().shift(1)
    xlo = df["low"].rolling(x, min_periods=x).min().shift(1)
    c = df["close"]
    return _sig(c > hi, c < lo, c < xlo, c > xhi, index=df.index)


TURTLE = Family(
    name="turtle", title="Donchian turtle breakout",
    description="Classic turtle system: enter on an N-bar channel breakout, exit on an M-bar counter-breakout.",
    entry_params=(Param("tt_entry", "int", 5, 100, 20, "buy"), Param("tt_exit", "int", 3, 60, 10, "buy")),
    signal_fn=_turtle, affinity="trend")


# ------------------------------------------- relative strength vs the market (BTC)
MARKET_PAIR = "BTC/USDT:USDT"


def _rel_strength(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Information the classic indicators don't have: how a coin moves *relative to the
    market* (BTC). Coins persistently out-/under-performing BTC tend to keep doing so for a
    while (cross-sectional momentum). Needs a 'mkt_close' column merged by the strategy."""
    no = pd.Series(False, index=df.index)
    if "mkt_close" not in df or df["mkt_close"].isna().all():
        return _sig(no, no, no, no, index=df.index)
    ratio = np.log(df["close"] / df["mkt_close"].replace(0, np.nan))
    n = int(p["rs_len"])
    rs = ratio - ratio.shift(n)
    w = max(4 * n, 200)
    z = (rs - rs.rolling(w, min_periods=w // 2).mean()) / rs.rolling(w, min_periods=w // 2).std().replace(0, np.nan)
    k, x = p["rs_z"], p["rs_exit"]
    t = int(p["rs_trend"])
    tr = ta.ema(df["close"], t) if t >= 20 else None
    ok_l = (df["close"] > tr) if tr is not None else True
    ok_s = (df["close"] < tr) if tr is not None else True
    return _sig(ta.crossed_above(z, k) & ok_l, ta.crossed_below(z, -k) & ok_s, z < x, z > -x,
                0.5 + z.abs() / (k + 1.0), index=df.index)


REL_STRENGTH = Family(
    name="rel_strength", title="Relative strength vs BTC",
    description="Trades coins that break out of their usual performance relative to BTC (cross-sectional "
                "momentum); exits when the relative move fades.",
    entry_params=(Param("rs_len", "int", 12, 336, 72, "buy"), Param("rs_z", "float", 0.5, 3.0, 1.5, "buy", 2),
                  Param("rs_exit", "float", -0.5, 1.5, 0.3, "buy", 2), Param("rs_trend", "int", 0, 400, 0, "buy")),
    signal_fn=_rel_strength, affinity="trend")


# ------------------------------------------------ open interest flow (who drives a move)
def _oi_flow(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Price move + open-interest change. Mode 0 (confirm): a breakout carried by *new*
    positions (OI rising) tends to continue. Mode 1 (fade): a sharp move while OI collapses
    is positions being closed (liquidations / short covering) and tends to revert.
    Needs an 'oi' column merged by the strategy; without it there are no signals."""
    no = pd.Series(False, index=df.index)
    if "oi" not in df or df["oi"].isna().all():
        return _sig(no, no, no, no, index=df.index)
    n = int(p["oi_len"])
    w = max(4 * n, 200)
    oi = df["oi"].astype(float).ffill()
    zs = lambda x: (x - x.rolling(w, min_periods=w // 2).mean()) / x.rolling(w, min_periods=w // 2).std().replace(0, np.nan)  # noqa: E731
    zr = zs(df["close"] / df["close"].shift(n) - 1)
    zo = zs(oi / oi.shift(n) - 1)
    k, m, x = p["oi_k"], p["oi_m"], p["oi_exit"]
    if int(p["oi_mode"]) == 0:
        long_sig, short_sig = ta.crossed_above(zr, k) & (zo > m), ta.crossed_below(zr, -k) & (zo > m)
        exit_l, exit_s = zr < x, zr > -x
    else:
        long_sig, short_sig = ta.crossed_below(zr, -k) & (zo < -m), ta.crossed_above(zr, k) & (zo < -m)
        exit_l, exit_s = zr > -x, zr < x
    return _sig(long_sig, short_sig, exit_l, exit_s, 0.5 + zo.abs().clip(0, 2) / 2, index=df.index)


OI_FLOW = Family(
    name="oi_flow", title="Open-interest flow",
    description="Combines the price move with the change in open interest: breakouts carried by new positions "
                "(confirm mode) or sharp moves on collapsing open interest (fade mode).",
    entry_params=(Param("oi_len", "int", 4, 96, 24, "buy"), Param("oi_k", "float", 0.5, 3.0, 1.5, "buy", 2),
                  Param("oi_m", "float", 0.0, 2.0, 0.5, "buy", 2), Param("oi_mode", "int", 0, 1, 0, "buy"),
                  Param("oi_exit", "float", -0.5, 1.0, 0.0, "buy", 2)),
    signal_fn=_oi_flow, affinity="trend")


FAMILIES: dict[str, Family] = {f.name: f for f in (TREND_EMA, MEANREV_BB, DONCHIAN, SQUEEZE, TSMOM, FUNDING, ZSCORE,
                                                   SUPERTREND, MACD, ADX_DI, HULL, RSI_REVERT, STOCH,
                                                   EMA_CROSS, BB_REVERT, TURTLE, REL_STRENGTH, OI_FLOW)}
# families researched on 15m as well as 1h (short-horizon ideas; funding needs 1h alignment)
MULTI_TF = {"zscore_revert", "meanrev_bb", "squeeze_momentum", "supertrend", "macd_cross", "adx_di", "hull_turn",
            "rsi_revert", "stoch_cross", "ema_cross", "bb_revert", "turtle", "rel_strength"}
NEEDS_FUNDING = {"funding_reversal"}
NEEDS_MARKET = {"rel_strength"}
NEEDS_OI = {"oi_flow"}  # hourly open interest (research downloads it; live fetches it)

# Freqtrade strategy class name used for hyperopting each family.
RESEARCH_CLASS: dict[str, str] = {
    "trend_ema": "FamTrendEma",
    "meanrev_bb": "FamMeanRevBB",
    "donchian_breakout": "FamDonchian",
    "squeeze_momentum": "FamSqueeze",
    "tsmom": "FamTsmom",
    "funding_reversal": "FamFunding",
    "zscore_revert": "FamZscore",
    "supertrend": "FamSupertrend",
    "macd_cross": "FamMacd",
    "adx_di": "FamAdxDi",
    "hull_turn": "FamHull",
    "rsi_revert": "FamRsiRevert",
    "stoch_cross": "FamStoch",
    "ema_cross": "FamEmaCross",
    "bb_revert": "FamBBRevert",
    "turtle": "FamTurtle",
    "rel_strength": "FamRelStrength",
    "oi_flow": "FamOiFlow",
}


def get_family(name: str) -> Family:
    try:
        return FAMILIES[name]
    except KeyError as e:
        raise ValueError(f"unknown family {name!r}; known: {sorted(FAMILIES)}") from e


__all__ = ["EXIT_PARAMS", "FAMILIES", "MARKET_PAIR", "NEEDS_FUNDING", "NEEDS_MARKET", "NEEDS_OI", "RESEARCH_CLASS", "Family", "Param", "get_family"]
