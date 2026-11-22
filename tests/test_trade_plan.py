"""A trade stays bound to the strategy that opened it (review 2026-11-22, Claude + ChatGPT).

Scenarios:
1. after rotation the trade exits on its own strategy's signal, never on another's;
2. a manager/bot restart (trade-less manifest, empty memory) does not change its stop, target
   or holding time – it keeps the plan it was opened with;
4. foreign exit columns never close a trade, and a missing own column means no signal exit.
"""

from datetime import timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from helpers import ohlcv

from aitrader.manifest import Manifest, Sleeve

PAIR = "BTC/USDT:USDT"


class FakeDP:
    def __init__(self, df):
        self.df = df

    def get_analyzed_dataframe(self, pair, timeframe):
        return self.df, None

    def get_pair_dataframe(self, pair, timeframe):
        return pd.DataFrame()

    def current_whitelist(self):
        return [PAIR]


class LiveTrade(SimpleNamespace):
    """Freqtrade Trade with its per-trade custom data (persisted in the bot's DB)."""

    def set_custom_data(self, key, value):
        self.__dict__.setdefault("_cd", {})[key] = value

    def get_custom_data(self, key, default=None):
        return self.__dict__.get("_cd", {}).get(key, default)


def _strategy(path):
    from AIPortfolio import AIPortfolio
    st = AIPortfolio({"aitrader": {"manifest_path": str(path)}, "runmode": "live",
                      "exchange": {"demo_trading": True}})
    st.bot_start()
    return st


def _populate(st, df, pair=PAIR):
    df = st.populate_indicators(df.copy(), {"pair": pair})
    df = st.populate_entry_trend(df, {"pair": pair})
    return st.populate_exit_trend(df, {"pair": pair})


def _trade(df, i, tag, tid=13):
    o = float(df["open"].iloc[i])
    return LiveTrade(id=tid, pair=PAIR, open_rate=o, open_date_utc=df["date"].iloc[i].to_pydatetime(),
                     is_short=False, leverage=1.0, max_rate=o, min_rate=o, enter_tag=tag)


@pytest.fixture
def live_trades(monkeypatch):
    from freqtrade.persistence import Trade
    box = []
    monkeypatch.setattr(Trade, "get_trades_proxy",
                        staticmethod(lambda pair=None, is_open=True, **kw: [t for t in box if pair in (None, t.pair)]),
                        raising=False)
    return box


def test_rotated_out_trade_exits_on_its_own_signal_only(tmp_path, live_trades):
    path = tmp_path / "manifest.json"
    Manifest(sleeves=[
        Sleeve(id="new", family="trend_ema", params={}, pairs=[PAIR], stage="exploration", risk=0.001),
        Sleeve(id="old", family="meanrev_bb", params={}, pairs=[], stage="closing", risk=0.0)]).save(path)
    st = _strategy(path)
    raw = ohlcv(1500, seed=4, vol=0.012)
    live_trades.append(_trade(raw, 1200, "old"))
    df = _populate(st, raw)
    # the closing strategy's signals are computed for the exit only
    assert {"xl:old", "xs:old", "at:old", "xl:new"} <= set(df.columns)
    assert "old" not in set(df.get("enter_tag", pd.Series(dtype=object)).dropna())
    own = df["xl:old"].fillna(False).astype(bool)
    assert own.any()
    assert (df["exit_long"].fillna(0).astype(bool) == own).all()  # its own exits, not "new"'s
    st.dp = FakeDP(df)
    tr = live_trades[0]
    assert st.confirm_trade_exit(PAIR, tr, "limit", 1, 1, "GTC", "exit_signal", tr.open_date_utc) is True


def test_foreign_exit_columns_never_close_a_trade(tmp_path, live_trades):
    path = tmp_path / "manifest.json"
    Manifest(sleeves=[Sleeve(id="a", family="trend_ema", params={}, pairs=[PAIR], stage="exploration",
                             risk=0.001)]).save(path)
    st = _strategy(path)
    raw = ohlcv(1500, seed=4, vol=0.012)
    # columns computed while nothing was open (primary sleeve "a"), then "b" opens on that candle
    df = _populate(st, raw)
    tr = _trade(raw, 1400, "b")
    live_trades.append(tr)
    st.dp = FakeDP(df)
    assert st.confirm_trade_exit(PAIR, tr, "limit", 1, 1, "GTC", "exit_signal", tr.open_date_utc) is False
    # a trade whose strategy is unknown (not in the manifest, no snapshot) gets no signal exit
    df2 = _populate(st, raw)
    assert not any(c.startswith("xl:b") for c in df2.columns)
    assert df2.get("exit_long", pd.Series(dtype=float)).fillna(0).sum() == 0
    assert st.confirm_trade_exit(PAIR, tr, "limit", 1, 1, "GTC", "exit_signal", tr.open_date_utc) is False
    assert st.confirm_trade_exit(PAIR, tr, "limit", 1, 1, "GTC", "managed_stop", tr.open_date_utc) is True
    # and none of "a"'s (or default) stops and targets either: its stop stays where it is
    st.dp = FakeDP(df2)
    assert st.custom_stoploss(PAIR, tr, tr.open_date_utc, tr.open_rate, 0.0, False) is None
    assert st.custom_exit(PAIR, tr, tr.open_date_utc + timedelta(days=30), tr.open_rate * 1.5, 0.0) is None


