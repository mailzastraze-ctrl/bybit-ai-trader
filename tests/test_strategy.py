"""Exercise the Freqtrade strategy glue (real freqtrade in CI, stub locally)."""

from datetime import timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from helpers import ohlcv

from aitrader.manifest import Manifest, Sleeve


class FakeDP:
    def __init__(self, df):
        self.df = df

    def get_analyzed_dataframe(self, pair, timeframe):
        return self.df, None


class FakeWallets:
    def get_total_stake_amount(self):
        return 10_000.0


def _trade(df, i, is_short=False, tag="s1"):
    return SimpleNamespace(id=7, pair="BTC/USDT:USDT", open_rate=float(df["open"].iloc[i]),
                           open_date_utc=df["date"].iloc[i].to_pydatetime(), is_short=is_short,
                           leverage=3.0, max_rate=float(df["open"].iloc[i]), min_rate=float(df["open"].iloc[i]),
                           enter_tag=tag)


@pytest.fixture
def portfolio(tmp_path):
    from AIPortfolio import AIPortfolio
    m = Manifest(sleeves=[Sleeve(id="s1", family="trend_ema", params={}, pairs=["BTC/USDT:USDT"],
                                 stage="production", risk=0.01, leverage=3.0)])
    path = tmp_path / "manifest.json"
    m.save(path)
    st = AIPortfolio({"aitrader": {"manifest_path": str(path)}, "runmode": "backtest",
                      "exchange": {"demo_trading": True}})
    st.bot_start()
    return st


def _populate(st, df, pair="BTC/USDT:USDT"):
    df = st.populate_indicators(df.copy(), {"pair": pair})
    df = st.populate_entry_trend(df, {"pair": pair})
    return st.populate_exit_trend(df, {"pair": pair})


def test_portfolio_entries_tagged_with_sleeve(portfolio):
    df = _populate(portfolio, ohlcv(2500, seed=11, vol=0.012))
    assert "enter_long" in df and df["enter_long"].fillna(0).sum() > 0
    tags = set(df.loc[df["enter_long"] == 1, "enter_tag"])
    assert tags == {"s1"}


def test_portfolio_unowned_pair_gets_no_signals(portfolio):
    df = _populate(portfolio, ohlcv(800), pair="ETH/USDT:USDT")
    assert "enter_long" not in df or df["enter_long"].fillna(0).sum() == 0


def test_portfolio_stoploss_tp_time_and_stake(portfolio):
    df = _populate(portfolio, ohlcv(1000, seed=2))
    portfolio.dp = FakeDP(df)
    portfolio.wallets = FakeWallets()
    i = 600
    tr = _trade(df, i)
    atr = float(df["atr"].iloc[i - 1])
    entry = tr.open_rate
    # initial stop = entry - 2*ATR (defaults sl_atr=2.0)
    sl = portfolio.custom_stoploss(tr.pair, tr, tr.open_date_utc, entry, 0.0, False)
    implied_stop = entry * (1 - sl / 3.0)
    assert implied_stop == pytest.approx(entry - 2.0 * atr, rel=1e-6)
    # take profit at entry + tp_rr(2) * 2 ATR
    assert portfolio.custom_exit(tr.pair, tr, tr.open_date_utc, entry + 4.01 * atr, 0.0) == "take_profit"
    assert portfolio.custom_exit(tr.pair, tr, tr.open_date_utc, entry + 0.5 * atr, 0.0) is None
    late = tr.open_date_utc + timedelta(hours=72)
    assert portfolio.custom_exit(tr.pair, tr, late, entry, 0.0) == "time_exit"
    assert portfolio.custom_exit(tr.pair, tr, tr.open_date_utc, entry - 2.5 * atr, 0.0) == "managed_stop"
    # risk sizing: loss at stop ≈ 1% of equity × conviction multiplier
    stake = portfolio.custom_stake_amount(tr.pair, tr.open_date_utc, entry, 100.0, 5.0, 9000.0, 3.0, "s1", "long")
    assert stake > 0
    last = df.iloc[-1]
    loss = stake * 3.0 * (2.0 * last["atr"] / entry)
    assert 50 <= loss <= 150  # 1% of 10k scaled by conviction ∈ [0.75, 1.25] (conv_w=0.5)
    assert portfolio.leverage(tr.pair, tr.open_date_utc, entry, 1.0, 10.0, "s1", "long") == 1.0  # owner: never leverage, even if a sleeve asks for 3x


def test_exit_signal_blocked_when_trade_sleeve_no_longer_runs_the_pair(portfolio, tmp_path):
    df = _populate(portfolio, ohlcv(700))
    portfolio.dp = FakeDP(df)
    tr = _trade(df, 500, tag="old")
    path = portfolio.config["aitrader"]["manifest_path"]
    m = Manifest.load(pd.io.common.stringify_path(path) and __import__("pathlib").Path(path))
    m.sleeves.append(Sleeve(id="old", family="meanrev_bb", params={}, pairs=[], stage="closing"))
    m.save(__import__("pathlib").Path(path))
    portfolio.bot_loop_start(tr.open_date_utc)
    assert portfolio.confirm_trade_exit(tr.pair, tr, "market", 1, 1, "GTC", "exit_signal", tr.open_date_utc) is False
    assert portfolio.confirm_trade_exit(tr.pair, tr, "market", 1, 1, "GTC", "take_profit", tr.open_date_utc) is True


