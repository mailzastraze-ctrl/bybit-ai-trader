"""Forward test v3: record now, judge later (docs/DECISIONS.md; audit 22.11 with ChatGPT).

The two most important properties (ChatGPT's review):
  * re-testing later never rewrites a published day (an open trade closing later included);
  * future results never change who is in Q1 or which days are observed.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_forward import _FwRunner

from aitrader import forward, forward3, observe
from aitrader.realism import SLIPPAGE_PER_SIDE, real_pnl
from aitrader.registry import Registry
from aitrader.research import marks, shadow
from aitrader.settings import Settings
from aitrader.util import iso, utcnow

BAL = shadow.BALANCE
FEE = 0.00075
D0 = datetime(2026, 11, 2, tzinfo=UTC)  # a Monday; every test day is relative to it


@pytest.fixture
def env(tmp_path):
    s = Settings(data_dir=tmp_path, app_dir=Path(__file__).resolve().parents[1])
    s.ensure_dirs()
    return s, Registry(s.registry_path)


def day(i: int) -> str:
    return (D0 + timedelta(days=i)).date().isoformat()


def at(i: int, hour: int = 12) -> datetime:
    return D0 + timedelta(days=i, hours=hour)


def candles(closes: dict[int, float], gaps=(), per_day: int = 6) -> dict:
    """One pair's ({day: last close}, {day: candle count}) on 4h candles."""
    return ({day(i): c for i, c in closes.items()},
            {day(i): (per_day - 1 if i in gaps else per_day) for i in closes})


def trade(o: int, c: int, close: float, *, short=False, lev=1.0, amount=1.0, funding=0.0, reason="exit_signal",
          o_hour=10, c_hour=12, fees=True) -> dict:
    sign = -1 if short else 1
    t = {"pair": "BTC/USDT:USDT", "open_date": iso(at(o, o_hour)), "close_date": iso(at(c, c_hour)),
         "open_rate": 100.0, "close_rate": close, "amount": amount, "is_short": short,
         "stake_amount": amount * 100.0 / lev, "leverage": lev, "exit_reason": reason,
         "profit_abs": sign * amount * (close - 100.0) - amount * 100 * FEE - amount * close * FEE + funding}
    if fees:
        t |= {"fee_open": FEE, "fee_close": FEE}
    return t


def liquidation(t: dict, mark: float) -> float:
    sign = -1 if t["is_short"] else 1
    hc = t["stake_amount"] * t["leverage"] * SLIPPAGE_PER_SIDE
    return sign * t["amount"] * (mark - 100.0) - t["amount"] * 100 * FEE - hc - t["amount"] * mark * FEE - hc


def rec(trades, closes, *, now_day, freeze=None, gaps=()):
    fz = freeze or at(0, 0) - timedelta(hours=10)  # frozen the evening before day 0
    return marks.v3_record(trades, fz, ["BTC/USDT:USDT"], {"BTC/USDT:USDT": candles(closes, gaps)}, "4h",
                           at(now_day, 3))


def result(rid, v3, freeze=None, score=1.0, **kw):
    return {"id": rid, "ok": True, "v3": v3, "freeze": iso(freeze or at(0, 0) - timedelta(hours=10)),
            "score": score, "tested_until": iso(utcnow()), "exchange": "bybit", "code_sha": "abc", **kw}


