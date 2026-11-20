"""SQLite registry: experiments, strategies (candidates/sleeves), live trades, learnings,
events, heartbeats, equity snapshots, market scans. Shared by all aitrader processes."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from aitrader.util import iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY, created TEXT, family TEXT, spec TEXT, status TEXT,
    started TEXT, finished TEXT, error TEXT, result TEXT, progress TEXT
);
CREATE TABLE IF NOT EXISTS strategies (
    id TEXT PRIMARY KEY, experiment_id TEXT, family TEXT, params TEXT, pairs TEXT,
    sides TEXT, stage TEXT, score REAL, oos TEXT, gates TEXT, live TEXT,
    created TEXT, updated TEXT, stage_since TEXT, history TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS live_trades (
    trade_id INTEGER PRIMARY KEY, sleeve_id TEXT, pair TEXT, is_short INTEGER,
    open_date TEXT, close_date TEXT, open_rate REAL, close_rate REAL,
    profit_ratio REAL, profit_abs REAL, exit_reason TEXT, max_rate REAL, min_rate REAL,
    leverage REAL, stake_amount REAL, raw TEXT
);
CREATE TABLE IF NOT EXISTS learnings (
    id TEXT PRIMARY KEY, ts TEXT, scope TEXT, key TEXT, insight TEXT,
    adjustment TEXT, active INTEGER, expires TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, level TEXT, source TEXT,
    message TEXT, data TEXT
);
CREATE TABLE IF NOT EXISTS heartbeats (
    service TEXT PRIMARY KEY, ts TEXT, status TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS equity (
    ts TEXT PRIMARY KEY, equity REAL, free REAL, open_trades INTEGER
);
CREATE TABLE IF NOT EXISTS market (
    pair TEXT PRIMARY KEY, ts TEXT, data TEXT
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS ix_trades_sleeve ON live_trades(sleeve_id);
CREATE INDEX IF NOT EXISTS ix_strat_stage ON strategies(stage);
"""

JSON_COLS = {"spec", "result", "progress", "params", "pairs", "sides", "oos", "gates", "live",
             "history", "adjustment", "data", "raw", "detail"}


def _dec(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    out = {}
    for k in row.keys():
        v = row[k]
        if k in JSON_COLS and isinstance(v, str) and v[:1] in "[{\"":
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                pass
        out[k] = v
    return out


def _enc(v: Any) -> Any:
    return json.dumps(v, default=str) if isinstance(v, (dict, list)) else v


class Registry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.conn() as c:
            return [_dec(r) for r in c.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def upsert(self, table: str, row: dict, key: str = "id") -> None:
        cols = list(row)
        vals = tuple(_enc(row[c]) for c in cols)
        upd = ", ".join(f"{c}=excluded.{c}" for c in cols if c != key)
        sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
               f"ON CONFLICT({key}) DO UPDATE SET {upd}")
        with self.conn() as c:
            c.execute(sql, vals)

    def update(self, table: str, key_val: Any, fields: dict, key: str = "id") -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        with self.conn() as c:
            c.execute(f"UPDATE {table} SET {sets} WHERE {key}=?",
                      (*[_enc(v) for v in fields.values()], key_val))

    # ------------------------------------------------------------------ helpers
    def event(self, source: str, message: str, level: str = "info", data: dict | None = None):
        with self.conn() as c:
            c.execute("INSERT INTO events (ts, level, source, message, data) VALUES (?,?,?,?,?)",
                      (iso(), level, source, message, _enc(data or {})))

    def heartbeat(self, service: str, status: str = "ok", detail: dict | None = None):
        self.upsert("heartbeats", {"service": service, "ts": iso(), "status": status,
                                   "detail": detail or {}}, key="service")

    def kv_get(self, key: str, default: Any = None) -> Any:
        r = self.one("SELECT value FROM kv WHERE key=?", (key,))
        if r is None:
            return default
        try:
            return json.loads(r["value"])
        except (TypeError, json.JSONDecodeError):
            return r["value"]

    def kv_set(self, key: str, value: Any) -> None:
        self.upsert("kv", {"key": key, "value": json.dumps(value, default=str)}, key="key")

    # ------------------------------------------------------------------ experiments
    def new_experiment(self, family: str, spec: dict) -> str:
        eid = f"x{uuid.uuid4().hex[:10]}"
        self.upsert("experiments", {"id": eid, "created": iso(), "family": family, "spec": spec,
                                    "status": "queued", "progress": {}})
        return eid

    def strategies(self, stages: tuple[str, ...] | None = None) -> list[dict]:
        if stages:
            marks = ",".join("?" * len(stages))
            return self.q(f"SELECT * FROM strategies WHERE stage IN ({marks}) ORDER BY score DESC",
                          tuple(stages))
        return self.q("SELECT * FROM strategies ORDER BY updated DESC")

    def set_stage(self, sid: str, stage: str, reason: str) -> None:
        s = self.one("SELECT history, stage FROM strategies WHERE id=?", (sid,))
        if s is None:
            return
        hist = s.get("history") or []
        hist.append({"ts": iso(), "from": s.get("stage"), "to": stage, "reason": reason})
        self.update("strategies", sid, {"stage": stage, "stage_since": iso(), "updated": iso(),
                                        "history": hist})
        self.event("lifecycle", f"{sid}: {s.get('stage')} → {stage} ({reason})",
                   data={"strategy": sid, "to": stage})
