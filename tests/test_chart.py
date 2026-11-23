"""Charts on every page (owner, 23.11): Bybit candles of any period, every trade on a coin –
demo trades and each trading strategy's backtest year from the lab – and per-coin figures only."""

from datetime import timedelta
from pathlib import Path

import pytest

from aitrader import lab
from aitrader.lifecycle import Lifecycle
from aitrader.registry import Registry
from aitrader.research import shadow
from aitrader.settings import Settings
from aitrader.util import iso, utcnow
from aitrader.web import chart, desks_api, explorer

BTC, ETH, SOL = "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("DEMO_MODE")
    monkeypatch.delenv("DEMO_CORE")
    s = Settings(data_dir=tmp_path, app_dir=Path(__file__).resolve().parents[1])
    s.ensure_dirs()
    return s, Registry(s.registry_path)


def add(reg, sid, pair_stats, days=360, n_pairs=10):
    reg.upsert("experiments", {"id": f"x-{sid}", "created": iso(), "family": "rsi_revert",
                               "spec": {"pairs": [f"C{i}/USDT:USDT" for i in range(n_pairs)]}, "status": "done",
                               "result": {"pair_stats": pair_stats, "oos": {"n_days": days, "max_drawdown": 0.04}}})
    reg.upsert("strategies", {"id": sid, "experiment_id": f"x-{sid}", "family": "rsi_revert", "params": {"rsi_len": 9},
                              "pairs": list(pair_stats), "sides": ["long", "short"], "stage": "exploration", "score": 1.0,
                              "oos": {"timeframe": "1h", "max_drawdown": 0.04, "trades": sum(v["trades"] for v in pair_stats.values()),
                                      "n_days": days}, "gates": {}, "live": {},
                              "created": iso(), "updated": iso(), "stage_since": iso(), "history": []})


def desks(reg, created=None):
    reg.kv_set("desks", {"epoch": 1, "created": created or iso(utcnow() - timedelta(hours=2)), "coins": {
        BTC: {"strategy": "own", "family": "macd_cross", "timeframe": "6h", "per_month": 1.52, "pnl_month": 53.0, "max_dd": 0.034,
              "oos_trades": 18, "params": {"a": 1}, "sides": ["long", "short"], "coin_scores": {ETH: 10.0}},
        ARB: {"strategy": "guest", "family": "rsi_revert", "timeframe": "1h", "per_month": 1.86, "pnl_month": 27.0, "max_dd": 0.04,
              "oos_trades": 22, "params": {"rsi_len": 9}, "sides": ["long", "short"], "coin_scores": {BTC: 9.2, SOL: 1.0}}}})


ARB = "ARB/USDT:USDT"


def test_bybit_symbols_and_kline_pages():
    assert chart.symbol(BTC) == "BTCUSDT" and chart.symbol("1000PEPE/USDT:USDT") == "1000PEPEUSDT"
    page = {"retCode": 0, "result": {"list": [["2000", "2", "3", "1", "2.5", "10", "0"], ["1000", "1", "2", "0.5", "2", "5", "0"], ["x"]]}}
    assert chart.parse_kline(page) == [[1000, 1.0, 2.0, 0.5, 2.0, 5.0], [2000, 2.0, 3.0, 1.0, 2.5, 10.0]]  # oldest first


def test_candles_any_period_cached_and_paged_back():
    calls = []

    def fetch(sym, interval, end, limit):
        calls.append((sym, interval, end, limit))
        top = end or 10_000_000_000_000
        return [[top - 3_600_000 * i, 1, 2, 0.5, 1.5, 1] for i in range(limit)][::-1]
    chart._cache.clear()
    a = chart.candles(BTC, "1h", None, 50, fetch=fetch)
    b = chart.candles(BTC, "1h", None, 50, fetch=fetch)
    assert a == b and len(calls) == 1 and calls[0][:2] == ("BTCUSDT", "60") and a["more"]  # newest page cached briefly
    old = chart.candles(BTC, "4h", 1_700_000_000_000, 2000, fetch=fetch)
    assert calls[-1] == ("BTCUSDT", "240", 1_700_000_000_000, 1000)  # older history: Bybit's page size, ends where asked
    assert old["candles"][-1][0] <= 1_700_000_000_000
    with pytest.raises(ValueError):
        chart.candles(BTC, "3m", None, 10, fetch=fetch)


