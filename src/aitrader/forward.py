"""Forward test of the whole research output ("shadow book").

Question this answers within days to weeks: *does the research find edges that keep
working on data nobody has seen yet?*

Every finished walk-forward experiment is frozen at the moment it finished (parameters
and pairs never change afterwards). Each research-lab run backtests every frozen
strategy on real Bybit candles **after its freeze time only** – genuinely unseen data –
with fees plus the demo→reality slippage haircut. That yields hundreds of forward trades
a week instead of the handful the demo account can carry, and it includes the weak
candidates too, so the system can test whether its own ranking predicts the future.

Pre-registered verdict (fixed before any forward data existed – do not tune):
  ranking by the backtest score known at freeze time → top quartile ("Q1") vs the rest
  * too early   – Q1 < 100 forward trades or < 7 forward days
  * early read  – ≥ 100 trades and ≥ 7 days: direction only, no conclusion
  * works       – Q1 ≥ 200 trades, ≥ 14 days, PF ≥ 1.15 after costs, daily t ≥ 2.0
  * not working – Q1 ≥ 200 trades, ≥ 14 days, and PF < 1.0 or mean return ≤ 0
  * inconclusive otherwise
Daily t-statistic: Q1 trades are pooled into an equal-weight daily return series, so many
correlated trades on the same day are not counted as independent evidence.

Strategies that individually prove themselves forward (≥ 20 trades, PF ≥ 1.3 after costs,
positive) become `exploratory` candidates and can receive small demo capital.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta

from aitrader.registry import Registry
from aitrader.util import iso, parse_dt, utcnow

BOOK_LIMIT = 120
BOOK_MAX_AGE_DAYS = 60
RULES = {"early_trades": 100, "early_days": 7, "final_trades": 200, "final_days": 14,
         "pf_works": 1.15, "t_works": 2.0}
PROMOTE = {"trades": 20, "pf": 1.3}


# ---------------------------------------------------------------------------- server: the book
def book(reg: Registry, limit: int = BOOK_LIMIT, max_age_days: int = BOOK_MAX_AGE_DAYS) -> list[dict]:
    """Frozen strategies for the lab to forward-test (newest experiments first)."""
    since = iso(utcnow() - timedelta(days=max_age_days))
    out = []
    for r in reg.q("SELECT id, family, spec, result, finished FROM experiments WHERE status='done' "
                   "AND finished >= ? ORDER BY finished DESC", (since,)):
        res, spec = r.get("result") or {}, r.get("spec") or {}
        if not isinstance(res, dict) or not res.get("params") or not r.get("finished"):
            continue
        if spec.get("revalidates"):
            continue  # a re-test of an existing strategy, not a new frozen hypothesis
        pairs = res.get("pairs") or (spec.get("pairs") or [])[:8]
        if not pairs:
            continue
        oos = res.get("oos") or {}
        out.append({"id": r["id"], "family": r["family"], "params": res["params"], "pairs": pairs,
                    "sides": spec.get("sides", ["long", "short"]), "freeze": r["finished"],
                    "score": float(res.get("score") or 0.0), "verdict": res.get("verdict"),
                    "bt_pf": oos.get("profit_factor"), "bt_trades": oos.get("trades"),
                    "variant": res.get("variant") or r["family"]})
        if len(out) >= limit:
            break
    # candidates imported as strategies (e.g. offline batches) whose experiment isn't stored here
    seen = {e["id"] for e in out}
    for st in reg.q("SELECT id, experiment_id, family, params, pairs, sides, score, stage, oos, created FROM strategies "
                    "WHERE created >= ? AND stage != 'retired' ORDER BY created DESC", (since,)):
        if len(out) >= limit or st.get("experiment_id") in seen or not st.get("params") or not st.get("pairs") \
                or str(st["id"]).startswith(("fw-", "boot-", "rnd-", "exec-test")):
            continue
        oos = st.get("oos") or {}
        out.append({"id": st["id"], "kind": "strategy", "family": st["family"], "params": st["params"],
                    "pairs": st["pairs"][:8], "sides": st.get("sides") or ["long", "short"], "freeze": st["created"],
                    "score": float(st.get("score") or 0.0), "verdict": st.get("stage"), "bt_pf": oos.get("profit_factor"),
                    "bt_trades": oos.get("trades"), "variant": oos.get("variant") or st["family"]})
    return out


# ---------------------------------------------------------------------------- stats (pure)
def _pf(xs: list[float]) -> float | None:
    g, lo = sum(x for x in xs if x > 0), -sum(x for x in xs if x < 0)
    return round(g / lo, 3) if lo > 0 else None


def _t(xs: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return round(m / sd * math.sqrt(n), 2) if sd > 0 else 0.0


def _spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 8:
        return None

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for k, i in enumerate(order):
            r[i] = float(k)
        return r
    ra, rb = ranks(a), ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return round(cov / (va * vb), 3) if va > 0 and vb > 0 else None


def _group(rows: list[dict]) -> dict:
    trades = [t for r in rows for t in r.get("trades", [])]
    rets = [t[1] for t in trades]
    days: dict[str, list[float]] = defaultdict(list)
    per_strat_day: dict[tuple, float] = defaultdict(float)
    for r in rows:
        for ts, x in r.get("trades", []):
            per_strat_day[(r["id"], ts[:10])] += x
    for (_sid, d), x in per_strat_day.items():
        days[d].append(x)
    n_strats = max(len(rows), 1)
    daily = [sum(v) / n_strats for _, v in sorted(days.items())]  # equal weight across the group
    return {"strategies": len(rows), "trades": len(rets), "pnl_pct": round(sum(rets) * 100, 3),
            "pf": _pf(rets), "win_rate": round(sum(1 for x in rets if x > 0) / len(rets), 3) if rets else None,
            "mean_bp": round(sum(rets) / len(rets) * 1e4, 2) if rets else None,
            "t_daily": _t(daily), "days_with_trades": len(daily)}


def summarize(results: list[dict], now=None) -> dict:
    """results: [{id, score, freeze, trades: [[close_ts, return_on_10k], ...], ...}]"""
    now = now or utcnow()
    rows = [r for r in results if r.get("ok", True)]
    rows.sort(key=lambda r: -float(r.get("score") or 0.0))
    q = max(1, len(rows) // 4)
    top, rest = rows[:q], rows[q:]
    freezes = [parse_dt(r.get("freeze")) for r in rows if parse_dt(r.get("freeze"))]
    fwd_days = round((now - min(freezes)).total_seconds() / 86400, 1) if freezes else 0.0
    g_top, g_rest, g_all = _group(top), _group(rest), _group(rows)
    ev = [(float(r.get("score") or 0.0), sum(t[1] for t in r.get("trades", [])))
          for r in rows if len(r.get("trades", [])) >= 5]
    rho = _spearman([a for a, _ in ev], [b for _, b in ev])
    n, R = g_top["trades"], RULES
    if n < R["early_trades"] or fwd_days < R["early_days"]:
        verdict, text = "too_early", (f"Too early: {n} forward trades in the top quartile over {fwd_days} days "
                                      f"(first read at {R['early_trades']} trades and {R['early_days']} days).")
    elif n < R["final_trades"] or fwd_days < R["final_days"]:
        lean = "positive" if (g_top["pf"] or 0) > 1.0 and g_top["pnl_pct"] > 0 else "negative"
        verdict, text = f"early_{lean}", (f"Early read ({n} trades, {fwd_days} days): leaning {lean}. "
                                          f"Decision at {R['final_trades']} trades and {R['final_days']} days.")
    elif (g_top["pf"] or 0) >= R["pf_works"] and g_top["t_daily"] >= R["t_works"]:
        verdict, text = "works", (f"Works: top-quartile strategies keep their edge on unseen data "
                                  f"(PF {g_top['pf']} after costs, daily t {g_top['t_daily']}, {n} trades).")
    elif (g_top["pf"] or 0) < 1.0 or g_top["pnl_pct"] <= 0:
        verdict, text = "not_working", (f"Not working: the best-ranked strategies lose on unseen data "
                                        f"(PF {g_top['pf']}, {n} trades). The search is finding noise – new "
                                        "data sources/ideas are needed, not more of the same.")
    else:
        verdict, text = "inconclusive", (f"Inconclusive: positive but not significant yet (PF {g_top['pf']}, "
                                         f"daily t {g_top['t_daily']}, {n} trades). Keep collecting.")
    best = sorted(({"id": r["id"], "variant": r.get("variant"), "family": r.get("family"),
                    "trades": len(r.get("trades", [])), "pnl_pct": round(sum(t[1] for t in r.get("trades", [])) * 100, 3),
                    "pf": _pf([t[1] for t in r.get("trades", [])]), "score": r.get("score"),
                    "freeze": r.get("freeze"), "bt_pf": r.get("bt_pf")} for r in rows),
                  key=lambda x: (-x["pnl_pct"], -x["trades"]))
    return {"ts": iso(now), "verdict": verdict, "text": text, "rules": R, "forward_days": fwd_days,
            "top": g_top, "rest": g_rest, "all": g_all, "rank_corr": rho, "n_strategies": len(rows),
            "best": best[:15], "worst": best[-5:][::-1] if len(best) > 15 else []}


def persistence(reg: Registry, max_age_days: int = 90) -> dict:
    """Immediate indicator from history: does a positive first half of the walk-forward
    holdout predict a positive second half? (each fold re-optimized on its own past)."""
    since = iso(utcnow() - timedelta(days=max_age_days))
    a_pos = a_pos_next = a_neg = a_neg_next = 0
    firsts, seconds = [], []
    for r in reg.q("SELECT result FROM experiments WHERE status='done' AND finished >= ?", (since,)):
        folds = [(f.get("oos") or {}).get("total_return") for f in ((r.get("result") or {}).get("folds") or [])]
        folds = [float(x) for x in folds if x is not None]
        if len(folds) < 4:
            continue
        h = len(folds) // 2
        f1, f2 = sum(folds[:h]), sum(folds[h:])
        firsts.append(f1)
        seconds.append(f2)
        if f1 > 0:
            a_pos += 1
            a_pos_next += f2 > 0
        else:
            a_neg += 1
            a_neg_next += f2 > 0
    return {"experiments": len(firsts),
            "p_second_pos_if_first_pos": round(a_pos_next / a_pos, 3) if a_pos else None,
            "p_second_pos_if_first_neg": round(a_neg_next / a_neg, 3) if a_neg else None,
            "rank_corr": _spearman(firsts, seconds), "n_first_pos": a_pos, "n_first_neg": a_neg}


# ---------------------------------------------------------------------------- server: import
def apply(reg: Registry, payload: dict) -> dict:
    """Store the lab's forward results, recompute the verdict, promote forward winners."""
    results = payload.get("results") or []
    prev = reg.kv_get("forward_results") or {}
    for r in results:  # every run re-tests from the freeze time, so the newest result supersedes
        if r.get("ok", True):
            prev[r["id"]] = r
    live_ids = {e["id"] for e in book(reg, limit=10_000)}
    prev = {k: v for k, v in prev.items() if k in live_ids}
    reg.kv_set("forward_results", prev)
    summ = summarize(list(prev.values()))
    summ["persistence"] = persistence(reg)
    summ["errors"] = sum(1 for r in results if not r.get("ok", True))
    old = (reg.kv_get("forward") or {}).get("verdict")
    reg.kv_set("forward", summ)
    if old != summ["verdict"]:
        reg.event("research", f"forward test: {summ['text']}", "info", data={"forward": summ["verdict"]})
    promoted = _promote(reg, list(prev.values()))
    return {"strategies": len(prev), "verdict": summ["verdict"], "promoted": promoted}


