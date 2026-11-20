"""Auto-imported by Python (PYTHONPATH) inside research freqtrade subprocesses when the
Bybit relay is enabled. Rewrites ccxt's HTTP requests to Bybit's public API so they go
through the live server's EU relay (Bybit blocks the US runners' IPs)."""

import os

RELAY = os.environ.get("AITRADER_RELAY", "")
TOKEN = os.environ.get("AITRADER_RELAY_TOKEN", "")
HOSTS = ("https://api.bybit.com/", "https://api.bytick.com/")


def _rewrite(url, headers):
    if RELAY and isinstance(url, str) and url.startswith(HOSTS):
        headers = dict(headers or {})
        headers["X-Lab-Token"] = TOKEN
        return RELAY + url, headers
    return url, headers


def install():
    try:
        from ccxt.base.exchange import Exchange as SyncExchange
    except Exception:  # noqa: BLE001
        return
    if getattr(SyncExchange, "_aitrader_relay", False):
        return
    sync_fetch = SyncExchange.fetch

    def fetch(self, url, method="GET", headers=None, body=None):
        url, headers = _rewrite(url, headers)
        return sync_fetch(self, url, method, headers, body)

    SyncExchange.fetch = fetch
    SyncExchange._aitrader_relay = True
    try:
        from ccxt.async_support.base.exchange import Exchange as AsyncExchange
    except Exception:  # noqa: BLE001
        return
    async_fetch = AsyncExchange.fetch

    async def afetch(self, url, method="GET", headers=None, body=None):
        url, headers = _rewrite(url, headers)
        return await async_fetch(self, url, method, headers, body)

    AsyncExchange.fetch = afetch
    AsyncExchange._aitrader_relay = True


if RELAY:
    install()