# ---------------------------------------------------------------------------- lab side: daily values
@pytest.mark.parametrize("short,lev", [(False, 1.0), (False, 3.0), (True, 1.0), (True, 3.0)])
def test_each_day_is_the_liquidation_value_change_and_the_close_reconciles(short, lev):
    t = trade(0, 3, 96.0 if short else 104.0, short=short, lev=lev, amount=2.0)
    cl = {0: 101.0, 1: 103.0, 2: 99.0, 3: 104.0, 4: 104.0}
    r = rec([t], cl, now_day=5)
    vals = dict(r["values"])
    assert vals[day(0)] == pytest.approx(liquidation(t, 101.0) / BAL)  # entry costs and the cost to leave now
    assert vals[day(1)] == pytest.approx((liquidation(t, 103.0) - liquidation(t, 101.0)) / BAL)
    assert vals[day(3)] == pytest.approx((real_pnl(t) - liquidation(t, 99.0)) / BAL)  # realised on the close day
    assert sum(vals.values()) == pytest.approx(real_pnl(t) / BAL)  # no fee or 5 bp counted twice or missed
    assert r["from"] == day(0) and r["until"] == day(4) and r["missing"] == [] and r["jumps"] == []


def test_a_published_day_never_changes_when_an_open_trade_closes_later(env):
    """ChatGPT's critical test: re-run tomorrow, today's open trade has closed meanwhile."""
    _, reg = env
    cl = {0: 101.0, 1: 104.0, 2: 106.0, 3: 103.0, 4: 102.0, 5: 107.0}
    open_now = trade(0, 3, 103.0, reason="force_exit", c_hour=2)  # run 1 at day 3, 03:00: still open
    r1 = rec([open_now], cl, now_day=3)
    forward3.apply(reg, [result("x1", r1)], at(3, 3))
    first = dict(forward3.valid_days_values(reg.kv_get(forward3.K_LEDGER)["x1"]))
    closed = trade(0, 5, 107.0)  # run 2 at day 6: the same trade closed on day 5
    r2 = rec([closed], cl, now_day=6)
    forward3.apply(reg, [result("x1", r2)], at(6, 3))
    led = reg.kv_get(forward3.K_LEDGER)["x1"]
    again = dict(forward3.valid_days_values(led))
    assert {d: again[d] for d in first} == first and led["revisions"] == 0  # days 0–2 untouched
    assert sum(again.values()) == pytest.approx(real_pnl(closed) / BAL)
    assert again[day(5)] == pytest.approx((real_pnl(closed) - liquidation(closed, 102.0)) / BAL)


def test_only_complete_days_from_the_first_full_day_after_the_freeze():
    fz = at(0, 14)  # frozen at 14:00 on day 0: day 0 is not a full day
    t_next = trade(1, 2, 103.0, o_hour=8)
    t_before = trade(0, 2, 103.0, o_hour=9)  # opened before the freeze: never part of the forward test
    r = marks.v3_record([t_next, t_before], fz, ["BTC/USDT:USDT"],
                        {"BTC/USDT:USDT": candles({0: 101, 1: 102, 2: 103, 3: 103})}, "4h", at(3, 9))
    assert r["from"] == day(1) and r["until"] == day(2)  # day 3 (today) is not complete
    assert r["diag"]["trades"] == 1
    assert sum(x for _, x in r["values"]) == pytest.approx(real_pnl(t_next) / BAL)


def test_a_trade_opened_on_the_freeze_day_enters_at_its_liquidation_value():
    """ChatGPT 23.11 (2): a position opened after the freeze on its partial day and held across the
    boundary is counted on every full day, starting from its value at the freeze day's close."""
    fz = at(0, 14)
    t = trade(0, 4, 106.0, o_hour=16)
    cl = {0: 101.0, 1: 103.0, 2: 102.0, 3: 105.0, 4: 106.0}
    r = marks.v3_record([t], fz, ["BTC/USDT:USDT"], {"BTC/USDT:USDT": candles(cl)}, "4h", at(5, 3))
    vals = dict(r["values"])
    assert vals[day(1)] == pytest.approx((liquidation(t, 103.0) - liquidation(t, 101.0)) / BAL)
    assert sum(vals.values()) == pytest.approx((real_pnl(t) - liquidation(t, 101.0)) / BAL)  # nothing from before
    assert r["diag"]["boundary"] == 1 and r["missing"] == []
    no_base = marks.v3_record([t], fz, ["BTC/USDT:USDT"], {"BTC/USDT:USDT": candles(cl, gaps=(0,))}, "4h", at(5, 3))
    assert no_base["diag"]["unmarked"] == 1 and no_base["values"] == []  # no start value: days missing, not zeros
    assert no_base["missing"] == [day(i) for i in range(1, 5)]


