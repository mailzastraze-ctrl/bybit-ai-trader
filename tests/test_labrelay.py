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
    assert int(lr.issue_token(8 * 3600, now=1000).split(".")[0]) == 1000 + lr.TOKEN_TTL_S
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
