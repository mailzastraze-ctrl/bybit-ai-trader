"""Forward test of the whole research output ("shadow book").

Question this answers within days to weeks: *does the research find edges that keep
working on data nobody has seen yet?*

Every finished walk-forward experiment is frozen at the moment it finished (parameters
and pairs never change afterwards). Each research-lab run backtests every frozen
strategy on real Bybit candles **after its freeze time only** – genuinely unseen data –
with fees plus the demo→reality slippage haircut. That yields hundreds of forward trades
a week instead of the handful the demo account can carry, and it includes the weak
candidates too, so the system can test whether its own ranking predicts the future.

Pre-registered verdict, v2 (amended 2026-11-21 while the book had 1 completed forward
trade, i.e. before any decision-relevant data existed; the amendment only makes "works"
harder to reach – do not tune further):
  ranking by the backtest score known at freeze time → top quartile ("Q1") vs the rest
  * too early   – Q1 < 100 forward trades or < 7 forward days
  * early read  – ≥ 100 trades and ≥ 7 days but < 90 days: direction only, no conclusion
  * works       – Q1 ≥ 200 trades, ≥ 90 days, PF ≥ 1.15 after costs, and daily t at or above
                  the anytime-valid threshold (evidence.anytime_t_boundary: 3.26 at 90 daily
                  observations, 2.79 at a year). The verdict is recomputed after every lab
                  run, so a fixed t ≥ 2 would be crossed by luck far more often than 5 %.
  * not working – Q1 ≥ 200 trades, ≥ 90 days, and PF < 1.0 or mean return ≤ 0
  * inconclusive otherwise
v1 used 14 days and a fixed t ≥ 2.0: for a real edge of Sharpe 1.5, 30 days give a 6 % chance
of "works" and a 33 % chance of "not working" – a coin flip, not evidence.
Daily t-statistic: Q1 trades are pooled into an equal-weight daily return series, so many
correlated trades on the same day are not counted as independent evidence.

What is tested, and how days are counted (audit 2026-11-22). The question is the quality of the
*continuous research process*: does the top quartile of what it freezes keep its edge during each
strategy's book life (60 days after its freeze) on data nobody has seen? It is not a fixed cohort
followed for 90 days. Each record is observed only from its freeze to `tested_until` (the last lab
run that re-tested it). "Days" in the rule are *observed* days: the calendar time covered by at
least one top-quartile strategy under test. A record that left the book still counts for the days
it was observed and adds nothing afterwards; the calendar age of the oldest freeze is reported
apart (`calendar_days`) and decides nothing. The daily series weighs equally the strategies under
test that day (a day under test without trades is a 0, a strategy not yet frozen or no longer
tested is absent), and the benchmark is compared on the same observed days only.

Objective comparison (does not change the verdict):
  * benchmark – a pre-registered fixed TSMOM configuration (research/external/benchmark-*.json)
    stays in the book permanently and is reported next to Q1: research must beat it;
  * alpha vs BTC – the Q1 daily series regressed on BTC daily returns (beta, alpha, its t);
  * leaderboard – per-strategy means shrunk towards the book mean (empirical Bayes), so a
    lucky handful of trades does not outrank a long steady record.

Strategies that individually prove themselves forward (≥ 20 trades, PF ≥ 1.3 after costs,
positive) become `exploratory` candidates and can receive small demo capital.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd

from aitrader import evidence as EV
from aitrader.registry import Registry
from aitrader.util import iso, parse_dt, utcnow

BOOK_LIMIT = 160
BOOK_MAX_AGE_DAYS = 60
# Research candidates (validated/exploratory, best score first) and strategies with a promising
# forward record keep their place for their whole 60-day book life, so their forward evidence
# accumulates. Before 2026-11-21 the book was simply the newest 120 experiments: ~2 lab runs,
# so every strategy was forward-tested for only a few hours and then dropped out.
BOOK_KEEP = 100
# A strategy is re-tested for its 60-day book life, but its forward record is kept longer: its
# observed days stay evidence, and the decision needs `final_days` (90) *observed* days of the
# top quartile – covered by a continuous research process, not by the age of old records (see
# the docstring). Until 2026-11-22 records were deleted when a strategy left the book, so the
# 90-day rule could never be reached. Records are dropped this many days after their freeze.
RECORD_KEEP_DAYS = 120  # longer than the 90-day window, bounded store
RULES = {"version": 2, "early_trades": 100, "early_days": 7, "final_trades": 200, "final_days": 90,
         "pf_works": 1.15, "t_works": EV.T_FLOOR, "t_rule": "anytime-valid (normal mixture, ρ = 90 days, α = 5 %)"}
PROMOTE = {"trades": 20, "pf": 1.3}


# ---------------------------------------------------------------------------- server: the book
def book(reg: Registry, limit: int = BOOK_LIMIT, max_age_days: int = BOOK_MAX_AGE_DAYS,
         keep: int = BOOK_KEEP) -> list[dict]:
    """Frozen strategies for the lab to forward-test: the research candidates and the
    forward-promising strategies first (they stay for their whole book life, so their forward
    record grows), then the newest experiments (a first look at every new hypothesis, weak
    ones included – the test is whether the research ranking predicts the future)."""
    since = iso(utcnow() - timedelta(days=max_age_days))
    exps = []
    benchmarks = {st["id"] for st in reg.strategies() if (st.get("oos") or {}).get("benchmark")}
    for r in reg.q("SELECT id, family, spec, result, finished FROM experiments WHERE status='done' "
                   "AND finished >= ? ORDER BY finished DESC", (since,)):
        res, spec = r.get("result") or {}, r.get("spec") or {}
        if not isinstance(res, dict) or not res.get("params") or not r.get("finished"):
            continue
        if spec.get("revalidates"):
            continue  # a re-test of an existing strategy, not a new frozen hypothesis
        if spec.get("external") in benchmarks:
            continue  # the benchmark's own replication run: the benchmark is in the book once, as itself
        pairs = res.get("pairs") or (spec.get("pairs") or [])[:8]
        if not pairs:
            continue
        oos = res.get("oos") or {}
        exps.append({"id": r["id"], "family": r["family"], "params": res["params"], "pairs": pairs,
                     "sides": spec.get("sides", ["long", "short"]), "freeze": r["finished"],
                     "score": float(res.get("score") or 0.0), "verdict": res.get("verdict"),
                     "bt_pf": oos.get("profit_factor"), "bt_trades": oos.get("trades"),
                     "variant": res.get("variant") or r["family"],
                     "timeframe": res.get("timeframe") or spec.get("timeframe") or "1h"})
    promising = {b["id"] for b in ((reg.kv_get("forward") or {}).get("best") or [])
                 if (b.get("p_pos") or 0) >= 0.8 and (b.get("trades") or 0) >= 10}
    kept = sorted((e for e in exps if e["verdict"] in ("validated", "exploratory") or e["id"] in promising),
                  key=lambda e: (e["id"] not in promising, -e["score"]))[:min(keep, limit)]
    kept_ids = {e["id"] for e in kept}
    out = kept + [e for e in exps if e["id"] not in kept_ids][:max(limit - len(kept), 0)]
    # candidates imported as strategies (e.g. offline batches) whose experiment isn't stored here
    seen = {e["id"] for e in out}
    for st in reg.strategies():  # pre-registered benchmarks stay in the book for good
        oos = st.get("oos") or {}
        # also after a demo retirement: the shadow book judges it on data, not on its demo luck
        if oos.get("benchmark") and st["id"] not in seen and st.get("params"):
            out.append({"id": st["id"], "kind": "strategy", "benchmark": True, "family": st["family"],
                        "params": st["params"], "pairs": st.get("pairs") or [], "sides": st.get("sides") or ["long", "short"],
                        "freeze": st["created"], "score": 0.0, "verdict": st.get("stage"), "bt_pf": oos.get("profit_factor"),
                        "bt_trades": oos.get("trades"), "variant": oos.get("variant") or st["family"],
                        "timeframe": oos.get("timeframe") or "1h", "external": True})
            seen.add(st["id"])
    for h in (reg.kv_get("hypotheses") or {}).values():  # pre-registered hypotheses: shadow only, for good
        if h.get("id") in seen or not h.get("params"):
            continue
        out.append({"id": h["id"], "kind": "hypothesis", "hypothesis": h.get("hypothesis"), "family": h["family"],
                    "params": h["params"], "pairs": h.get("pairs") or [], "sides": h.get("sides") or ["long", "short"],
                    "freeze": h["freeze"], "score": 0.0, "verdict": "shadow", "bt_pf": None, "bt_trades": None,
                    "variant": f"{h.get('hypothesis')} {h['family']} {h.get('timeframe')}", "timeframe": h.get("timeframe") or "1h",
                    "external": True})
        seen.add(h["id"])
    for st in reg.q("SELECT id, experiment_id, family, params, pairs, sides, score, stage, oos, created FROM strategies "
                    "WHERE created >= ? AND stage != 'retired' ORDER BY created DESC", (since,)):
        if len(out) >= limit or st["id"] in seen or st.get("experiment_id") in seen or not st.get("params") or not st.get("pairs") \
                or str(st["id"]).startswith(("fw-", "boot-", "rnd-", "exec-test")):
            continue
        oos = st.get("oos") or {}
        out.append({"id": st["id"], "kind": "strategy", "family": st["family"], "params": st["params"],
                    "pairs": st["pairs"][:8], "sides": st.get("sides") or ["long", "short"], "freeze": st["created"],
                    "score": float(st.get("score") or 0.0), "verdict": st.get("stage"), "bt_pf": oos.get("profit_factor"),
                    "bt_trades": oos.get("trades"), "variant": oos.get("variant") or st["family"],
                    "timeframe": oos.get("timeframe") or "1h", "external": bool(oos.get("external"))})
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


def _window(r: dict, now: datetime) -> tuple[datetime, datetime] | None:
    """When a record was really observed: its freeze → the last lab run that re-tested it.
    Records stored before 2026-11-22 carry no `tested_until`: they count up to their last
    forward trade (never longer than the evidence shows)."""
    fz = parse_dt(r.get("freeze"))
    if fz is None:
        return None
    end = parse_dt(r.get("tested_until"))
    if end is None:
        closes = [parse_dt(t[0]) for t in r.get("trades", []) if t and t[0]]
        end = max((c for c in closes if c is not None), default=fz)
    return fz, min(max(end, fz), now)


def observed_days(rows: list[dict], now: datetime | None = None) -> float:
    """Calendar time covered by at least one record under test (union of the windows), in days."""
    now = now or utcnow()
    spans = sorted(w for w in (_window(r, now) for r in rows) if w)
    total, cur_a, cur_b = 0.0, None, None
    for a, b in spans:
        if cur_b is None or a > cur_b:
            if cur_b is not None:
                total += (cur_b - cur_a).total_seconds()
            cur_a, cur_b = a, b
        else:
            cur_b = max(cur_b, b)
    if cur_b is not None:
        total += (cur_b - cur_a).total_seconds()
    return round(total / 86400, 1)


def calendar_days(rows: list[dict], now: datetime | None = None) -> float:
    now = now or utcnow()
    fz = [parse_dt(r.get("freeze")) for r in rows if parse_dt(r.get("freeze"))]
    return round((now - min(fz)).total_seconds() / 86400, 1) if fz else 0.0


def _daily_series(rows: list[dict], now: datetime | None = None) -> dict[str, float]:
    """Equal-weight daily return over the strategies under test that day (0 for a day under test
    without trades). Days on which no member was under test are absent."""
    now = now or utcnow()
    pnl: dict[tuple, float] = defaultdict(float)
    active: dict[str, set] = defaultdict(set)
    for r in rows:
        for ts, x in r.get("trades", []):
            pnl[(r["id"], ts[:10])] += x
            active[ts[:10]].add(r["id"])
        w = _window(r, now)
        if w:
            d, last = w[0].date(), w[1].date()
            while d <= last:
                active[d.isoformat()].add(r["id"])
                d += timedelta(days=1)
    return {d: sum(pnl.get((sid, d), 0.0) for sid in ids) / len(ids) for d, ids in sorted(active.items())}


def versus(top: list[dict], bench: list[dict], min_days: int = 10, now: datetime | None = None) -> dict | None:
    """Interim signal for an observer: does the research's top quartile beat the fixed
    benchmark over the same days? Paired daily difference on the days both were under test
    (a day under test without trades counts as 0), its t and P(top better) under a normal
    approximation. Not a verdict – a direction with its uncertainty."""
    a, b = _daily_series(top, now), _daily_series(bench, now)
    days = sorted(set(a) & set(b))  # the same observed days only
    if len(days) < min_days:
        return None
    diff = [a[d] - b[d] for d in days]
    t = _t(diff)
    return {"days": len(days), "t": t, "p_top_better": round(0.5 * (1 + math.erf(t / math.sqrt(2))), 3),
            "top_pct": round(sum(a[d] for d in days) * 100, 3), "bench_pct": round(sum(b[d] for d in days) * 100, 3)}


def _group(rows: list[dict], btc: pd.Series | None = None, now: datetime | None = None) -> dict:
    now = now or utcnow()
    trades = [t for r in rows for t in r.get("trades", [])]
    rets = [t[1] for t in trades]
    series = _daily_series(rows, now)  # equal weight across the members under test that day
    ordered = list(series.items())
    daily = [v for _, v in ordered]
    out = {"strategies": len(rows), "trades": len(rets), "pnl_pct": round(sum(rets) * 100, 3),
           "pf": _pf(rets), "win_rate": round(sum(1 for x in rets if x > 0) / len(rets), 3) if rets else None,
           "mean_bp": round(sum(rets) / len(rets) * 1e4, 2) if rets else None,
           "t_daily": _t(daily), "series_days": len(daily),
           "days_with_trades": len({ts[:10] for ts, _ in trades}), "observed_days": observed_days(rows, now)}
    if btc is not None and len(daily) >= 5:
        try:  # reporting only – never let it break the forward import
            y = pd.Series(daily, index=pd.to_datetime([d for d, _ in ordered], utc=True))
            ab = EV.alpha_beta(y, btc)
            out["beta"], out["alpha_t"] = ab["beta"], ab["alpha_t"]
            out["alpha_bp"] = round(ab["alpha"] * 1e4, 2) if ab["alpha"] is not None else None
        except Exception:  # noqa: BLE001
            out["beta"] = out["alpha_t"] = out["alpha_bp"] = None
    return out


def leaderboard(rows: list[dict], min_trades: int = 5) -> list[dict]:
    """Per-strategy forward record with the mean return shrunk towards the book mean
    (empirical Bayes), ranked by the conservative bound (posterior mean − 1 sd): what the
    evidence supports, not the luckiest streak."""
    means, ses, base = {}, {}, {}
    for r in rows:
        xs = [t[1] for t in r.get("trades", [])]
        base[r["id"]] = {"id": r["id"], "variant": r.get("variant"), "family": r.get("family"), "trades": len(xs),
                         "pnl_pct": round(sum(xs) * 100, 3), "pf": _pf(xs), "score": r.get("score"),
                         "freeze": r.get("freeze"), "bt_pf": r.get("bt_pf"), "benchmark": bool(r.get("benchmark")),
                         "hypothesis": r.get("hypothesis"),
                         "shrunk_bp": None, "lcb_bp": None, "p_pos": None}
        if len(xs) >= min_trades:
            m = sum(xs) / len(xs)
            sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
            if sd > 0:
                means[r["id"]], ses[r["id"]] = m, sd / math.sqrt(len(xs))
    for k, v in EV.shrink(means, ses).items():
        base[k]["shrunk_bp"], base[k]["lcb_bp"], base[k]["p_pos"] = (round(v["shrunk"] * 1e4, 2),
                                                                     round(v["lcb"] * 1e4, 2), v["p_pos"])
    return sorted(base.values(), key=lambda x: (x["lcb_bp"] is None, -(x["lcb_bp"] or 0.0), -x["trades"]))


def summarize(results: list[dict], now=None, btc: pd.Series | None = None) -> dict:
    """results: [{id, score, freeze, trades: [[close_ts, return_on_10k], ...], ...}]
    btc: optional BTC daily returns (evidence.btc_returns) for beta/alpha."""
    now = now or utcnow()
    rows_all = [r for r in results if r.get("ok", True)]
    bench = [r for r in rows_all if r.get("benchmark")]
    hyp = [r for r in rows_all if r.get("hypothesis")]
    # the verdict judges the research output only (not the benchmark, not the pre-registered hypotheses)
    rows = [r for r in rows_all if not r.get("benchmark") and not r.get("hypothesis")]
    rows.sort(key=lambda r: -float(r.get("score") or 0.0))
    q = max(1, len(rows) // 4)
    top, rest = rows[:q], rows[q:]
    cal_days = calendar_days(rows, now)  # age of the oldest freeze: reported, decides nothing
    g_top, g_rest, g_all = _group(top, btc, now), _group(rest, now=now), _group(rows, now=now)
    fwd_days = g_top["observed_days"]  # the rule's clock: days the top quartile was really under test
    g_bench = _group(bench, btc, now) if bench else None
    vs = versus(top, bench, now=now) if bench else None
    t_need = EV.anytime_t_boundary(g_top["series_days"])
    ev = [(float(r.get("score") or 0.0), sum(t[1] for t in r.get("trades", [])))
          for r in rows if len(r.get("trades", [])) >= 5]
    rho = _spearman([a for a, _ in ev], [b for _, b in ev])
    n, R = g_top["trades"], RULES
    if n < R["early_trades"] or fwd_days < R["early_days"]:
        verdict, text = "too_early", (f"Too early: {n} forward trades in the top quartile over {fwd_days} observed days "
                                      f"(first read at {R['early_trades']} trades and {R['early_days']} days).")
    elif n < R["final_trades"] or fwd_days < R["final_days"]:
        lean = "positive" if (g_top["pf"] or 0) > 1.0 and g_top["pnl_pct"] > 0 else "negative"
        verdict, text = f"early_{lean}", (f"Early read ({n} trades, {fwd_days} observed days of {cal_days} "
                                          f"calendar): leaning {lean}. Decision at {R['final_trades']} trades "
                                          f"and {R['final_days']} observed days.")
    elif (g_top["pf"] or 0) >= R["pf_works"] and g_top["t_daily"] >= t_need:
        verdict, text = "works", (f"Works: top-quartile strategies keep their edge on unseen data "
                                  f"(PF {g_top['pf']} after costs, daily t {g_top['t_daily']} ≥ {t_need}, {n} trades).")
    elif (g_top["pf"] or 0) < 1.0 or g_top["pnl_pct"] <= 0:
        verdict, text = "not_working", (f"Not working: the best-ranked strategies lose on unseen data "
                                        f"(PF {g_top['pf']}, {n} trades). The search is finding noise – new "
                                        "data sources/ideas are needed, not more of the same.")
    else:
        verdict, text = "inconclusive", (f"Inconclusive: positive but not significant yet (PF {g_top['pf']}, "
                                         f"daily t {g_top['t_daily']} of {t_need} needed, {n} trades). Keep collecting.")
    board = leaderboard(rows_all)
    families: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        families[r.get("family") or "?"].append(r)
    fam = {f: {k: g[k] for k in ("strategies", "trades", "pf", "mean_bp", "t_daily")}
           for f, g in ((f, _group(rs, now=now)) for f, rs in families.items()) if g["trades"]}
    if g_bench and g_bench["trades"]:
        text += f" Benchmark (fixed TSMOM): {g_bench['trades']} trades, PF {g_bench['pf']}"
        text += (f"; on the same {vs['days']} observed days benchmark {vs['bench_pct']}% vs top quartile "
                 f"{vs['top_pct']}%." if vs else ".")
    hyps = {}
    for name in sorted({r["hypothesis"] for r in hyp}):
        legs = [r for r in hyp if r["hypothesis"] == name]
        if name == "H1":  # its 30-day leg is the benchmark itself
            legs = legs + bench
        g = _group(legs, btc, now)
        hyps[name] = {**g, "legs": sorted(r["id"] for r in legs),
                      "forward_days": observed_days([r for r in legs if not r.get("benchmark")], now),
                      "vs_benchmark": versus(legs, bench, now=now) if bench else None}
    return {"ts": iso(now), "verdict": verdict, "text": text, "rules": R, "t_needed": t_need, "forward_days": fwd_days,
            "calendar_days": cal_days, "days_rule": "observed days of the top quartile (freeze → last re-test)",
            "top": g_top, "rest": g_rest, "all": g_all, "benchmark": g_bench, "vs_benchmark": vs, "families": fam,
            "hypotheses": hyps,
            "rank_corr": rho,
            "n_strategies": len(rows), "best": board[:15], "worst": board[-5:][::-1] if len(board) > 15 else []}


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
    now = utcnow()
    for r in results:  # every run re-tests from the freeze time, so the newest result supersedes
        if r.get("ok", True):
            # observed up to this run (the lab stamps its own test time; the import time otherwise)
            until = parse_dt(r.get("tested_until"))
            r["tested_until"] = iso(min(until, now) if until else now)
            prev[r["id"]] = r
    live_ids = {e["id"] for e in book(reg, limit=10_000)}
    keep_since = now - timedelta(days=RECORD_KEEP_DAYS)
    # strategies still in the book, and the records of those that left it (no longer re-tested,
    # their forward trades up to then stay evidence) until RECORD_KEEP_DAYS after their freeze
    prev = {k: v for k, v in prev.items()
            if k in live_ids or ((parse_dt(v.get("freeze")) or keep_since) > keep_since)}
    reg.kv_set("forward_results", prev)
    summ = summarize(list(prev.values()), now=now, btc=EV.btc_returns(reg.kv_get("btc_daily")) if reg.kv_get("btc_daily") else None)
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
        if r.get("kind") in ("strategy", "hypothesis") or r.get("hypothesis"):
            continue  # a strategy has its own lifecycle; a pre-registered hypothesis is shadow only
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