def test_a_close_on_a_missing_day_is_realised_on_the_next_valid_day():
    """ChatGPT 23.11 (1): the result of a trade closed on a day without candles must not vanish."""
    t = trade(0, 2, 105.0)
    r = rec([t], {0: 101.0, 1: 102.0, 2: 104.0, 3: 104.5, 4: 104.0}, now_day=5, gaps=(2,))
    vals = dict(r["values"])
    assert r["missing"] == [day(2)] and r["jumps"] == [day(3)] and r["diag"]["close_carried"] == 1
    assert vals[day(3)] == pytest.approx((real_pnl(t) - liquidation(t, 102.0)) / BAL)
    assert sum(vals.values()) == pytest.approx(real_pnl(t) / BAL) and day(4) not in vals


def test_a_trade_that_cannot_be_valued_makes_its_days_missing():
    good = trade(0, 3, 104.0)
    bad = trade(1, 2, 103.0) | {"amount": None}
    r = rec([good, bad], {0: 101.0, 1: 102.0, 2: 103.0, 3: 104.0, 4: 104.0}, now_day=5)
    vals = dict(r["values"])
    assert r["diag"]["unmarked"] == 1 and r["missing"] == [day(1), day(2)]
    assert day(1) not in vals and r["jumps"] == [day(3)]  # the good trade's days 1–3 land on day 3
    assert sum(vals.values()) == pytest.approx(real_pnl(good) / BAL)


def test_a_candle_gap_is_missing_not_zero_and_the_next_day_is_a_jump():
    t = trade(0, 4, 105.0)
    r = rec([t], {0: 101.0, 1: 102.0, 2: 104.0, 3: 104.0, 4: 105.0, 5: 105.0}, now_day=6, gaps=(2,))
    vals = dict(r["values"])
    assert r["missing"] == [day(2)] and day(2) not in vals
    assert r["jumps"] == [day(3)]  # carries days 2 and 3
    assert vals[day(3)] == pytest.approx((liquidation(t, 104.0) - liquidation(t, 102.0)) / BAL)


def test_funding_is_recognised_on_the_day_it_becomes_known_and_flagged():
    t = trade(0, 3, 104.0, funding=-1.2)  # a long paying funding for three days
    cl = {0: 101.0, 1: 102.0, 2: 103.0, 3: 104.0}
    r = rec([t], cl, now_day=4)
    vals = dict(r["values"])
    assert vals[day(0)] == pytest.approx(liquidation(t, 101.0) / BAL)  # no future funding spread backwards
    assert vals[day(3)] == pytest.approx((real_pnl(t) - liquidation(t, 103.0)) / BAL)
    assert r["diag"]["unallocated"] == pytest.approx(-1.2 / BAL) and r["diag"]["funding_mismatch"] == 0
    t2 = t | {"funding_fees": -0.2}  # freqtrade's own total disagrees with what profit_abs implies
    assert rec([t2], cl, now_day=4)["diag"]["funding_mismatch"] == 1


def test_a_force_exit_is_never_a_realised_result_and_missing_fees_are_flagged():
    t = trade(0, 2, 103.0, reason="force_exit", c_hour=23, funding=-1.0)  # data end on a complete day
    r = rec([t], {0: 101.0, 1: 102.0, 2: 103.0}, now_day=3)
    assert sum(x for _, x in r["values"]) == pytest.approx(liquidation(t, 103.0) / BAL)  # funding not known yet
    assert real_pnl(t) != pytest.approx(liquidation(t, 103.0))
    assert rec([trade(0, 1, 102.0, fees=False)], {0: 101.0, 1: 102.0}, now_day=2)["diag"]["fees_unknown"] == 1


