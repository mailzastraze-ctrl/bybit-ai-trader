"""EU egress proxy for the research lab: auth, allow-list, real tunnelling."""

import asyncio
import base64
import re

import pytest

from aitrader import bybitproxy as bp


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("LAB_PROXY_SECRET", "s3cret")


def test_tokens_expire_and_cannot_be_forged(monkeypatch):
    tok = bp.issue_token(60, now=1000)
    assert bp.verify_token(tok, now=1030)
    assert not bp.verify_token(tok, now=1061)
    exp, sig = tok.split(".")
    assert not bp.verify_token(f"{int(exp) + 999}.{sig}", now=1030)
    monkeypatch.setenv("LAB_PROXY_SECRET", "other")
    assert not bp.verify_token(tok, now=1030)


def test_parse_connect_and_allow_list():
    auth = base64.b64encode(b"lab:abc").decode()
    head = f"CONNECT api.bybit.com:443 HTTP/1.1\r\nProxy-Authorization: Basic {auth}\r\n\r\n".encode()
    assert bp.parse_connect(head) == ("api.bybit.com", 443, "abc")
    assert bp.parse_connect(b"GET http://x/ HTTP/1.1\r\n\r\n")[0] is None
    assert bp.ALLOWED_HOST.match("api.bybit.com") and bp.ALLOWED_HOST.match("api.bytick.com")
    assert not bp.ALLOWED_HOST.match("evil.com") and not bp.ALLOWED_HOST.match("api.bybit.com.evil.com")


def test_tunnel_relays_bytes_and_rejects_bad_requests():
    async def run():
        async def echo(r, w):
            data = await r.read(100)
            w.write(b"echo:" + data)
            await w.drain()
            w.close()
        up = await asyncio.start_server(echo, "127.0.0.1", 0)
        up_port = up.sockets[0].getsockname()[1]
        proxy = bp.Proxy(allowed=re.compile(r"^127\.0\.0\.1$"))
        orig = asyncio.open_connection

        async def fake_open(host, port):  # map :443 to the local echo server
            return await orig(host, up_port)
        asyncio_open = asyncio.open_connection
        asyncio.open_connection = fake_open
        srv = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]

        async def ask(head: bytes, payload: bytes = b"") -> bytes:
            r, w = await orig("127.0.0.1", port)
            w.write(head)
            await w.drain()
            status = await r.readuntil(b"\r\n\r\n")
            if payload and status.startswith(b"HTTP/1.1 200"):
                w.write(payload)
                await w.drain()
                status += await r.read(100)
            w.close()
            return status
        try:
            tok = base64.b64encode(f"lab:{bp.issue_token()}".encode()).decode()
            ok = await ask(f"CONNECT 127.0.0.1:443 HTTP/1.1\r\nProxy-Authorization: Basic {tok}\r\n\r\n".encode(), b"hi")
            assert ok.startswith(b"HTTP/1.1 200") and ok.endswith(b"echo:hi")
            noauth = await ask(b"CONNECT 127.0.0.1:443 HTTP/1.1\r\n\r\n")
            assert noauth.startswith(b"HTTP/1.1 407")
            badhost = await ask(f"CONNECT example.com:443 HTTP/1.1\r\nProxy-Authorization: Basic {tok}\r\n\r\n".encode())
            assert badhost.startswith(b"HTTP/1.1 403")
            badport = await ask(f"CONNECT 127.0.0.1:22 HTTP/1.1\r\nProxy-Authorization: Basic {tok}\r\n\r\n".encode())
            assert badport.startswith(b"HTTP/1.1 403")
        finally:
            asyncio.open_connection = asyncio_open
            srv.close()
            up.close()
    asyncio.run(run())
