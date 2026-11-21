"""Strategy explorer (/explorer): every strategy with research, forward and demo numbers, and
one strategy in full (read-only views over the registry)."""

from datetime import timedelta
from pathlib import Path

import pytest

from aitrader.registry import Registry
from aitrader.settings import Settings
from aitrader.util import iso, utcnow
from aitrader.web import explorer


@pytest.fixture
def reg(tmp_path):
    s = Settings(data_dir=tmp_path, app_dir=Path(__file__).resolve().parents[1])
    s.ensure_dirs()
    return Registry(s.registry_path)


def _seed(reg):
    now = utcnow()
    fin = iso(now - timedelta(days=3))
    reg.upsert("experiments", {"id": "xe1", "created": fin, "family": "tsmom", "status": "done", "finished": fin,
                               "spec": {"family": "tsmom"},
                               "result": {"verdict": "exploratory", "oos": {"trades": 80, "profit_factor": 1.4, "sharpe": 1.1},
                                          "gates": {"deflated_sharpe": {"value": 0.2, "threshold": 0.8, "pass": False},
                                                    "trades": {"value": 80, "threshold": 40, "pass": True}},
                                          "curve": [[1700000000000, 10000], [1700100000000, 10400]],
                                          "folds": [{"test": "a", "oos": {"total_return": 0.02}}], "market": {"alpha_ann": 0.1, "alpha_t": 1.4}}})
    for sid, stage, exp in (("s-live", "exploration", "xe1"), ("s-wait", "exploratory", ""), ("s-old", "retired", "")):
        reg.upsert("strategies", {"id": sid, "experiment_id": exp, "family": "tsmom", "params": {"lookback": 200},
                                  "pairs": ["BTC/USDT:USDT", "ETH/USDT:USDT"], "sides": ["long", "short"], "stage": stage, "score": 1.0,
                                  "oos": {"timeframe": "4h", "trades": 80, "profit_factor": 1.4}, "gates": {},
                                  "live": {"trades": 2, "profit_factor": 3.0, "pnl": 12.5}, "created": fin, "updated": fin,
                                  "stage_since": fin, "history": [{"ts": fin, "to": stage, "reason": "test reason"}]})
    reg.kv_set("forward_results", {"xe1": {"id": "xe1", "freeze": fin, "trades": [[iso(now)[:16], 0.002], [iso(now)[:16], -0.001]]}})
    for i, (pnl, closed) in enumerate(((10.0, True), (2.5, True), (0.0, False))):
        reg.upsert("live_trades", {"trade_id": 100 + i, "sleeve_id": "s-live", "pair": "BTC/USDT:USDT", "is_short": 1,
                                   "open_date": iso(now - timedelta(hours=10 - i)), "close_date": iso(now - timedelta(hours=5 - i)) if closed else None,
                                   "open_rate": 60000, "close_rate": 59000 if closed else None, "profit_ratio": 0.01, "profit_abs": pnl,
                                   "exit_reason": "take_profit" if closed else None, "max_rate": 0, "min_rate": 0, "leverage": 1.0,
                                   "stake_amount": 1000.0, "raw": {}}, key="trade_id")


def test_listing_shows_research_forward_and_demo_side_by_side(reg):
    _seed(reg)
    out = explorer.listing(reg)
    ids = [r["id"] for r in out["strategies"]]
    assert ids[0] == "s-live" and "s-wait" in ids and "s-old" not in ids  # trading first, retired hidden
    r = out["strategies"][0]
    assert r["research"]["pf"] == 1.4 and r["forward"]["trades"] == 2 and r["forward"]["pf"] == 2.0
    assert r["demo"]["trades"] == 2 and r["status"].startswith("Торгует") and r["timeframe"] == "4h"
    assert out["groups"] == {"live": 1, "waiting": 1, "retired": 1}
    assert [x["id"] for x in explorer.listing(reg, "retired")["strategies"]] == ["s-old"]


def test_detail_has_everything_for_one_strategy(reg):
    _seed(reg)
    d = explorer.detail(reg, "s-live")
    assert len(d["trades"]) == 3 and d["trades"][0]["open_rate"] == 60000  # demo trades with prices for the chart
    assert d["card"]["curve"] and d["card"]["idea"] and d["research"]["market"]["alpha_t"] == 1.4
    assert {g["id"] for g in d["gates"]} == {"deflated_sharpe", "trades"} and any(not g["pass"] for g in d["gates"])
    assert len(d["forward_trades"]) == 2 and d["history"][-1]["reason"] == "test reason"
    assert explorer.detail(reg, "nope") is None
    w = explorer.detail(reg, "s-wait")  # no experiment behind it: still a complete page
    assert w["trades"] == [] and w["row"]["stage"] == "exploratory"


def test_candles_are_browser_safe_and_built_for_the_strategy_timeframe():
    payload = {"columns": ["date", "open", "high", "low", "close", "volume"],
               "data": [[f"2026-11-21 {h:02d}:{m:02d}:00", 10 + h, 11 + h, 9 + h, 10.5 + h, 1] for h in range(3, 9) for m in (0, 15, 30, 45)]}
    rows = explorer.candle_rows(payload)
    assert rows[0][0] == "2026-11-21T03:00:00Z" and len(rows) == 24  # Safari-safe ISO dates
    four = explorer.resample(rows, 240)
    # 03:00-03:45 belongs to the incomplete 00:00 bucket and is dropped; 04:00-07:45 makes one 4h candle
    assert four[0] == ["2026-11-21T04:00:00Z", 14, 18, 13, 17.5] and len(four) == 2
    assert explorer.candle_rows({"columns": ["date"], "data": [[1]]}) == []


def test_open_positions_belong_to_their_strategy_only():
    status = [{"trade_id": 7, "enter_tag": "s-live", "pair": "ETH/USDT:USDT", "is_short": True, "open_date": "2026-11-21 10:00:00",
               "open_rate": 3000, "current_rate": 2950, "profit_abs": 4.2},
              {"trade_id": 8, "enter_tag": "other", "pair": "ETH/USDT:USDT"}]
    out = explorer.open_trades(status, "s-live")
    assert len(out) == 1 and out[0]["is_open"] and out[0]["close_date"] is None and out[0]["open_date"] == "2026-11-21T10:00:00Z"