def test_the_shadow_record_carries_v3_and_its_provenance(env, tmp_path, monkeypatch):
    s, _ = env
    now = utcnow()
    cd = (now - timedelta(days=3)).replace(hour=12, minute=0, second=0, microsecond=0)
    t = {"pair": "BTC/USDT:USDT", "open_date": iso(cd - timedelta(days=1)), "close_date": iso(cd), "open_rate": 100.0,
         "close_rate": 101.0, "amount": 1.0, "stake_amount": 100.0, "leverage": 1.0, "fee_open": FEE, "fee_close": FEE,
         "profit_abs": 0.85, "exit_reason": "exit_signal"}

    class Runner(_FwRunner):
        def backtest(self, job, configs, strategy, timerange, fee, out_name):
            out = job.path(out_name)
            out.mkdir(parents=True, exist_ok=True)
            (out / "bt.json").write_text(json.dumps({"strategy": {"AIPortfolio": {"trades": [t]}}}))
            (out / ".last_result.json").write_text(json.dumps({"latest_backtest": "bt.json"}))
            return out
    days = [(now - timedelta(days=k)).date().isoformat() for k in range(8)]
    monkeypatch.setattr(marks, "day_candles", lambda path: ({d: 101.0 for d in days}, {d: 24 for d in days}))
    monkeypatch.setenv("GITHUB_SHA", "deadbeef")
    entry = {"id": "x1", "family": "trend_ema", "params": {}, "pairs": ["BTC/USDT:USDT"], "timeframe": "1h",
             "freeze": iso(now - timedelta(days=6)), "score": 1.0}
    r = shadow.run(s, [entry], tmp_path / "sh", workers=1, ft=Runner(True))[0]
    assert r["exchange"] == "bybit" and r["code_sha"] == "deadbeef" and r["format"] == 3
    assert r["v3"]["diag"]["trades"] == 1
    assert sum(x for _, x in r["v3"]["values"]) == pytest.approx(real_pnl(t) / BAL)
    assert r["trades"] and r["trades"][0][1] == pytest.approx(real_pnl(t) / BAL)  # the v2 record is unchanged


# ---------------------------------------------------------------------------- server side: the ledger
def test_a_revision_is_counted_and_the_published_value_kept(env):
    _, reg = env
    v = {"from": day(0), "until": day(2), "values": [[day(1), 0.001]], "missing": [], "jumps": [], "diag": {}}
    forward3.apply(reg, [result("x1", v)], at(3))
    forward3.apply(reg, [result("x1", v | {"values": [[day(1), 0.005]], "until": day(3)})], at(4))
    led = reg.kv_get(forward3.K_LEDGER)["x1"]
    assert dict(forward3.valid_days_values(led))[day(1)] == 0.001 and led["revisions"] == 1
    assert led["revised_days"] == [day(1)] and led["until"] == day(3)


def test_a_missing_day_may_be_published_later_but_a_valid_day_never_changes(env):
    _, reg = env
    forward3.apply(reg, [result("x1", {"from": day(0), "until": day(2), "values": [], "missing": [day(2)],
                                       "jumps": [], "diag": {}})], at(3))
    forward3.apply(reg, [result("x1", {"from": day(0), "until": day(3), "values": [[day(2), 0.002]], "missing": [],
                                       "jumps": [], "diag": {}})], at(4))
    led = reg.kv_get(forward3.K_LEDGER)["x1"]
    assert led["missing"] == [] and dict(forward3.valid_days_values(led))[day(2)] == 0.002 and led["revisions"] == 0


def _ref(reg, n, freeze, scores=None, prefix="r"):
    for i in range(n):
        fin = iso(freeze - timedelta(hours=6 * (i + 1)))
        reg.upsert("experiments", {"id": f"{prefix}{i}", "created": fin, "family": "trend_ema", "status": "done",
                                   "finished": fin, "spec": {"family": "trend_ema"},
                                   "result": {"params": {"a": 1}, "score": (scores or list(range(n)))[i]}})


