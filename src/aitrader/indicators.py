"""Pure pandas/numpy indicators (no TA-Lib) so strategy logic is testable anywhere.

All rolling indicators only use past and current bars – no look-ahead.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=int(n), adjust=False, min_periods=int(n)).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(int(n), min_periods=int(n)).mean()


def rma(s: pd.Series, n: int) -> pd.Series:
    """Wilder's moving average."""
    return s.ewm(alpha=1.0 / int(n), adjust=False, min_periods=int(n)).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return rma(true_range(df), n)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = rma(delta.clip(lower=0.0), n)
    down = rma((-delta).clip(lower=0.0), n)
    rs = up / down.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    return out.where(down != 0.0, 100.0).where(up.notna())


def adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr_n = rma(true_range(df), n)
    plus_di = 100.0 * rma(pd.Series(plus_dm, index=df.index), n) / tr_n
    minus_di = 100.0 * rma(pd.Series(minus_dm, index=df.index), n) / tr_n
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return pd.DataFrame({"adx": rma(dx.fillna(0.0), n), "plus_di": plus_di, "minus_di": minus_di})


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    sd = close.rolling(int(n), min_periods=int(n)).std(ddof=0)
    return pd.DataFrame({"bb_mid": mid, "bb_upper": mid + k * sd, "bb_lower": mid - k * sd})


def keltner(df: pd.DataFrame, n: int = 20, mult: float = 1.5) -> pd.DataFrame:
    mid = ema(df["close"], n)
    a = atr(df, n)
    return pd.DataFrame({"kc_mid": mid, "kc_upper": mid + mult * a, "kc_lower": mid - mult * a})


def donchian_prev(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Channel of the *previous* n bars (excludes current bar → usable for breakouts)."""
    return pd.DataFrame(
        {
            "dc_high": df["high"].shift(1).rolling(int(n), min_periods=int(n)).max(),
            "dc_low": df["low"].shift(1).rolling(int(n), min_periods=int(n)).min(),
        }
    )


def crossed_above(a: pd.Series, b: pd.Series | float) -> pd.Series:
    b_prev = b.shift(1) if isinstance(b, pd.Series) else b
    return (a > b) & (a.shift(1) <= b_prev)


def crossed_below(a: pd.Series, b: pd.Series | float) -> pd.Series:
    b_prev = b.shift(1) if isinstance(b, pd.Series) else b
    return (a < b) & (a.shift(1) >= b_prev)


def efficiency_ratio(close: pd.Series, n: int = 20) -> pd.Series:
    """Kaufman efficiency ratio: 1 = straight trend, 0 = pure noise."""
    change = (close - close.shift(n)).abs()
    vol = close.diff().abs().rolling(n, min_periods=n).sum()
    return change / vol.replace(0.0, np.nan)
