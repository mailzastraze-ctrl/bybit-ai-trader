"""Evidence fixes of 2026-11-22 (review with ChatGPT).

Scenario 5: re-used out-of-sample data never earns independent validation.
Scenario 6: the bot is compared with the owner's engine on the same coin over the same time.
Plus: research pairs are chosen on regime scores measured before the test windows.
"""

from datetime import UTC, datetime

import pandas as pd

from aitrader.research.validation import clean_oos, evaluate_gates
from aitrader.settings import Gates


def _all_pass():
    oos = {"trades": 500, "profit_factor": 3.0, "sharpe": 3.0, "max_drawdown": 0.05, "total_return": 0.5}
    return {"oos": oos, "stress": {"profit_factor": 2.5}, "wfe": 1.0, "robust_frac": 1.0,
            "mc": {"prob_profit": 1.0}, "dsr": 0.99, "fold_pos": 1.0, "alpha": 0.01, "alpha_t": 3.0}


def test_refinements_and_revalidations_cannot_validate():
    assert clean_oos({"family": "rsi_revert"}) is True  # a fresh search: clean test windows
    for spec in ({"refines": "x1"}, {"revalidates": "s1"}, {"screen": "scr-1"}, {"external": "owner-1"}):
        assert clean_oos(spec) is False
        verdict, gates = evaluate_gates(Gates(), {**_all_pass(), "clean_oos": clean_oos(spec)})
        assert verdict == "exploratory" and gates["clean_oos"]["pass"] is False  # can trade tiny, never "validated"
    assert evaluate_gates(Gates(), {**_all_pass(), "clean_oos": True})[0] == "validated"


def _trades(pair, pnls):
    return [{"pair": pair, "profit_abs": p} for p in pnls]


def _spec(primary="ZEC/USDT:USDT", pf=5.0, trades=65, years=2.9, b_trades=9):
    return {"screen_holdout": {"A": {"pf": pf, "trades": trades, "years": years}, "B": {"trades": b_trades},
                               "coins": {"list": [primary, "ADA/USDT:USDT", "RARE/USDT:USDT"]}}}


def test_parity_is_judged_on_the_primary_coin_like_for_like():
    from aitrader.research.pipeline import parity
    # first 3-year run, 22.11: ZEC repeated (66 trades vs ~64 expected, profitable); the added
    # coins lost – the old pooled check called this "broken"
    tr = _trades("ZEC/USDT:USDT", [30.0] * 40 + [-20.0] * 26) + _trades("ADA/USDT:USDT", [10.0] * 20 + [-15.0] * 39)
    p = parity(_spec(), {"profit_factor": 0.8, "trades": len(tr)}, tr, days=990)
    assert p["coin"] == "ZEC/USDT:USDT" and p["bot_trades"] == 66
    assert 60 <= p["expected_trades"] <= 68 and p["signals_ok"] and p["profit_ok"] and p["ok"]
    assert p["others"]["trades"] == 59 and p["others"]["pf"] < 1.0  # reported apart: transfer, not parity
    # same coin, far fewer trades than the engine over the same time: the signals differ
    few = _trades("ZEC/USDT:USDT", [30.0] * 20 + [-20.0] * 10)
    q = parity(_spec(), {}, few, days=990)
    assert q["signals_ok"] is False and q["ok"] is False
    # same signals, but it loses where the engine earned: a money gap
    lose = _trades("ZEC/USDT:USDT", [10.0] * 30 + [-20.0] * 36)
    r = parity(_spec(), {}, lose, days=990)
    assert r["signals_ok"] and r["profit_ok"] is False
    # no trade detail (old results): the pooled comparison, marked as such
    assert parity(_spec(), {"profit_factor": 0.5, "trades": 60})["pooled"] is True


def test_parity_alarm_only_when_half_fail_on_their_own_coin(tmp_path):
    from aitrader.lab import record_parity
    from aitrader.registry import Registry
    reg = Registry(tmp_path / "r.db")
    good = {"coin": "ZEC", "ok": True, "signals_ok": True, "profit_ok": True, "others": {"trades": 100, "pnl": -50}}
    gap = {**good, "ok": False, "profit_ok": False}
    rows = [good] * 10 + [gap] * 5
    out = record_parity(reg, {"batch_id": "b", "experiments_full": [
        {"spec": {"screen": f"s{i}"}, "result": {"parity": p}} for i, p in enumerate(rows)]}, "t")
    assert out["checked"] == 15 and out["profit_gaps"] == 5 and out["signals_broken"] == 0
    assert out["like_for_like"] and not out["alarm"]
    assert out["others"]["trades"] == 1500


def test_research_pairs_are_ranked_on_scores_from_before_the_test_windows(tmp_path):
    from pathlib import Path

    from aitrader.registry import Registry
    from aitrader.research.generator import Generator
    from aitrader.scanner import holdout_start, pair_scores
    from aitrader.settings import Settings
    assert holdout_start(360, datetime(2026, 11, 22, 13, 5, tzinfo=UTC)) == datetime(2025, 11, 27, tzinfo=UTC)
    # pair_scores of the data before the cut ignores what happened after it
    n = 24 * 200
    dates = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    import numpy as np
    rng = np.random.default_rng(3)
    close = 100 * np.exp(np.cumsum(np.r_[rng.normal(0, 0.01, n - 24 * 60), np.full(24 * 60, 0.004)]))
    df = pd.DataFrame({"date": dates, "open": close, "high": close * 1.002, "low": close * 0.998, "close": close,
                       "volume": 1.0})
    late, early = pair_scores(df), pair_scores(df.iloc[: n - 24 * 60])
    assert late["trend_score"] > early["trend_score"]  # the strong trend sits in the last 60 days only
    # the generator ranks on pre_oos, not on the recent score
    s = Settings(data_dir=tmp_path, app_dir=Path(__file__).resolve().parents[1])
    s.ensure_dirs()
    reg = Registry(s.registry_path)
    reg.upsert("market", {"pair": "A", "ts": "t", "data": {"trend_score": 9.0, "pre_oos": {"trend_score": 0.1}}}, key="pair")
    reg.upsert("market", {"pair": "B", "ts": "t", "data": {"trend_score": 0.2, "pre_oos": {"trend_score": 5.0}}}, key="pair")
    for i in range(8):  # ordinary coins: middling before the test windows, flat recently
        reg.upsert("market", {"pair": f"Z{i}", "ts": "t", "data": {"trend_score": 0.0, "pre_oos": {"trend_score": 1.0}}},
                   key="pair")
    s.research.pairs_per_experiment = 1
    g = Generator(s, reg, seed=1)
    picks = {g.next_spec(["A", "B"] + [f"Z{i}" for i in range(8)], family="trend_ema")["pairs"][0] for _ in range(30)}
    assert "B" in picks and "A" not in picks  # A only looks good inside the test windows
