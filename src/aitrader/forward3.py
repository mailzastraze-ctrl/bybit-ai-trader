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
  * a daily snapshot of the book served to the lab: the days each strategy was scheduled for. They
    fix the composition of line A per day and are the denominator of coverage: a scheduled day
    without a valid published value is missing, whatever the reason. A strategy that leaves the book
    and returns is not scheduled for the days in between; values the lab publishes for them are a
    diagnostic and never enter line A.
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
RESULT_FORMAT = 3                  # lab results of this format always carry `exchange`
STALE_H = 24
K_LEDGER, K_Q1, K_SCHED, K_PROM, K_STATUS = "fw3_ledger", "fw3_q1", "fw3_scheduled", "fw3_promising", "fw3_status"
K_BOOKDAYS = "fw3_book_days"


# ---------------------------------------------------------------------------- source of the data
def accept_source(r: dict, now: datetime | None = None) -> bool:
    """Bybit data only. Results of format ≥ 3 always state their exchange, so one without it is of
    unknown source and ignored. Older results (lab code before 23.11) carry neither: they are accepted
    by the explicit migration rule (every lab import since 20.11 was on Bybit) and counted as legacy."""
    ex = r.get("exchange")
    if int(r.get("format") or 0) >= RESULT_FORMAT:
        return ex == EVIDENCE_EXCHANGE
    return ex is None or ex == EVIDENCE_EXCHANGE


def is_legacy(r: dict) -> bool:
    return int(r.get("format") or 0) < RESULT_FORMAT


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


TOL = 1e-8  # share of the wallet (1e-8 × 10 000 = 0.0001 USDT): rounding of a few summed days


def _next_day(d: str) -> str:
    return (datetime.fromisoformat(d).date() + timedelta(days=1)).isoformat()


def _prev_day(d: str) -> str:
    return (datetime.fromisoformat(d).date() - timedelta(days=1)).isoformat()


def merge(entry: dict | None, v3: dict, sha: str | None, now: datetime) -> tuple[dict, int]:
    """Append a lab run's v3 record to a strategy's ledger (DECISIONS §3). Returns the entry and the
    number of published days this run disagreed with (revisions; the published value is kept).

    * Published days never change. A later run is checked against them at common checkpoints (days
      valid in both): the change since the previous common checkpoint must agree. So the same total
      split differently (a gap later refilled: D and D+1 instead of one jump on D+1) is not a revision;
      a different total is, and is counted at every run that sees it.
    * A missing day may be published later only while no later day has been published. Once a later
      day is published, that day's jump already carries the missing day's change: the day stays
      missing and is recorded as `refilled` (publishing it would count its change twice).
    * New days are appended after the last published valid day, which must be valid in the run too
      (the anchor of the change). If it is not, the run adds nothing (`anchor_missing`) rather than
      guessing which part of its change belongs to days already published."""
    if entry is None:
        entry = {"from": v3["from"], "until": None, "values": {}, "missing": [], "jumps": [],
                 "recorded_since": now.date().isoformat(), "sha_first": sha, "revisions": 0, "revised_days": []}
    vals, miss, jumps = entry["values"], set(entry["missing"]), set(entry["jumps"])
    refilled = set(entry.get("refilled_days") or [])
    inc_vals = {d: round(float(x), 10) for d, x in v3.get("values") or []}
    inc_miss, inc_jumps = set(v3.get("missing") or []), set(v3.get("jumps") or [])
    frm, until = entry["from"], entry["until"]
    inc_valid = {d for d in _span(v3["from"], v3["until"]) if d >= frm and d not in inc_miss}
    published = [d for d in _span(frm, until) if d not in miss] if until else []
    last = published[-1] if published else None
    revisions = 0
    # 1. the published part: checked at common checkpoints, never rewritten
    acc_pub = acc_in = 0.0
    for d in _span(frm, last) if last else []:
        is_pub, is_in = d not in miss, d in inc_valid
        acc_pub += float(vals.get(d, 0.0)) if is_pub else 0.0
        acc_in += inc_vals.get(d, 0.0) if is_in else 0.0
        if not is_pub and is_in:
            refilled.add(d)  # valid now, but its change is inside the next published day
        if is_pub and is_in:
            if abs(acc_pub - acc_in) > TOL:
                revisions += 1
                if d not in entry["revised_days"]:
                    entry["revised_days"] = sorted(entry["revised_days"] + [d])[-50:]
            acc_pub = acc_in = 0.0
    # 2. after the last published valid day: late and new days, anchored on that day
    if last is not None and last <= v3["until"] and last not in inc_valid:
        entry["anchor_missing"] = int(entry.get("anchor_missing") or 0) + 1
    else:
        start = _next_day(last) if last else frm
        for d in _span(start, v3["until"]):
            if d not in inc_valid:
                miss.add(d)  # missing so far; a later run may still publish it
                continue
            miss.discard(d)
            if inc_vals.get(d, 0.0) != 0.0:
                vals[d] = inc_vals[d]
            if d in inc_jumps or (d > frm and _prev_day(d) in miss):
                jumps.add(d)  # the change since the last valid day, not one day's change
        entry["until"] = max(filter(None, [until, v3["until"]]))
    entry["missing"], entry["jumps"] = sorted(miss), sorted(jumps)
    entry["refilled_days"] = sorted(refilled)[-50:]
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


