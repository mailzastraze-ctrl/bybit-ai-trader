"""Audit 2026-11-22 (ChatGPT follow-up), A1: the account caps must judge a new entry by the
risk it is actually sized to, not by the sleeve's nominal risk.

`custom_stake_amount` sizes a trade to `risk × size_multiplier(conviction, conv_w)` (up to 1.5×)
and may round a small stake up to the exchange minimum (up to another 1.5×), while
`confirm_trade_entry` used to add only `sleeve.risk × equity` to the open risk."""

from types import SimpleNamespace

import pandas as pd
import pytest

from aitrader.manifest import Manifest, Sleeve

EQ = 10_000.0


class Wallets:
    def get_total_stake_amount(self):
        return EQ


def _st(tmp_path, conv_w):
    from AIPortfolio import AIPortfolio
    path = tmp_path / "m.json"
    Manifest(sleeves=[Sleeve(id="x", family="trend_ema", params={"sl_atr": 2.0, "conv_w": conv_w},
                             pairs=["BTC/USDT:USDT"], stage="exploration", risk=0.001)]).save(path)
    st = AIPortfolio({"aitrader": {"manifest_path": str(path), "max_open_risk": 0.08, "max_side_risk": 0.04,
                                   "max_explore_risk": 0.03, "max_explore_trades": 99, "max_same_side": 99},
                      "runmode": "live", "exchange": {"demo_trading": True}})
    st.bot_start()
    st.wallets = Wallets()
    # last analysed candle: ATR 1.0 at price 100 (stop 2 ATR = 2 %), conviction 1.5 (the cap of size_multiplier)
    st.dp = SimpleNamespace(get_analyzed_dataframe=lambda pair, tf: (pd.DataFrame(
        {"close": [100.0], "atr": [1.0], "at:x": [1.0], "cv:x": [1.5]}), None))
    return st


def _open_shorts(monkeypatch, risk_frac):
    """Open shorts whose stops put `risk_frac` of equity at risk."""
    from freqtrade.persistence import Trade
    t = SimpleNamespace(is_short=True, open_rate=100.0, stop_loss=102.0, stake_amount=risk_frac * EQ / 0.02,
                        leverage=1.0, enter_tag="other", pair="ETH/USDT:USDT", id=1)
    monkeypatch.setattr(Trade, "get_open_trades", staticmethod(lambda: [t]), raising=False)


@pytest.mark.parametrize("conv_w, expected", [(0.0, True), (1.0, False)])
def test_side_cap_counts_the_sized_risk_of_the_new_entry(tmp_path, monkeypatch, conv_w, expected):
    st = _st(tmp_path, conv_w)
    _open_shorts(monkeypatch, 0.0389)  # 3.89 % on the short side, cap 4 %
    stake = st.custom_stake_amount("BTC/USDT:USDT", None, 100.0, 0.0, None, 1e9, 1.0, "x", "short")
    amount = stake / 100.0
    sized = amount * 2.0 * 1.0 / EQ  # loss at the stop = amount × sl_atr × ATR
    assert sized == pytest.approx(0.001 * (1.5 if conv_w else 1.0))
    # nominal 0.10 % keeps the side at 3.99 % (accepted); sized 0.15 % → 4.04 % > 4 % must be declined
    ok = st.confirm_trade_entry("BTC/USDT:USDT", "limit", amount, 100.0, "GTC", None, "x", "short")
    assert ok is expected


def test_min_stake_bump_is_counted_too(tmp_path, monkeypatch):
    st = _st(tmp_path, 0.0)
    _open_shorts(monkeypatch, 0.0389)
    # the exchange minimum lifted the stake 1.4× above the risk budget (allowed up to 1.5×)
    stake = st.custom_stake_amount("BTC/USDT:USDT", None, 100.0, 0.0, 700.0, 1e9, 1.0, "x", "short")
    assert stake == 700.0  # 500 by risk, bumped to the minimum
    assert st.confirm_trade_entry("BTC/USDT:USDT", "limit", stake / 100.0, 100.0, "GTC", None, "x", "short") is False


def test_caps_never_get_looser_than_the_nominal_risk(tmp_path, monkeypatch):
    """A tiny or unknown order is still counted at least at the sleeve's nominal risk."""
    st = _st(tmp_path, 0.0)
    _open_shorts(monkeypatch, 0.0395)
    assert st.confirm_trade_entry("BTC/USDT:USDT", "limit", 0.0001, 100.0, "GTC", None, "x", "short") is False
    st.dp = SimpleNamespace(get_analyzed_dataframe=lambda pair, tf: (None, None))  # no candles: nominal
    assert st.confirm_trade_entry("BTC/USDT:USDT", "limit", 1e6, 100.0, "GTC", None, "x", "short") is False
    _open_shorts(monkeypatch, 0.0389)
    assert st.confirm_trade_entry("BTC/USDT:USDT", "limit", 1e6, 100.0, "GTC", None, "x", "short") is True
