"""Observation only: missed-signal summary and effective number of independent bets."""

import json
from datetime import timedelta

from aitrader import observe
from aitrader.util import iso, utcnow


def test_every_signal_gets_one_outcome(tmp_path):
    now = utcnow()
    t = lambda m: iso(now - timedelta(minutes=m))  # noqa: E731
    p = tmp_path / "signals.jsonl"
    rows = [
        {"ts": t(100), "k": "sig", "s": "a", "p": "BTC", "d": "long", "o": "emitted", "c": "c1"},
        {"ts": t(99), "k": "cfm", "s": "a", "p": "BTC", "d": "long", "o": "open_risk"},
        {"ts": t(95), "k": "cfm", "s": "a", "p": "BTC", "d": "long", "o": "accepted"},
        {"ts": t(100), "k": "sig", "s": "a", "p": "BTC", "d": "long", "o": "emitted", "c": "c1"},
        {"ts": t(80), "k": "sig", "s": "a", "p": "ETH", "d": "short", "o": "pair_busy", "c": "c2"},
        {"ts": t(70), "k": "sig", "s": "b", "p": "SOL", "d": "short", "o": "emitted", "c": "c3"},
        {"ts": t(69), "k": "cfm", "s": "b", "p": "SOL", "d": "short", "o": "side_risk"},
        {"ts": t(60), "k": "sig", "s": "b", "p": "XRP", "d": "long", "o": "emitted", "c": "c4"},
        {"ts": t(30), "k": "cfm", "s": "b", "p": "ADA", "d": "long", "o": "accepted"},
        {"ts": iso(now - timedelta(days=9)), "k": "sig", "s": "a", "p": "BTC", "d": "long", "o": "emitted", "c": "old"},
    ]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n")
    out = observe.summarize_signals(p, days=7, now=now)
    a, b = out["per_sleeve"]["a"], out["per_sleeve"]["b"]
    assert a == {"signals": 2, "executed": 1, "missed": {"pair_busy": 1}}
    assert b == {"signals": 3, "executed": 1, "missed": {"side_risk": 1, "not_entered": 1}}
    assert out["total"]["signals"] == 5 and out["total"]["executed"] == 2
    assert observe.trim_journal(p, keep_days=7, now=now) == 9 and "old" not in p.read_text()
    assert observe.summarize_signals(tmp_path / "missing.jsonl")["total"]["signals"] == 0


def test_ten_correlated_shorts_are_about_one_bet():
    trades = [{"pair": f"C{i}", "is_short": True, "open_rate": 100.0, "stop_loss_abs": 102.0, "stake_amount": 1000.0}
              for i in range(10)]
    import random
    rnd = random.Random(1)
    common = [rnd.gauss(0, 1) for _ in range(500)]
    rets = {f"C{i}": [0.9 * c + 0.436 * rnd.gauss(0, 1) for c in common] for i in range(10)}  # ρ ≈ 0.8
    out = observe.exposure(trades, rets, equity=50000)
    assert 1.0 < out["eff_bets"] < 1.6 and out["one_side_share"] == 1.0 and out["short"] == 10
    assert out["risk_short"] == 200.0 and out["risk_pct"] == 0.4
    indep = {f"C{i}": [rnd.gauss(0, 1) for _ in range(500)] for i in range(10)}
    assert observe.exposure(trades, indep)["eff_bets"] > 8.5
    hedge = [dict(trades[0]), {**trades[1], "is_short": False, "stop_loss_abs": 98.0}]
    h = observe.exposure(hedge, rets)
    assert h["eff_bets"] == 2.0 and h["one_side_share"] == 0.5  # a hedge is never "more than n" bets
    assert observe.exposure([], {})["eff_bets"] is None
    assert observe.exposure(trades[:2], {})["eff_bets"] == round(4 / (2 + 2 * 0.6), 2)  # no candles: crypto default 0.6


def test_replication_quarters_fit_the_history_that_exists():
    from aitrader.research.pipeline import fit_folds
    now = utcnow()
    assert fit_folds(now - timedelta(days=1600), 185, 90, 12, now=now) == 12
    assert fit_folds(now - timedelta(days=1200), 185, 90, 12, now=now) == 10   # 6h: 3 of 12 quarters do not fit
    assert fit_folds(now - timedelta(days=1200), 365, 90, 12, now=now) == 8    # 12h needs a year of warm-up
    assert fit_folds(now - timedelta(days=500), 365, 90, 12, now=now) == 4     # never below the old one year
    assert fit_folds(None, 185, 90, 12, now=now) == 4