def test_q1_membership_is_decided_once_from_strategies_frozen_before(env):
    _, reg = env
    fz = at(20, 0)
    _ref(reg, 45, fz)  # scores 0..44, all in the 30 days before the freeze: 75th percentile 33
    reg.upsert("experiments", {"id": "later", "created": iso(fz + timedelta(hours=2)), "family": "x", "status": "done",
                               "finished": iso(fz + timedelta(hours=2)), "spec": {}, "result": {"params": {}, "score": 1e6}})
    v = {"from": day(21), "until": day(22), "values": [], "missing": [], "jumps": [], "diag": {}}
    forward3.apply(reg, [result("a", v, freeze=fz, score=40.0), result("b", v, freeze=fz, score=20.0)], at(23))
    q1 = reg.kv_get(forward3.K_Q1)
    assert q1["a"]["member"] is True and q1["b"]["member"] is False
    assert q1["a"]["threshold"] == pytest.approx(33.0) and q1["a"]["ref_n"] == 45  # the later 1e6 is not in it
    # a newcomer with a higher score and many later high-score experiments change nothing that is decided
    _ref(reg, 60, fz + timedelta(days=10), scores=[100.0] * 60, prefix="n")
    forward3.apply(reg, [result("c", v, freeze=fz + timedelta(days=10), score=99.0), result("a", v, freeze=fz, score=40.0)],
                   at(31))
    q1b = reg.kv_get(forward3.K_Q1)
    assert q1b["a"] == q1["a"] and q1b["c"]["member"] is False


def test_too_few_reference_strategies_is_burn_in(env):
    _, reg = env
    fz = at(20, 0)
    _ref(reg, 10, fz)
    v = {"from": day(21), "until": day(22), "values": [], "missing": [], "jumps": [], "diag": {}}
    forward3.apply(reg, [result("a", v, freeze=fz, score=99.0)], at(23))
    q = reg.kv_get(forward3.K_Q1)["a"]
    assert q["status"] == "burn_in" and q["member"] is None and q["ref_n"] == 10


def test_a_new_high_score_strategy_does_not_rewrite_q1_history(env):
    """The v2 behaviour (test_forward: population quartile) re-ranks the past; v3 keeps it."""
    _, reg = env
    fz = at(0, 0) - timedelta(hours=10)
    _ref(reg, 45, fz)
    old = {"from": day(0), "until": day(9), "values": [[day(i), 0.001] for i in range(10)], "missing": [],
           "jumps": [], "diag": {}}
    forward3.apply(reg, [result("a", old, freeze=fz, score=40.0)], at(10))
    before = (reg.kv_get(forward3.K_Q1)["a"], forward3.valid_days_values(reg.kv_get(forward3.K_LEDGER)["a"]))
    _ref(reg, 50, at(10, 0), scores=[500.0] * 50, prefix="hi")
    new = {"from": day(11), "until": day(12), "values": [[day(11), -0.01]], "missing": [], "jumps": [], "diag": {}}
    forward3.apply(reg, [result("z", new, freeze=at(10, 0), score=900.0)], at(13))
    after = (reg.kv_get(forward3.K_Q1)["a"], forward3.valid_days_values(reg.kv_get(forward3.K_LEDGER)["a"]))
    assert after == before


def test_a_strategy_leaving_the_book_keeps_its_recorded_days(env):
    _, reg = env
    v = {"from": day(0), "until": day(3), "values": [[day(1), 0.002]], "missing": [], "jumps": [], "diag": {}}
    forward3.apply(reg, [result("weak", v)], at(4))
    forward3.apply(reg, [result("other", v)], at(5))  # "weak" is no longer re-tested
    assert dict(forward3.valid_days_values(reg.kv_get(forward3.K_LEDGER)["weak"]))[day(1)] == 0.002


