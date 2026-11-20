"""Minimal client for the Freqtrade REST API (HTTP basic auth)."""

from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class FtClient:
    def __init__(self, url: str, user: str, password: str, timeout: float = 10.0):
        self.url = url.rstrip("/") + "/api/v1"
        self.auth = (user, password)
        self.timeout = timeout
        self.session = requests.Session()
        # The API server drops idle keep-alive connections ("connection reset by peer"):
        # retry idempotent GETs; POSTs are never retried automatically.
        retry = Retry(total=3, connect=3, read=2, status=0, backoff_factor=0.5,
                      allowed_methods=frozenset({"GET"}), raise_on_status=False)
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _get(self, path: str, **params) -> Any:
        r = self.session.get(f"{self.url}/{path}", auth=self.auth, params=params or None,
                             timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, data: dict | None = None) -> Any:
        r = self.session.post(f"{self.url}/{path}", auth=self.auth, json=data or {},
                              timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def ping(self) -> bool:
        try:
            r = self.session.get(f"{self.url}/ping", timeout=5)
            return r.ok and r.json().get("status") == "pong"
        except requests.RequestException:
            return False

    def status(self) -> list[dict]:
        return self._get("status")

    def balance(self) -> dict:
        return self._get("balance")

    def profit(self) -> dict:
        return self._get("profit")

    def health(self) -> dict:
        return self._get("health")

    def show_config(self) -> dict:
        return self._get("show_config")

    def performance(self) -> list[dict]:
        return self._get("performance")

    def whitelist(self) -> dict:
        return self._get("whitelist")

    def daily(self, days: int = 30) -> dict:
        return self._get("daily", timescale=days)

    def trades(self, limit: int = 500, offset: int = 0) -> dict:
        return self._get("trades", limit=limit, offset=offset)

    def all_closed_trades(self, page: int = 500, max_pages: int = 40) -> list[dict]:
        out: list[dict] = []
        for i in range(max_pages):
            res = self.trades(limit=page, offset=i * page)
            batch = res.get("trades", [])
            out += [t for t in batch if not t.get("is_open")]
            if len(batch) < page:
                break
        return out

    def start(self) -> Any:
        return self._post("start")

    def stopentry(self) -> Any:
        return self._post("stopentry")

    def reload_config(self) -> Any:
        return self._post("reload_config")

    def forceenter(self, pair: str, side: str, stake: float, tag: str) -> Any:
        return self._post("forceenter", {"pair": pair, "side": side, "stakeamount": stake,
                                         "entry_tag": tag, "ordertype": "market"})

    def forceexit(self, trade_id: int) -> Any:
        return self._post("forceexit", {"tradeid": trade_id, "ordertype": "market"})

    def forceexit_all(self) -> Any:
        return self._post("forceexit", {"tradeid": "all"})