def test_restart_does_not_change_an_open_trades_plan(tmp_path, live_trades):
    path = tmp_path / "manifest.json"
    own = {"sl_atr": 3.5, "tp_rr": 3.0, "max_hold": 400}
    Manifest(sleeves=[
        Sleeve(id="mine", family="trend_ema", params=own, pairs=[PAIR], stage="exploration", risk=0.001),
        Sleeve(id="other", family="trend_ema", params={"sl_atr": 1.0, "tp_rr": 1.0, "max_hold": 12},
               pairs=[PAIR], stage="production", risk=0.01, score=9.0)]).save(path)
    st = _strategy(path)
    raw = ohlcv(1500, seed=2)
    tr = _trade(raw, 1300, "mine")
    live_trades.append(tr)
    df = _populate(st, raw)
    st.dp = FakeDP(df)
    rate = tr.open_rate
    sl_before = st.custom_stoploss(PAIR, tr, tr.open_date_utc, rate, 0.0, False)
    assert tr.get_custom_data(st.PLAN_KEY)["sleeve"]["params"] == own  # the plan is stored with the trade
    assert tr.get_custom_data(st.PLAN_KEY)["atr"] > 0

    # manager restart: manifest rewritten without the strategy; bot restart: memory is empty
    Manifest(sleeves=[Sleeve(id="other", family="trend_ema", params={"sl_atr": 1.0, "tp_rr": 1.0, "max_hold": 12},
                             pairs=[PAIR], stage="production", risk=0.01, score=9.0)]).save(path)
    st2 = _strategy(path)
    st2.dp = FakeDP(_populate(st2, raw))
    assert st2.sleeve_for_trade(tr).id == "mine"  # never the coin's new owner
    assert st2.custom_stoploss(PAIR, tr, tr.open_date_utc, rate, 0.0, False) == pytest.approx(sl_before)
    late = tr.open_date_utc + timedelta(hours=13)  # past "other"'s 12 bars, far inside its own 400
    assert st2.custom_exit(PAIR, tr, late, rate, 0.0) is None


def test_higher_timeframe_trade_without_its_candles_keeps_its_stop(tmp_path, live_trades):
    path = tmp_path / "manifest.json"
    Manifest(sleeves=[Sleeve(id="h4", family="trend_ema", params={}, pairs=[], stage="closing",
                             timeframe="4h")]).save(path)
    st = _strategy(path)
    st.timeframe = "15m"
    raw = ohlcv(1500, seed=2)
    tr = _trade(raw, 1300, "h4")
    live_trades.append(tr)
    st.dp = FakeDP(raw.assign(atr=1.0))  # only the bot's own 15m ATR, no 4h candles yet
    assert st.custom_stoploss(PAIR, tr, tr.open_date_utc, tr.open_rate, 0.0, False) is None
    assert st.custom_exit(PAIR, tr, tr.open_date_utc, tr.open_rate, 0.0) is None
    assert ("BTC/USDT:USDT", "4h") in st.informative_pairs()  # and the 4h candles are requested


# ---------------------------------------------------------------- manager (scenarios 2 and 3)
def _env(tmp_path):
    from pathlib import Path

    from aitrader.registry import Registry
    from aitrader.settings import Settings
    s = Settings(data_dir=tmp_path, app_dir=Path(__file__).resolve().parents[1])
    s.ensure_dirs()
    return s, Registry(s.registry_path)


def _retired_with_open_trade(s, reg):
    from aitrader.lifecycle import Lifecycle
    from aitrader.util import iso
    for sid, stage, pairs in (("live", "exploration", ["ETH/USDT:USDT"]), ("old", "retired", ["XRP/USDT:USDT"])):
        reg.upsert("strategies", {"id": sid, "experiment_id": "", "family": "trend_ema", "params": {"sl_atr": 3.0},
                                  "pairs": pairs, "sides": ["long", "short"], "stage": stage, "score": 1.0,
                                  "oos": {}, "gates": {}, "live": {}, "created": "2020-01-01", "updated": iso(),
                                  "stage_since": "2020-01-01T00:00:00Z", "history": []})
    life = Lifecycle(s, reg)
    trades = [{"enter_tag": "old", "pair": "XRP/USDT:USDT"}]
    life.write(life.build_manifest(trades, set(), False), trades)
    return life


def test_manager_restart_keeps_the_closing_strategies(tmp_path):
    from aitrader.manager import startup_manifest
    s, reg = _env(tmp_path)
    life = _retired_with_open_trade(s, reg)
    before = Manifest.load(s.manifest_path).to_dict()
    assert any(x["id"] == "old" and x["stage"] == "closing" for x in before["sleeves"])
    assert startup_manifest(life, s, set()) is False  # open trades unknown yet: nothing rewritten
    assert Manifest.load(s.manifest_path).to_dict() == before
    s.pairlist_path.unlink()
    startup_manifest(life, s, set())
    assert s.pairlist_path.exists() and Manifest.load(s.manifest_path).to_dict() == before
    s.manifest_path.unlink()  # first start ever: a manifest is created
    assert startup_manifest(life, s, set()) is True and s.manifest_path.exists()


def test_bot_api_down_keeps_the_last_manifest(tmp_path):
    from aitrader.manager import refresh_manifest
    s, reg = _env(tmp_path)
    life = _retired_with_open_trade(s, reg)
    before = Manifest.load(s.manifest_path).to_dict()
    assert refresh_manifest(life, False, [], set(), False) is None  # unreachable bot: no "no positions" rewrite
    assert Manifest.load(s.manifest_path).to_dict() == before
    man = refresh_manifest(life, True, [{"enter_tag": "old", "pair": "XRP/USDT:USDT"}], set(), False)
    assert man is not None and man.by_id("old").stage == "closing"
