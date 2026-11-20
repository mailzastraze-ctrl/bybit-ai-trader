"""Open interest (OI) – how many contracts are open – as a new information source.

Price alone can't tell whether a move is carried by new positions (OI rising) or by
positions being closed (OI falling). Research downloads Bybit's OI history (public
`/v5/market/open-interest`, through the server relay on GitHub runners) into the data
directory; the live bot fetches recent OI through ccxt. Strategies see OI as of the start
of each candle (no look-ahead).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)
INTERVAL = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h", "1d": "1d"}


def symbol(pair: str) -> str:
    return pair.split(":")[0].replace("/", "")


def oi_path(datadir: Path, pair: str, tf: str) -> Path:
    base = pair
    for ch in ["/", " ", ".", "@", "$", "+", ":"]:
        base = base.replace(ch, "_")
    return Path(datadir) / "futures" / f"{base}-{tf}-oi.csv.gz"


def load(datadir: Path, pair: str, tf: str) -> pd.DataFrame | None:
    p = oi_path(datadir, pair, tf)
    if not p.exists():
        return None
    try:
        df = pd.read_csv(p)
        df["date"] = pd.to_datetime(df["date"], utc=True)
        return df
    except Exception:  # noqa: BLE001
        return None


def download(datadir: Path, pairs: list[str], tf: str, since: datetime, relay: str = "", token: str = "",
             session=None, sleep: float = 0.05, max_pages: int = 400) -> int:
    """Incremental OI history download (newest page first, back to `since`). Returns rows added."""
    import requests
    s = session or requests.Session()
    iv = INTERVAL.get(tf)
    if iv is None:
        return 0
    added = 0
    for pair in pairs:
        old = load(datadir, pair, tf)
        start_ms = int(since.timestamp() * 1000)
        if old is not None and not old.empty:
            start_ms = max(start_ms, int(old["date"].max().timestamp() * 1000) + 1)
        rows, cursor, end_ms = [], "", int(time.time() * 1000)
        for _ in range(max_pages):
            url = (f"https://api.bybit.com/v5/market/open-interest?category=linear&symbol={symbol(pair)}"
                   f"&intervalTime={iv}&startTime={start_ms}&endTime={end_ms}&limit=200" + (f"&cursor={cursor}" if cursor else ""))
            try:
                r = s.get((relay + url) if relay else url, headers={"X-Lab-Token": token} if relay else {}, timeout=30)
                js = r.json()
            except Exception as e:  # noqa: BLE001
                log.warning("OI %s: %s", pair, e)
                break
            if js.get("retCode") != 0:
                log.warning("OI %s: %s", pair, str(js)[:200])
                break
            res = js.get("result") or {}
            lst = res.get("list") or []
            rows += [(int(x["timestamp"]), float(x["openInterest"])) for x in lst]
            cursor = res.get("nextPageCursor") or ""
            if not lst or not cursor:
                break
            time.sleep(sleep)
        if not rows:
            continue
        new = pd.DataFrame(rows, columns=["ts", "oi"])
        new["date"] = pd.to_datetime(new["ts"], unit="ms", utc=True)
        new = new[["date", "oi"]]
        df = pd.concat([old, new]) if old is not None else new
        df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
        p = oi_path(datadir, pair, tf)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(p, index=False)
        added += len(new)
    log.info("open interest %s: %d new rows for %d pairs", tf, added, len(pairs))
    return added


def merge(dataframe: pd.DataFrame, oi: pd.DataFrame | None) -> pd.DataFrame:
    """OI as of each candle's start (backward as-of join): known before the candle closes."""
    if oi is None or oi.empty:
        dataframe["oi"] = float("nan")
        return dataframe
    o = oi[["date", "oi"]].sort_values("date")
    out = pd.merge_asof(dataframe[["date"]].sort_values("date"), o, on="date", direction="backward")
    dataframe["oi"] = out["oi"].to_numpy()
    return dataframe


def fetch_live(api, pair: str, tf: str = "1h", limit: int = 200) -> pd.DataFrame | None:
    """Recent OI through ccxt (live bot)."""
    try:
        rows = api.fetch_open_interest_history(pair, tf, limit=limit)
    except Exception as e:  # noqa: BLE001
        log.debug("live OI %s: %s", pair, e)
        return None
    out = [(datetime.fromtimestamp(int(r["timestamp"]) / 1000, timezone.utc),
            float(r.get("openInterestAmount") or r.get("baseVolume") or (r.get("info") or {}).get("openInterest") or "nan"))
           for r in rows or [] if r.get("timestamp")]
    if not out:
        return None
    return pd.DataFrame(out, columns=["date", "oi"]).sort_values("date")
