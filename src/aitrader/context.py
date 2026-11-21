"""Market context a human trader keeps in mind: which exchanges are open, which scheduled
events are close (US inflation, jobs report, Fed decisions), how the crowd is positioned and
how nervous the options market is.

Two uses, kept apart on purpose:
  * research genes (`session`, `no_weekend`, `event_guard` in families/base.py) – pure
    functions of the candle time and the official calendar, identical in backtests and live,
    so the walk-forward, the decoys and the forward test decide whether they help;
  * a live snapshot for the control room (Fear & Greed, Deribit DVOL, Bybit long/short
    accounts, Bybit delisting announcements). The only thing that acts on it is a safety
    rule: no new entries on a coin Bybit has announced to delist.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Regular trading hours (local time, Monday–Friday). Asia = Tokyo open → Hong Kong close.
MARKETS = [
    {"key": "tokyo", "name": "Токио", "tz": "Asia/Tokyo", "open": (9, 0), "close": (15, 30), "region": "asia"},
    {"key": "hongkong", "name": "Гонконг", "tz": "Asia/Hong_Kong", "open": (9, 30), "close": (16, 0), "region": "asia"},
    {"key": "frankfurt", "name": "Франкфурт", "tz": "Europe/Berlin", "open": (9, 0), "close": (17, 30), "region": "europe"},
    {"key": "london", "name": "Лондон", "tz": "Europe/London", "open": (8, 0), "close": (16, 30), "region": "europe"},
    {"key": "newyork", "name": "Нью-Йорк", "tz": "America/New_York", "open": (9, 30), "close": (16, 0), "region": "us"},
]
REGIONS = {1: ("asia",), 2: ("europe",), 3: ("us",), 4: ("europe", "us")}
EVENT_RU = {"CPI": "Инфляция США (CPI)", "NFP": "Рынок труда США (NFP)", "FOMC": "Решение ФРС по ставке"}
GUARD_HOURS = {1: 2.0, 2: 12.0}  # event_guard gene → no entries this many hours either side


# ------------------------------------------------------------------ calendar
@lru_cache(maxsize=1)
def macro_events() -> tuple[tuple[pd.Timestamp, str], ...]:
    """Official US release times (Fed, BLS) as UTC timestamps, sorted."""
    doc = json.loads((Path(__file__).parent / "data" / "macro_events.json").read_text())
    tz = ZoneInfo(doc.get("tz", "America/New_York"))
    out = []
    for e in doc["events"]:
        local = datetime.fromisoformat(f"{e['date']}T{e['time']}").replace(tzinfo=tz)
        out.append((pd.Timestamp(local).tz_convert("UTC"), e["kind"]))
    return tuple(sorted(out))


def _event_ns() -> np.ndarray:
    return np.array([t.value for t, _ in macro_events()], dtype=np.int64)


def near_event(times: pd.Series, hours: float) -> pd.Series:
    """True where a high-impact US release is within ±`hours` of the time."""
    ev = _event_ns()
    t = pd.to_datetime(times, utc=True).dt.as_unit("ns").astype("int64").to_numpy()
    idx = np.searchsorted(ev, t)
    lo = np.abs(t - ev[np.clip(idx - 1, 0, len(ev) - 1)])
    hi = np.abs(ev[np.clip(idx, 0, len(ev) - 1)] - t)
    return pd.Series(np.minimum(lo, hi) <= hours * 3600e9, index=times.index)


# ------------------------------------------------------------------ sessions
def region_open(times: pd.Series, region: str) -> pd.Series:
    """True while any regular market of the region is open (weekdays, local hours)."""
    t = pd.to_datetime(times, utc=True)
    out = pd.Series(False, index=times.index)
    for m in MARKETS:
        if m["region"] != region:
            continue
        loc = t.dt.tz_convert(m["tz"])
        minutes = loc.dt.hour * 60 + loc.dt.minute
        o, c = m["open"][0] * 60 + m["open"][1], m["close"][0] * 60 + m["close"][1]
        out |= (loc.dt.weekday < 5) & (minutes >= o) & (minutes < c)
    return out


def decision_times(df: pd.DataFrame) -> pd.Series:
    """When a candle's signal is acted on: at its close (open time + candle length)."""
    d = pd.to_datetime(df["date"], utc=True)
    step = d.diff().median() if len(d) > 2 else pd.Timedelta(hours=1)
    if pd.isna(step) or step <= pd.Timedelta(0):
        step = pd.Timedelta(hours=1)
    return d + step


def entry_filter(df: pd.DataFrame, session: int, no_weekend: int, event_guard: int) -> pd.Series | None:
    """Combined mask for the context genes (None when all are off)."""
    if not (session or no_weekend or event_guard) or "date" not in df:
        return None
    t = decision_times(df)
    ok = pd.Series(True, index=df.index)
    if session in REGIONS:
        on = pd.Series(False, index=df.index)
        for r in REGIONS[session]:
            on |= region_open(t, r)
        ok &= on
    if no_weekend:
        ok &= t.dt.weekday < 5
    if event_guard in GUARD_HOURS:
        ok &= ~near_event(t, GUARD_HOURS[event_guard])
    return ok


