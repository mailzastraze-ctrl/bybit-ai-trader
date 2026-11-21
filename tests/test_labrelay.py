"""Bybit market-data relay: token auth and a strict allow-list."""

import pytest

from aitrader import labrelay as lr


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("LAB_PROXY_SECRET", "s3cret")


def test_tokens_expire_and_cannot_be_forged(monkeypatch):
    tok = lr.issue_token(60, now=1000)
    assert lr.verify_token(tok, now=1030) and not lr.verify_token(tok, now=1061)
    exp, sig = tok.split(".")
    assert not lr.verify_token(f"{int(exp) + 999}.{sig}", now=1030)
    assert not lr.verify_token(None) and not lr.verify_token("garbage")
    monkeypatch.setenv("LAB_PROXY_SECRET", "other")
    assert not lr.verify_token(tok, now=1030)


@pytest.mark.parametrize("rest,query,ok", [
    ("https://api.bybit.com/v5/market/kline", "category=linear&symbol=BTCUSDT", True),
    ("https:/api.bybit.com/v5/market/instruments-info", "", True),  # collapsed slashes
    ("https://api.bytick.com/v5/market/funding/history", "symbol=X", True),
    ("https://api.bybit.com/v5/order/create", "", False),           # trading endpoints never
    ("https://api.bybit.com/v5/account/wallet-balance", "", False),
    ("https://evil.com/v5/market/kline", "", False),
    ("https://api.bybit.com.evil.com/v5/market/kline", "", False),
    ("https://api.bybit.com/v5/market/../order/create", "", False),
    ("file:///etc/passwd", "", False),
])
def test_allow_list(rest, query, ok):
    assert (lr.target_url(rest, query) is not None) == ok



def test_relay_hook_rewrites_ccxt_bybit_requests(monkeypatch, tmp_path):
    ccxt = pytest.importorskip("ccxt")  # present in the freqtrade image (CI)
    import importlib
    import sys

    from aitrader.research.ftrunner import RELAY_HOOK_DIR, relay_env
    from aitrader.settings import Settings
    s = Settings(data_dir=tmp_path)
    s.research.exchange, s.research.relay, s.research.relay_token = "bybit", "https://srv/relay/", "tok"
    env = relay_env(s)
    assert str(RELAY_HOOK_DIR) in env["PYTHONPATH"] and env["AITRADER_RELAY_TOKEN"] == "tok"
    seen = {}
    from ccxt.base.exchange import Exchange
    monkeypatch.setattr(Exchange, "fetch", lambda self, url, method="GET", headers=None, body=None:
                        seen.update(url=url, headers=headers) or {"retCode": 0, "result": {}})
    monkeypatch.setattr(Exchange, "_aitrader_relay", False, raising=False)
    monkeypatch.setenv("AITRADER_RELAY", "https://srv/relay/")
    monkeypatch.setenv("AITRADER_RELAY_TOKEN", "tok")
    monkeypatch.syspath_prepend(str(RELAY_HOOK_DIR))
    sys.modules.pop("sitecustomize", None)
    hook = importlib.import_module("sitecustomize")
    assert hook.RELAY == "https://srv/relay/"
    ccxt.bybit().fetch("https://api.bybit.com/v5/market/time", "GET", {}, None)
    assert seen["url"] == "https://srv/relay/https://api.bybit.com/v5/market/time"
    assert seen["headers"]["X-Lab-Token"] == "tok"
    ccxt.bybit().fetch("https://example.com/x", "GET", {}, None)
    assert seen["url"] == "https://example.com/x"  # other hosts untouched
    sys.modules.pop("sitecustomize", None)


def test_relay_hook_caches_market_metadata_per_runner(tmp_path, monkeypatch):
    """instruments-info / risk-limit are fetched once per runner (shared by its freqtrade
    subprocesses) instead of by every subprocess – the live server's egress is billed."""
    import importlib
    import sys

    from aitrader.research.ftrunner import RELAY_HOOK_DIR
    monkeypatch.delenv("AITRADER_RELAY", raising=False)  # import without patching ccxt
    monkeypatch.setenv("AITRADER_RELAY_CACHE", str(tmp_path / "cache"))
    monkeypatch.syspath_prepend(str(RELAY_HOOK_DIR))
    sys.modules.pop("sitecustomize", None)
    hook = importlib.import_module("sitecustomize")
    monkeypatch.setattr(hook, "RELAY", "https://srv/relay/")
    monkeypatch.setattr(hook, "TOKEN", "tok")
    calls = []

    def upstream(self, url, method="GET", headers=None, body=None):
        calls.append((url, headers))
        return {"retCode": 0, "result": {"list": [1, 2, 3]}} if "instruments" in url else {"retCode": 10001}
    fetch = hook.cached_fetch(upstream)
    url = "https://api.bybit.com/v5/market/instruments-info?category=linear&limit=1000"
    a = fetch(None, url, "GET", {}, None)
    b = fetch(None, url, "GET", {}, None)
    assert a == b == {"retCode": 0, "result": {"list": [1, 2, 3]}}
    assert len(calls) == 1 and calls[0][0] == "https://srv/relay/" + url and calls[0][1]["X-Lab-Token"] == "tok"
    k = "https://api.bybit.com/v5/market/kline?symbol=BTCUSDT"
    fetch(None, k, "GET", {}, None)
    fetch(None, k, "GET", {}, None)
    assert len(calls) == 3  # candles are never cached
    bad = "https://api.bybit.com/v5/market/risk-limit?category=linear"
    fetch(None, bad, "GET", {}, None)
    fetch(None, bad, "GET", {}, None)
    assert len(calls) == 5  # error answers are not cached
    import asyncio

    async def aup(self, url, method="GET", headers=None, body=None):
        calls.append((url, headers))
        return {"retCode": 0, "result": {}}
    afetch = hook.cached_afetch(aup)
    asyncio.run(afetch(None, url, "GET", {}, None))
    assert len(calls) == 5  # the async path shares the same cache
    sys.modules.pop("sitecustomize", None)

