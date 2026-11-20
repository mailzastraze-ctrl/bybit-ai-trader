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


# ---- ported from the owner's Bybit Strategy Lab engine (same definitions) ----
def wma(s: pd.Series, n: int) -> pd.Series:
    n = max(1, int(n))
    w = np.arange(1, n + 1, dtype=float)
    x = s.to_numpy(dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        out[n - 1:] = np.convolve(x, w[::-1], mode="valid") / w.sum()  # NaN inside a window → NaN
    return pd.Series(out, index=s.index)


def hma(s: pd.Series, n: int) -> pd.Series:
    n = max(1, int(n))
    diff = 2.0 * wma(s, max(1, n // 2)) - wma(s, n)
    return wma(diff, max(1, int(round(np.sqrt(n)))))


def macd(close: pd.Series, fast: int, slow: int, signal: int) -> pd.DataFrame:
    m = ema(close, fast) - ema(close, slow)
    sg = ema(m, signal)
    return pd.DataFrame({"macd": m, "signal": sg, "hist": m - sg})


def stoch(df: pd.DataFrame, k_len: int, k_smooth: int = 3, d_len: int = 3) -> pd.DataFrame:
    hh = df["high"].rolling(int(k_len), min_periods=int(k_len)).max()
    ll = df["low"].rolling(int(k_len), min_periods=int(k_len)).min()
    rng = (hh - ll)
    raw = (100.0 * (df["close"] - ll) / rng.replace(0.0, np.nan)).where(rng > 0, 50.0).where(hh.notna())
    k = sma(raw, max(1, int(k_smooth)))
    return pd.DataFrame({"k": k, "d": sma(k, max(1, int(d_len)))})


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> pd.DataFrame:
    """ATR band flip indicator; dir = 1 (up) / -1 (down)."""
    a = atr(df, int(n)).to_numpy()
    h, lo, c = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
    m = len(c)
    line, dirs = np.full(m, np.nan), np.zeros(m, dtype=int)
    fu = fl = np.nan
    d = 1
    for i in range(m):
        if not np.isfinite(a[i]):
            continue
        mid = (h[i] + lo[i]) / 2
        bu, bl = mid + mult * a[i], mid - mult * a[i]
        pc = c[i - 1] if i > 0 else c[i]
        nfu = bu if (not np.isfinite(fu) or bu < fu or pc > fu) else fu
        nfl = bl if (not np.isfinite(fl) or bl > fl or pc < fl) else fl
        if np.isfinite(fu):
            if d == -1 and c[i] > nfu:
                d = 1
            elif d == 1 and c[i] < nfl:
                d = -1
        fu, fl = nfu, nfl
        dirs[i] = d
        line[i] = fl if d == 1 else fu
    return pd.DataFrame({"st_line": line, "st_dir": dirs}, index=df.index)