def eligible(entry: dict) -> bool:
    """Primary sample of lines A/B: research strategies frozen on or after V3_START (DECISIONS §4).
    Always computed from the freeze and the current V3_START, so moving the date moves every entry."""
    return entry.get("line") != "research" or str(entry.get("freeze") or "")[:10] >= V3_START


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
        entry |= {"line": _line(r), "freeze": r.get("freeze"), "score": r.get("score")}
        ledger[r["id"]] = entry
        revisions += n
        if entry["line"] == "research" and r["id"] not in q1:
            q1[r["id"]] = q1_decide(ref, r, now)
    for v in ledger.values():  # stored flags follow the current V3_START, also for strategies no longer re-tested
        v["eligible"] = eligible(v)
    keep = iso(now - timedelta(days=LEDGER_KEEP_DAYS))
    ledger = {k: v for k, v in ledger.items() if str(v.get("freeze") or "9") >= keep or v.get("line") != "research"}
    q1 = {k: v for k, v in q1.items() if str(v.get("freeze") or "9") >= keep}
    reg.kv_set(K_LEDGER, ledger)
    reg.kv_set(K_Q1, q1)
    return diagnostics(reg, now) | {"revisions_this_run": revisions}


# ---------------------------------------------------------------------------- recording status
def record_status(reg: Registry, results: list[dict], error: Exception | None, now: datetime | None = None) -> dict:
    """When v3 last recorded something, and the last error. `results` are this import's Bybit results,
    failed forward tests (`ok=False`) included. A fresh v2 forward import proves nothing about v3.

    * `ok` — every result that should carry a v3 record did, and it was stored: `last_ok` moves.
    * `partial` — some did, others failed (no v3 record, or the whole forward test failed):
      `last_partial` moves, `last_ok` does not, so a partial import never looks like a healthy one.
    * `error` — the server could not store the records, or nothing carried a v3 record and something failed."""
    now = now or utcnow()
    st = reg.kv_get(K_STATUS) or {"since": iso(now)}
    done = [r for r in results if r.get("ok", True)]
    failed = [r.get("error") or "forward test failed" for r in results if not r.get("ok", True)]
    with_v3 = [r for r in done if isinstance(r.get("v3"), dict) and r["v3"].get("from")]
    lab_err = [r["v3"]["error"] for r in done if isinstance(r.get("v3"), dict) and r["v3"].get("error")]
    errors = [f"lab: {e}" for e in lab_err] + [f"forward test: {e}" for e in failed]
    st["last_attempt"] = iso(now)
    st["last_results"], st["last_with_v3"] = len(results), len(with_v3)
    st["last_lab_errors"], st["last_failed"] = len(lab_err), len(failed)
    st["last_failures"] = f"{len(errors)}/{len(errors) + len(with_v3)}" if errors else None
    if error is not None:
        st["last_error"], st["error_at"], st["state"] = str(error)[:200], iso(now), "error"
    elif errors and not with_v3:
        st["last_error"], st["error_at"], st["state"] = str(errors[0])[:200], iso(now), "error"
    elif errors:
        st["last_error"], st["error_at"] = str(errors[0])[:200], iso(now)
        st["last_partial"], st["state"] = iso(now), "partial"
    elif with_v3:
        st["last_ok"], st["state"] = iso(now), "ok"
    reg.kv_set(K_STATUS, st)
    return st


def status_flags(reg: Registry, now: datetime | None = None) -> list[str]:
    """`v3 error`, `v3 partial F/N` (the last import), `v3 > 24h` (no fully successful import for a day)."""
    now = now or utcnow()
    st = reg.kv_get(K_STATUS)
    if not st:
        return []
    out = []
    ok = parse_dt(st.get("last_ok"))
    if st.get("state") == "error":  # the last attempt that concerned v3 failed
        out.append("v3 error")
    elif st.get("state") == "partial":
        out.append(f"v3 partial {st.get('last_failures')}")
    ref = ok or parse_dt(st.get("since"))
    if ref is not None and (now - ref).total_seconds() > STALE_H * 3600:
        out.append("v3 > 24h")
    return out


# ---------------------------------------------------------------------------- schedule and coverage
def _served(s: dict) -> list[str]:
    """UTC days on which the strategy was in a book served to the lab. Entries stored before 23.11
    (09:00 UTC) carry only first/last time; both fall on the deploy day, so the span is exact."""
    if s.get("days"):
        return list(s["days"])
    first, last = parse_dt(s.get("first_seen")), parse_dt(s.get("last_seen"))
    return _span(first.date().isoformat(), last.date().isoformat()) if first and last else []


