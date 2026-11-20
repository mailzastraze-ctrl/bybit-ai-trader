"""Run the native Freqtrade worker with Bybit Demo as its only trade destination."""

from __future__ import annotations

from urllib.parse import urlsplit

DEMO_HOST = "api-demo.bybit.com"


def validate_trade_config(config: dict) -> None:
    exchange = config.get("exchange", {})
    orders = config.get("order_types", {})
    if not (
        exchange.get("name") == "bybit"
        and exchange.get("demo_trading") is True
        and exchange.get("enable_ws") is False
        and config.get("dry_run") is False
        and config.get("trading_mode") == "futures"
        and config.get("margin_mode") == "isolated"
        and config.get("timeframe") == "1h"
        and config.get("stake_currency") == "USDT"
        and config.get("strategy") == "AIPortfolio"
        and orders.get("entry") == "limit"
        and orders.get("stoploss_on_exchange") is True
        and orders.get("stoploss") == "market"
    ):
        raise ValueError("Trading requires Bybit Demo REST, isolated USDT futures, 1h and exchange market stops")
    for section in ("ccxt_config", "ccxt_async_config", "ccxt_sync_config"):
        ccxt = exchange.get(section, {})
        if any(k != "options" for k in ccxt):
            raise ValueError("Bybit Demo does not permit CCXT transport overrides")
    if config.get("api_server", {}).get("listen_ip_address") != "127.0.0.1":
        raise ValueError("The Freqtrade control API must listen on loopback")
    if config.get("order_time_in_force", {}).get("entry") != "PO":
        raise ValueError("Maker entries require PostOnly time in force")


def check_demo_url(url: str) -> None:
    target = urlsplit(url)
    if (
        target.scheme != "https" or target.netloc != DEMO_HOST or not target.path.startswith("/v5/")
    ):
        raise ValueError("Blocked Bybit request outside the Demo V5 REST endpoint")


def protect_ccxt(exchange_cls: type) -> None:
    native_sign = exchange_cls.sign

    def sign(self, *args, **kwargs):
        request = native_sign(self, *args, **kwargs)
        check_demo_url(request["url"])
        return request

    exchange_cls.sign = sign


def main() -> None:
    import sys

    import ccxt
    import ccxt.async_support
    import ccxt.pro
    from freqtrade import worker
    from freqtrade.main import main as freqtrade_main

    from aitrader.demobot import DemoTradingBot

    protect_ccxt(ccxt.bybit)
    protect_ccxt(ccxt.async_support.bybit)
    protect_ccxt(ccxt.pro.bybit)
    worker.FreqtradeBot = DemoTradingBot
    freqtrade_main(["trade", *sys.argv[1:]])


if __name__ == "__main__":
    main()