def test_every_trade_on_a_coin_demo_and_the_labs_history(env):
    s, reg = env
    desks(reg)
    reg.upsert("live_trades", {"trade_id": 28, "sleeve_id": "guest", "pair": BTC, "is_short": 1, "open_date": "2026-11-23 17:12:11",
                               "close_date": "2026-11-23 17:15:06", "open_rate": 61883.0, "close_rate": 62032.9,
                               "profit_abs": -3.02, "profit_ratio": -0.00325, "exit_reason": "exit_signal"}, key="trade_id")
    reg.upsert("live_trades", {"trade_id": 1, "sleeve_id": "exec-test-1", "pair": BTC, "is_short": 0, "open_date": "2026-11-23 10:00:00",
                               "close_date": "2026-11-23 10:01:00", "open_rate": 1, "close_rate": 1, "profit_abs": 0}, key="trade_id")
    status = [{"trade_id": 30, "pair": BTC, "enter_tag": "own", "is_short": False, "open_date": "2026-11-23 18:00:00", "amount": 0.01,
               "open_rate": 62000, "current_rate": 62100, "profit_abs": 1.0, "stop_loss_abs": 60000},
              {"trade_id": 31, "pair": BTC, "enter_tag": "own", "is_short": False, "open_date": "2026-11-23 18:01:00", "amount": 0}]
    stored = chart.store_history(reg, [{"id": "guest", "ok": True, "from": "2025-11-23T00:00:00Z", "to": "2026-11-23T00:00:00Z",
                                        "params_key": "k", "pairs": {BTC: [[1, 2, 1, 100.0, 99.0, 0.01, "exit_signal"]]}},
                                       {"id": "broken", "ok": False}])
    assert stored == 1
    d = chart.coin_trades(reg, BTC, status, {"own": [BTC, ETH], "guest": [ARB, BTC, SOL]})
    assert d["strategies"] == ["own", "guest"]  # the coin's own strategy first, then the guests
    assert [t["id"] for t in d["demo"]] == [28, 30]  # execution tests and an unfilled entry are not trades
    assert d["demo"][1]["open"] and d["demo"][1]["stop"] == 60000
    h = d["history"]["guest"]["trades"]
    assert h == [{"sid": "guest", "short": True, "t0": 1, "t1": 2, "p0": 100.0, "p1": 99.0, "ret": 0.01, "why": "exit_signal", "hist": True}]
    assert d["history"]["own"]["trades"] == []  # not yet backtested by the lab


def test_lab_backtests_a_year_for_every_trading_strategy_on_all_its_coins(env):
    s, reg = env
    desks(reg)
    book = {e["id"]: e for e in lab.history_book(reg)}
    assert set(book) == {"own", "guest"}
    assert book["guest"]["pairs"] == [ARB, BTC, SOL] and book["own"]["pairs"] == [BTC, ETH]  # its coin + the proven ones
    assert book["own"]["params"] == {"a": 1} and book["own"]["timeframe"] == "6h"  # frozen as on demo
    chart.store_history(reg, [{"id": "guest", "ok": True, "params_key": book["guest"]["params_key"], "pairs": {}}])
    assert {e["id"] for e in lab.history_book(reg)} == {"own"}  # done this week with these parameters
    assert {e["id"] for e in lab.history_book(reg, now=utcnow() + timedelta(days=8))} == {"own", "guest"}  # redone weekly
    assert "history" in lab.build_state(s, reg)


def test_backtest_trades_are_compacted_per_coin():
    rows = shadow._compact([{"pair": BTC, "open_date": "2026-01-01 00:00:00+00:00", "close_date": "2026-01-01 05:00:00+00:00",
                             "is_short": True, "open_rate": 100.0, "close_rate": 98.0, "profit_ratio": 0.0199, "exit_reason": "exit_signal"}])
    assert rows == {BTC: [[1767225600000, 1767243600000, 1, 100.0, 98.0, 0.0199, "exit_signal"]]}


def test_coin_page_shows_figures_on_that_coin_only_and_its_guests(env):
    s, reg = env
    add(reg, "guest", {ARB: {"pnl": 327.6, "trades": 22}, BTC: {"pnl": 331.3, "trades": 24}})
    add(reg, "own", {BTC: {"pnl": 600.0, "trades": 18}})
    desks(reg)
    ev = Lifecycle(s, reg).desk_evidence()
    ov = desks_api.overview(reg, [], {"own": [BTC, ETH], "guest": [ARB, BTC]}, ev)
    btc = next(r for r in ov["desks"] if r["pair"] == BTC)
    assert btc["picks"][0]["per_month"] == 1.52 and "demo_all" not in btc["picks"][0] and "coins" not in btc["picks"][0]
    g = btc["guests"][0]
    assert g["id"] == "guest" and g["per_month"] == pytest.approx(24 / (360 / 30.44), abs=0.01)  # on BTC, not over all coins
    assert g["pnl_month"] == pytest.approx(331.3 / (360 / 30.44), abs=0.01)


def test_strategy_base_counts_trades_per_month_on_one_coin(env):
    s, reg = env
    add(reg, "guest", {ARB: {"pnl": 327.6, "trades": 22}, BTC: {"pnl": 331.3, "trades": 24}}, n_pairs=10)
    add(reg, "other", {SOL: {"pnl": 50.0, "trades": 236}}, n_pairs=10)
    desks(reg)
    rows = {r["id"]: r for r in explorer.listing(reg)["strategies"]}
    assert rows["guest"]["research"]["per_month_coin"] == 1.86  # its own coin's frozen figure
    assert rows["other"]["research"]["per_month_coin"] == pytest.approx(236 / (360 / 30.44) / 10, abs=0.01)  # not 19.9 over 10 coins
    d = explorer.detail(reg, "guest")
    assert [c["pair"] for c in d["coins"]] == [BTC, ARB] and d["coins"][0]["per_month"] == pytest.approx(2.03, abs=0.01)