def note_scheduled(reg: Registry, book: list[dict], now: datetime | None = None) -> None:
    """The book served to the lab, kept as an immutable daily snapshot: per strategy, the UTC days it
    was served on, and the days on which any book was served (DECISIONS §5, §6)."""
    now = now or utcnow()
    today = now.date().isoformat()
    sched = reg.kv_get(K_SCHED) or {}
    book_days = reg.kv_get(K_BOOKDAYS) or sorted({d for s in sched.values() for d in _served(s)})
    for e in book:
        fz = parse_dt(e.get("freeze"))
        if fz is None:
            continue
        s = sched.get(e["id"]) or {"freeze": e.get("freeze"), "first_seen": iso(now)}
        days = _served(s)
        s["days"] = sorted(set(days) | {today})[-(LEDGER_KEEP_DAYS + 10):]
        s["last_seen"] = iso(now)
        sched[e["id"]] = s
    book_days = sorted(set(book_days) | {today})[-(LEDGER_KEEP_DAYS + 10):]
    reg.kv_set(K_BOOKDAYS, book_days)
    keep, recent = iso(now - timedelta(days=LEDGER_KEEP_DAYS)), iso(now - timedelta(days=3))
    # entries that never covered a complete day are dropped after 3 days (most new experiments leave
    # the book within hours); the rest stay as long as the ledger keeps the strategy
    reg.kv_set(K_SCHED, {k: v for k, v in sched.items()
                         if (str(v.get("freeze") or "9") >= keep or k.startswith(("benchmark", "h1-")))
                         and (scheduled_days(v, book_days) or str(v.get("last_seen") or "") >= recent)})


def scheduled_days(s: dict, book_days: list[str] | None = None) -> list[str]:
    """Complete days the strategy is scheduled for (DECISIONS §5, §6): from the first full day after
    its freeze, the days d on which it was in the served book and still in it on d+1, the day whose
    runs first value d. A day without any lab run keeps the previous day's book (an outage counts
    against coverage; it never removes a day). Fixed once the book of d+1 was served: a strategy
    that leaves the book and returns later is not scheduled for the days in between."""
    from aitrader.research.marks import first_full_day
    fz, served = parse_dt(s.get("freeze")), set(_served(s))
    if fz is None or not served:
        return []
    start = min(served)
    bd = served | set(book_days) if book_days is not None else set(_span(start, max(served)))
    days, present, cur = _span(start, max(bd)), [], False
    for d in days:
        if d in bd:
            cur = d in served
        present.append(cur)
    a = max(first_full_day(fz).isoformat(), start)
    return [d for i, d in enumerate(days[:-1]) if d >= a and present[i] and present[i + 1]]


def composition(reg: Registry, day: str) -> dict:
    """Who makes up line A on `day` (DECISIONS §5): eligible Q1 members scheduled for it, and those
    of them with a valid published value (M(d)). No returns are computed here. A value published for
    a day the strategy was not scheduled for (e.g. after a return to the book) is a diagnostic only."""
    ledger, q1, sched = (reg.kv_get(k) or {} for k in (K_LEDGER, K_Q1, K_SCHED))
    bd = reg.kv_get(K_BOOKDAYS) or []
    ids = sorted(k for k, d in q1.items() if d.get("member") and k in ledger
                 and ledger[k].get("line") == "research" and eligible(ledger[k]))
    sch = [k for k in ids if day in set(scheduled_days(sched.get(k) or {}, bd))]
    return {"scheduled": sch, "members": [k for k in sch if day in set(valid_days(ledger[k]))]}


def diagnostics(reg: Registry, now: datetime | None = None) -> dict:
    ledger, q1, sched = (reg.kv_get(k) or {} for k in (K_LEDGER, K_Q1, K_SCHED))
    bd = reg.kv_get(K_BOOKDAYS) or []
    elig = {k: v for k, v in ledger.items() if v.get("line") == "research" and eligible(v)}
    members = [k for k, d in q1.items() if d.get("member") and k in elig]

    def coverage(ids) -> tuple[float | None, int]:
        want = got = off = 0
        for k in ids:
            days = set(scheduled_days(sched.get(k) or {}, bd))
            ok = set(valid_days(ledger.get(k) or {"from": "", "until": None}))
            want += len(days)
            got += len(days & ok)
            off += len(ok - days)
        return (round(got / want, 3) if want else None), off
    bench = [k for k, v in ledger.items() if v.get("line") == "benchmark"]
    diag = [v.get("diag") or {} for v in ledger.values()]
    cov_q1, off_q1 = coverage(members)
    return {"start": V3_START, "records": len(ledger), "research_eligible": len(elig), "q1_members": len(members),
            "burn_in": sum(1 for d in q1.values() if d.get("status") == "burn_in"),
            "valid_days": sum(len(valid_days(v)) for v in ledger.values()),
            "missing_days": sum(len(v.get("missing") or []) for v in ledger.values()),
            "jumps": sum(len(v.get("jumps") or []) for v in ledger.values()),
            "revisions": sum(int(v.get("revisions") or 0) for v in ledger.values()),
            "refilled_days": sum(len(v.get("refilled_days") or []) for v in ledger.values()),
            "anchor_missing": sum(int(v.get("anchor_missing") or 0) for v in ledger.values()),
            "coverage_q1": cov_q1, "coverage_benchmark": coverage(bench)[0],
            "q1_off_schedule_days": off_q1,  # valid days outside the schedule: diagnostic, never in R_Q1
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
