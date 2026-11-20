"""EU egress for the research lab: a tiny authenticated HTTPS CONNECT proxy.

Why: Bybit blocks requests from US IP addresses, and GitHub-hosted runners run in the US.
The live server runs in Railway's EU region, where Bybit is reachable. The research lab
tunnels its *public market-data* requests (markets, candles, funding, mark prices) through
this proxy, so research uses the exact Bybit data the bot trades on.

Safety:
  * only CONNECT to Bybit API hosts on port 443 (no open proxy);
  * TLS is end-to-end between the runner and Bybit — the proxy only relays bytes;
  * credentials are short-lived HMAC tokens issued to GitHub OIDC-authenticated lab runs;
  * no API keys ever pass through it (research uses public endpoints only).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import re
import time

log = logging.getLogger("bybitproxy")
ALLOWED_HOST = re.compile(r"^(api|api2|api-testnet|api-demo)\.(bybit|bytick)\.com$")
TOKEN_TTL_S = 8 * 3600
MAX_TUNNELS = 48
IDLE_TIMEOUT_S = 180


def _secret() -> bytes:
    s = os.environ.get("LAB_PROXY_SECRET", "")
    if not s:
        raise RuntimeError("LAB_PROXY_SECRET not set")
    return s.encode()


def issue_token(ttl_s: int = TOKEN_TTL_S, now: float | None = None) -> str:
    exp = int((now or time.time()) + ttl_s)
    sig = hmac.new(_secret(), f"lab|{exp}".encode(), hashlib.sha256).hexdigest()[:40]
    return f"{exp}.{sig}"


def verify_token(token: str, now: float | None = None) -> bool:
    try:
        exp_s, sig = token.split(".", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < (now or time.time()):
        return False
    good = hmac.new(_secret(), f"lab|{exp}".encode(), hashlib.sha256).hexdigest()[:40]
    return hmac.compare_digest(sig, good)


def parse_connect(head: bytes) -> tuple[str | None, int | None, str | None]:
    """→ (host, port, token) from a CONNECT request head; Nones when malformed."""
    try:
        lines = head.decode("latin-1").split("\r\n")
        method, target, _ = lines[0].split(" ", 2)
    except ValueError:
        return None, None, None
    if method.upper() != "CONNECT" or ":" not in target:
        return None, None, None
    host, port = target.rsplit(":", 1)
    token = None
    for ln in lines[1:]:
        if ln.lower().startswith("proxy-authorization:"):
            val = ln.split(":", 1)[1].strip()
            if val.lower().startswith("basic "):
                try:
                    user, _, pw = base64.b64decode(val[6:]).decode().partition(":")
                    token = pw if user == "lab" else None
                except (ValueError, UnicodeDecodeError):
                    token = None
    try:
        return host.lower(), int(port), token
    except ValueError:
        return None, None, None


class Proxy:
    def __init__(self, allowed=ALLOWED_HOST):
        self.allowed = allowed
        self.active = 0
        self.stats = {"tunnels": 0, "denied": 0, "bytes": 0}

    async def _pipe(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            while True:
                data = await asyncio.wait_for(r.read(65536), IDLE_TIMEOUT_S)
                if not data:
                    break
                self.stats["bytes"] += len(data)
                w.write(data)
                await w.drain()
        except (TimeoutError, ConnectionError, OSError):
            pass
        finally:
            try:
                w.close()
            except Exception:  # noqa: BLE001
                pass

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async def deny(code: str) -> None:
            self.stats["denied"] += 1
            writer.write(f"HTTP/1.1 {code}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
            try:
                await writer.drain()
            finally:
                writer.close()

        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 15)
        except (TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            writer.close()
            return
        host, port, token = parse_connect(head)
        if host is None:
            return await deny("405 Method Not Allowed")
        if not token or not verify_token(token):
            return await deny("407 Proxy Authentication Required")
        if port != 443 or not self.allowed.match(host):
            return await deny("403 Forbidden")
        if self.active >= MAX_TUNNELS:
            return await deny("503 Service Unavailable")
        try:
            ur, uw = await asyncio.wait_for(asyncio.open_connection(host, port), 15)
        except (TimeoutError, OSError):
            return await deny("502 Bad Gateway")
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        self.active += 1
        self.stats["tunnels"] += 1
        try:
            await asyncio.gather(self._pipe(reader, uw), self._pipe(ur, writer))
        finally:
            self.active -= 1


async def serve(port: int) -> None:
    p = Proxy()
    server = await asyncio.start_server(p.handle, "0.0.0.0", port, limit=16384)
    log.info("bybit egress proxy listening on :%d", port)

    async def report():
        while True:
            await asyncio.sleep(900)
            if p.stats["tunnels"] or p.stats["denied"]:
                log.info("proxy stats: %s active=%d", p.stats, p.active)

    async with server:
        await asyncio.gather(server.serve_forever(), report())


def main() -> None:
    from aitrader.util import setup_logging
    setup_logging("bybitproxy")
    asyncio.run(serve(int(os.environ.get("LAB_PROXY_PORT", "8899"))))


if __name__ == "__main__":
    main()