def test_a_failed_retest_stays_in_the_coverage_denominator(env, monkeypatch):
    _, reg = env
    monkeypatch.setattr(forward3, "V3_START", "2000-01-01")
    fz = at(0, 0) - timedelta(hours=10)
    _ref(reg, 45, fz)
    e = {"id": "a", "freeze": iso(fz)}
    forward3.note_scheduled(reg, [e], at(0, 1))
    forward3.note_scheduled(reg, [e], at(6, 1))  # in the book through day 5: days 0–5 scheduled
    v = {"from": day(0), "until": day(2), "values": [], "missing": [], "jumps": [], "diag": {}}
    forward3.apply(reg, [result("a", v, freeze=fz, score=40.0)], at(3))  # later re-tests failed: days 3–5 absent
    d = forward3.diagnostics(reg, at(6, 2))
    assert d["q1_members"] == 1 and d["coverage_q1"] == pytest.approx(3 / 6)


def test_a_return_to_the_book_never_changes_a_past_day_of_q1(env, monkeypatch):
    """ChatGPT 23.11 (round 2): `b` leaves the book on day 3 and returns on day 10. The lab then
    publishes b's days 2–9 too, but the composition, weights and line-A day values of those days stay
    as they were: they were fixed by the daily book snapshots before the return."""
    _, reg = env
    monkeypatch.setattr(forward3, "V3_START", "2000-01-01")
    fz = at(0, 0) - timedelta(hours=10)
    _ref(reg, 45, fz)
    a, b = {"id": "a", "freeze": iso(fz)}, {"id": "b", "freeze": iso(fz)}

    def v(rid, x, until):  # one run's record: a constant daily change from day 0
        return result(rid, {"from": day(0), "until": day(until), "values": [[day(i), x] for i in range(until + 1)],
                            "missing": [], "jumps": [], "diag": {}}, freeze=fz, score=40.0)

    def line_a(d):  # what the v3 verdict will compute for day d (DECISIONS §5): mean over M(d)
        led, m = reg.kv_get(forward3.K_LEDGER), forward3.composition(reg, d)["members"]
        return m, (sum(dict(forward3.valid_days_values(led[k]))[d] for k in m) / len(m) if m else None)

    for i in range(10):  # one lab run per day at 01:00; it values the days up to the day before
        forward3.note_scheduled(reg, [a, b] if i < 3 else [a], at(i, 1))
        if i:
            forward3.apply(reg, [v("a", 0.001, i - 1)] + ([v("b", 0.01, i - 1)] if i < 3 else []), at(i, 2))
    before = {day(d): line_a(day(d)) for d in range(9)}
    cov_before = forward3.diagnostics(reg, at(9, 3))["coverage_q1"]
    for i in range(10, 13):  # b is back: the run of day 10 publishes b's days 2–9 as well
        forward3.note_scheduled(reg, [a, b], at(i, 1))
        forward3.apply(reg, [v("a", 0.001, i - 1), v("b", 0.01, i - 1)], at(i, 2))
    assert forward3.valid_days(reg.kv_get(forward3.K_LEDGER)["b"])[:10] == [day(d) for d in range(10)]
    assert {day(d): line_a(day(d)) for d in range(9)} == before  # nothing in the past moved
    assert before[day(1)] == (["a", "b"], pytest.approx(0.0055)) and before[day(5)] == (["a"], 0.001)
    assert before[day(2)] == (["a"], 0.001)  # b was dropped before day 3's run: not scheduled for day 2
    assert forward3.scheduled_days(reg.kv_get(forward3.K_SCHED)["b"], reg.kv_get(forward3.K_BOOKDAYS)) == \
        [day(0), day(1), day(10), day(11)]
    d = forward3.diagnostics(reg, at(12, 3))
    assert cov_before == 1.0 and d["coverage_q1"] == 1.0 and d["q1_off_schedule_days"] == 8  # b's days 2–9


