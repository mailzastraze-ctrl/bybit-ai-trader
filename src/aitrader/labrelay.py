"""Bybit market-data relay for the research lab (EU egress through the live server).

Why: Bybit blocks US IP addresses and GitHub-hosted runners run in the US. The live server
runs in Railway's EU region. Research ccxt instances use `proxyUrl` = <server>/relay/, so
each *public market-data* GET (instruments, klines, mark-price klines, funding history,
tickers, order book snapshot) is fetched by the server and returned unchanged.

Scope is deliberately tiny:
  * GET only, https://api.bybit.com (or api.bytick.com) and paths under /v5/market/ only;
  * no API keys are involved (research uses public endpoints), no other hosts;
  * callers need a short-lived HMAC token issued to GitHub-OIDC-authenticated lab runs.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import time

ALLOWED_HOSTS = {"api.bybit.com", "api.bytick.com"}
ALLOWED_PATH = re.compile(r"^/v5/market/[a-z0-9\-/]+$")
TOKEN_TTL_S = 15 * 60
TARGET = re.compile(r"https:/+([^/]+)(/[^?]*)")


def _secret() -> bytes:
    s = os.environ.get("LAB_PROXY_SECRET", "")
    if not s:
        raise RuntimeError("LAB_PROXY_SECRET not set")
    return s.encode()


def issue_token(ttl_s: int = TOKEN_TTL_S, now: float | None = None) -> str:
    current = time.time() if now is None else now
    exp = int(current + min(ttl_s, TOKEN_TTL_S))
    sig = hmac.new(_secret(), f"relay|{exp}".encode(), hashlib.sha256).hexdigest()[:40]
    return f"{exp}.{sig}"


def verify_token(token: str | None, now: float | None = None) -> bool:
    try:
        exp_s, sig = (token or "").split(".", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    current = time.time() if now is None else now
    # A signed token issued by the previous release can finish its active lab run.
    if exp <= current:
        return False
    try:
        good = hmac.new(_secret(), f"relay|{exp}".encode(), hashlib.sha256).hexdigest()[:40]
    except RuntimeError:
        return False
    return hmac.compare_digest(sig, good)


def target_url(rest: str, query: str) -> str | None:
    """'https:/api.bybit.com/v5/market/kline' + query → validated upstream URL or None."""
    m = TARGET.fullmatch(rest)
    if not m:
        return None
    host, path = m.group(1).lower(), m.group(2)
    if host not in ALLOWED_HOSTS or not ALLOWED_PATH.fullmatch(path) or "//" in path or len(query) > 2048:
        return None
    return f"https://{host}{path}" + (f"?{query}" if query else "")
