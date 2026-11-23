"""Coin desks (owner, 2026-11-23): top coins, on each coin the one tested strategy that is best on
that coin by return and stability, frequencies mixed, frozen for the whole experiment; the monthly
TSMOM core off on demo; an alarm when the demo stops entering."""

from datetime import timedelta
from pathlib import Path

import pytest

from aitrader import desks as D
from aitrader import observe
from aitrader.lifecycle import Lifecycle
from aitrader.registry import Registry
from aitrader.settings import Settings
from aitrader.util import iso, utcnow


def opt(sid, pnl, trades, days=360.0, dd=0.05, family="rsi_revert", tf="1h"):
    return D.Option(strategy=sid, family=family, timeframe=tf, pnl=pnl, trades=trades, days=days, dd=dd, rank=(1, 0.5))


# ------------------------------------------------------------------ pure selection
def test_best_on_a_coin_is_return_with_a_drawdown_discount():
    ev = {"BTC": [opt("a", 120, 12, dd=0.27),   # most profit, but a deep drawdown
                  opt("b", 100, 12, dd=0.03),   # a little less profit, steady → best
                  opt("c", 500, 2),             # too few trades on this coin
                  opt("d", -50, 30),            # loses on this coin
                  opt("e", 900, 40, dd=0.35)]}  # drawdown beyond MAX_DD: excluded
    desks, _ = D.assign(ev, ["BTC"], 5)
    assert desks["BTC"]["strategy"] == "b" and desks["BTC"]["best_on_coin"]


def test_one_strategy_per_coin_and_never_the_same_strategy_twice():
    ev = {"BTC": [opt("star", 300, 20), opt("b1", 100, 10)],
          "ETH": [opt("star", 280, 20), opt("e1", 90, 10)],
          "SOL": [opt("star", 250, 20)]}
    desks, _ = D.assign(ev, ["BTC", "ETH", "SOL"], 5)
    assert desks["BTC"]["strategy"] == "star" and desks["ETH"]["strategy"] == "e1"
    assert "SOL" not in desks  # its only strategy already runs BTC
    assert len({d["strategy"] for d in desks.values()}) == len(desks)


def test_frequencies_are_mixed_among_near_best_strategies():
    ev = {}
    for i in range(6):  # every coin: a frequent, a medium and a rare strategy with similar results
        ev[f"C{i}"] = [opt(f"fast{i}", 100 + i, 60), opt(f"mid{i}", 95 + i, 20), opt(f"slow{i}", 90 + i, 6)]
    desks, cuts = D.assign(ev, [f"C{i}" for i in range(6)], 6)
    assert D.summary(desks) == {"coins": 6, "active": 2, "medium": 2, "rare": 2}
    # a much weaker strategy is never taken just for variety
    ev2 = {"X": [opt("fast", 100, 60), opt("slow", 20, 6)]}
    d2, _ = D.assign(ev2, ["X"], 2, frozen={"Y": {"strategy": "q", "bucket": "active", "family": "f"}}, cuts=cuts)
    assert d2["X"]["strategy"] == "fast"


def test_coins_in_liquidity_order_frozen_desks_kept_excluded_skipped():
    ev = {c: [opt(f"s{c}", 100, 10)] for c in ("BTC", "ETH", "SOL", "PEPE")}
    frozen = {"ETH": {"pair": "ETH", "strategy": "old", "family": "macd_cross", "bucket": "rare"}}
    desks, _ = D.assign(ev, ["BTC", "ETH", "SOL", "PEPE"], 3, frozen=frozen, excluded={"SOL"})
    assert desks["ETH"]["strategy"] == "old"  # frozen: a fresh choice never replaces it
    assert set(desks) == {"BTC", "ETH", "PEPE"}  # SOL excluded (e.g. delisting), next coin instead


# ------------------------------------------------------------------ lifecycle
@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("DEMO_MODE")
    monkeypatch.delenv("DEMO_CORE")
    s = Settings(data_dir=tmp_path, app_dir=Path(__file__).resolve().parents[1])
    s.ensure_dirs()
    assert s.lifecycle.demo_mode == "desks" and not s.lifecycle.demo_core  # production defaults
    return s, Registry(s.registry_path)