def _promote(reg: Registry, rows: list[dict]) -> int:
    n, now = 0, iso()
    for r in rows:
        if r.get("kind") == "strategy":
            continue  # already a strategy with its own lifecycle
        xs = [t[1] for t in r.get("trades", [])]
        pf = _pf(xs)
        if len(xs) < PROMOTE["trades"] or sum(xs) <= 0 or pf is None or pf < PROMOTE["pf"]:
            continue
        sid = f"fw-{r['id'][1:9]}"
        if reg.one("SELECT id FROM strategies WHERE id=?", (sid,)):
            continue
        e = reg.one("SELECT family, spec, result FROM experiments WHERE id=?", (r["id"],))
        if not e:
            continue
        res = e.get("result") or {}
        note = (f"forward-proven: {len(xs)} trades on unseen Bybit data after {r.get('freeze', '')[:16]}, "
                f"PF {pf} after costs")
        reg.upsert("strategies", {
            "id": sid, "experiment_id": r["id"], "family": e["family"], "params": res.get("params") or {},
            "pairs": r.get("pairs") or res.get("pairs") or [], "sides": (e.get("spec") or {}).get("sides", ["long", "short"]),
            "stage": "exploratory", "score": round(float(res.get("score") or 0) + min(pf, 3.0), 4),
            "oos": {**(res.get("oos") or {}), "forward": {"trades": len(xs), "pf": pf, "pnl_pct": round(sum(xs) * 100, 3)},
                    "variant": res.get("variant")},
            "gates": res.get("gates") or {}, "live": {}, "created": now, "updated": now, "stage_since": now,
            "history": [{"ts": now, "to": "exploratory", "reason": note}], "note": note})
        reg.event("lifecycle", f"{sid} ({res.get('variant')}) {note} → exploratory (demo capital)",
                  data={"strategy": sid})
        n += 1
    return n
