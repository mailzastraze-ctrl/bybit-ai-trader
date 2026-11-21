"""Evidence statistics shared by the forward test, the lifecycle and the readiness gate.

Principle: *fast to protect, slow to trust*. Decisions that add risk or declare an edge real
need evidence that survives the usual traps of live trading:

  * trades on the same day are not independent → daily series with a Newey–West
    (autocorrelation-robust) t-statistic instead of a per-trade t;
  * crypto strategies make or lose money with the market → beta to BTC and the alpha
    left after it, so a short book in a falling market is not mistaken for skill;
  * the forward verdict is re-checked after every lab run → an anytime-valid threshold
    (normal-mixture boundary, Robbins 1970) keeps the false "works" rate at α however
    often it is looked at;
  * small samples are noisy → per-strategy means are shrunk towards the group mean
    (empirical Bayes) before they are ranked.
All functions are pure (numbers in, numbers out) and covered by tests/test_evidence.py.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

import numpy as np
import pandas as pd

# anytime-valid forward verdict: α one-sided, mixture scale ρ in days (≈ the first look)
ANYTIME_ALPHA = 0.05
ANYTIME_RHO_DAYS = 90.0
T_FLOOR = 2.0


def newey_west_t(x: Iterable[float], lags: int | None = None) -> float:
    """t-statistic of the mean with a Newey–West (Bartlett) long-run variance."""
    a = np.asarray(list(x), dtype=float)
    n = len(a)
    if n < 3:
        return 0.0
    if lags is None:
        lags = int(math.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    lags = max(0, min(lags, n - 1))
    e = a - a.mean()
    lrv = float(e @ e) / n
    for k in range(1, lags + 1):
        w = 1.0 - k / (lags + 1.0)
        lrv += 2.0 * w * float(e[k:] @ e[:-k]) / n
    if lrv <= 0:
        return 0.0
    return float(a.mean() / math.sqrt(lrv / n))


def anytime_t_boundary(n_obs: float, rho: float = ANYTIME_RHO_DAYS, alpha: float = ANYTIME_ALPHA) -> float:
    """t a daily series must reach so that "works" stays valid under continuous monitoring.

    Normal-mixture boundary: P(∃n: S_n ≥ σ·sqrt((n+ρ)·ln((n+ρ)/(ρ·a²)))) ≤ a (two-sided a);
    one-sided α uses a = 2α. In t units: sqrt((1+ρ/n)·ln((n+ρ)/(ρ·(2α)²))). Never below 2.0.
    Values (ρ = 90, α = 5%): 90 obs → 3.26, 180 → 2.93, 365 → 2.79, 730 → 2.77.
    """
    n = max(float(n_obs), 1.0)
    a = min(2.0 * alpha, 0.5)
    b = math.sqrt((1.0 + rho / n) * math.log((n + rho) / (rho * a * a)))
    return round(max(b, T_FLOOR), 3)


def daily_returns(trades: Iterable[Mapping], equity: float, pnl_fn, end=None) -> pd.Series:
    """Calendar-day returns (realised PnL / equity) from the first trade's day to `end`
    (default: the last trade's day); days without closed trades count as 0."""
    rows = [(str(t.get("close_date") or "")[:10], float(pnl_fn(t))) for t in trades if t.get("close_date")]
    if not rows or equity <= 0:
        return pd.Series(dtype=float)
    s = pd.Series([v for _, v in rows], index=pd.to_datetime([d for d, _ in rows], utc=True)).groupby(level=0).sum()
    last = pd.Timestamp(end).tz_convert("UTC").normalize() if end is not None else s.index.max()
    idx = pd.date_range(s.index.min(), max(last, s.index.max()), freq="1D", tz="UTC")
    return (s.reindex(idx, fill_value=0.0) / equity).astype(float)


def btc_returns(closes: Mapping[str, float] | None) -> pd.Series:
    """{'YYYY-MM-DD': close} (UTC daily candles) → daily log returns indexed by UTC day."""
    if not closes:
        return pd.Series(dtype=float)
    s = pd.Series({pd.Timestamp(k, tz="UTC"): float(v) for k, v in closes.items() if v}).sort_index()
    return np.log(s).diff().dropna()


def alpha_beta(y: pd.Series, x: pd.Series, min_days: int = 5) -> dict:
    """OLS y = α + β·x on the common days. α is per day; `alpha_t` uses Newey–West on the
    residual-plus-alpha series (the market-neutral part of the returns)."""
    df = pd.concat({"y": y, "x": x}, axis=1, join="inner").dropna()
    n = len(df)
    if n < min_days:
        return {"days": n, "alpha": None, "beta": None, "alpha_t": None, "alpha_ann": None}
    xv, yv = df["x"].to_numpy(), df["y"].to_numpy()
    vx = float(np.var(xv))
    beta = float(np.cov(xv, yv, bias=True)[0, 1] / vx) if vx > 0 else 0.0
    neutral = yv - beta * xv  # what is left after the market move
    alpha = float(neutral.mean())
    return {"days": n, "alpha": alpha, "beta": round(beta, 3), "alpha_t": round(newey_west_t(neutral), 2),
            "alpha_ann": round(alpha * 365, 4)}


def shrink(means: Mapping[str, float], ses: Mapping[str, float]) -> dict[str, dict]:
    """Empirical-Bayes shrinkage of per-strategy means towards their precision-weighted
    grand mean. Returns {id: {"shrunk": posterior mean, "lcb": posterior mean − 1 posterior sd
    (the conservative ranking key: a short lucky streak has a wide posterior), "p_pos": P(true mean > 0)}}."""
    keys = [k for k in means if ses.get(k) and ses[k] > 0 and np.isfinite(means[k])]
    if not keys:
        return {}
    m = np.array([means[k] for k in keys])
    v = np.array([ses[k] ** 2 for k in keys])
    w = 1.0 / v
    grand = float((w * m).sum() / w.sum())
    tau2 = max(float(np.var(m) - v.mean()), 0.0)  # between-strategy variance of true means
    out = {}
    for k, mk, vk in zip(keys, m, v, strict=True):
        if tau2 > 0:
            post_v = 1.0 / (1.0 / tau2 + 1.0 / vk)
            post_m = post_v * (grand / tau2 + mk / vk)
        else:
            post_v, post_m = 1e-18, grand
        z = post_m / math.sqrt(post_v) if post_v > 0 else 0.0
        out[k] = {"shrunk": float(post_m), "lcb": float(post_m - math.sqrt(post_v)),
                  "p_pos": round(0.5 * (1 + math.erf(z / math.sqrt(2))), 3)}
    return out
