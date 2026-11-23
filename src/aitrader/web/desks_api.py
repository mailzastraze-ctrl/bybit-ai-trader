"""Coin desks in the control room: which strategy trades which coin, its live record on that
coin, and the coin's list of best tested strategies for the owner to choose from."""

from __future__ import annotations

import time

from aitrader import desks as D
from aitrader.lifecycle import Lifecycle
from aitrader.registry import Registry
from aitrader.util import parse_dt
from aitrader.web import names as N

_cache: dict = {}
CACHE_S = 600


def _pf(xs: list[float]) -> float | None:
    g, lo = sum(x for x in xs if x > 0), -sum(x for x in xs if x < 0)
    return round(g / lo, 2) if lo > 0 else (None if not g else 99.0)


def evidence(life: Lifecycle) -> dict:
    """Every tested strategy's record per coin – a few hundred experiment results, so cached
    until the next lab import (or 10 minutes)."""
    key = (life.reg.kv_get("lab") or {}).get("last_import")
    hit = _cache.get("ev")
    if hit and hit[0] == key and time.time() - hit[1] < CACHE_S:
        return hit[2]
    ev = life.desk_evidence()
    _cache["ev"] = (key, time.time(), ev)
    return ev


def _live(reg: Registry, since: str | None) -> dict[tuple, list[float]]:
    """Closed trades per (strategy, coin) opened in this experiment (owner, 23.11: everything starts anew)."""
    out: dict[tuple, list[float]] = {}
    for r in reg.q("SELECT sleeve_id, pair, profit_abs, open_date FROM live_trades"):
        od = parse_dt(r.get("open_date"))
        if since and (od is None or od < parse_dt(since)):
            continue
        out.setdefault((r["sleeve_id"], r["pair"]), []).append(float(r["profit_abs"] or 0))
    return out


def _label(nm: dict, sid: str) -> dict:
    n = nm.get(sid) or {}
    return {"code": n.get("code"), "method": n.get("method") or sid}


def overview(reg: Registry, open_trades: list[dict]) -> dict:
    st = reg.kv_get("desks") or {}
    nm = N.names(reg)
    live = _live(reg, st.get("created"))
    pos = {t.get("pair"): t for t in open_trades or [] if isinstance(t, dict)}
    rows = []
    for pair, d in (st.get("coins") or {}).items():
        ps = []
        for x in D.picks(d):
            xs = live.get((x["strategy"], pair), [])
            ps.append({"id": x["strategy"], **_label(nm, x["strategy"]), "timeframe": x.get("timeframe"),
                       "bucket": x.get("bucket"), "per_month": x.get("per_month"), "pnl_month": x.get("pnl_month"),
                       "max_dd": x.get("max_dd"), "oos_trades": x.get("oos_trades"), "manual": bool(x.get("manual")),
                       "demo": {"trades": len(xs), "pnl": round(sum(xs), 2), "pf": _pf(xs),
                                "wins": sum(1 for v in xs if v > 0)}})
        t = pos.get(pair)
        rows.append({"pair": pair, "coin": D.coin_name(pair), "picks": ps, "manual": bool(d.get("manual")),
                     "position": None if not t else {
                         "side": "short" if t.get("is_short") else "long", "tag": t.get("enter_tag"),
                         **_label(nm, t.get("enter_tag") or ""), "profit_abs": t.get("profit_abs"),
                         "profit_ratio": t.get("profit_ratio"), "open_date": t.get("open_date")}})
    return {"epoch": st.get("epoch"), "created": st.get("created"), "summary": D.summary(st.get("coins") or {}),
            "desks": rows}


def options(life: Lifecycle, pair: str) -> dict:
    """The coin's list of best tested strategies, best first, with what is chosen now."""
    reg = life.reg
    st = reg.kv_get("desks") or {}
    chosen = {x["strategy"] for x in D.picks((st.get("coins") or {}).get(pair) or {})}
    elsewhere = {x["strategy"]: p for p, d in (st.get("coins") or {}).items() if p != pair for x in D.picks(d)}
    ev = evidence(life)
    cuts = tuple(st.get("cuts") or ()) or None
    opts = sorted((o for o in ev.get(pair, []) if o.qualifies()), key=lambda o: (-o.score, tuple(-x for x in o.rank)))
    if cuts is None:
        cuts = D.bucket_cuts(opts)
    nm = N.names(reg)
    rows = []
    for i, o in enumerate(opts, 1):
        r = reg.one("SELECT stage, oos FROM strategies WHERE id=?", (o.strategy,)) or {}
        oos = r.get("oos") or {}
        rows.append({"rank": i, "id": o.strategy, **_label(nm, o.strategy), "family": o.family, "timeframe": o.timeframe,
                     "bucket": D.bucket(o.per_month, cuts), "per_month": round(o.per_month, 2),
                     "pnl_month": round(o.pnl_month, 2), "max_dd": round(o.dd, 4), "score": round(o.score, 2),
                     "oos_trades": o.trades, "pf_all": oos.get("profit_factor"), "stage": r.get("stage"),
                     "chosen": o.strategy in chosen, "elsewhere": D.coin_name(elsewhere[o.strategy]) if o.strategy in elsewhere else None})
    return {"pair": pair, "coin": D.coin_name(pair), "options": rows}


def coins(life: Lifecycle) -> list[dict]:
    """Coins with at least one qualifying tested strategy, for adding a desk."""
    st = life.reg.kv_get("desks") or {}
    have = {p for p, d in (st.get("coins") or {}).items() if D.picks(d)}
    out = []
    for pair, xs in evidence(life).items():
        q = [o for o in xs if o.qualifies()]
        if q:
            out.append({"pair": pair, "coin": D.coin_name(pair), "options": len(q), "desk": pair in have,
                        "best_score": round(max(o.score for o in q), 2)})
    return sorted(out, key=lambda r: -r["best_score"])


def set_desk(life: Lifecycle, pair: str, ids: list[str]) -> dict:
    _cache.pop("ev", None)  # stages change: rebuild the evidence on the next request
    return life.set_desk(pair, ids)