def test_real_money_guard():
    from AIPortfolio import AIPortfolio
    from freqtrade.exceptions import OperationalException

    from aitrader.ftbase import RunMode
    st = AIPortfolio({"runmode": RunMode.LIVE, "exchange": {"demo_trading": False}})
    with pytest.raises(OperationalException):
        st.bot_start()


def test_research_strategy_parameters_and_signals():
    from FamDonchian import FamDonchian
    st = FamDonchian({"aitrader": {"risk": 0.01, "leverage": 3}, "runmode": "hyperopt",
                      "exchange": {}})
    st.bot_start()
    assert st.dc_len.space == "buy" and st.sl_atr.space == "sell"
    df = _populate(st, ohlcv(2000, seed=4, vol=0.012))
    n_default = df["enter_long"].fillna(0).sum() + df["enter_short"].fillna(0).sum()
    st.dc_len.value = 20
    st.vol_mult.value = 1.0
    df2 = _populate(st, ohlcv(2000, seed=4, vol=0.012))
    n_loose = df2["enter_long"].fillna(0).sum() + df2["enter_short"].fillna(0).sum()
    assert n_loose > n_default  # entry params take effect without re-running populate_indicators


def test_exec_test_entries_bypass_sleeve_sizing(portfolio):
    df = _populate(portfolio, ohlcv(400))
    portfolio.dp = FakeDP(df)
    portfolio.wallets = FakeWallets()
    t = df["date"].iloc[-1].to_pydatetime()
    assert portfolio.custom_stake_amount("XRP/USDT:USDT", t, 1.0, 30.0, 5.0, 1000.0, 2.0, "exec-test-1", "long") == 30.0
    assert portfolio.custom_stake_amount("XRP/USDT:USDT", t, 1.0, 30.0, 5.0, 1000.0, 2.0, "random", "long") == 0.0
    assert portfolio.leverage("XRP/USDT:USDT", t, 1.0, 1.0, 10.0, "exec-test-1", "long") == 1.0



def test_portfolio_limits_cap_same_side_and_open_risk(portfolio, monkeypatch):
    from freqtrade.persistence import Trade
    portfolio.config["runmode"] = "live"
    portfolio.wallets = FakeWallets()
    mk = lambda short, stop: SimpleNamespace(is_short=short, open_rate=100.0, stop_loss=stop,  # noqa: E731
                                             stake_amount=1000.0, leverage=3.0)
    ok = lambda side: portfolio.confirm_trade_entry("BTC/USDT:USDT", "limit", 1, 100, "GTC", None, "s1", side)  # noqa: E731
    # 7 longs open with break-even stops (no risk left) → 8th long blocked, short still allowed
    monkeypatch.setattr(Trade, "get_open_trades", staticmethod(lambda: [mk(False, 100.0)] * 7), raising=False)
    assert ok("long") is False and ok("short") is True
    # open risk: 2 trades × (2% stop × 3000 notional) = 120 = 1.2%; + new 1% risk = 2.2% < 3% → allowed
    monkeypatch.setattr(Trade, "get_open_trades", staticmethod(lambda: [mk(False, 98.0)] * 2), raising=False)
    assert ok("short") is True
    # 4 such trades = 2.4% + 1% > 3% → blocked
    monkeypatch.setattr(Trade, "get_open_trades", staticmethod(lambda: [mk(True, 102.0)] * 4), raising=False)
    assert ok("long") is False
    portfolio.config["runmode"] = "backtest"
    assert ok("long") is True  # research backtests are single-sleeve: no account limits


def test_maker_first_entry_then_cross(portfolio):
    from datetime import datetime, timezone
    portfolio.config["runmode"] = "live"
    portfolio.dp = SimpleNamespace(orderbook=lambda pair, n: {"bids": [[99.9, 1]], "asks": [[100.1, 1]]})
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    order = SimpleNamespace(order_date_utc=t0)
    adj = lambda secs, prop, cur, side="long": portfolio.adjust_entry_price(  # noqa: E731
        None, order, "BTC/USDT:USDT", t0 + timedelta(seconds=secs), prop, cur, "s1", side)
    assert adj(30, 99.9, 99.9) == 99.9            # resting at the bid (maker)
    assert adj(60, 99.95, 99.8) == 99.95          # follows the touch
    assert adj(200, 99.9, 99.9) == pytest.approx(100.1 * 1.0005)   # crosses after 3 min
    assert adj(200, 99.9, 100.1 * 1.0005) == pytest.approx(100.1 * 1.0005)  # already crossing: keep
    assert adj(200, 100.1, 100.1, "short") == pytest.approx(99.9 * 0.9995)
    portfolio.config["runmode"] = "backtest"
    assert adj(200, 99.9, 99.0) == 99.0           # no repricing in backtests


