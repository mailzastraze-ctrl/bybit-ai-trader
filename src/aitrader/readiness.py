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
  diversified    ≥ 2 strategies with ≥ 50 trades each, daily PnL correlation < 0.5
  t_stat         per-trade t-statistic ≥ 2.5 (realistic returns)
  t_daily        daily t-statistic ≥ 2.5 with a Newey–West correction: trades of one day (all
                 shorts in one sell-off) are one bet, not many – required together with t_stat
  alpha          alpha over BTC with t ≥ 2.0 (Newey–West): the profit is not just market beta
  profit_factor  ≥ 1.3 (realistic)
  drawdown       max drawdown ≤ 10% of equity (realistic PnL curve)
  stability      profitable in ≥ 2 of 3 equal time thirds
  consistency    no strategy's live results diverge from its out-of-sample expectation
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from aitrader import evidence as EV
from aitrader.realism import SLIPPAGE_PER_SIDE, real_pnl, real_ratio
from aitrader.registry import Registry
from aitrader.util import iso, parse_dt, utcnow

REQ = {"forward_days": 90, "trades": 250, "strategies": 2, "per_strategy": 50, "max_corr": 0.5,
       "t_stat": 2.5, "t_daily": 2.5, "alpha_t": 2.0, "min_days": 30,
       "profit_factor": 1.3, "max_dd": 0.10, "stable_thirds": 2}


def _stats(trades: list[dict], equity: float) -> dict:
    if not trades:
        return {"trades": 0}
    pnl = np.array([real_pnl(t) for t in trades])
    raw = np.array([float(t.get("profit_abs") or 0.0) for t in trades])
    ret = np.array([real_ratio(t) for t in trades])
    gains, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    pf = float(gains / losses) if losses > 0 else (99.0 if gains > 0 else 0.0)
    sd = ret.std(ddof=1) if len(ret) > 1 else 0.0
    t = float(ret.mean() / sd * math.sqrt(len(ret))) if sd > 0 else 0.0
    curve = equity + np.cumsum(pnl)
    peak = np.maximum.accumulate(np.r_[equity, curve])[1:]
    dd = float(((peak - curve) / np.maximum(peak, 1e-9)).max()) if len(curve) else 0.0
    thirds = np.array_split(pnl, 3) if len(pnl) >= 3 else [pnl]
    return {"trades": len(trades), "pnl_real": round(float(pnl.sum()), 2), "pnl_demo": round(float(raw.sum()), 2),
            "haircut": round(float(raw.sum() - pnl.sum()), 2), "profit_factor": round(pf, 3),
            "t_stat": round(t, 2), "max_dd": round(dd, 4), "win_rate": round(float((pnl > 0).mean()), 3),
            "stable_thirds": int(sum(1 for x in thirds if len(x) and x.sum() > 0))}


def _max_corr(by_sleeve: dict[str, list[dict]]) -> float | None:
    big = {k: v for k, v in by_sleeve.items() if len(v) >= REQ["per_strategy"]}
    if len(big) < 2:
        return None
    daily = {}
    for k, ts in big.items():
        s = pd.Series([real_pnl(t) for t in ts], index=pd.to_datetime([t["close_date"] for t in ts], utc=True))
        daily[k] = s.resample("1D").sum()
    df = pd.DataFrame(daily).fillna(0.0)
    if len(df) < 20:
        return None
    c = df.corr().to_numpy().copy()
    np.fill_diagonal(c, np.nan)
    return round(float(np.nanmax(c)), 3)


