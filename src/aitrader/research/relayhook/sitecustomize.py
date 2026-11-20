"""Auto-imported by Python (PYTHONPATH) inside research freqtrade subprocesses when the
Bybit relay is enabled. Rewrites ccxt's HTTP requests to Bybit's public API so they go
through the live server's EU relay (Bybit blocks the US runners' IPs)."""

import asyncio
import os
import threading
import time

RELAY = os.environ.get("AITRADER_RELAY", "")
TOKEN = os.environ.get("AITRADER_RELAY_TOKEN", "")
HOSTS = ("https://api.bybit.com/", "https://api.bytick.com/")
_lock = threading.Lock()


def _token():
    global TOKEN
    with _lock:
        expires, sep, _ = TOKEN.partition(".")
        if sep and expires.isdecimal() and int(expires) < time.time() + 60:
            from aitrader.research.labclient import LabClient
            new = LabClient(RELAY.removesuffix("/relay/")).relay()
            if new and new[0] == RELAY:
                TOKEN = new[1]
        return TOKEN


def _rewrite(url, method, headers):
    if RELAY and isinstance(url, str) and url.startswith(HOSTS):
        from aitrader.labrelay import target_url

        if method != "GET" or target_url(*url.partition("?")[::2]) is None:
            raise ValueError("Bybit research relay accepts public market GET requests only")
        return RELAY + url, {"X-Lab-Token": _token()}
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
        url, headers = _rewrite(url, method, headers)
        return sync_fetch(self, url, method, headers, body)

    SyncExchange.fetch = fetch
    SyncExchange._aitrader_relay = True
    try:
        from ccxt.async_support.base.exchange import Exchange as AsyncExchange
    except Exception:  # noqa: BLE001
        return
    async_fetch = AsyncExchange.fetch

    async def afetch(self, url, method="GET", headers=None, body=None):
        if RELAY and isinstance(url, str) and url.startswith(HOSTS):
            url, headers = await asyncio.to_thread(_rewrite, url, method, headers)
        return await async_fetch(self, url, method, headers, body)

    AsyncExchange.fetch = afetch
    AsyncExchange._aitrader_relay = True


if RELAY:
    install()