def test_maker_first_exit_and_urgent_cross(portfolio):
    from datetime import datetime, timezone
    portfolio.config["runmode"] = "live"
    portfolio.dp = SimpleNamespace(orderbook=lambda pair, n: {"bids": [[99.9, 1]], "asks": [[100.1, 1]]})
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    long_tr, short_tr = SimpleNamespace(is_short=False), SimpleNamespace(is_short=True)
    px = lambda tr, tag: portfolio.custom_exit_price("BTC/USDT:USDT", tr, t0, 100.1, 0.01, tag)  # noqa: E731
    assert px(long_tr, "take_profit") == 100.1                       # resting at the ask (maker)
    assert px(long_tr, "managed_stop") == pytest.approx(99.9 * 0.9995)  # stop-type exit crosses
    assert px(short_tr, "managed_stop") == pytest.approx(100.1 * 1.0005)
    order = SimpleNamespace(order_date_utc=t0)
    adj = lambda secs, prop, cur: portfolio.adjust_exit_price(  # noqa: E731
        long_tr, order, "BTC/USDT:USDT", t0 + timedelta(seconds=secs), prop, cur, "s1", "long")
    assert adj(30, 100.1, 100.1) == 100.1
    assert adj(120, 100.1, 100.1) == pytest.approx(99.9 * 0.9995)    # crosses after 90 s



def test_several_sleeves_share_a_pair(tmp_path):
    from AIPortfolio import AIPortfolio
    pair = "BTC/USDT:USDT"
    m = Manifest(sleeves=[
        Sleeve(id="a", family="trend_ema", params={}, pairs=[pair], stage="exploration", risk=0.001, score=0.5),
        Sleeve(id="b", family="meanrev_bb", params={}, pairs=[pair], stage="exploration", risk=0.002, score=0.4)])
    path = tmp_path / "manifest.json"
    m.save(path)
    st = AIPortfolio({"aitrader": {"manifest_path": str(path)}, "runmode": "backtest", "exchange": {"demo_trading": True}})
    st.bot_start()
    assert [x.id for x in st.sleeves_for_pair(pair)] == ["a", "b"]
    df = _populate(st, ohlcv(2500, seed=11, vol=0.012), pair)
    tags = set(df.loc[(df["enter_long"] == 1) | (df.get("enter_short", 0) == 1), "enter_tag"].dropna())
    assert tags == {"a", "b"}  # both strategies trade the same pair
    assert {"xl:a", "xl:b", "cv:a", "cv:b"} <= set(df.columns)
    assert st.sleeve_by_tag(pair, "b").risk == 0.002  # sizing uses the entry's own sleeve


def test_one_bot_two_timeframes_hourly_sleeve_on_15m_bot(tmp_path):
    """A 1h strategy on the 15m bot fires exactly when a 1h bot would: once, on the first
    15m candle after the hourly candle closed – and uses the hourly ATR for its stop."""
    from AIPortfolio import AIPortfolio

    from aitrader.families import get_family
    pair = "BTC/USDT:USDT"
    h1 = ohlcv(1500, seed=11, vol=0.012)  # hourly candles
    rows = []
    for _, r in h1.iterrows():  # 4 quarter-hours per hour, same OHLC path
        for q in range(4):
            rows.append({"date": r["date"] + pd.Timedelta(minutes=15 * q), "open": r["open"], "high": r["high"],
                         "low": r["low"], "close": r["close"], "volume": r["volume"] / 4})
    m15 = pd.DataFrame(rows)
    m = Manifest(sleeves=[Sleeve(id="h", family="trend_ema", params={}, pairs=[pair], stage="exploration",
                                 risk=0.001, timeframe="1h")])
    path = tmp_path / "manifest.json"
    m.save(path)
    st = AIPortfolio({"aitrader": {"manifest_path": str(path)}, "runmode": "backtest", "exchange": {"demo_trading": True}})
    st.timeframe = "15m"
    st.bot_start()
    st.dp = SimpleNamespace(get_pair_dataframe=lambda p, tf, **kw: h1 if tf == "1h" else m15,
                            current_whitelist=lambda: [pair])
    assert (pair, "1h") in st.informative_pairs()
    df = _populate(st, m15, pair)
    ref = get_family("trend_ema").populate(h1, {})
    sig_hours = set(h1.loc[ref["long_sig"], "date"])
    got = df.loc[df["enter_long"] == 1, "date"]
    # the hourly candle starting at H closes at H+60m: the 15m candle H+45m (closing then) carries it
    assert set(got - pd.Timedelta(minutes=45)) == sig_hours and len(got) == len(sig_hours)
    i = df.index[df["date"] == h1["date"].iloc[1000] + pd.Timedelta(minutes=45)][0]
    assert df.loc[i, "at:h"] == pytest.approx(ref["atr"].iloc[1000])  # hourly ATR drives the stop


