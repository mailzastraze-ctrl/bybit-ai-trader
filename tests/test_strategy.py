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
    # market shock: BTC +3% in the last hour → a profitable short goes to break-even; a long is untouched
    btc = pd.DataFrame({"close": [100.0] * 10 + [103.0]})
    portfolio.dp = SimpleNamespace(get_pair_dataframe=lambda pair, tf: btc, get_analyzed_dataframe=lambda pair, tf: (None, None))
    tr = SimpleNamespace(id=7, is_short=True, min_rate=98.8, max_rate=100.0, open_rate=100.0, enter_tag="s1")
    stop = portfolio._stop("ETH/USDT:USDT", tr, EntryContext(entry=100.0, atr=1.0, is_short=True), dict(p), t0)
    assert stop == pytest.approx(99.88)
    lt = SimpleNamespace(id=8, is_short=False, min_rate=100.0, max_rate=103.0, open_rate=100.0, enter_tag="s1")
    assert portfolio._stop("ETH/USDT:USDT", lt, EntryContext(entry=100.0, atr=1.0, is_short=False), dict(p), t0) \
        == EntryContext(entry=100.0, atr=1.0, is_short=False).managed_stop(dict(p), 103.0)
    portfolio.config["runmode"] = "backtest"
    portfolio._shock_at = None
    assert portfolio._stop("ETH/USDT:USDT", tr, EntryContext(entry=100.0, atr=1.0, is_short=True), dict(p), t0) == pytest.approx(102.0)
