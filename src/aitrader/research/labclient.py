"""Research-lab client (runs on GitHub Actions): talks to the live server's sync API with
short-lived GitHub OIDC tokens. Every call is best-effort – research never fails because
the server is unreachable; results are also committed to the repository."""

from __future__ import annotations

import logging
import os
import threading
import time

import requests

log = logging.getLogger(__name__)
AUDIENCE = "aitrader-lab"


class LabClient:
    def __init__(self, server: str | None, run_id: str = ""):
        self.server = (server or "").rstrip("/")
        self.run_id = run_id
        self._tok: tuple[float, str] | None = None
        self._lock = threading.Lock()
        self._last_progress = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.server and os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"))

    def token(self) -> str:
        with self._lock:
            if self._tok and time.time() - self._tok[0] < 240:
                return self._tok[1]
            url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
            r = requests.get(url + ("&" if "?" in url else "?") + f"audience={AUDIENCE}",
                             headers={"Authorization": "bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]},
                             timeout=20)
            r.raise_for_status()
            self._tok = (time.time(), r.json()["value"])
            return self._tok[1]

    def _call(self, method: str, path: str, payload: dict | None = None, timeout: float = 30):
        if not self.enabled:
            return None
        for attempt in range(3):
            try:
                r = requests.request(method, self.server + path, json=payload, timeout=timeout,
                                     headers={"Authorization": "Bearer " + self.token()})
                if r.status_code == 200:
                    return r.json()
                log.warning("lab %s %s → HTTP %s %s", method, path, r.status_code, r.text[:200])
                if r.status_code in (401, 403, 404):
                    return None
            except requests.RequestException as e:
                log.warning("lab %s %s failed: %s", method, path, e)
            time.sleep(3 * (attempt + 1))
        return None

    def state(self) -> dict:
        return self._call("GET", "/api/lab/state") or {}

    def run_event(self, kind: str, **extra) -> None:
        self._call("POST", "/api/lab/run", {"kind": kind, "run_id": self.run_id, **extra})

    def progress(self, experiment: str, stage: str, force: bool = True, **extra) -> None:
        now = time.time()
        if not force and now - self._last_progress < 20:
            return
        self._last_progress = now
        self._call("POST", "/api/lab/progress", {"experiment": experiment, "stage": stage,
                                                 "run_id": self.run_id, **extra}, timeout=15)

    def import_batch(self, data: dict) -> dict | None:
        return self._call("POST", "/api/lab/import", data, timeout=120)
