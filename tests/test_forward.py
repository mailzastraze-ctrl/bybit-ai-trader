"""Forward test (shadow book): frozen strategies on unseen data, pre-registered verdict."""

import json
import random
from datetime import timedelta
from pathlib import Path

import pytest
from test_lifecycle import FakeRunner

from aitrader import forward, lab
from aitrader.registry import Registry
from aitrader.research import shadow
from aitrader.settings import Settings
from aitrader.util import iso, utcnow


@pytest.fixture
def env(tmp_path):
    s = Settings(data_dir=tmp_path, app_dir=Path(__file__).resolve().parents[1])
    s.ensure_dirs()
    return s, Registry(s.registry_path)


def _exp(reg, eid, score, hours_ago=48, folds=(0.02, 0.01, 0.01, -0.005), revalidates=None):
    fin = iso(utcnow() - timedelta(hours=hours_ago))
    reg.upsert("experiments", {"id": eid, "created": fin, "family": "trend_ema", "status": "done", "finished": fin,
                               "spec": {"family": "trend_ema", "pairs": ["BTC/USDT:USDT", "ETH/USDT:USDT"],
                                        **({"revalidates": revalidates} if revalidates else {})},
                               "result": {"params": {"fast": 10}, "pairs": ["BTC/USDT:USDT"], "score": score,
                                          "verdict": "rejected", "oos": {"profit_factor": 1.1, "trades": 40},
                                          "folds": [{"oos": {"total_return": x}} for x in folds]}})


def _rows(n, edge_top, edge_rest, days=20, per_day=2, seed=1):
    rng, now, rows = random.Random(seed), utcnow(), []
    for i in range(n):
        top = i < n // 4
        trades = []
        for d in range(days):
            for _ in range(per_day):
                ts = iso(now - timedelta(days=days - d))[:16]
                trades.append([ts, rng.gauss(edge_top if top else edge_rest, 0.002)])
        rows.append({"id": f"x{i:05d}", "score": 10 - i * 0.1, "freeze": iso(now - timedelta(days=days + 1)),
                     "trades": trades, "variant": "v"})
    return rows


def test_book_freezes_finished_experiments_but_not_revalidations(env):
    s, reg = env
    _exp(reg, "x1", 0.5)
    _exp(reg, "x2", 0.1, revalidates="prod-1")
    b = forward.book(reg)
    assert [e["id"] for e in b] == ["x1"] and b[0]["params"] == {"fast": 10} and b[0]["freeze"]
    assert lab.build_state(s, reg)["shadow"][0]["id"] == "x1"


def test_verdict_is_too_early_without_enough_evidence():
    rows = _rows(8, 0.002, 0.0, days=3, per_day=1)
    assert forward.summarize(rows)["verdict"] == "too_early"


def test_verdict_works_when_top_quartile_keeps_its_edge():
    v = forward.summarize(_rows(40, 0.0015, -0.0005))
    assert v["verdict"] == "works" and v["top"]["trades"] >= 200 and v["top"]["pf"] > 1.15
    assert v["rank_corr"] > 0  # the backtest ranking predicted the forward ranking


def test_verdict_not_working_when_best_ranked_lose():
    v = forward.summarize(_rows(40, -0.001, 0.0))
    assert v["verdict"] == "not_working"


def test_persistence_indicator_from_walk_forward_folds(env):
    _, reg = env
    for i in range(6):
        _exp(reg, f"xp{i}", 0.1, folds=(0.02, 0.01, 0.01, 0.01))
    for i in range(4):
        _exp(reg, f"xn{i}", 0.1, folds=(-0.02, -0.01, -0.01, 0.0))
    p = forward.persistence(reg)
    assert p["experiments"] == 10 and p["p_second_pos_if_first_pos"] == 1.0 and p["p_second_pos_if_first_neg"] == 0.0


def test_apply_stores_verdict_and_promotes_forward_winners(env):
    s, reg = env
    _exp(reg, "xwin000001", 0.9)
    _exp(reg, "xlose00002", 0.8)
    now = utcnow()
    win = [[iso(now - timedelta(hours=h))[:16], 0.002 if h % 3 else -0.001] for h in range(1, 31)]
    lose = [[iso(now - timedelta(hours=h))[:16], -0.001] for h in range(1, 31)]
    res = lab.apply_import(s, reg, {"shadow": {"results": [
        {"id": "xwin000001", "score": 0.9, "freeze": iso(now - timedelta(days=2)), "pairs": ["BTC/USDT:USDT"], "trades": win},
        {"id": "xlose00002", "score": 0.8, "freeze": iso(now - timedelta(days=2)), "pairs": ["BTC/USDT:USDT"], "trades": lose}]}})
    assert res["forward"]["promoted"] == 1
    st = reg.one("SELECT stage, note FROM strategies WHERE id='fw-win00000'")
    assert st["stage"] == "exploratory" and "forward-proven" in st["note"]
    assert reg.kv_get("forward")["verdict"] == "too_early"


class _FwRunner(FakeRunner):
    def backtest(self, job, configs, strategy, timerange, fee, out_name):
        out = job.path(out_name)
        out.mkdir(parents=True, exist_ok=True)
        now = utcnow()
        trades = [{"pair": "BTC/USDT:USDT", "open_date": iso(now - timedelta(hours=h + 2)),
                   "close_date": iso(now - timedelta(hours=h)), "profit_abs": 5.0, "stake_amount": 300.0,
                   "leverage": 3.0, "exit_reason": "take_profit"} for h in (1, 10, 100)]
        trades.append(dict(trades[0], exit_reason="force_exit"))
        (out / "bt.json").write_text(json.dumps({"strategy": {"AIPortfolio": {"trades": trades}}}))
        (out / ".last_result.json").write_text(json.dumps({"latest_backtest": "bt.json"}))
        return out


def test_shadow_counts_only_trades_after_the_freeze(env, tmp_path):
    s, _ = env
    entry = {"id": "x1", "family": "trend_ema", "params": {}, "pairs": ["BTC/USDT:USDT"],
             "freeze": iso(utcnow() - timedelta(hours=50)), "score": 1.0}
    res = shadow.run(s, [entry], tmp_path / "sh", workers=1, ft=_FwRunner(True))
    tr = res[0]["trades"]
    assert len(tr) == 2  # the trade opened before the freeze and the force-exit are excluded
    assert abs(tr[0][1] - (5.0 - 900 * 0.0005 * 2) / 10_000) < 1e-9  # slippage haircut applied


def test_book_includes_imported_candidate_strategies(env):
    _, reg = env
    now = iso(utcnow() - timedelta(hours=30))
    reg.upsert("strategies", {"id": "b1-trend-00", "experiment_id": "x-not-here", "family": "trend_ema", "params": {"fast": 9},
                              "pairs": ["ETH/USDT:USDT"], "sides": ["long"], "stage": "exploratory", "score": 0.4,
                              "oos": {"profit_factor": 1.2}, "gates": {}, "live": {}, "created": now, "updated": now,
                              "stage_since": now, "history": []})
    b = forward.book(reg)
    assert b[0]["id"] == "b1-trend-00" and b[0]["kind"] == "strategy" and b[0]["freeze"] == now