# ------------------------------------------------------------------ live snapshot
def markets_now(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    for m in MARKETS:
        tz = ZoneInfo(m["tz"])
        loc = now.astimezone(tz)
        o = loc.replace(hour=m["open"][0], minute=m["open"][1], second=0, microsecond=0)
        c = loc.replace(hour=m["close"][0], minute=m["close"][1], second=0, microsecond=0)
        is_open = loc.weekday() < 5 and o <= loc < c
        if is_open:
            nxt = c
        else:
            nxt = o if loc < o and loc.weekday() < 5 else o + timedelta(days=1)
            while nxt.weekday() >= 5:
                nxt += timedelta(days=1)
        out.append({"key": m["key"], "name": m["name"], "open": is_open, "local": loc.strftime("%H:%M"),
                    "next": nxt.astimezone(timezone.utc).isoformat(), "region": m["region"]})
    return out


def upcoming_events(now: datetime | None = None, days: int = 21) -> list[dict]:
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    end = now + pd.Timedelta(days=days)
    recent = now - pd.Timedelta(hours=3)
    return [{"kind": k, "name": EVENT_RU.get(k, k), "ts": t.isoformat()}
            for t, k in macro_events() if recent <= t <= end]


def _get(url: str, timeout: float = 6.0) -> dict:
    import requests
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "aitrader-context/1.0"})
    r.raise_for_status()
    return r.json()


def fetch_fear_greed(get=_get) -> dict | None:
    d = get("https://api.alternative.me/fng/?limit=8")
    rows = d.get("data") or []
    if not rows:
        return None
    return {"value": int(rows[0]["value"]), "label": rows[0].get("value_classification"),
            "week_ago": int(rows[-1]["value"]) if len(rows) > 1 else None}


def fetch_dvol(get=_get, currency: str = "BTC") -> dict | None:
    end = int(datetime.now(timezone.utc).timestamp() * 1000)
    start = end - 30 * 86400 * 1000
    d = get("https://www.deribit.com/api/v2/public/get_volatility_index_data"
            f"?currency={currency}&start_timestamp={start}&end_timestamp={end}&resolution=3600")
    rows = (d.get("result") or {}).get("data") or []
    closes = [float(r[4]) for r in rows if len(r) >= 5]
    if not closes:
        return None
    last = closes[-1]
    return {"value": round(last, 1), "pct30": round(100 * sum(c <= last for c in closes) / len(closes)),
            "min30": round(min(closes), 1), "max30": round(max(closes), 1)}


def fetch_long_short(get=_get, symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT")) -> dict:
    out = {}
    for sym in symbols:
        try:
            d = get(f"https://api.bybit.com/v5/market/account-ratio?category=linear&symbol={sym}&period=1h&limit=1")
            row = ((d.get("result") or {}).get("list") or [None])[0]
            if row:
                out[sym.replace("USDT", "")] = round(float(row["buyRatio"]) * 100, 1)
        except Exception as e:  # noqa: BLE001
            log.debug("long/short %s: %s", sym, e)
    return out


_SYM = re.compile(r"\b([A-Z0-9]{2,20})USDT\b")


def parse_delistings(rows: list[dict], now: datetime | None = None, days: int = 45) -> list[dict]:
    """Bybit announcements → perpetual pairs announced for delisting in the last `days`."""
    now = now or datetime.now(timezone.utc)
    out: dict[str, dict] = {}
    for r in rows:
        title = str(r.get("title") or "")
        if "delist" not in title.lower():
            continue
        ts = r.get("dateTimestamp") or r.get("publishTime") or 0
        when = datetime.fromtimestamp(int(ts) / 1000, timezone.utc) if ts else now
        if now - when > timedelta(days=days):
            continue
        if not re.search(r"perpetual|contract|derivative|futures", title, re.I):
            continue
        for base in _SYM.findall(title):
            out.setdefault(f"{base}/USDT:USDT", {"pair": f"{base}/USDT:USDT", "title": title[:160], "ts": when.isoformat()})
    return list(out.values())


def fetch_delistings(get=_get) -> list[dict]:
    d = get("https://api.bybit.com/v5/announcements/index?locale=en-US&limit=50")
    return parse_delistings((d.get("result") or {}).get("list") or [])


def refresh(reg, get=_get) -> dict:
    """Live snapshot (every ~15 min from the manager). Each source is optional: a failure
    keeps the previous value and never blocks the manager loop."""
    prev = reg.kv_get("context") or {}
    snap = dict(prev)
    for key, fn in (("fear_greed", fetch_fear_greed), ("dvol", fetch_dvol), ("long_short", fetch_long_short),
                    ("delistings", fetch_delistings)):
        try:
            v = fn(get)
            if v is not None:
                snap[key] = v
                snap.setdefault("ok", {})[key] = datetime.now(timezone.utc).isoformat()
        except Exception as e:  # noqa: BLE001 – context is optional
            log.info("context source %s unavailable: %s", key, e)
    snap["ts"] = datetime.now(timezone.utc).isoformat()
    reg.kv_set("context", snap)
    # hourly history of the numbers (kept 90 days) – evidence for later research
    hist = reg.kv_get("context_hist") or []
    hour = snap["ts"][:13]
    if not hist or hist[-1].get("h") != hour:
        hist.append({"h": hour, "fg": (snap.get("fear_greed") or {}).get("value"), "dvol": (snap.get("dvol") or {}).get("value"),
                     "ls": snap.get("long_short") or {}})
        reg.kv_set("context_hist", hist[-24 * 90:])
    return snap


def delisted_pairs(reg) -> set[str]:
    return {d["pair"] for d in ((reg.kv_get("context") or {}).get("delistings") or [])}


def snapshot(reg, now: datetime | None = None) -> dict:
    """Everything the control room shows in «Мир сейчас»."""
    live = reg.kv_get("context") or {}
    return {"now": (now or datetime.now(timezone.utc)).isoformat(), "markets": markets_now(now),
            "events": upcoming_events(now), **{k: live.get(k) for k in ("fear_greed", "dvol", "long_short", "delistings", "ts")}}
