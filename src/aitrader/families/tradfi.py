"""Strategy families of the TradFi lane (gold, S&P 500). Pre-registered, never searched.

They are deliberately **not** in `FAMILIES`: the research lab's bandit, generator, screener,
bootstrap and random explorers iterate `FAMILIES`, and the crypto search must not change
(observation period). `get_family` resolves them, so the live bot, the lab's backtests and the
forward book run them with the same code as every other family.

The third strategy of the lane, *Trend Following*, needs no new code: it is the system's own
pre-registered TSMOM benchmark construction (family `tsmom`), applied to gold and the S&P 500 –
the asset classes where time-series momentum was documented first (Moskowitz, Ooi & Pedersen
2012; Hurst, Ooi & Pedersen 2017).

All parameters are given in candles of the strategy's timeframe (4h on 24/7 perpetual candles:
6 candles a day).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from aitrader import indicators as ta
from aitrader.families.base import Family, Param


def _out(long_sig, short_sig, exit_long, exit_short, index, conviction=None) -> pd.DataFrame:
    return pd.DataFrame({"long_sig": long_sig, "short_sig": short_sig, "exit_long_sig": exit_long,
                         "exit_short_sig": exit_short,
                         "conviction": conviction if conviction is not None else pd.Series(1.0, index=index)})


# ----------------------------------------------------------------------------- Gold Regime
def _gold_regime(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Gold trades in long regimes (2001–2011 up, 2013–2015 down, 2019–2026 up). A regime is the
    slow trend (EMA ≈ 50 days) with the medium trend (EMA ≈ 10 days) on the same side and the
    slow trend still sloping that way. Inside a regime the strategy buys the end of a pullback
    (close back above the ≈ 3-day EMA) or the regime's start, never in a volatility shock (ATR%
    above `vol_cap` × its 60-day median, e.g. the margin-call selloffs). It leaves when the
    medium trend crosses back through the slow one. Shorts are the mirror in a bear regime."""
    c = df["close"]
    slow = ta.ema(c, int(p["regime_len"]))
    fast = ta.ema(c, int(p["fast_len"]))
    slope = slow - slow.shift(int(p["slope_len"]))
    bull = (c > slow) & (fast > slow) & (slope > 0)
    bear = (c < slow) & (fast < slow) & (slope < 0)
    atr_pct = ta.atr(df, 14) / c
    calm = atr_pct <= p["vol_cap"] * atr_pct.rolling(360, min_periods=120).median()
    pb = ta.ema(c, int(p["pullback_len"]))
    long_sig = bull & calm & (ta.crossed_above(c, pb) | ta.crossed_above(fast, slow))
    short_sig = bear & calm & (ta.crossed_below(c, pb) | ta.crossed_below(fast, slow))
    return _out(long_sig, short_sig, fast < slow, fast > slow, df.index)


GOLD_REGIME = Family(
    name="gold_regime",
    title="Gold regime (trend regime + pullback entries)",
    description="Gold only: in a bull (bear) regime of the ≈50-day trend it buys (sells) the end of pullbacks, "
                "skips volatility shocks, and exits when the ≈10-day trend crosses back. TradFi lane, pre-registered.",
    entry_params=(
        Param("regime_len", "int", 120, 600, 300, "buy"),    # 300 × 4h ≈ 50 days
        Param("fast_len", "int", 20, 160, 60, "buy"),        # 60 × 4h ≈ 10 days
        Param("slope_len", "int", 6, 120, 30, "buy"),        # slope of the slow EMA over ≈ 5 days
        Param("pullback_len", "int", 6, 60, 20, "buy"),      # ≈ 3.3 days
        Param("vol_cap", "float", 1.0, 3.0, 1.5, "buy", 2),  # no entries above 1.5× the usual ATR%
    ),
    signal_fn=_gold_regime,
    affinity="trend",
)


# ----------------------------------------------------------------------- Momentum Rotation
def _vol_momentum(close: pd.Series, lookback: int, vol_len: int) -> pd.Series:
    ret = np.log(close).diff()
    vol = ret.rolling(vol_len, min_periods=48).std()
    return np.log(close / close.shift(lookback)) / (vol * np.sqrt(lookback)).replace(0, np.nan)


def _rotation(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Dual momentum between two assets (Antonacci): hold the instrument whose risk-adjusted
    momentum leads the other's by more than `band` and is itself above `abs_min` (beats cash);
    leave when it falls behind by `band` or its own momentum turns negative. Long only. The
    other asset's close comes in as `peer_close` (merged by the strategy on the same candle);
    without it there are no signals. The entry is a state: while the asset leads and no trade
    is open, the next candle re-offers it (one trade per pair)."""
    no = pd.Series(False, index=df.index)
    if "peer_close" not in df or df["peer_close"].isna().all():
        return _out(no, no, no, no, df.index)
    L, V = int(p["rot_lookback"]), int(p["rot_vol_len"])
    m_self = _vol_momentum(df["close"], L, V)
    m_peer = _vol_momentum(df["peer_close"].astype(float), L, V)
    lead = m_self - m_peer
    band = float(p["rot_band"])
    hold = (m_self > float(p["abs_min"])) & (lead > band)
    leave = (m_self < 0) | (lead < -band)
    return _out(hold.fillna(False), no, leave.fillna(False), no, df.index)


ROTATION = Family(
    name="tradfi_rotation",
    title="Momentum rotation gold ↔ S&P 500 (dual momentum)",
    description="Holds whichever of gold and the S&P 500 has the stronger risk-adjusted ≈60-day momentum, "
                "if that momentum is positive; long only. TradFi lane, pre-registered.",
    entry_params=(
        Param("rot_lookback", "int", 120, 540, 360, "buy"),  # 360 × 4h ≈ 60 days
        Param("rot_vol_len", "int", 72, 336, 180, "buy"),    # ≈ 30 days
        Param("rot_band", "float", 0.0, 1.0, 0.25, "buy", 2),
        Param("abs_min", "float", -0.5, 1.0, 0.0, "buy", 2),
    ),
    signal_fn=_rotation,
    affinity="trend",
)

TRADFI_FAMILIES: dict[str, Family] = {f.name: f for f in (GOLD_REGIME, ROTATION)}
NEEDS_PEER = {"tradfi_rotation"}  # the other instrument's close, as `peer_close`