def test_market_relative_sleeve_gets_btc_merged_without_look_ahead(tmp_path):
    from AIPortfolio import AIPortfolio
    pair = "SOL/USDT:USDT"
    coin, btc = ohlcv(3000, seed=4, vol=0.012), ohlcv(3000, seed=9, vol=0.008)
    m = Manifest(sleeves=[Sleeve(id="r", family="rel_strength", params={}, pairs=[pair], stage="exploration", risk=0.001)])
    path = tmp_path / "manifest.json"
    m.save(path)
    st = AIPortfolio({"aitrader": {"manifest_path": str(path)}, "runmode": "backtest", "exchange": {"demo_trading": True}})
    st.bot_start()
    st.dp = SimpleNamespace(get_pair_dataframe=lambda p, tf, **kw: btc, current_whitelist=lambda: [pair])
    assert ("BTC/USDT:USDT", "1h") in st.informative_pairs()
    df = _populate(st, coin, pair)
    assert (df["mkt_close"].to_numpy() == btc["close"].to_numpy()).all()  # same candle, same moment
    assert df["enter_long"].fillna(0).sum() + df.get("enter_short", pd.Series(0)).fillna(0).sum() > 0


def test_crossing_falls_back_when_quotes_fail(portfolio):
    """Regression (live 2026-11-21): the order-book websocket failed ('already subscribed'),
    the maker entry could never cross and sat 12 minutes until it timed out."""
    from datetime import datetime, timezone

    def boom(*a, **k):
        raise RuntimeError("bybit error:already subscribed")
    portfolio.config["runmode"] = "live"
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    order = SimpleNamespace(order_date_utc=t0)
    portfolio.dp = SimpleNamespace(orderbook=boom, ticker=lambda pair: {"bid": 0.05274, "ask": 0.05276})
    tr = SimpleNamespace(is_short=True)
    px = portfolio.adjust_entry_price(tr, order, "DOGE/USDT:USDT", t0 + timedelta(seconds=200), 0.0529, 0.0529, "s1", "short")
    assert px == pytest.approx(0.05274 * 0.9995)          # ticker bid → crosses for a short entry
    portfolio.dp = SimpleNamespace(orderbook=boom, ticker=boom)
    px = portfolio.adjust_entry_price(tr, order, "DOGE/USDT:USDT", t0 + timedelta(seconds=200), 0.0529, 0.0529, "s1", "short")
    assert px == pytest.approx(0.0529 * 0.998)            # no quotes at all: protected 0.2% cross
    long_tr = SimpleNamespace(is_short=False)
    assert portfolio.adjust_exit_price(long_tr, order, "X", t0 + timedelta(seconds=120), 100.0, 100.0, "s1", "long") \
        == pytest.approx(100.0 * 0.998)


def test_take_profit_waits_at_target_side_risk_cap_and_market_shock_guard(portfolio, monkeypatch):
    from datetime import datetime, timezone

    import pandas as pd
    from freqtrade.persistence import Trade

    from aitrader.riskcore import EntryContext
    portfolio.config["runmode"] = "live"
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    p = {"sl_atr": 2.0, "tp_rr": 2.0, "be_rr": 1.0, "lock_rr": 1.5, "lock_frac": 0.4, "trail_rr": 3.0, "trail_atr": 2.5,
         "max_hold": 72}
    monkeypatch.setattr(portfolio, "_ctx", lambda pair, tr: EntryContext(entry=100.0, atr=1.0, is_short=tr.is_short))
    monkeypatch.setattr(portfolio, "_params", lambda tr: dict(p))
    long_tr, short_tr = SimpleNamespace(is_short=False), SimpleNamespace(is_short=True)   # TP 104 / 96
    portfolio.dp = SimpleNamespace(orderbook=lambda pair, n: {"bids": [[103.0, 1]], "asks": [[103.2, 1]]})
    order = SimpleNamespace(order_date_utc=t0, ft_order_tag="take_profit")
    # a wick hit TP and fell back: the resting order waits at 104 instead of chasing down to 103.2
    assert portfolio.adjust_exit_price(long_tr, order, "X", t0 + timedelta(seconds=30), 103.2, 104.0, "s1", "long") == 104.0
    assert portfolio.custom_exit_price("X", long_tr, t0, 103.2, 0.03, "take_profit") == 104.0
    assert portfolio.custom_exit_price("X", short_tr, t0, 96.5, 0.03, "take_profit") == 96.0
    assert portfolio.custom_exit_price("X", long_tr, t0, 103.2, 0.03, "exit_signal") == 103.2
    # risk per side: 1.5% of equity by default (half of max_open_risk) – the other side stays open
    portfolio.wallets = FakeWallets()
    mk = lambda short: SimpleNamespace(is_short=short, open_rate=100.0, stop_loss=101.0 if short else 99.0,  # noqa: E731
                                       stake_amount=1000.0, leverage=1.0)
    monkeypatch.setattr(Trade, "get_open_trades", staticmethod(lambda: [mk(True)] * 1), raising=False)
    ok = lambda side: portfolio.confirm_trade_entry("BTC/USDT:USDT", "limit", 1, 100, "GTC", None, "s1", side)  # noqa: E731
    portfolio.config.setdefault("aitrader", {})["max_side_risk"] = 0.001
    assert ok("short") is False and ok("long") is False   # 0.1% cap: any new risk exceeds it
    portfolio.config["aitrader"]["max_side_risk"] = 0.5
    assert ok("short") is True
    # market shock: BTC +3% in the last hour. Off by default (owner 23.11: exits follow the strategy
    # only) – the stop stays the strategy's own …
    btc = pd.DataFrame({"close": [100.0] * 10 + [103.0]})
    portfolio.dp = SimpleNamespace(get_pair_dataframe=lambda pair, tf: btc, get_analyzed_dataframe=lambda pair, tf: (None, None))
    tr = SimpleNamespace(id=7, is_short=True, min_rate=98.8, max_rate=100.0, open_rate=100.0, enter_tag="s1")
    assert portfolio.MARKET_SHOCK_GUARD is False
    assert portfolio._stop("ETH/USDT:USDT", tr, EntryContext(entry=100.0, atr=1.0, is_short=True), dict(p), t0) == pytest.approx(102.0)
    # … and when switched on, a profitable short goes to break-even; a long is untouched
    monkeypatch.setattr(portfolio, "MARKET_SHOCK_GUARD", True)
    stop = portfolio._stop("ETH/USDT:USDT", tr, EntryContext(entry=100.0, atr=1.0, is_short=True), dict(p), t0)
    assert stop == pytest.approx(99.88)
    lt = SimpleNamespace(id=8, is_short=False, min_rate=100.0, max_rate=103.0, open_rate=100.0, enter_tag="s1")
    assert portfolio._stop("ETH/USDT:USDT", lt, EntryContext(entry=100.0, atr=1.0, is_short=False), dict(p), t0) \
        == EntryContext(entry=100.0, atr=1.0, is_short=False).managed_stop(dict(p), 103.0)
    portfolio.config["runmode"] = "backtest"
    portfolio._shock_at = None
    assert portfolio._stop("ETH/USDT:USDT", tr, EntryContext(entry=100.0, atr=1.0, is_short=True), dict(p), t0) == pytest.approx(102.0)


