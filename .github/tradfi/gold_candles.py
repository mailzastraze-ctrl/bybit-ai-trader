"""Gold candles for the screener (TradFi lane, 2026-11-23).

Bybit's XAUUSDT perpetual has ~8 months of history; the Strategy Lab autopilot (swing mode)
needs >= 900 days. The proxy is PAXG (Pax Gold: one token = one fine troy ounce of LBMA gold,
traded 24/7 like the perpetual): Binance public data archive (data.binance.vision), fallback
Coinbase Exchange (PAXG-USD). Output: <out>/XAU_USDT_USDT__<tf>.json in the screener's format.

    python gold_candles.py --out DIR [--days 1230]
"""
import argparse
import io
import json
import sys
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

TFS = {"2h": 120, "4h": 240, "6h": 360, "12h": 720}
UA = {"User-Agent": "aitrader-research/1.0"}


def _get(url, **kw):
    for i in range(4):
        try:
            r = requests.get(url, timeout=30, headers=UA, **kw)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if i == 3:
                print(f"  {url}: {e}", file=sys.stderr)
                return None
            time.sleep(2 * (i + 1))


def binance(tf: str, start: datetime, end: datetime) -> pd.DataFrame:
    base = "https://data.binance.vision/data/spot"
    frames, m = [], datetime(start.year, start.month, 1, tzinfo=UTC)
    while m <= end:
        r = _get(f"{base}/monthly/klines/PAXGUSDT/{tf}/PAXGUSDT-{tf}-{m:%Y-%m}.zip")
        if r is None and m.year == end.year and m.month == end.month:  # current month: daily files
            d = m
            while d <= end:
                rd = _get(f"{base}/daily/klines/PAXGUSDT/{tf}/PAXGUSDT-{tf}-{d:%Y-%m-%d}.zip")
                if rd is not None:
                    frames.append(_csv(rd.content))
                d += timedelta(days=1)
        elif r is not None:
            frames.append(_csv(r.content))
        m = (m + timedelta(days=32)).replace(day=1)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames)


def _csv(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0]).decode()
    rows = [ln.split(",") for ln in raw.strip().splitlines() if ln and ln[0].isdigit()]
    df = pd.DataFrame([r[:6] for r in rows], columns=["t", "o", "h", "l", "c", "v"]).astype(float)
    df["t"] = df["t"].where(df["t"] < 1e14, df["t"] // 1000)  # microseconds since 2025 → ms
    return df


def coinbase(tf: str, start: datetime, end: datetime) -> pd.DataFrame:
    gran = 21600 if tf in ("6h", "12h") else 3600
    out, t = [], start
    while t < end:
        t2 = min(end, t + timedelta(seconds=gran * 290))
        r = _get("https://api.exchange.coinbase.com/products/PAXG-USD/candles",
                 params={"granularity": gran, "start": t.isoformat(), "end": t2.isoformat()})
        if r is not None:
            out += r.json()  # [time, low, high, open, close, volume]
        t = t2
        time.sleep(0.25)
    if not out:
        return pd.DataFrame()
    df = pd.DataFrame(out, columns=["t", "l", "h", "o", "c", "v"])
    df["t"] = df["t"] * 1000
    df = df.drop_duplicates("t").sort_values("t")
    idx = pd.to_datetime(df["t"], unit="ms", utc=True)
    g = df.set_index(idx).resample(f"{TFS[tf]}min", origin="epoch")
    df = pd.DataFrame({"o": g["o"].first(), "h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last(),
                       "v": g["v"].sum()}).dropna()
    df["t"] = (df.index.view("int64") // 1_000_000).astype(float)
    return df.reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--days", type=int, default=1230)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    end = datetime.now(UTC)
    start = end - timedelta(days=a.days)
    meta = {}
    for tf, mins in TFS.items():
        df, src = binance(tf, start, end), "binance PAXGUSDT spot"
        if len(df) < 900 * 1440 / mins:
            print(f"{tf}: binance gave {len(df)} bars – trying coinbase", file=sys.stderr)
            df, src = coinbase(tf, start, end), "coinbase PAXG-USD"
        df = df.drop_duplicates("t").sort_values("t")
        df = df[df["t"] >= start.timestamp() * 1000]
        df = df[df["t"] <= (end.timestamp() - mins * 60) * 1000]  # complete candles only
        if len(df) < 900 * 1440 / mins:
            print(f"{tf}: only {len(df)} bars – skipped", file=sys.stderr)
            continue
        (out / f"XAU_USDT_USDT__{tf}.json").write_text(json.dumps({
            "t": df["t"].astype("int64").tolist(), "o": df["o"].round(4).tolist(), "h": df["h"].round(4).tolist(),
            "l": df["l"].round(4).tolist(), "c": df["c"].round(4).tolist(), "v": df["v"].round(4).tolist()}))
        meta[tf] = {"bars": len(df), "source": src,
                    "from": datetime.fromtimestamp(df["t"].iloc[0] / 1000, UTC).isoformat(),
                    "to": datetime.fromtimestamp(df["t"].iloc[-1] / 1000, UTC).isoformat(),
                    "last_close": float(df["c"].iloc[-1])}
        print(f"{tf}: {len(df)} bars from {src}, {meta[tf]['from'][:10]} .. {meta[tf]['to'][:16]}, last {meta[tf]['last_close']}")
    (out.parent / "candles-meta.json").write_text(json.dumps(meta, indent=1))
    return 0 if meta else 1


if __name__ == "__main__":
    raise SystemExit(main())
