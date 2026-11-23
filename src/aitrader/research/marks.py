"""Forward test v3, lab side: a frozen strategy's value per complete UTC day (docs/DECISIONS.md §3).

Each open position is worth its liquidation value at the day's last close: the move since entry,
minus the entry costs already paid, minus the costs of leaving now (exit fee and the demo→reality
slippage haircut). A closed trade is worth its realised result, so everything first known at the
close (funding above all; freqtrade reports only its total) is recognised on the close day. Each
day's value therefore depends only on what was known by the end of that day: re-testing later,
when today's open trade has closed, never changes a day already published.

Only complete UTC days count, from the first full day after the freeze; the day of the freeze and
today are never published. A day without the full set of candles for every pair of the strategy is
`missing` (never a zero); the first valid day after a gap carries a multi-day change and is marked a
`jump`, so it can be kept out of daily statistics. Trades opened before the first full day are not
part of the v3 record (the v2 `trades` record is unchanged).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache

import pandas as pd

from aitrader.realism import SLIPPAGE_PER_SIDE, real_pnl
from aitrader.util import parse_dt

log = logging.getLogger(__name__)
_UNITS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


def tf_seconds(tf: str) -> int:
    return int(tf[:-1]) * _UNITS[tf[-1]]


def first_full_day(freeze: datetime) -> date:
    """The first UTC day the strategy is observed for its whole length."""
    d = freeze.date()
    return d if (freeze.hour, freeze.minute, freeze.second, freeze.microsecond) == (0, 0, 0, 0) else d + timedelta(days=1)


def last_complete_day(now: datetime) -> date:
    return now.date() - timedelta(days=1)


def _days(a: date, b: date) -> list[str]:
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)] if b >= a else []


@lru_cache(maxsize=512)
def _day_file(path: str, mtime: float) -> tuple[dict, dict]:
    d = pd.read_feather(path, columns=["date", "close"]).set_index("date")["close"]
    g = d.resample("1D")
    last, count = g.last().dropna(), g.count()
    return ({i.date().isoformat(): float(v) for i, v in last.items()},
            {i.date().isoformat(): int(v) for i, v in count.items()})


def day_candles(path) -> tuple[dict, dict] | None:
    """{day: last close}, {day: candle count} from a Freqtrade candle file (None if unavailable)."""
    try:
        return _day_file(str(path), path.stat().st_mtime) if path.exists() else None
    except Exception as ex:  # noqa: BLE001 – an odd file means missing days, not a crash
        log.info("forward v3: unreadable candles %s: %s", path, ex)
        return None


def _f(t: dict, k: str) -> float | None:
    try:
        v = t.get(k)
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def trade_path(t: dict, closes: dict, valid: dict, days: list[str], baseline_day: str | None = None
               ) -> tuple[dict, set, dict]:
    """Daily value changes of one trade over `days` (share of the research wallet), the days that
    carry a multi-day change after a gap, and diagnostics. The caller has checked that the trade can
    be valued (`markable`). `baseline_day`: for a trade opened after the freeze but before the first
    full day, the freeze day; the position enters the record at its liquidation value at that day's
    close, so nothing from before the observation (entry costs included) is counted."""
    from aitrader.research.shadow import BALANCE
    amount, entry = _f(t, "amount") or 0.0, _f(t, "open_rate") or 0.0
    od, cd = parse_dt(str(t.get("open_date") or "")), parse_dt(str(t.get("close_date") or ""))
    out, jumps = {}, set()
    diag = {"unallocated": 0.0, "fees_unknown": 0, "funding_mismatch": 0, "close_carried": 0, "boundary": 0}
    od_s, cd_s = od.date().isoformat(), cd.date().isoformat()
    forced = t.get("exit_reason") == "force_exit"  # still open at the data end: never a realised result
    sign = -1.0 if t.get("is_short") else 1.0
    stake, lev = _f(t, "stake_amount") or 0.0, _f(t, "leverage") or 1.0
    haircut = max(stake * lev, 0.0) * SLIPPAGE_PER_SIDE  # realism.trade_cost: one side of two
    fee_o, fee_c = _f(t, "fee_open"), _f(t, "fee_close")
    if fee_o is None or fee_c is None:
        diag["fees_unknown"] = 1
    fo, fc = fee_o or 0.0, fee_c if fee_c is not None else (fee_o or 0.0)
    entry_cost = amount * entry * fo + haircut

    def liquidation(mark: float) -> float:
        return sign * amount * (mark - entry) - entry_cost - amount * mark * fc - haircut

    realised = real_pnl(t)
    rate = _f(t, "close_rate")
    if not forced and rate is not None and fee_o is not None and fee_c is not None:
        residual = realised - (sign * amount * (rate - entry) - amount * entry * fee_o - amount * rate * fee_c - 2 * haircut)
        diag["unallocated"] = residual / BALANCE  # funding and rounding, first known at the close
        ff = _f(t, "funding_fees")
        if ff is not None and abs(residual - ff) > max(0.01, 1e-4 * amount * entry):
            diag["funding_mismatch"] = 1
    prev, gap, pending = 0.0, False, False
    if baseline_day is not None:
        prev, diag["boundary"] = liquidation(closes[baseline_day]), 1
        od_s = days[0]
    for d in days:
        if d < od_s:
            continue
        if d > cd_s:
            if not pending:
                break
            if not valid.get(d):
                continue
            # the close fell on a missing day: the realised result lands on the next valid day
            out[d], diag["close_carried"] = (realised - prev) / BALANCE, 1
            jumps.add(d)
            break
        if not valid.get(d):
            gap = True
            pending = d == cd_s and not forced
            continue
        val = realised if d == cd_s and not forced else liquidation(closes[d])
        out[d] = (val - prev) / BALANCE
        if gap and (d != od_s or baseline_day is not None):
            jumps.add(d)  # the change since the last valid day, not one day's change
        prev, gap = val, False
    return out, jumps, diag


def markable(t: dict, closes: dict, counts: dict, need: int, first_day: str) -> tuple[bool, str | None]:
    """(can the trade be valued, baseline day). A trade without size, prices or dates cannot; one
    opened before the first full day needs a complete freeze day to start from."""
    od, cd = parse_dt(str(t.get("open_date") or "")), parse_dt(str(t.get("close_date") or ""))
    if od is None or cd is None or (_f(t, "amount") or 0.0) <= 0 or (_f(t, "open_rate") or 0.0) <= 0:
        return False, None
    if od.date().isoformat() >= first_day:
        return True, None
    b = od.date().isoformat()
    return (b in closes and counts.get(b, 0) >= need), b


def v3_record(trades: list[dict], freeze: datetime, pairs: list[str], candles: dict, tf: str, now: datetime) -> dict:
    """The strategy's v3 record: complete days from the first full day after the freeze to the last
    complete day before `now`; `values` holds the non-zero days (a valid day not listed is a 0).

    Every trade opened after the freeze counts; one opened on the freeze day enters at its
    liquidation value at that day's close. A trade that cannot be valued (no size, prices or dates,
    or no complete freeze day to start from) makes its days missing, never zeros: the other trades'
    changes on those days move to the next valid day as a jump."""
    start, until = first_full_day(freeze), last_complete_day(now)
    rec = {"from": start.isoformat(), "until": until.isoformat(), "values": [], "missing": [], "jumps": [],
           "diag": {"trades": 0, "unallocated": 0.0, "fees_unknown": 0, "funding_mismatch": 0, "unmarked": 0,
                    "close_carried": 0, "boundary": 0}}
    days = _days(start, until)
    if not days:
        return rec
    need = 86400 // tf_seconds(tf)
    valid = {d: all(((candles.get(p) or ({}, {}))[1]).get(d, 0) >= need for p in pairs) for d in days}
    scope, plans = [], []
    for t in trades:
        od = parse_dt(str(t.get("open_date") or ""))
        if od is not None and od < freeze:
            continue  # opened before the freeze: never part of the forward test (as in v2)
        scope.append(t)
    for t in scope:  # pass 1: trades that cannot be valued make their days missing
        closes, counts = candles.get(t.get("pair")) or ({}, {})
        ok, base = markable(t, closes, counts, need, days[0])
        if ok:
            plans.append((t, closes, base))
            continue
        rec["diag"]["unmarked"] += 1
        od, cd = parse_dt(str(t.get("open_date") or "")), parse_dt(str(t.get("close_date") or ""))
        lo = od.date().isoformat() if od else days[0]
        hi = cd.date().isoformat() if cd else days[-1]
        for d in days:
            if lo <= d <= hi:
                valid[d] = False
    rec["missing"] = [d for d in days if not valid[d]]
    acc: dict[str, float] = {}
    jumps: set = set()
    for t, closes, base in plans:  # pass 2
        path, j, dg = trade_path(t, closes, valid, days, base)
        for d, x in path.items():
            acc[d] = acc.get(d, 0.0) + x
        jumps |= j
        rec["diag"]["trades"] += 1
        for k in ("unallocated", "fees_unknown", "funding_mismatch", "close_carried", "boundary"):
            rec["diag"][k] += dg.get(k, 0)
    rec["values"] = [[d, round(x, 10)] for d, x in sorted(acc.items()) if round(x, 10) != 0.0 and valid[d]]
    rec["jumps"] = sorted(jumps)
    rec["diag"]["unallocated"] = round(rec["diag"]["unallocated"], 10)
    return rec