def test_a_day_without_any_lab_run_keeps_the_previous_book(env, monkeypatch):
    """An outage is not a departure: the days stay scheduled and count against coverage until valued."""
    _, reg = env
    fz = at(0, 0) - timedelta(hours=10)
    e = {"id": "a", "freeze": iso(fz)}
    forward3.note_scheduled(reg, [e], at(0, 1))
    forward3.note_scheduled(reg, [e], at(4, 1))  # no lab run on days 1–3
    assert forward3.scheduled_days(reg.kv_get(forward3.K_SCHED)["a"], reg.kv_get(forward3.K_BOOKDAYS)) == \
        [day(i) for i in range(4)]


def test_moving_v3_start_moves_every_stored_eligibility_flag(env, monkeypatch):
    """ChatGPT 23.11 (round 2): a later V3_START must not leave early strategies in the primary sample,
    also those no longer re-tested."""
    _, reg = env
    monkeypatch.setattr(forward3, "V3_START", "2000-01-01")
    fz = at(0, 0) - timedelta(hours=10)
    _ref(reg, 45, fz)
    v = {"from": day(0), "until": day(1), "values": [], "missing": [], "jumps": [], "diag": {}}
    forward3.apply(reg, [result("early", v, freeze=fz, score=40.0)], at(2))
    assert reg.kv_get(forward3.K_LEDGER)["early"]["eligible"] is True
    monkeypatch.setattr(forward3, "V3_START", day(5))
    assert forward3.diagnostics(reg, at(3))["research_eligible"] == 0  # computed, never the stored flag
    forward3.apply(reg, [result("other", v, freeze=at(6), score=1.0)], at(7))  # "early" is not re-tested
    led = reg.kv_get(forward3.K_LEDGER)
    assert led["early"]["eligible"] is False and led["other"]["eligible"] is True


def test_the_book_keeps_promising_strategies_by_the_set_from_two_days_ago(env):
    _, reg = env
    now = utcnow()
    for i, eid in enumerate(["a", "b", "c"]):  # a oldest … c newest, all rejected (not candidates)
        fin = iso(now - timedelta(hours=30 - i))
        reg.upsert("experiments", {"id": eid, "created": fin, "family": "trend_ema", "status": "done", "finished": fin,
                                   "spec": {"pairs": ["BTC/USDT:USDT"]},
                                   "result": {"params": {"f": 1}, "pairs": ["BTC/USDT:USDT"], "score": 0.1,
                                              "verdict": "rejected"}})
    forward3.note_promising(reg, {"a"}, now - timedelta(days=2))
    forward3.note_promising(reg, {"b"}, now)  # today's results: must not decide today's book
    ids = [e["id"] for e in forward.book(reg, limit=2, keep=1)]
    assert ids == ["a", "c"]


def test_v3_records_leave_the_v2_verdict_unchanged(env, tmp_path):
    _, reg = env
    reg2 = Registry(tmp_path / "plain.sqlite")
    now = utcnow()
    rows = [{"id": f"x{i}", "score": 5 - i, "freeze": iso(now - timedelta(days=12)), "tested_until": iso(now),
             "exchange": "bybit", "trades": [[iso(now - timedelta(days=k))[:16], 0.001 * (i - 2)] for k in range(10)]}
            for i in range(8)]
    v = {"from": day(0), "until": day(1), "values": [[day(1), 0.5]], "missing": [], "jumps": [], "diag": {}}
    forward.apply(reg, {"results": [r | {"v3": v} for r in rows]})
    forward.apply(reg2, {"results": rows})
    a, b = reg.kv_get("forward"), reg2.kv_get("forward")
    for k in ("verdict", "top", "rest", "all", "forward_days", "best"):
        assert a[k] == b[k]
    assert "v3" not in reg.kv_get("forward_results")["x0"]  # the ledger keeps it, not the v2 records


