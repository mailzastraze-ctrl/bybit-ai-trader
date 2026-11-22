"""Forward test v3, server side: record now, judge later (docs/DECISIONS.md).

What is recorded, from the first lab run after the deploy of 23.11.2026:
  * a ledger per frozen strategy of its value change per complete UTC day (research/marks.py).
    It is append-only: a published day never changes. A later run that computes another value for
    a published day is counted as a revision (and the published value is kept); a day that was
    `missing` may be filled later, since that publishes a day late rather than rewriting it.
  * the Q1 membership of each research strategy, decided once, from data that existed before its
    freeze: Q1 = score at or above the 75th percentile of the scores of every eligible experiment
    frozen in the 30 days before it (weak and evicted ones included). Fewer than Q1_MIN_REF
    reference experiments: `burn_in`, no membership. Never recomputed afterwards.
  * the days each strategy was scheduled (in the book served to the lab), the denominator of
    coverage: a scheduled day without a valid published value is missing, whatever the reason.
  * the "promising" set by day: the book decides which forward-promising strategies keep their
    place with the set from two days before, so whether a strategy is observed on day D never
    depends on day D's own results (DECISIONS.md, condition 1).
Nothing here computes or shows returns: the v3 verdict is computed later from these records under
the rules fixed in DECISIONS.md before the first record. The v2 verdict (aitrader.forward) is
unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from aitrader.registry import Registry
from aitrader.util import iso, parse_dt, utcnow

V3_START = "2026-11-25"            # first UTC day of the primary v3 sample (DECISIONS.md §6)
Q1_REF_DAYS, Q1_QUANTILE, Q1_MIN_REF = 30, 0.75, 40
LEDGER_KEEP_DAYS = 240             # after the freeze: beyond the 180-day look
PROMISING_LAG_DAYS = 2
EVIDENCE_EXCHANGE = "bybit"        # forward evidence is Bybit prices only (live trading is Bybit)
# Lab runs started before the deploy carry no `exchange`; every lab import since 20.11 (before the
# book existed) was on Bybit data. A record without it is accepted only if tested before this time.
EXCHANGE_STAMPED_SINCE = "2026-11-23T18:00:00Z"
K_LEDGER, K_Q1, K_SCHED, K_PROM = "fw3_ledger", "fw3_q1", "fw3_scheduled", "fw3_promising"


# ---------------------------------------------------------------------------- source of the data
def accept_source(r: dict, now: datetime | None = None) -> bool:
    ex = r.get("exchange")
    if ex:
        return ex == EVIDENCE_EXCHANGE
    until = parse_dt(r.get("tested_until")) or now or utcnow()
    return until < parse_dt(EXCHANGE_STAMPED_SINCE)  # migration rule for runs of the old lab code


# ---------------------------------------------------------------------------- Q1 at the freeze
def _quantile(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def reference_scores(reg: Registry, since: datetime, until: datetime) -> list[tuple[str, float]]:
    """(finished, score) of every eligible experiment frozen in [since, until), oldest first. The JSON
    is read by SQLite (json_extract), so thousands of stored results are never decoded in Python."""
    rows = reg.q("SELECT finished, json_extract(result, '$.score') AS score FROM experiments "
                 "WHERE status='done' AND finished >= ? AND finished < ? "
                 "AND json_extract(result, '$.params') IS NOT NULL AND json_extract(spec, '$.revalidates') IS NULL "
                 "ORDER BY finished", (iso(since), iso(until)))
    out = []
    for r in rows:
        try:
            out.append((str(r["finished"]), float(r["score"])))
        except (TypeError, ValueError):
            continue
    return out


def q1_decide(ref: list[tuple[str, float]], r: dict, now: datetime) -> dict:
    """Q1 membership from the reference experiments frozen in the Q1_REF_DAYS strictly before the freeze."""
    fz = parse_dt(r.get("freeze"))
    score = float(r.get("score") or 0.0)
    lo = iso(fz - timedelta(days=Q1_REF_DAYS)) if fz else None
    xs = [sc for fin, sc in ref if fz and lo <= fin < iso(fz)]
    base = {"score": score, "freeze": r.get("freeze"), "ref_n": len(xs), "decided": iso(now),
            "ref_from": lo, "ref_to": r.get("freeze")}
    if len(xs) < Q1_MIN_REF:
        return base | {"status": "burn_in", "member": None, "threshold": None}
    thr = round(_quantile(xs, Q1_QUANTILE), 6)
    return base | {"status": "decided", "member": score >= thr, "threshold": thr}


# ---------------------------------------------------------------------------- the ledger
def _span(a: str, b: str) -> list[str]:
    da, db = datetime.fromisoformat(a).date(), datetime.fromisoformat(b).date()
    return [(da + timedelta(days=i)).isoformat() for i in range((db - da).days + 1)] if db >= da else []


def merge(entry: dict | None, v3: dict, sha: str | None, now: datetime) -> tuple[dict, int]:
    """Append a lab run's v3 record to a strategy's ledger. Returns the entry and the number of
    published days this run disagreed with (revisions; the published value is kept)."""
    if entry is None:
        entry = {"from": v3["from"], "until": None, "values": {}, "missing": [], "jumps": [],
                 "recorded_since": now.date().isoformat(), "sha_first": sha, "revisions": 0, "revised_days": []}
    vals, miss, jumps = entry["values"], set(entry["missing"]), set(entry["jumps"])
    inc_vals = {d: x for d, x in v3.get("values") or []}
    inc_miss, inc_jumps = set(v3.get("missing") or []), set(v3.get("jumps") or [])
    until = entry["until"]
    revisions = 0
    for d in _span(v3["from"], v3["until"]):
        if d < entry["from"]:
            continue
        if d in inc_miss:
            if until is None or d > until:
                miss.add(d)  # missing so far; a later run may still publish it
            continue
        x = round(float(inc_vals.get(d, 0.0)), 10)
        if until is not None and d <= until and d not in miss:  # already published: never rewritten
            if abs(round(float(vals.get(d, 0.0)), 10) - x) > 1e-9:
                revisions += 1
                if d not in entry["revised_days"]:
                    entry["revised_days"] = sorted(entry["revised_days"] + [d])[-50:]
            continue
        miss.discard(d)  # first publication (or a late one)
        if x != 0.0:
            vals[d] = x
        if d in inc_jumps:
            jumps.add(d)
    entry["until"] = max(filter(None, [until, v3["until"]])) if (until or v3["until"]) else None
    entry["missing"], entry["jumps"] = sorted(miss), sorted(jumps)
    entry["sha_last"], entry["revisions"] = sha, entry["revisions"] + revisions
    entry["diag"] = v3.get("diag") or {}
    return entry, revisions


def valid_days(entry: dict) -> list[str]:
    miss = set(entry.get("missing") or [])
    return [d for d in _span(entry["from"], entry["until"]) if d not in miss] if entry.get("until") else []


def valid_days_values(entry: dict) -> list[tuple[str, float]]:
    """Every published valid day with its value (a valid day without a value change is a 0)."""
    vals = entry.get("values") or {}
    return [(d, float(vals.get(d, 0.0))) for d in valid_days(entry)]


def _line(r: dict) -> str:
    if r.get("benchmark"):
        return "benchmark"
    if r.get("hypothesis"):
        return f"hypothesis:{r['hypothesis']}"
    return "research"


def apply(reg: Registry, results: list[dict], now: datetime | None = None) -> dict:
    """Store the v3 records of one lab run; returns data-quality diagnostics (no returns)."""
    now = now or utcnow()
    ledger, q1 = reg.kv_get(K_LEDGER) or {}, reg.kv_get(K_Q1) or {}
    todo = [r for r in results if r.get("ok", True) and isinstance(r.get("v3"), dict)
            and r["v3"].get("from") and r["v3"].get("until") and r["v3"]["until"] >= r["v3"]["from"]]
    need = [parse_dt(r.get("freeze")) for r in todo if _line(r) == "research" and r["id"] not in q1]
    need = [f for f in need if f]
    ref = reference_scores(reg, min(need) - timedelta(days=Q1_REF_DAYS), max(need)) if need else []
    revisions = 0
    for r in todo:  # strategies without a complete day yet have nothing to record
        entry, n = merge(ledger.get(r["id"]), r["v3"], r.get("code_sha"), now)
        entry |= {"line": _line(r), "freeze": r.get("freeze"), "score": r.get("score"),
                  "eligible": _line(r) != "research" or str(r.get("freeze") or "")[:10] >= V3_START}
        ledger[r["id"]] = entry
        revisions += n
        if entry["line"] == "research" and r["id"] not in q1:
            q1[r["id"]] = q1_decide(ref, r, now)
    keep = iso(now - timedelta(days=LEDGER_KEEP_DAYS))
    ledger = {k: v for k, v in ledger.items() if str(v.get("freeze") or "9") >= keep or v.get("line") != "research"}
    q1 = {k: v for k, v in q1.items() if str(v.get("freeze") or "9") >= keep}
    reg.kv_set(K_LEDGER, ledger)
    reg.kv_set(K_Q1, q1)
    return diagnostics(reg, now) | {"revisions_this_run": revisions}


# ---------------------------------------------------------------------------- schedule and coverage
def note_scheduled(reg: Registry, book: list[dict], now: datetime | None = None) -> None:
    """The book served to the lab: every entry is scheduled for the complete days it can cover."""
    now = now or utcnow()
    sched = reg.kv_get(K_SCHED) or {}
    for e in book:
        fz = parse_dt(e.get("freeze"))
        if fz is None:
            continue
        s = sched.get(e["id"]) or {"freeze": e.get("freeze"), "first_seen": iso(now)}
        s["last_seen"] = iso(now)
        sched[e["id"]] = s
    keep, recent = iso(now - timedelta(days=LEDGER_KEEP_DAYS)), iso(now - timedelta(days=3))
    # entries that never covered a complete day are dropped after 3 days (most new experiments leave
    # the book within hours); the rest stay as long as the ledger keeps the strategy
    reg.kv_set(K_SCHED, {k: v for k, v in sched.items()
                         if (str(v.get("freeze") or "9") >= keep or k.startswith(("benchmark", "h1-")))
                         and (scheduled_days(v) or str(v.get("last_seen") or "") >= recent)})


def scheduled_days(s: dict) -> list[str]:
    """Complete days a strategy should have been observed: from the first full day after its freeze
    (and after it was first served) to the day before the last run that had it in the book."""
    from aitrader.research.marks import first_full_day
    fz, first, last = parse_dt(s.get("freeze")), parse_dt(s.get("first_seen")), parse_dt(s.get("last_seen"))
    if fz is None or first is None or last is None:
        return []
    a = max(first_full_day(fz), first.date())
    b = last.date() - timedelta(days=1)
    return _span(a.isoformat(), b.isoformat()) if b >= a else []


def diagnostics(reg: Registry, now: datetime | None = None) -> dict:
    ledger, q1, sched = (reg.kv_get(k) or {} for k in (K_LEDGER, K_Q1, K_SCHED))
    elig = {k: v for k, v in ledger.items() if v.get("line") == "research" and v.get("eligible")}
    members = [k for k, d in q1.items() if d.get("member") and k in elig]

    def coverage(ids) -> float | None:
        want = got = 0
        for k in ids:
            days = scheduled_days(sched.get(k) or {})
            ok = set(valid_days(ledger.get(k) or {"from": "", "until": None}))
            want += len(days)
            got += sum(1 for d in days if d in ok)
        return round(got / want, 3) if want else None
    bench = [k for k, v in ledger.items() if v.get("line") == "benchmark"]
    diag = [v.get("diag") or {} for v in ledger.values()]
    return {"start": V3_START, "records": len(ledger), "research_eligible": len(elig), "q1_members": len(members),
            "burn_in": sum(1 for d in q1.values() if d.get("status") == "burn_in"),
            "valid_days": sum(len(valid_days(v)) for v in ledger.values()),
            "missing_days": sum(len(v.get("missing") or []) for v in ledger.values()),
            "jumps": sum(len(v.get("jumps") or []) for v in ledger.values()),
            "revisions": sum(int(v.get("revisions") or 0) for v in ledger.values()),
            "coverage_q1": coverage(members), "coverage_benchmark": coverage(bench),
            "fees_unknown": sum(int(d.get("fees_unknown") or 0) for d in diag),
            "funding_mismatch": sum(int(d.get("funding_mismatch") or 0) for d in diag)}


# ---------------------------------------------------------------------------- condition 1: lagged retention
def note_promising(reg: Registry, ids: set[str], now: datetime | None = None) -> None:
    now = now or utcnow()
    hist = reg.kv_get(K_PROM) or {}
    hist[now.date().isoformat()] = sorted(ids)  # the last import of the day wins
    reg.kv_set(K_PROM, {k: hist[k] for k in sorted(hist)[-10:]})


def lagged_promising(reg: Registry, now: datetime | None = None) -> set[str] | None:
    """The promising set the book may use today: the one recorded PROMISING_LAG_DAYS days ago (or
    earlier). None until such a record exists (the first days after the deploy)."""
    now = now or utcnow()
    hist = reg.kv_get(K_PROM) or {}
    key = (now.date() - timedelta(days=PROMISING_LAG_DAYS)).isoformat()
    old = [k for k in hist if k <= key]
    return set(hist[max(old)]) if old else None