def test_exploration_cannot_crowd_out_proven_strategies(tmp_path, monkeypatch):
    """Unproven exploration sleeves share a sub-budget (positions and open risk): a proven
    strategy always finds room, even when exploration signalled first."""
    from AIPortfolio import AIPortfolio
    from freqtrade.persistence import Trade
    m = Manifest(sleeves=[Sleeve(id="ex", family="trend_ema", params={}, pairs=["ETH/USDT:USDT", "SOL/USDT:USDT"],
                                 stage="exploration", risk=0.001),
                          Sleeve(id="pro", family="tsmom", params={}, pairs=["BTC/USDT:USDT"], stage="production", risk=0.0075)])
    path = tmp_path / "manifest.json"
    m.save(path)
    st = AIPortfolio({"aitrader": {"manifest_path": str(path), "max_open_risk": 0.08, "max_side_risk": 0.04,
                                   "max_same_side": 25, "max_explore_trades": 3, "max_explore_risk": 0.03},
                      "runmode": "live", "exchange": {"demo_trading": True}})
    st.bot_start()
    st.wallets = FakeWallets()
    mk = lambda pair: SimpleNamespace(pair=pair, enter_tag="ex", is_short=True, open_rate=100.0,  # noqa: E731
                                      stop_loss=101.0, stake_amount=100.0, leverage=1.0)  # 0.01 % risk each
    monkeypatch.setattr(Trade, "get_open_trades", staticmethod(lambda: [mk("ETH/USDT:USDT")] * 3), raising=False)
    assert st.confirm_trade_entry("SOL/USDT:USDT", "limit", 1, 100, "GTC", None, "ex", "short") is False  # 3 of 3
    assert st.confirm_trade_entry("BTC/USDT:USDT", "limit", 1, 100, "GTC", None, "pro", "short") is True  # room kept
    st.config["aitrader"]["max_explore_trades"] = 24
    st.config["aitrader"]["max_explore_risk"] = 0.0002  # risk sub-cap below one more exploration trade
    assert st.confirm_trade_entry("SOL/USDT:USDT", "limit", 1, 100, "GTC", None, "ex", "short") is False
    st.config["aitrader"]["max_explore_risk"] = 0.03
    assert st.confirm_trade_entry("SOL/USDT:USDT", "limit", 1, 100, "GTC", None, "ex", "short") is True


