"""Performance and overfitting statistics computed from trade lists (framework independent)."""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime

import numpy as np
import pandas as pd

from aitrader.util import parse_dt

EULER_GAMMA = 0.5772156649015329


def trades_frame(trades: Iterable[dict]) -> pd.DataFrame:
    rows = []
    for t in trades:
        cd = parse_dt(t.get("close_date") or t.get("close_timestamp"))
        od = parse_dt(t.get("open_date") or t.get("open_timestamp"))
        if cd is None:
            continue
        rows.append(
            {
                "pair": t.get("pair"),
                "open_date": od,
                "close_date": cd,
                "profit_abs": float(t.get("profit_abs") or t.get("close_profit_abs") or 0.0),
                "profit_ratio": float(t.get("profit_ratio") or t.get("close_profit") or 0.0),
                "exit_reason": t.get("exit_reason") or "",
                "enter_tag": t.get("enter_tag") or "",
                "is_short": bool(t.get("is_short", False)),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("close_date").reset_index(drop=True)
    return df


def daily_returns(df: pd.DataFrame, starting_balance: float,
                  start: datetime | None = None, end: datetime | None = None) -> pd.Series:
    """Daily equity returns (compounded equity path), zero-filled on days without exits."""
    if df.empty:
        return pd.Series(dtype=float)
    pnl = df.set_index("close_date")["profit_abs"].resample("1D").sum()
    if start is not None or end is not None:
        idx = pd.date_range(
            pd.Timestamp(start or pnl.index.min()).floor("D"),
            pd.Timestamp(end or pnl.index.max()).floor("D"),
            freq="1D",
            tz="UTC",
        )
        pnl = pnl.reindex(idx, fill_value=0.0)
    equity = starting_balance + pnl.cumsum()
    prev = equity.shift(1).fillna(starting_balance)
    return (pnl / prev.replace(0, np.nan)).fillna(0.0)


def sharpe(r: pd.Series, periods: int = 365) -> float:
    if len(r) < 2 or r.std(ddof=1) == 0 or np.isnan(r.std(ddof=1)):
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(periods))


def sortino(r: pd.Series, periods: int = 365) -> float:
    if len(r) < 2:
        return 0.0
    downside = np.sqrt(np.mean(np.minimum(r.values, 0.0) ** 2))
    if downside == 0:
        return 0.0
    return float(r.mean() / downside * math.sqrt(periods))


def max_drawdown_from_pnl(pnl: np.ndarray, starting_balance: float) -> float:
    if len(pnl) == 0:
        return 0.0
    equity = starting_balance + np.cumsum(pnl)
    equity = np.concatenate([[starting_balance], equity])
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / np.where(peak > 0, peak, np.nan)
    return float(np.nanmax(dd)) if len(dd) else 0.0


def profit_factor(pnl: np.ndarray) -> float:
    gains = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def summarize(trades: Iterable[dict] | pd.DataFrame, starting_balance: float,
              start: datetime | None = None, end: datetime | None = None) -> dict:
    df = trades if isinstance(trades, pd.DataFrame) else trades_frame(trades)
    n = int(len(df))
    if n == 0:
        return {"trades": 0, "profit_factor": 0.0, "sharpe": 0.0, "sortino": 0.0,
                "max_drawdown": 0.0, "total_return": 0.0, "annual_return": 0.0,
                "win_rate": 0.0, "expectancy": 0.0, "days": 0.0}
    pnl = df["profit_abs"].to_numpy(dtype=float)
    r = daily_returns(df, starting_balance, start, end)
    days = max((pd.Timestamp(end) - pd.Timestamp(start)).days if start and end else len(r), 1)
    total = float(pnl.sum() / starting_balance)
    growth = max(1.0 + total, 1e-9)
    annual = growth ** (365.0 / days) - 1.0
    pf = profit_factor(pnl)
    return {
        "trades": n,
        "profit_factor": round(pf, 4) if math.isfinite(pf) else 99.0,
        "sharpe": round(sharpe(r), 4),
        "sortino": round(sortino(r), 4),
        "max_drawdown": round(max_drawdown_from_pnl(pnl, starting_balance), 4),
        "total_return": round(total, 5),
        "annual_return": round(annual, 5),
        "win_rate": round(float((pnl > 0).mean()), 4),
        "expectancy": round(float(df["profit_ratio"].mean()), 6),
        "avg_profit_abs": round(float(pnl.mean()), 4),
        "days": float(days),
        "long_trades": int((~df["is_short"]).sum()),
        "short_trades": int(df["is_short"].sum()),
        "skew": round(float(r.skew()) if len(r) > 2 else 0.0, 4),
        "kurtosis": round(float(r.kurt() + 3.0) if len(r) > 3 else 3.0, 4),
        "n_days": int(len(r)),
        "daily_sharpe": round(sharpe(r, 1), 6),
    }


# --------------------------------------------------------------------- overfitting stats
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse normal CDF (Acklam's approximation, |err| < 1.2e-9)."""
    p = min(max(p, 1e-12), 1 - 1e-12)
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
        ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def probabilistic_sharpe(sr: float, sr_benchmark: float, n_obs: int,
                         skew: float = 0.0, kurtosis: float = 3.0) -> float:
    """PSR (Bailey & López de Prado). `sr` per-period (not annualised)."""
    if n_obs < 3:
        return 0.0
    denom = 1.0 - skew * sr + (kurtosis - 1.0) / 4.0 * sr * sr
    if denom <= 0:
        return 0.0
    return _norm_cdf((sr - sr_benchmark) * math.sqrt(n_obs - 1) / math.sqrt(denom))


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """Expected maximum per-period Sharpe among n_trials unskilled strategies."""
    n = max(int(n_trials), 1)
    if n == 1:
        return 0.0
    return math.sqrt(max(sr_variance, 0.0)) * (
        (1 - EULER_GAMMA) * _norm_ppf(1 - 1.0 / n) + EULER_GAMMA * _norm_ppf(1 - 1.0 / (n * math.e))
    )


def deflated_sharpe(sr: float, n_obs: int, n_trials: int, sr_variance: float,
                    skew: float = 0.0, kurtosis: float = 3.0) -> float:
    """DSR: probability the true Sharpe > 0 after correcting for the number of trials."""
    return probabilistic_sharpe(sr, expected_max_sharpe(n_trials, sr_variance), n_obs, skew, kurtosis)


def monte_carlo(pnl: np.ndarray, starting_balance: float, samples: int = 2000,
                seed: int = 7) -> dict:
    """Bootstrap trade outcomes (with replacement) → distribution of return and drawdown."""
    pnl = np.asarray(pnl, dtype=float)
    if len(pnl) < 5:
        return {"prob_profit": 0.0, "ret_p5": 0.0, "ret_p50": 0.0, "dd_p95": 1.0}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(pnl), size=(samples, len(pnl)))
    paths = pnl[idx]
    totals = paths.sum(axis=1) / starting_balance
    equity = starting_balance + np.cumsum(paths, axis=1)
    equity = np.concatenate([np.full((samples, 1), starting_balance), equity], axis=1)
    peak = np.maximum.accumulate(equity, axis=1)
    dd = ((peak - equity) / peak).max(axis=1)
    return {
        "prob_profit": round(float((totals > 0).mean()), 4),
        "ret_p5": round(float(np.percentile(totals, 5)), 5),
        "ret_p50": round(float(np.percentile(totals, 50)), 5),
        "dd_p95": round(float(np.percentile(dd, 95)), 5),
    }


def robust_loss(df: pd.DataFrame, starting_balance: float, start: datetime, end: datetime,
                min_trades: int = 30, dd_limit: float = 0.20) -> float:
    """Hyperopt objective (lower is better): Sharpe scaled by trade-count confidence,
    with a steep penalty for drawdowns above the limit and for too few trades."""
    n = len(df)
    if n < min_trades:
        return 50.0 - n / max(min_trades, 1)  # monotone: more trades is better
    s = summarize(df, starting_balance, start, end)
    confidence = min(1.0, n / 100.0) ** 0.5
    penalty = 10.0 * max(0.0, s["max_drawdown"] - dd_limit)
    if s["profit_factor"] < 1.0:
        penalty += 1.0 - s["profit_factor"]
    return -s["sharpe"] * confidence + penalty
