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