def test_signal_journal_records_decisions_without_changing_them(tmp_path, monkeypatch):
    """Observation only: every refusal and acceptance is journalled once per 15 minutes, every
    new signal once per candle with what happened to it; decisions stay exactly the same."""
    import json

    import pandas as pd
    from AIPortfolio import AIPortfolio
    from freqtrade.persistence import Trade
    m = Manifest(sleeves=[Sleeve(id="ex", family="trend_ema", params={}, pairs=["ETH/USDT:USDT", "SOL/USDT:USDT"],
                                 stage="exploration", risk=0.001, sides=["long", "short"])])
    path = tmp_path / "manifest.json"
    m.save(path)
    st = AIPortfolio({"aitrader": {"manifest_path": str(path), "max_open_risk": 0.08, "max_side_risk": 0.04,
                                   "max_same_side": 25, "max_explore_trades": 1, "max_explore_risk": 0.03},
                      "runmode": "live", "exchange": {"demo_trading": True}})
    st.bot_start()
    st.wallets = FakeWallets()
    t = SimpleNamespace(pair="ETH/USDT:USDT", enter_tag="ex", is_short=True, open_rate=100.0, stop_loss=101.0,
                        stake_amount=100.0, leverage=1.0)
    monkeypatch.setattr(Trade, "get_open_trades", staticmethod(lambda: [t]), raising=False)
    for _ in range(3):  # offered again every few seconds while the candle lasts
        assert st.confirm_trade_entry("SOL/USDT:USDT", "limit", 1, 100, "GTC", None, "ex", "short") is False
    st.config["aitrader"]["max_explore_trades"] = 5
    assert st.confirm_trade_entry("SOL/USDT:USDT", "limit", 1, 100, "GTC", None, "ex", "short") is True
    df = pd.DataFrame({"date": pd.date_range("2026-11-22", periods=3, freq="15min", tz="UTC")})
    sl = st.sleeves_for_pair("SOL/USDT:USDT")[0]
    rise, flat = pd.Series([False, False, True]), pd.Series([True, True, True])
    monkeypatch.setattr(st, "_open_tag", lambda pair: "other")
    st._journal_signals(df, "SOL/USDT:USDT", sl, rise, flat, pd.Series([True] * 3))   # long: new; short: lasting state
    st._journal_signals(df, "SOL/USDT:USDT", sl, rise, flat, pd.Series([True] * 3))   # same candle again: no new line
    monkeypatch.setattr(st, "_open_tag", lambda pair: "ex")
    st._journal_signals(df.assign(date=df["date"] + pd.Timedelta("15min")), "SOL/USDT:USDT", sl, rise, flat,
                        pd.Series([True] * 3))  # its own position: not a missed signal
    lines = [json.loads(x) for x in (tmp_path / "signals.jsonl").read_text().splitlines()]
    assert [(x["k"], x["o"]) for x in lines] == [("cfm", "explore_count"), ("cfm", "accepted"), ("sig", "pair_busy")]
    assert lines[-1]["d"] == "long" and lines[-1]["s"] == "ex"


def test_late_higher_timeframe_candle_is_still_acted_on_once_live(tmp_path):
    """Live: if the hourly candle reached the bot after the first 15m candle that should carry its
    signal was analysed, the next analysis still acts on it (within 2 bot candles), and a signal
    the bot already acted on is never repeated."""
    from AIPortfolio import AIPortfolio

    from aitrader.families import get_family
    pair = "BTC/USDT:USDT"
    h1 = ohlcv(1500, seed=11, vol=0.012)
    rows = []
    for _, r in h1.iterrows():
        for q in range(4):
            rows.append({"date": r["date"] + pd.Timedelta(minutes=15 * q), "open": r["open"], "high": r["high"],
                         "low": r["low"], "close": r["close"], "volume": r["volume"] / 4})
    m15 = pd.DataFrame(rows)
    ref = get_family("trend_ema").populate(h1, {})
    k = int(ref.index[ref["long_sig"] & (ref.index > 1100)][0])  # an hourly candle with a long signal
    due = h1["date"].iloc[k] + pd.Timedelta(minutes=45)  # the 15m candle that closes with it

    def bot(path_name):
        m = Manifest(sleeves=[Sleeve(id="h", family="trend_ema", params={}, pairs=[pair], stage="exploration",
                                     risk=0.001, timeframe="1h")])
        path = tmp_path / path_name
        m.save(path)
        st = AIPortfolio({"aitrader": {"manifest_path": str(path)}, "runmode": "live",
                          "exchange": {"demo_trading": True}})
        st.timeframe = "15m"
        st.bot_start()
        return st

    def analyse(st, upto_15m, hours):
        st.dp = SimpleNamespace(get_pair_dataframe=lambda p, tf, **kw: h1.iloc[:hours].reset_index(drop=True)
                                if tf == "1h" else m15, current_whitelist=lambda: [pair])
        df = m15[m15["date"] <= upto_15m].reset_index(drop=True)
        return _populate(st, df, pair)

    # on time: fires on the 15m candle that closes with the hourly candle, and only there
    st = bot("on_time.json")
    assert analyse(st, due, k + 1)["enter_long"].iloc[-1] == 1
    assert analyse(st, due + pd.Timedelta(minutes=15), k + 1)["enter_long"].iloc[-1] != 1
    # late: the hourly candle was not there yet at the first analysis – the next one acts on it
    st = bot("late.json")
    assert analyse(st, due, k)["enter_long"].iloc[-1] != 1
    assert analyse(st, due + pd.Timedelta(minutes=15), k + 1)["enter_long"].iloc[-1] == 1
    assert analyse(st, due + pd.Timedelta(minutes=30), k + 1)["enter_long"].iloc[-1] != 1  # once only
    # too late (beyond the grace of 2 bot candles): not chased
    st = bot("too_late.json")
    assert analyse(st, due + pd.Timedelta(minutes=45), k + 1)["enter_long"].iloc[-1] != 1
    # a restart after the signal was acted on: the new process never repeats it (23.11 18:23–18:37)
    st = bot("before_restart.json")
    assert analyse(st, due, k + 1)["enter_long"].iloc[-1] == 1
    st = bot("after_restart.json")
    assert analyse(st, due + pd.Timedelta(minutes=15), k + 1)["enter_long"].iloc[-1] != 1
    assert analyse(st, due + pd.Timedelta(minutes=30), k + 1)["enter_long"].iloc[-1] != 1