def add(reg, sid, stage, pair_stats, tf="1h", dd=0.05, family="rsi_revert", days=360):
    reg.upsert("experiments", {"id": f"x-{sid}", "created": iso(), "family": family, "spec": {}, "status": "done",
                               "result": {"pair_stats": pair_stats, "oos": {"n_days": days, "max_drawdown": dd}}})
    reg.upsert("strategies", {"id": sid, "experiment_id": f"x-{sid}", "family": family, "params": {"p": sid},
                              "pairs": list(pair_stats), "sides": ["long", "short"], "stage": stage, "score": 1.0,
                              "oos": {"timeframe": tf, "max_drawdown": dd}, "gates": {}, "live": {},
                              "created": iso(), "updated": iso(), "stage_since": iso(), "history": []})


def test_manifest_is_one_strategy_per_coin_frozen_for_the_experiment(env):
    s, reg = env
    s.lifecycle.desk_all_coins = False  # the desks alone (guests: next test)
    life = Lifecycle(s, reg)
    reg.kv_set("universe", {"pairs": ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]})
    reg.kv_set("lab", {"last_import": "t1"})
    add(reg, "btc-best", "exploratory", {"BTC/USDT:USDT": {"pnl": 300, "trades": 20}, "ETH/USDT:USDT": {"pnl": 10, "trades": 5}})
    add(reg, "eth-best", "exploratory", {"ETH/USDT:USDT": {"pnl": 200, "trades": 12}}, tf="4h", family="macd_cross")
    add(reg, "was-trading", "exploration", {"XRP/USDT:USDT": {"pnl": -5, "trades": 9}})
    add(reg, "rejected", "rejected", {"SOL/USDT:USDT": {"pnl": 999, "trades": 50}})  # failed the tests: never a desk
    man = life.build_manifest([], set(), False)
    by = {x.id: x for x in man.sleeves}
    assert set(by) == {"btc-best", "eth-best"}
    assert by["btc-best"].pairs == ["BTC/USDT:USDT"] and by["eth-best"].pairs == ["ETH/USDT:USDT"]
    assert by["eth-best"].timeframe == "4h" and by["eth-best"].params == {"p": "eth-best"}
    assert all(x.stage == "exploration" and x.risk == s.lifecycle.risk_exploration for x in man.sleeves)
    st = {r["id"]: r["stage"] for r in reg.strategies()}
    assert st["btc-best"] == st["eth-best"] == "exploration" and st["was-trading"] == "exploratory"
    # a better strategy arriving later never moves a desk; it may fill an open coin
    add(reg, "btc-better", "exploratory", {"BTC/USDT:USDT": {"pnl": 900, "trades": 30},
                                            "SOL/USDT:USDT": {"pnl": 50, "trades": 6}})
    reg.kv_set("lab", {"last_import": "t2"})
    man = life.build_manifest([], set(), False)
    by = {x.pairs[0]: x.id for x in man.sleeves}
    assert by == {"BTC/USDT:USDT": "btc-best", "ETH/USDT:USDT": "eth-best", "SOL/USDT:USDT": "btc-better"}
    # the stage machine does not touch the experiment
    life.evaluate(50_000.0)
    assert {r["id"] for r in reg.strategies(("exploration",))} == {"btc-best", "eth-best", "btc-better"}
    # a new experiment number makes a fresh choice
    s.lifecycle.desk_epoch = 2
    man = life.build_manifest([], set(), False)
    assert {x.pairs[0]: x.id for x in man.sleeves}["BTC/USDT:USDT"] == "btc-better"


