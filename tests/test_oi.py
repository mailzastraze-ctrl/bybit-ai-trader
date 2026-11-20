"""Open interest: incremental download through the relay, as-of merge without look-ahead."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd

from aitrader import oi


class FakeSession:
    """Bybit /v5/market/open-interest: newest first, 200 per page, cursor paging."""

    def __init__(self, n=450):
        t0 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        self.rows = [{"timestamp": str(t0 + i * 3_600_000), "openInterest": str(1000 + i)} for i in range(n)][::-1]
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        q = dict(x.split("=", 1) for x in url.split("?", 1)[1].split("&"))
        rows = [r for r in self.rows if int(q["startTime"]) <= int(r["timestamp"]) <= int(q["endTime"])]
        i = int(q.get("cursor") or 0)
        page = rows[i:i + 200]
        nxt = str(i + 200) if i + 200 < len(rows) else ""
        return SimpleNamespace(json=lambda: {"retCode": 0, "result": {"list": page, "nextPageCursor": nxt}})


def test_download_pages_through_the_relay_and_is_incremental(tmp_path):
    sess = FakeSession()
    since = datetime(2025, 12, 1, tzinfo=timezone.utc)
    assert oi.download(tmp_path, ["SOL/USDT:USDT"], "1h", since, "https://srv/relay/", "tok", session=sess, sleep=0) == 450
    url, headers = sess.calls[0]
    assert url.startswith("https://srv/relay/https://api.bybit.com/v5/market/open-interest?category=linear&symbol=SOLUSDT")
    assert headers == {"X-Lab-Token": "tok"} and len(sess.calls) == 3
    df = oi.load(tmp_path, "SOL/USDT:USDT", "1h")
    assert len(df) == 450 and df["date"].is_monotonic_increasing and df["oi"].iloc[-1] == 1449
    sess2 = FakeSession(460)
    assert oi.download(tmp_path, ["SOL/USDT:USDT"], "1h", since, session=sess2, sleep=0) == 10  # only the new hours
    assert len(oi.load(tmp_path, "SOL/USDT:USDT", "1h")) == 460


def test_merge_uses_oi_known_at_candle_start():
    o = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=5, freq="1h", tz="UTC"), "oi": [1.0, 2, 3, 4, 5]})
    candles = pd.DataFrame({"date": pd.date_range("2026-01-01 00:00", periods=8, freq="30min", tz="UTC")})
    out = oi.merge(candles, o)
    assert out["oi"].tolist() == [1, 1, 2, 2, 3, 3, 4, 4]  # never a value stamped after the candle start
    assert oi.merge(candles.copy(), None)["oi"].isna().all()


def test_backtest_strategy_reads_downloaded_oi(tmp_path):
    from FamOiFlow import FamOiFlow
    from helpers import ohlcv
    df = ohlcv(1200, seed=3)
    o = pd.DataFrame({"date": df["date"] - timedelta(minutes=0), "oi": range(1200)})
    p = oi.oi_path(tmp_path, "BTC/USDT:USDT", "1h")
    p.parent.mkdir(parents=True)
    o.to_csv(p, index=False)
    st = FamOiFlow({"aitrader": {}, "runmode": "backtest", "datadir": str(tmp_path), "exchange": {"demo_trading": True}})
    st.bot_start()
    out = st.populate_indicators(df.copy(), {"pair": "BTC/USDT:USDT"})
    assert out["oi"].tolist() == list(range(1200))
