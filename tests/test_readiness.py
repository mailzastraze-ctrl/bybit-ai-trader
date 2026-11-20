"""Real-money readiness gate and the demo→reality haircut."""

from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

from aitrader import readiness
from aitrader.learner import live_metrics
from aitrader.realism import real_pnl, trade_cost
from aitrader.registry import Registry
from aitrader.settings import Settings
from aitrader.util import iso, utcnow


@pytest.fixture
def reg(tmp_path):
    s = Settings(data_dir=tmp_path, app_dir=Path(__file__).resolve().parents[1])
    s.ensure_dirs()
    return Registry(s.registry_path)


def _strategy(reg, sid, since_days, stage="production"):
    since = iso(utcnow() - timedelta(days=since_days))
    reg.upsert("strategies", {"id": sid, "experiment_id": "", "family": "trend_ema", "params": {}, "pairs": ["BTC/USDT:USDT"],
                              "sides": ["long"], "stage": stage, "score": 1, "oos": {"expectancy": 0.004}, "gates": {},
                              "live": {}, "created": since, "updated": since, "stage_since": since, "history": []})


def _trades(reg, sid, n, start_id, days, seed, edge=0.5, stake=100.0, lev=3.0):
    rng = np.random.default_rng(seed)
    t0 = utcnow() - timedelta(days=days)
    for i in range(n):
        win = rng.random() < 0.5 + 0.1 * edge
        pnl = (16.0 if win else -10.0) * rng.uniform(0.7, 1.3)
        cd = t0 + timedelta(hours=i * days * 24 / n + 1)
        reg.upsert("live_trades", {"trade_id": start_id + i, "sleeve_id": sid, "pair": "BTC/USDT:USDT", "is_short": 0,
                                   "open_date": iso(cd - timedelta(hours=2)), "close_date": iso(cd), "open_rate": 100,
                                   "close_rate": 101, "profit_ratio": pnl / stake, "profit_abs": pnl, "exit_reason": "x",
                                   "max_rate": 0, "min_rate": 0, "leverage": lev, "stake_amount": stake, "raw": {}},
                   key="trade_id")


def test_haircut_is_applied_to_every_fill():
    t = {"profit_abs": 10.0, "profit_ratio": 0.1, "stake_amount": 100.0, "leverage": 3.0}
    assert trade_cost(t) == pytest.approx(300 * 0.0005 * 2)
    assert real_pnl(t) == pytest.approx(10.0 - 0.3)
    m = live_metrics([t, {**t, "profit_abs": -5.0, "profit_ratio": -0.05}], 10_000)
    assert m["pnl"] < m["pnl_demo"]


def test_not_ready_without_production_evidence(reg):
    r = readiness.evaluate(reg, 10_000)
    assert r["ready"] is False and r["passed"] == 0 and r["evidence"]["trades"] == 0


def test_ready_only_with_enough_independent_post_promotion_evidence(reg):
    _strategy(reg, "a", 100)
    _strategy(reg, "b", 100)
    _trades(reg, "a", 160, 1, 95, seed=1, edge=1.0)
    _trades(reg, "b", 160, 1000, 95, seed=2, edge=1.0)
    # trades before promotion and exploration trades are not evidence
    _trades(reg, "a", 50, 5000, 130, seed=3, edge=-3.0)
    r = readiness.evaluate(reg, 10_000)
    chk = {c["id"]: c for c in r["checks"]}
    assert r["evidence"]["trades"] >= 320 - 50
    assert chk["forward_days"]["pass"] and chk["trades"]["pass"] and chk["diversified"]["pass"]
    assert chk["profit_factor"]["pass"] and chk["t_stat"]["pass"], chk
    assert r["ready"] is True


def test_slippage_can_destroy_a_thin_edge(reg, monkeypatch):
    _strategy(reg, "a", 100)
    _trades(reg, "a", 300, 1, 95, seed=5, edge=0.15, stake=1000.0, lev=5.0)
    r = readiness.evaluate(reg, 10_000)
    assert r["evidence"]["pnl_real"] < r["evidence"]["pnl_demo"]
    assert r["ready"] is False


def test_update_records_and_announces(reg):
    readiness.update(reg, 10_000)
    assert reg.kv_get("readiness")["total"] == 8
