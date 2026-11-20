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
    assert portfolio.leverage(tr.pair, tr.open_date_utc, entry, 1.0, 10.0, "s1", "long") == 3.0


def test_exit_signal_blocked_when_pair_reassigned(portfolio, tmp_path):
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
    assert portfolio.leverage("XRP/USDT:USDT", t, 1.0, 1.0, 10.0, "exec-test-1", "long") == 2.0



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
