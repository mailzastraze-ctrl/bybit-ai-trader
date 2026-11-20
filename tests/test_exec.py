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