def _hourly_on_15m(h1):
    rows = []
    for _, r in h1.iterrows():  # 4 quarter-hours per hour, same OHLC path
        for q in range(4):
            rows.append({"date": r["date"] + pd.Timedelta(minutes=15 * q), "open": r["open"], "high": r["high"],
                         "low": r["low"], "close": r["close"], "volume": r["volume"] / 4})
    return pd.DataFrame(rows)


GUEST = {"rsi_len": 9, "rsi_lower": 37.3, "rsi_exit": -10.0, "rsi_trend": 0}  # exit (RSI ≤ 60) below entry (62.7)


def _owner_and_guest(tmp_path, runmode):
    from AIPortfolio import AIPortfolio
    pair = "BTC/USDT:USDT"
    m = Manifest(sleeves=[
        Sleeve(id="own", family="trend_ema", params={"adx_min": 35.0}, pairs=[pair], stage="exploration", risk=0.001,
               score=0.9, timeframe="1h", lead=[pair]),
        Sleeve(id="guest", family="rsi_revert", params=GUEST, pairs=[pair], stage="exploration", risk=0.001,
               score=0.1, timeframe="1h")])
    path = tmp_path / f"m_{runmode}.json"
    m.save(path)
    st = AIPortfolio({"aitrader": {"manifest_path": str(path)}, "runmode": runmode, "exchange": {"demo_trading": True}})
    st.timeframe = "15m"
    st.bot_start()
    return st, pair


def test_a_guest_enters_only_where_its_own_backtest_would(tmp_path):
    """23.11, BTC: a guest strategy shorted on an hourly candle that already carried its own exit
    (Freqtrade checked the coin owner's exit columns) and left 3 minutes later. Each strategy's
    entries now obey Freqtrade's rule with its own columns: no entry on a candle with the same
    side's exit or the opposite entry – exactly the candles its single-strategy backtest trades."""
    from aitrader.families import get_family
    h1 = ohlcv(1500, seed=11, vol=0.012)
    m15 = _hourly_on_15m(h1)
    ref = get_family("rsi_revert").populate(h1, GUEST)
    both = ref["short_sig"] & ref["exit_short_sig"]
    assert both.sum() > 0  # the case of 23.11 exists in this data
    bt_short = set(h1.loc[ref["short_sig"] & ~ref["exit_short_sig"] & ~ref["long_sig"], "date"])
    bt_long = set(h1.loc[ref["long_sig"] & ~ref["exit_long_sig"] & ~ref["short_sig"], "date"])
    for runmode in ("backtest", "live"):
        st, pair = _owner_and_guest(tmp_path, runmode)
        st.dp = SimpleNamespace(get_pair_dataframe=lambda p, tf, **kw: h1 if tf == "1h" else m15,
                                current_whitelist=lambda pr=pair: [pr])
        df = _populate(st, m15, pair)
        g = df["enter_tag"] == "guest"
        shorts = set(df.loc[g & (df["enter_short"] == 1), "date"] - pd.Timedelta(minutes=45))
        longs = set(df.loc[g & (df["enter_long"] == 1), "date"] - pd.Timedelta(minutes=45))
        own_rows = set(df.loc[df["enter_tag"] == "own", "date"] - pd.Timedelta(minutes=45))
        assert shorts == bt_short - own_rows and longs == bt_long - own_rows  # never a candle its backtest skips
        assert not (df.loc[g & (df["enter_short"] == 1), "xs:guest"]).any()
        assert not (df.loc[g & (df["enter_long"] == 1), "xl:guest"]).any()
        if runmode == "live":  # no open trade: no exit column can veto (or speak for) another strategy
            assert "exit_short" not in df or df["exit_short"].fillna(0).sum() == 0


def test_an_open_trade_is_never_vetoed_by_another_strategys_entry(tmp_path, monkeypatch):
    """Live, one trade per coin: Freqtrade lets an exit signal through only without an entry flag
    on the trade's side. Another strategy's entry flag must not hold the trade (its backtest has
    no such veto); the trade's own exit columns drive its exit."""
    h1 = ohlcv(1500, seed=11, vol=0.012)
    m15 = _hourly_on_15m(h1)
    st, pair = _owner_and_guest(tmp_path, "live")
    st.dp = SimpleNamespace(get_pair_dataframe=lambda p, tf, **kw: h1 if tf == "1h" else m15,
                            current_whitelist=lambda: [pair])
    monkeypatch.setattr(st, "_open_trade", lambda p: SimpleNamespace(enter_tag="guest"))
    df = _populate(st, m15, pair)
    assert set(df["enter_tag"].dropna()) <= {"guest"}  # the owner's entries are not written while the guest holds
    assert (df["exit_short"].fillna(0) == df["xs:guest"].astype(int)).all()