# ---------------------------------------------------------------------------- data source and monitoring
def test_a_fallback_run_on_okx_data_never_replaces_bybit_evidence(env):
    _, reg = env
    freeze = iso(utcnow() - timedelta(days=3))
    bybit = {"id": "x1", "score": 1.0, "freeze": freeze, "tested_until": iso(utcnow() - timedelta(hours=5)),
             "exchange": "bybit", "trades": [[iso(utcnow() - timedelta(days=1))[:16], 0.01]]}
    forward.apply(reg, {"results": [bybit]})
    okx = bybit | {"tested_until": iso(utcnow()), "exchange": "okx", "trades": [[iso(utcnow())[:16], -0.05]]}
    out = forward.apply(reg, {"results": [okx, okx | {"id": "x2"}]})
    stored = reg.kv_get("forward_results")
    assert stored["x1"]["exchange"] == "bybit" and stored["x1"]["tested_until"] == bybit["tested_until"]
    assert "x2" not in stored and out["ignored"] == 2 and reg.kv_get("forward")["ignored_other_source"] == 2
    assert any("okx data ignored" in e["message"] for e in reg.q("SELECT message FROM events"))


def test_the_source_rule_follows_the_result_format_not_a_date(env):
    """ChatGPT 23.11: results of format 3 always state their exchange, so one without it is of unknown
    source; older results (the lab code before 23.11) are accepted by the explicit migration rule."""
    _, reg = env
    now = utcnow()
    base = {"score": 1.0, "freeze": iso(now - timedelta(days=2)), "tested_until": iso(now), "trades": []}
    forward.apply(reg, {"results": [base | {"id": "legacy"}, base | {"id": "unknown", "format": 3},
                                    base | {"id": "new", "format": 3, "exchange": "bybit"}]})
    stored = reg.kv_get("forward_results")
    assert "legacy" in stored and "new" in stored and "unknown" not in stored
    summ = reg.kv_get("forward")
    assert summ["legacy_source"] == 1 and summ["ignored_other_source"] == 1


def test_a_stalled_or_failing_v3_recording_is_a_red_flag_while_v2_arrives(env, monkeypatch):
    """ChatGPT 23.11 (4): a fresh v2 forward import proves nothing about the v3 recording."""
    _, reg = env
    t0 = utcnow() - timedelta(hours=30)
    v = {"from": day(0), "until": day(1), "values": [], "missing": [], "jumps": [], "diag": {}}
    forward3.record_status(reg, [result("a", v)], None, t0)
    forward3.record_status(reg, [result("a", None)], None, t0 + timedelta(hours=6))  # v2 only, no v3
    assert "v3 > 24h" in forward3.status_flags(reg)  # last v3 record 30 h ago
    forward3.record_status(reg, [result("a", v)], None)
    assert forward3.status_flags(reg) == []
    forward3.record_status(reg, [result("a", {"error": "boom"})], None)  # the lab could not build v3
    assert forward3.status_flags(reg) == ["v3 error"]
    monkeypatch.setattr(forward3, "apply", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk")))
    forward.apply(reg, {"results": [result("b", v, tested_until=iso(utcnow()))]})
    assert reg.kv_get(forward3.K_STATUS)["last_error"] == "disk" and "v3 error" in observe.red_flags(reg)
    assert reg.kv_get("forward_results")["b"]  # the v2 forward import still went through


def test_a_stalled_forward_is_a_red_flag_while_imports_look_fresh(tmp_path):
    reg = Registry(tmp_path / "r.db")
    reg.heartbeat("manager", "ok", {})
    reg.kv_set("lab", {"last_import": iso(), "last_batch_total": 40, "last_batch_failed": 0})
    reg.kv_set("forward", {"last_accepted": iso(utcnow() - timedelta(hours=30)), "ts": iso()})
    assert "forward > 24h" in observe.red_flags(reg)
    reg.kv_set("forward", {"last_accepted": iso(utcnow() - timedelta(hours=2)), "ts": iso()})
    assert "forward > 24h" not in observe.red_flags(reg)
    assert "v3=[" in observe.status_line(reg)
