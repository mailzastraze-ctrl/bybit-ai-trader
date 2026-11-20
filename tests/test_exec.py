from aitrader.selftest import execution_test


class FakeFt:
    """Simulates the freqtrade REST API through one forced trade lifecycle."""

    def __init__(self, place_sl=True):
        self.state, self.place_sl, self.calls, self.trade = "idle", place_sl, [], None

    def whitelist(self):
        return {"whitelist": ["BTC/USDT:USDT", "XRP/USDT:USDT"]}

    def status(self):
        self.calls.append(("status", self.state))
        if self.state == "submitted":
            self.state = "filled"
            return [{**self.trade, "has_open_orders": True, "orders": []}]
        if self.state == "filled":
            self.state = "sl"
            return [{**self.trade, "has_open_orders": False, "amount": 50, "orders": []}]
        if self.state == "sl":
            orders = [{"ft_order_side": "stoploss", "status": "open", "stop_price": 0.5, "order_id": "x"}] if self.place_sl else []
            return [{**self.trade, "has_open_orders": False, "amount": 50, "orders": orders}]
        return []

    def forceenter(self, pair, side, stake, tag):
        self.trade = {"trade_id": 9, "pair": pair, "enter_tag": tag, "open_rate": 0.6, "leverage": 2}
        self.state = "submitted"

    def forceexit(self, tid):
        self.state = "closed"

    def trades(self, limit=50):
        return {"trades": [{**self.trade, "close_rate": 0.61, "profit_abs": 0.1, "exit_reason": "force_exit"}]}


def test_execution_test_full_path():
    ft = FakeFt()
    res = execution_test(ft, sleep=lambda s: None, timeout_s=5)
    assert res["ok"], res
    assert set(res["steps"]) == {"entry_submitted", "entry_filled", "stoploss_on_exchange", "exit"}
    assert res["steps"]["entry_submitted"]["detail"]["pair"] == "XRP/USDT:USDT"


def test_execution_test_flags_missing_exchange_stop():
    res = execution_test(FakeFt(place_sl=False), sleep=lambda s: None, timeout_s=1)
    assert not res["ok"] and not res["steps"]["stoploss_on_exchange"]["ok"]


def test_execution_test_survives_connection_reset_and_cleans_up():
    import requests
    ft = FakeFt()
    orig = ft.status
    n = {"i": 0}

    def flaky():
        n["i"] += 1
        if n["i"] in (3, 4):
            raise requests.ConnectionError("Connection reset by peer")
        return orig()
    ft.status = flaky
    res = execution_test(ft, sleep=lambda s: None, timeout_s=5)
    assert res["ok"], res


def test_leftover_test_trade_is_closed_first():
    ft = FakeFt()
    exits = []
    ft.forceexit = lambda tid: exits.append(tid)
    leftover = [{"trade_id": 1, "pair": "XRP/USDT:USDT", "enter_tag": "exec-test-1"}]
    calls = {"n": 0}

    def status():
        calls["n"] += 1
        return leftover if calls["n"] == 1 else []
    ft.status = status
    res = execution_test(ft, sleep=lambda s: None, timeout_s=1)
    assert exits[0] == 1 and res["steps"]["cleanup_previous"]["detail"]["closed_trade_ids"] == [1]


def test_demo_guard_validates_before_opening_exchange():
    import json
    from pathlib import Path

    import pytest

    from aitrader.demo import validate_trade_config

    cfg = json.loads((Path(__file__).resolve().parents[1] / "config" / "trade.json").read_text())
    validate_trade_config(cfg)
    for patch in ({"dry_run": True}, {"margin_mode": "cross"}, {"exchange": {"name": "bybit"}}):
        with pytest.raises(ValueError):
            validate_trade_config({**cfg, **patch})
    with pytest.raises(ValueError):
        validate_trade_config({**cfg, "exchange": {**cfg["exchange"], "ccxt_sync_config": {"urls": {}}}})


def test_native_ccxt_signing_is_demo_only(monkeypatch):
    import pytest

    from aitrader.demo import DEMO_HOST, protect_ccxt

    ccxt = pytest.importorskip("ccxt")
    async_ccxt = pytest.importorskip("ccxt.async_support")
    pro = pytest.importorskip("ccxt.pro")
    for cls in (ccxt.bybit, async_ccxt.bybit, pro.bybit):
        monkeypatch.setattr(cls, "sign", cls.sign)
        protect_ccxt(cls)
        client = cls({"apiKey": "test-key", "secret": "test-secret"})
        with pytest.raises(ValueError):
            client.sign("v5/order/create", ["private"], "POST", {})
        client.enable_demo_trading(True)
        for path, access, method in (("v5/order/create", "private", "POST"),
                                     ("v5/market/time", "public", "GET")):
            signed = client.sign(path, [access], method, {})
            assert signed["url"].startswith(f"https://{DEMO_HOST}/")
