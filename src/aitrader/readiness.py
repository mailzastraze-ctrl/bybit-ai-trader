"""Real-money readiness gate.

Answers one question with data only: *is there enough independent, realistic evidence to
justify a small real-money pilot?* It is advisory — the system never switches to real
money by itself (demo_trading stays hard-required); the owner decides.

Evidence set: closed demo trades of strategies currently in **production**, taken *after*
their promotion (so the trades did not influence the decision that is being judged), with
every fill haircut for slippage the demo cannot simulate (see realism.py).

All checks must pass at the same time:
  forward_days   ≥ 90 days of post-promotion trading
  trades         ≥ 250 closed trades
  diversified    ≥ 2 strategies with ≥ 50 trades each and absolute daily PnL correlation < 0.5
  t_stat         serial-dependence-adjusted daily t-statistic ≥ 2.5
  profit_factor  ≥ 1.3 (realistic)
  drawdown       max drawdown ≤ 10% of equity (realistic PnL curve)
  stability      profitable in ≥ 2 of 3 equal time thirds
  consistency    no strategy's live results diverge from its out-of-sample expectation
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from aitrader.realism import SLIPPAGE_PER_SIDE, real_pnl, real_ratio
from aitrader.registry import Registry
from aitrader.util import iso, parse_dt

REQ = {"forward_days": 90, "trades": 250, "strategies": 2, "per_strategy": 50, "max_corr": 0.5,
       "t_stat": 2.5, "profit_factor": 1.3, "max_dd": 0.10, "stable_thirds": 2}


def _daily_t(returns: np.ndarray) -> float:
    """Newey–West t for the mean daily return, with up to a week of autocorrelation."""
    n = len(returns)
    if n < 2:
        return 0.0
    residuals = returns - returns.mean()
    variance = float(residuals @ residuals / n)
    lags = min(7, n - 1)
    for lag in range(1, lags + 1):
        variance += 2 * (1 - lag / (lags + 1)) * float(residuals[lag:] @ residuals[:-lag] / n)
    return float(returns.mean() * math.sqrt(n / variance)) if variance > 0 else 0.0


def _stats(trades: list[dict], equity: float) -> dict:
    if not trades:
        return {"trades": 0}
    pnl = np.array([real_pnl(t) for t in trades])
    raw = np.array([float(t.get("profit_abs") or 0.0) for t in trades])
    gains, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    pf = float(gains / losses) if losses > 0 else (99.0 if gains > 0 else 0.0)
    dates = pd.to_datetime([t["close_date"] for t in trades], utc=True, format="mixed")
    daily = pd.Series(pnl, index=dates).resample("1D").sum()
    previous_equity = equity + daily.cumsum().shift(1, fill_value=0)
    t = _daily_t((daily / previous_equity).to_numpy()) if (previous_equity > 0).all() else 0.0
    curve = equity + np.cumsum(pnl)
    peak = np.maximum.accumulate(np.r_[equity, curve])[1:]
    dd = float(((peak - curve) / np.maximum(peak, 1e-9)).max()) if len(curve) else 0.0
    thirds = np.array_split(daily.to_numpy(), 3)
    return {"trades": len(trades), "pnl_real": round(float(pnl.sum()), 2), "pnl_demo": round(float(raw.sum()), 2),
            "haircut": round(float(raw.sum() - pnl.sum()), 2), "profit_factor": pf,
            "t_stat": t, "max_dd": dd, "win_rate": round(float((pnl > 0).mean()), 3),
            "stable_thirds": int(sum(1 for x in thirds if len(x) and x.sum() > 0))}


def _min_corr(by_sleeve: dict[str, list[dict]]) -> float | None:
    from itertools import combinations

    big = {k: v for k, v in by_sleeve.items() if len(v) >= REQ["per_strategy"]}
    daily = {}
    for k, ts in big.items():
        dates = pd.to_datetime([t["close_date"] for t in ts], utc=True, format="mixed")
        s = pd.Series([real_ratio(t) for t in ts], index=dates)
        daily[k] = s.resample("1D").sum()
    correlations = []
    for a, b in combinations(daily.values(), 2):
        overlap = pd.concat([a, b], axis=1, join="inner")
        if len(overlap) < REQ["forward_days"] or (overlap.std() == 0).any():
            continue
        corr = float(overlap.iloc[:, 0].corr(overlap.iloc[:, 1]))
        if math.isfinite(corr):
            correlations.append(abs(corr))
    return min(correlations, default=None)


def evaluate(reg: Registry, equity: float | None = None) -> dict:
    from aitrader.lifecycle import Lifecycle  # local import: lifecycle imports learner → realism
    equity = float(equity or reg.kv_get("last_equity", 0.0) or 10_000.0)
    prod = reg.strategies(("production",))
    life = Lifecycle.__new__(Lifecycle)
    life.reg = reg
    evidence, by_sleeve = [], {}
    for s in prod:
        rows = life.stage_trades(s)
        evidence += rows
        by_sleeve[s["id"]] = rows
    evidence.sort(key=lambda t: parse_dt(t["close_date"]))
    start = min((parse_dt(t["open_date"]) for t in evidence), default=None)
    end = parse_dt(evidence[-1]["close_date"]) if evidence else None
    base = equity
    have_equity = False
    if start:
        snapshot = reg.one(
            "SELECT equity FROM equity WHERE julianday(ts) <= julianday(?) ORDER BY ts DESC LIMIT 1", (iso(start),)
        )
        if snapshot and snapshot["equity"] > 0:
            base = snapshot["equity"]
            have_equity = True
    st = _stats(evidence, base)
    days = (end - start).total_seconds() / 86400 if start and end else 0.0
    big = [k for k, v in by_sleeve.items() if len(v) >= REQ["per_strategy"]]
    corr = _min_corr(by_sleeve)
    diverging = [s["id"] for s in prod if not (s.get("oos") or {}).get("expectancy")
                 or len(by_sleeve[s["id"]]) < 20 or life.diverges(s, rows=by_sleeve[s["id"]])]
    n = st.get("trades", 0)
    checks = [
        {"id": "forward_days", "title": "Post-promotion forward test", "value": round(days, 1),
         "need": f"≥ {REQ['forward_days']} days", "pass": days >= REQ["forward_days"]},
        {"id": "trades", "title": "Closed trades (evidence)", "value": n, "need": f"≥ {REQ['trades']}",
         "pass": n >= REQ["trades"]},
        {"id": "diversified", "title": "Independent strategies", "value": f"{len(big)} (|corr| {round(corr, 3) if corr is not None else '–'})",
         "need": f"≥ {REQ['strategies']} with ≥ {REQ['per_strategy']} trades and 90 common days, |corr| < {REQ['max_corr']}",
         "pass": len(big) >= REQ["strategies"] and corr is not None and corr < REQ["max_corr"]},
        {"id": "t_stat", "title": "Statistical significance (t)", "value": st.get("t_stat", 0.0),
         "need": f"≥ {REQ['t_stat']}", "pass": n >= 30 and st.get("t_stat", 0.0) >= REQ["t_stat"]},
        {"id": "profit_factor", "title": "Profit factor after haircut", "value": st.get("profit_factor", 0.0),
         "need": f"≥ {REQ['profit_factor']}", "pass": n >= 30 and st.get("profit_factor", 0.0) >= REQ["profit_factor"]},
        {"id": "drawdown", "title": "Max drawdown (realistic)", "value": st.get("max_dd") if have_equity else None,
         "need": f"Verified opening equity and drawdown ≤ {REQ['max_dd']:.0%}",
         "pass": have_equity and n >= 30 and st.get("max_dd", 1.0) <= REQ["max_dd"]},
        {"id": "stability", "title": "Profitable time thirds", "value": f"{st.get('stable_thirds', 0)}/3",
         "need": f"≥ {REQ['stable_thirds']}/3", "pass": n >= 30 and st.get("stable_thirds", 0) >= REQ["stable_thirds"]},
        {"id": "consistency", "title": "Live consistent with out-of-sample", "value": ", ".join(diverging) or "ok",
         "need": "OOS expectations and sufficient consistent demo evidence", "pass": bool(prod) and not diverging},
    ]
    passed = sum(c["pass"] for c in checks)
    # Indicative only: every non-test strategy trade (includes exploration; selection-biased)
    allt = reg.q("SELECT * FROM live_trades WHERE sleeve_id NOT LIKE 'exec-test%' ORDER BY close_date")
    return {"ts": iso(), "ready": passed == len(checks), "passed": passed, "total": len(checks),
            "checks": checks, "evidence": st, "production": [s["id"] for s in prod],
            "slippage_per_side": SLIPPAGE_PER_SIDE, "indicative_all_trades": _stats(allt, equity),
            "note": "Advisory only. Evidence = post-promotion demo trades of production strategies, "
                    "haircut for slippage the demo cannot simulate. The system never switches to real money itself."}


def update(reg: Registry, equity: float | None = None) -> dict:
    r = evaluate(reg, equity)
    old = reg.kv_get("readiness") or {}
    if old and old.get("passed") != r["passed"]:
        reg.event("readiness", f"real-money readiness {r['passed']}/{r['total']} checks"
                  + (" — READY for a small pilot (owner decides)" if r["ready"] else ""),
                  "warning" if r["ready"] else "info")
    reg.kv_set("readiness", r)
    return r