def test_monthly_core_off_and_its_open_trades_end_on_their_own_rules(env):
    s, reg = env
    life = Lifecycle(s, reg)
    root = Path(__file__).resolve().parents[1] / "research"
    assert life.import_core(root / "external", root / "hypotheses") == 3  # still known (forward benchmark)
    add(reg, "desk1", "exploratory", {"ADA/USDT:USDT": {"pnl": 100, "trades": 8}})
    man = life.build_manifest([{"enter_tag": "core-tsmom-4h-30d", "pair": "BCH/USDT:USDT"}], set(), False)
    core = [x for x in man.sleeves if x.id.startswith("core-")]
    assert [(x.id, x.stage, x.pairs, x.timeframe) for x in core] == [("core-tsmom-4h-30d", "closing", [], "4h")]
    assert man.sleeves_for("BCH/USDT:USDT") == []  # no new core entries anywhere


# ------------------------------------------------------------------ activity alarm
def test_activity_counts_entries_and_alarms_after_six_quiet_hours(env):
    s, reg = env
    now = utcnow()
    reg.upsert("live_trades", {"trade_id": 1, "sleeve_id": "a", "pair": "BTC/USDT:USDT", "is_short": 1,
                               "open_date": iso(now - timedelta(hours=30)), "close_date": iso(now - timedelta(hours=20))},
               key="trade_id")
    reg.upsert("live_trades", {"trade_id": 2, "sleeve_id": "exec-test-1", "pair": "XAU/USDT:USDT", "is_short": 0,
                               "open_date": iso(now - timedelta(hours=1)), "close_date": iso(now)}, key="trade_id")
    older = {"trade_id": 3, "enter_tag": "b", "is_short": False,
             "open_date": (now - timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S")}  # Freqtrade's API format
    a = observe.activity(reg, [older], now)
    assert (a["entries_24h"], a["long_24h"], a["short_24h"]) == (1, 1, 0)  # the execution test is not an entry
    reg.kv_set("activity", a)
    assert "no entry > 6h" in observe.red_flags(reg, now)
    a = observe.activity(reg, [older, {"trade_id": 4, "enter_tag": "c", "is_short": True, "open_date": iso(now)}], now)
    reg.kv_set("activity", a)
    assert "no entry > 6h" not in observe.red_flags(reg, now)
    reg.kv_set("desks", {"coins": {"BTC/USDT:USDT": {"strategy": "a", "bucket": "active"},
                                   "ETH/USDT:USDT": {"strategy": "b", "bucket": "rare"},
                                   "SOL/USDT:USDT": {"pair": "SOL/USDT:USDT", "picks": [], "manual": True}}})  # owner: none
    line = observe.status_line(reg, now)
    assert "entries_24h=2 (L 1/S 1)" in line and "desks=[2: active 1, medium 0, rare 1]" in line
    reg.kv_set("signals", {"days": 7, "total": {"signals": 5, "executed": 3, "missed": {"pair_busy": 2}},
                           "per_sleeve": {"desk1": {"signals": 4, "executed": 3}}})
    assert observe.signals_line(reg) == ("SIGNALS days=7 since=None signals=5 executed=3 missed=[pair_busy 2] "
                                         "by_strategy=[desk1 3/4]")


def test_a_new_experiment_starts_flat_once(env):
    """Owner, 23.11: the previous stage is over – open trades that are not a current desk's own
    (strategy, coin) are closed at market once per experiment; TradFi and execution tests stay."""
    s, reg = env
    life = Lifecycle(s, reg)
    reg.kv_set("universe", {"pairs": ["ADA/USDT:USDT"]})
    add(reg, "desk-ada", "exploratory", {"ADA/USDT:USDT": {"pnl": 100, "trades": 8}})
    reg.kv_set("tradfi_cfg", {"xau-macd-12h": {"id": "xau-macd-12h", "family": "macd_cross", "params": {}, "rank": 0,
                                               "pairs": ["XAU/USDT:USDT"], "demo_pairs": ["XAU/USDT:USDT"],
                                               "sides": ["long", "short"], "timeframe": "12h"}})
    life.build_manifest([], set(), False)

    class FT:
        def __init__(self):
            self.closed = []

        def forceexit(self, tid):
            self.closed.append(tid)

    trades = [{"trade_id": 1, "enter_tag": "core-tsmom-4h-30d", "pair": "BCH/USDT:USDT", "is_short": True},
              {"trade_id": 2, "enter_tag": "desk-ada", "pair": "ADA/USDT:USDT"},          # the desk's own trade
              {"trade_id": 3, "enter_tag": "desk-ada", "pair": "DOT/USDT:USDT"},          # same strategy, not its desk coin
              {"trade_id": 4, "enter_tag": "xau-macd-12h", "pair": "XAU/USDT:USDT"},      # TradFi lane
              {"trade_id": 5, "enter_tag": "exec-test-1", "pair": "BTC/USDT:USDT"}]
    ft = FT()
    assert len(life.flatten_for_experiment(ft, trades)) == 2 and ft.closed == [1, 3]
    assert life.flatten_for_experiment(ft, trades) == [] and ft.closed == [1, 3]  # once per experiment

    class Broken(FT):
        def forceexit(self, tid):
            raise RuntimeError("bot busy")

    s.lifecycle.desk_epoch = 2
    life.build_manifest([], set(), False)
    assert life.flatten_for_experiment(Broken(), trades) == []
    ft = FT()
    assert life.flatten_for_experiment(ft, trades) and ft.closed == [1, 3]  # a failed close is tried again


def test_owner_picks_any_strategies_from_the_coins_list_of_best(env):
    s, reg = env
    s.lifecycle.desk_all_coins = False
    life = Lifecycle(s, reg)
    reg.kv_set("universe", {"pairs": ["BTC/USDT:USDT", "ETH/USDT:USDT"]})
    add(reg, "a", "exploratory", {"BTC/USDT:USDT": {"pnl": 300, "trades": 20}, "ETH/USDT:USDT": {"pnl": 120, "trades": 9}})
    add(reg, "b", "exploratory", {"ETH/USDT:USDT": {"pnl": 200, "trades": 12}})
    add(reg, "c", "exploratory", {"ETH/USDT:USDT": {"pnl": 150, "trades": 10}})
    life.build_manifest([], set(), False)
    assert [o["strategy"] for o in life.desk_options("ETH/USDT:USDT")] == ["b", "c", "a"]  # best first
    with pytest.raises(ValueError):
        life.set_desk("ETH/USDT:USDT", ["nope"])
    life.set_desk("ETH/USDT:USDT", ["c", "a"])  # two strategies; "a" also runs BTC
    man = life.build_manifest([], set(), False)
    by = {x.id: sorted(x.pairs) for x in man.sleeves}
    assert by == {"a": ["BTC/USDT:USDT", "ETH/USDT:USDT"], "c": ["ETH/USDT:USDT"]}
    assert {r["id"]: r["stage"] for r in reg.strategies()} == {"a": "exploration", "b": "exploratory", "c": "exploration"}
    life.set_desk("ETH/USDT:USDT", [])  # none: the coin takes no entries, and is not refilled automatically
    reg.kv_set("lab", {"last_import": "later"})
    man = life.build_manifest([], set(), False)
    assert {x.id: x.pairs for x in man.sleeves} == {"a": ["BTC/USDT:USDT"]}


def test_desk_strategies_also_trade_their_proven_coins_and_go_first_on_their_own(env):
    """Owner, 23.11: a strategy trades far more than once a month – across its coins. Each desk
    strategy also trades the other coins where it proved itself (≥ 3 trades, profit), as a guest:
    the desk owner goes first on its coin, at most `desk_max_per_coin` strategies per coin."""
    s, reg = env
    s.lifecycle.desk_max_per_coin = 2
    life = Lifecycle(s, reg)
    reg.kv_set("universe", {"pairs": ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]})
    add(reg, "a", "exploratory", {"BTC/USDT:USDT": {"pnl": 300, "trades": 20}, "ETH/USDT:USDT": {"pnl": 120, "trades": 9},
                                  "SOL/USDT:USDT": {"pnl": 90, "trades": 8}, "DOGE/USDT:USDT": {"pnl": 50, "trades": 6},
                                  "PEPE/USDT:USDT": {"pnl": 80, "trades": 2}, "XRP/USDT:USDT": {"pnl": -30, "trades": 9}})
    add(reg, "b", "exploratory", {"ETH/USDT:USDT": {"pnl": 200, "trades": 12}, "SOL/USDT:USDT": {"pnl": 100, "trades": 9}})
    add(reg, "c", "exploratory", {"SOL/USDT:USDT": {"pnl": 400, "trades": 15}, "BTC/USDT:USDT": {"pnl": 30, "trades": 4}})
    man = life.build_manifest([], set(), False)
    by = {x.id: x for x in man.sleeves}
    assert by["a"].lead == ["BTC/USDT:USDT"] and by["b"].lead == ["ETH/USDT:USDT"] and by["c"].lead == ["SOL/USDT:USDT"]
    # a: its desk + proven coins (not PEPE: too few trades; not XRP: lost there); SOL is full (2 per coin)
    assert sorted(by["a"].pairs) == ["BTC/USDT:USDT", "DOGE/USDT:USDT", "ETH/USDT:USDT"]
    assert sorted(by["b"].pairs) == ["ETH/USDT:USDT", "SOL/USDT:USDT"] and "SOL/USDT:USDT" not in by["a"].pairs
    assert [x.id for x in man.sleeves_for("ETH/USDT:USDT")] == ["b", "a"]  # the desk owner first
    assert [x.id for x in man.sleeves_for("BTC/USDT:USDT")] == ["a", "c"]
    assert man.owner_of("SOL/USDT:USDT").id == "c"
    assert sorted(by["c"].pairs) == ["BTC/USDT:USDT", "SOL/USDT:USDT"]
    # the proven coins are frozen with the desk
    st = reg.kv_get("desks")
    assert st["coins"]["BTC/USDT:USDT"]["coin_scores"]["DOGE/USDT:USDT"] > 0


def test_signal_check_finds_signals_the_bot_never_acted_on(env):
    """Owner, 23.11: "entries without stalls". Signals on the bot's own analysed candles since the
    experiment start are compared with its entries: taken, coin busy, or missed (red flag)."""
    s, reg = env
    now = utcnow().replace(second=0, microsecond=0)
    start = now - timedelta(hours=6)

    def row(minutes_ago, tag, long=True):
        d = (now - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")
        return [d, 1 if long else 0, 0 if long else 1, tag]

    cols = ["date", "enter_long", "enter_short", "enter_tag"]
    candles = {"BNB/USDT:USDT": {"columns": cols, "data": [row(120, "a"), row(500, "a")]},  # second: before the start
               "ETH/USDT:USDT": {"columns": cols, "data": [row(200, "b", False), row(100, "b")]},
               "SOL/USDT:USDT": {"columns": cols, "data": [row(60, "c"), row(45, "c"), row(30, "c")]},
               "XRP/USDT:USDT": {"columns": cols, "data": [row(0, "d")]}}  # too fresh to judge
    trades = [{"sleeve_id": "a", "pair": "BNB/USDT:USDT", "open_date": iso(now - timedelta(minutes=104))},  # taken
              {"sleeve_id": "b", "pair": "ETH/USDT:USDT", "open_date": iso(now - timedelta(minutes=184)),
               "close_date": iso(now - timedelta(minutes=50))}]  # ETH 200: taken; ETH 100: busy (b's own trade open)
    out = observe.signal_check(candles, trades, iso(start), now)
    assert (out["signals"], out["taken"], out["busy"], out["missed"]) == (6, 2, 1, 3)
    assert out["missed_by"] == {"SOL:c": 3}
    reg.kv_set("sigcheck", out)
    assert "signals not acted on 3" in observe.red_flags(reg, now)
    assert observe.sigcheck_line(reg).startswith("SIGCHECK since=") and "SOL:c 3" in observe.sigcheck_line(reg)

    class FT:
        def pair_candles(self, pair, tf, limit):
            assert tf == "15m" and 8 < limit <= 700
            if pair == "XRP/USDT:USDT":
                raise RuntimeError("bot busy")
            return candles[pair]

    reg.kv_set("desks", {"created": iso(start), "coins": {}})
    res = observe.run_signal_check(reg, FT(), list(candles), [], now)
    assert res["coins"] == 3 and reg.kv_get("sigcheck")["signals"] == res["signals"]