def test_maker_wait_is_over_after_3_min_and_the_new_order_crosses(portfolio):
    """Freqtrade moves a resting order only on a new bot candle (15 min), after the 12-min unfilled
    timeout – the 3-minute cross never ran (23.11, BTC entry 0.53 % late). The order is now
    cancelled when its maker wait is over and the re-placed one crosses the spread, once."""
    from datetime import datetime, timezone
    portfolio.config["runmode"] = "live"
    portfolio.dp = SimpleNamespace(orderbook=lambda pair, n: {"bids": [[99.9, 1]], "asks": [[100.1, 1]]})
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tr = SimpleNamespace(enter_tag="s1", is_short=False)
    order = SimpleNamespace(order_date_utc=t0, filled=0.0)
    pair = "BTC/USDT:USDT"
    assert portfolio.check_entry_timeout(pair, tr, order, t0 + timedelta(seconds=120)) is False  # still a maker
    assert portfolio.custom_entry_price(pair, None, t0, 99.9, "s1", "long") == 99.9  # first order rests
    assert portfolio.check_entry_timeout(pair, tr, order, t0 + timedelta(seconds=181)) is True
    t1 = t0 + timedelta(seconds=182)
    assert portfolio.custom_entry_price(pair, None, t1, 99.9, "s1", "long") == pytest.approx(100.1 * 1.0005)
    assert portfolio.custom_entry_price(pair, None, t1, 99.9, "s1", "long") == 99.9  # the mark is used once
    assert portfolio.check_entry_timeout(pair, tr, order, t1) is True
    assert portfolio.custom_entry_price(pair, None, t1, 100.1, "s1", "short") == pytest.approx(99.9 * 0.9995)
    # a partly filled order keeps resting; exits cross after 90 s the same way
    assert portfolio.check_entry_timeout(pair, tr, SimpleNamespace(order_date_utc=t0, filled=0.5), t1) is False
    assert portfolio.check_exit_timeout(pair, tr, order, t0 + timedelta(seconds=60)) is False
    assert portfolio.check_exit_timeout(pair, tr, order, t0 + timedelta(seconds=91)) is True
    assert portfolio.custom_exit_price(pair, tr, t1, 100.1, 0.01, "exit_signal") == pytest.approx(99.9 * 0.9995)
    assert portfolio.custom_exit_price(pair, tr, t1, 100.1, 0.01, "exit_signal") == 100.1
    portfolio.config["runmode"] = "backtest"
    assert portfolio.check_entry_timeout(pair, tr, order, t1) is False  # backtests: Freqtrade's own fills


def test_a_pending_entry_counts_at_its_sized_risk_not_at_the_guard_stop(portfolio):
    """An entry that has not filled carries Freqtrade's −30 % guard as its stop. Counted at that,
    one pending entry weighed ~6× its real risk and could block other entries at the side cap."""
    df = _populate(portfolio, ohlcv(800, seed=3))
    portfolio.dp = FakeDP(df)
    atr = float(df["at:s1"].iloc[-1])
    sl_atr = 2.0  # trend_ema default
    stake, rate = 500.0, 100.0
    pending = SimpleNamespace(pair="BTC/USDT:USDT", enter_tag="s1", open_rate=rate, stop_loss=rate * 1.3, is_short=True,
                              stake_amount=stake, leverage=1.0, amount=0.0)
    sized = max(0.01 * 10_000, stake / rate * sl_atr * atr)
    assert portfolio._trade_risk(pending, 10_000.0) == pytest.approx(min(0.3 * stake, sized))
    filled = SimpleNamespace(**{**pending.__dict__, "amount": 5.0, "stop_loss": rate * 1.02})
    assert portfolio._trade_risk(filled, 10_000.0) == pytest.approx(0.02 * stake)  # a real stop counts as it is
    unknown = SimpleNamespace(**{**pending.__dict__, "enter_tag": "gone"})
    portfolio.sleeve_for_trade = lambda t: None
    assert portfolio._trade_risk(unknown, 10_000.0) == pytest.approx(0.3 * stake)  # unknown strategy: stricter guard


def test_the_bot_client_asks_for_candles_at_the_right_address():
    from aitrader.ftclient import FtClient as FTClient
    c = FTClient("http://127.0.0.1:8080", "u", "p")
    seen = []
    c.session.get = lambda url, **kw: (seen.append(url), SimpleNamespace(raise_for_status=lambda: None,
                                                                         json=lambda: {}))[1]
    c.pair_candles("BTC/USDT:USDT", "15m", 13)
    assert seen == ["http://127.0.0.1:8080/api/v1/pair_candles"]  # was /api/v1//api/v1/… → 404 since 22.11
