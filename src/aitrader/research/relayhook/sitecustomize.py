"""Auto-imported by Python (PYTHONPATH) inside research freqtrade subprocesses when the
Bybit relay is enabled. Rewrites ccxt's HTTP requests to Bybit's public API so they go
through the live server's EU relay (Bybit blocks the US runners' IPs)."""

import hashlib
import json
import os
import tempfile
import time

RELAY = os.environ.get("AITRADER_RELAY", "")
TOKEN = os.environ.get("AITRADER_RELAY_TOKEN", "")
HOSTS = ("https://api.bybit.com/", "https://api.bytick.com/")
# Market metadata is fetched by every freqtrade subprocess (load_markets) – hundreds of times a
# lab run, ~0.5 MB each, all through the live server, whose egress Railway bills. It changes
# rarely, so one copy per runner (shared by its subprocesses) is kept for a few hours.
CACHEABLE = ("/v5/market/instruments-info", "/v5/market/risk-limit")
CACHE_DIR = os.environ.get("AITRADER_RELAY_CACHE") or os.path.join(tempfile.gettempdir(), "aitrader-relay-cache")
CACHE_TTL_S = 6 * 3600


def _cache_path(url, method):
    if method != "GET" or not isinstance(url, str) or not any(p in url for p in CACHEABLE):
        return None
    return os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".json")


def _cache_get(path):
    try:
        if path and time.time() - os.path.getmtime(path) < CACHE_TTL_S:
            with open(path) as f:
                return json.load(f)
    except (OSError, ValueError):
        pass
    return None


def _cache_put(path, data):
    # only successful Bybit answers (retCode 0); never let caching break a request
    if not path or not isinstance(data, dict) or data.get("retCode") not in (0, "0"):
        return
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError):
        pass


def cached_fetch(fetch):
    """Wrap a ccxt-style fetch(self, url, method, headers, body) with the relay rewrite and
    the metadata cache (sync)."""
    def wrapped(self, url, method="GET", headers=None, body=None):
        path = _cache_path(url, method)
        hit = _cache_get(path)
        if hit is not None:
            return hit
        u, h = _rewrite(url, headers)
        out = fetch(self, u, method, h, body)
        _cache_put(path, out)
        return out
    return wrapped


def cached_afetch(afetch):
    async def wrapped(self, url, method="GET", headers=None, body=None):
        path = _cache_path(url, method)
        hit = _cache_get(path)
        if hit is not None:
            return hit
        u, h = _rewrite(url, headers)
        out = await afetch(self, u, method, h, body)
        _cache_put(path, out)
        return out
    return wrapped


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
    SyncExchange.fetch = cached_fetch(SyncExchange.fetch)
    SyncExchange._aitrader_relay = True
    try:
        from ccxt.async_support.base.exchange import Exchange as AsyncExchange
    except Exception:  # noqa: BLE001
        return
    AsyncExchange.fetch = cached_afetch(AsyncExchange.fetch)
    AsyncExchange._aitrader_relay = True


if RELAY:
    install()