def _trade(tid, reason, close, isl=2.986, o=2.817, amount=229.5, short=True, closed=None):
    return {"trade_id": tid, "sleeve_id": "s", "pair": "NEAR", "is_short": int(short), "open_rate": o, "close_rate": close,
            "close_date": iso(closed or (utcnow() - timedelta(days=2))), "exit_reason": reason,
            "raw": {"initial_stop_loss_abs": isl, "amount": amount}}


def _candles(start, prices):
    t0 = start.timestamp() * 1000
    return [[t0 + (i + 1) * 900e3, p, p * 1.001, p * 0.999, p] for i, p in enumerate(prices)]


def test_post_mortem_judges_each_exit_against_its_own_plan():
    closed = utcnow() - timedelta(days=2)
    p = {"tp_rr": 2.0}
    risk = 2.986 - 2.817
    # protective exit (stop moved near entry), then price ran to the original stop: the exit saved money
    a = observe.judge_exit(_trade(1, "managed_stop", 2.842, closed=closed), p, _candles(closed, [2.85, 2.95, 3.0]))
    assert a["kind"] == "protective" and a["status"] == "done" and a["hold_r"] == -1.0
    assert abs(a["saved_usd"] - (-(2.842 - 2.817) / risk + 1) * risk * 229.5) < 0.05 and a["saved_usd"] > 30
    # … or to the target: the early exit cost money
    b = observe.judge_exit(_trade(2, "managed_stop", 2.842, closed=closed), p, _candles(closed, [2.7, 2.5, 2.45]))
    assert b["hold_r"] == 2.0 and b["saved_usd"] < -70
    # planned stop, then price went another half R against: the stop was right
    c = observe.judge_exit(_trade(3, "managed_stop", 2.986, closed=closed), p, _candles(closed, [3.0, 3.1]))
    assert c["kind"] == "stop" and c["status"] == "confirmed"
    # planned stop, then price came back to the target: a wider stop would have won
    d = observe.judge_exit(_trade(4, "stoploss_on_exchange", 2.99, closed=closed), p, _candles(closed, [2.9, 2.6, 2.47]))
    assert d["kind"] == "stop" and d["status"] == "reversed" and "slip_usd" not in d
    g = observe.judge_exit(_trade(8, "stoploss_on_exchange", 3.07, closed=closed), p, [])  # filled 0.5 R beyond the stop
    assert abs(g["slip_usd"] - 0.497 * risk * 229.5) < 0.5
    # take profit: how much further it went
    e = observe.judge_exit(_trade(5, "take_profit", 2.479, closed=closed), p, _candles(closed, [2.45, 2.40, 2.50]))
    assert e["kind"] == "take_profit" and 0.3 < e["further_r"] < 0.6
    # nothing after the exit yet / no initial stop known → open / not judged
    assert observe.judge_exit(_trade(6, "exit_signal", 2.8, closed=closed), p, [])["status"] == "open"
    assert observe.judge_exit({**_trade(7, "exit_signal", 2.8), "raw": {}}, p, []) is None
    s = observe.summarize_postmortem([a, b, c, d, e])
    assert s["protective"] == {"n": 2, "done": 2, "saved_usd": round(a["saved_usd"] + b["saved_usd"], 2), "better": 1, "worse": 1, "open": 0}
    assert s["stop"] == {"n": 2, "reversed": 1, "confirmed": 1, "open": 0, "slipped": 0, "slip_usd": 0.0} and s["take_profit"]["avg_further_r"] == e["further_r"]


def test_post_mortem_runs_on_the_registry_and_keeps_verdicts(tmp_path):
    from aitrader.registry import Registry
    reg = Registry(tmp_path / "r.db")
    closed = utcnow() - timedelta(days=1)
    reg.upsert("live_trades", {**_trade(11, "managed_stop", 2.842, closed=closed), "open_date": iso(closed - timedelta(hours=5)),
                               "profit_abs": -6.2, "profit_ratio": -0.01, "max_rate": 0, "min_rate": 0, "leverage": 1.0,
                               "stake_amount": 650.0}, key="trade_id")
    reg.upsert("strategies", {"id": "s", "family": "tsmom", "params": {"tp_rr": 2.0}, "stage": "exploration", "pairs": ["NEAR"]})

    class FT:
        calls = 0

        def pair_candles(self, pair, tf, limit):
            FT.calls += 1
            rows = _candles(closed, [2.85, 2.95, 3.0])
            return {"columns": ["date", "open", "high", "low", "close", "__date_ts"],
                    "data": [[None, x[1], x[2], x[3], x[4], x[0]] for x in rows]}
    out = observe.postmortem(reg, FT())
    assert out["trades"]["11"]["status"] == "done" and out["summary"]["protective"]["better"] == 1
    observe.postmortem(reg, FT())
    assert FT.calls == 1  # a finished verdict is not recomputed