def evaluate(reg: Registry, equity: float | None = None) -> dict:
    from aitrader.lifecycle import Lifecycle  # local import: lifecycle imports learner → realism
    equity = float(equity or reg.kv_get("last_equity", 0.0) or 10_000.0)
    prod = reg.strategies(("production",))
    evidence, by_sleeve, start = [], {}, None
    for s in prod:
        since = s.get("stage_since") or ""
        rows = reg.q("SELECT * FROM live_trades WHERE sleeve_id=? AND close_date >= ? ORDER BY close_date",
                     (s["id"], since))
        evidence += rows
        by_sleeve[s["id"]] = rows
        st = parse_dt(since)
        if st and (start is None or st < start):
            start = st
    evidence.sort(key=lambda t: t.get("close_date") or "")
    st = _stats(evidence, equity)
    days = (utcnow() - start).total_seconds() / 86400 if start else 0.0
    big = [k for k, v in by_sleeve.items() if len(v) >= REQ["per_strategy"]]
    corr = _max_corr(by_sleeve)
    life = Lifecycle.__new__(Lifecycle)
    life.reg = reg
    diverging = [s["id"] for s in prod if Lifecycle.diverges(life, s)]
    n = st.get("trades", 0)
    daily = EV.daily_returns(evidence, equity, real_pnl, end=utcnow())
    t_daily = round(EV.newey_west_t(daily.to_numpy()), 2) if len(daily) else 0.0
    btc = EV.btc_returns(reg.kv_get("btc_daily"))
    ab = EV.alpha_beta(daily, btc, min_days=REQ["min_days"]) if len(daily) and len(btc) else {"alpha_t": None}
    alpha_val = (f"t {ab['alpha_t']}, β {ab['beta']}" if ab.get("alpha_t") is not None
                 else ("нет данных BTC" if not len(btc) else f"{len(daily)} дн."))
    st["t_daily"], st["days"] = t_daily, len(daily)
    st["alpha"] = {k: ab.get(k) for k in ("alpha_ann", "beta", "alpha_t", "days")}
    checks = [
        {"id": "forward_days", "title": "Post-promotion forward test", "value": round(days, 1),
         "need": f"≥ {REQ['forward_days']} days", "pass": days >= REQ["forward_days"]},
        {"id": "trades", "title": "Closed trades (evidence)", "value": n, "need": f"≥ {REQ['trades']}",
         "pass": n >= REQ["trades"]},
        {"id": "diversified", "title": "Independent strategies", "value": f"{len(big)} (corr {corr if corr is not None else '–'})",
         "need": f"≥ {REQ['strategies']} with ≥ {REQ['per_strategy']} trades, corr < {REQ['max_corr']}",
         "pass": len(big) >= REQ["strategies"] and corr is not None and corr < REQ["max_corr"]},
        {"id": "t_stat", "title": "Statistical significance (t)", "value": st.get("t_stat", 0.0),
         "need": f"≥ {REQ['t_stat']}", "pass": n >= 30 and st.get("t_stat", 0.0) >= REQ["t_stat"]},
        {"id": "t_daily", "title": "Significance by day (Newey–West)", "value": t_daily,
         "need": f"≥ {REQ['t_daily']} over ≥ {REQ['min_days']} days",
         "pass": len(daily) >= REQ["min_days"] and t_daily >= REQ["t_daily"]},
        {"id": "alpha", "title": "Alpha over BTC (not just market beta)", "value": alpha_val,
         "need": f"alpha > 0, t ≥ {REQ['alpha_t']}",
         "pass": ab.get("alpha_t") is not None and (ab.get("alpha") or 0) > 0 and ab["alpha_t"] >= REQ["alpha_t"]},
        {"id": "profit_factor", "title": "Profit factor after haircut", "value": st.get("profit_factor", 0.0),
         "need": f"≥ {REQ['profit_factor']}", "pass": n >= 30 and st.get("profit_factor", 0.0) >= REQ["profit_factor"]},
        {"id": "drawdown", "title": "Max drawdown (realistic)", "value": st.get("max_dd", 0.0),
         "need": f"≤ {REQ['max_dd']:.0%}", "pass": n >= 30 and st.get("max_dd", 1.0) <= REQ["max_dd"]},
        {"id": "stability", "title": "Profitable time thirds", "value": f"{st.get('stable_thirds', 0)}/3",
         "need": f"≥ {REQ['stable_thirds']}/3", "pass": n >= 30 and st.get("stable_thirds", 0) >= REQ["stable_thirds"]},
        {"id": "consistency", "title": "Live consistent with out-of-sample", "value": ", ".join(diverging) or "ok",
         "need": "no divergence", "pass": bool(prod) and not diverging},
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
