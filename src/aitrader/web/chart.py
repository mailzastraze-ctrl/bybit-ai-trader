"""One candle chart for every page (owner, 23.11: "everywhere proper charts with candles and
trades, on history too"): Bybit candles of any coin and timeframe, back as far as the history
goes, and every trade on that coin – the demo trades of this bot and the strategies' trades
from the lab's backtest on history. Read-only; nothing here changes trading.

Candles come from Bybit's public market data (the same prices the demo trades on), not from the
bot, which keeps only ~10 days of its own 15m candles."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

from aitrader.registry import Registry
from aitrader.util import iso, parse_dt
from aitrader.web import names

BYBIT = "https://api.bybit.com/v5/market/kline"
INTERVAL = {"15m": "15", "30m": "30", "1h": "60", "2h": "120", "4h": "240", "6h": "360", "12h": "720", "1d": "D"}
TF_MS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "6h": 21_600_000,
         "12h": 43_200_000, "1d": 86_400_000}
MAX_LIMIT = 1000          # Bybit's page size
LIVE_TTL_S = 30           # the newest page changes with every candle
HIST_TTL_S = 6 * 3600     # closed history never changes
CACHE_MAX = 400
HISTORY_KEY = "history_trades"  # kv: strategy id → the lab's backtest trades per coin (lab.apply_import)

_cache: dict[tuple, tuple[float, list]] = {}
_lock = threading.Lock()


def symbol(pair: str) -> str:
    """'BTC/USDT:USDT' → 'BTCUSDT' (also '1000PEPE/USDT:USDT' → '1000PEPEUSDT')."""
    base, _, rest = str(pair).partition("/")
    quote = rest.split(":")[0] or "USDT"
    return f"{base}{quote}".upper()


def parse_kline(payload: dict | None) -> list[list]:
    """Bybit kline page (newest first) → [[ms, open, high, low, close, volume], ...] oldest first."""
    rows = (((payload or {}).get("result") or {}).get("list")) or []
    out = []
    for r in rows:
        try:
            out.append([int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
        except (TypeError, ValueError, IndexError):
            continue
    out.sort(key=lambda r: r[0])
    return out


def _fetch(sym: str, interval: str, end_ms: int | None, limit: int) -> list[list]:
    import requests
    params = {"category": "linear", "symbol": sym, "interval": interval, "limit": limit}
    if end_ms:
        params["end"] = end_ms
    r = requests.get(BYBIT, params=params, timeout=10, headers={"User-Agent": "aitrader-chart"})
    r.raise_for_status()
    data = r.json()
    if data.get("retCode") not in (0, None):
        raise RuntimeError(f"bybit: {data.get('retMsg')}")
    return parse_kline(data)


def candles(pair: str, tf: str = "1h", end_ms: int | None = None, limit: int = 500, fetch=None) -> dict:
    """Up to `limit` candles ending at `end_ms` (default: now). Older pages are immutable and kept
    for hours; the newest page for 30 s. `fetch` is injectable for tests and previews."""
    if tf not in INTERVAL:
        raise ValueError(f"timeframe {tf} not supported")
    limit = max(10, min(int(limit), MAX_LIMIT))
    now = int(time.time() * 1000)
    live = end_ms is None or end_ms >= now - TF_MS[tf]
    # bucket the end so neighbouring requests share a cache entry
    key = (symbol(pair), tf, None if live else int(end_ms) // TF_MS[tf], limit)
    with _lock:
        hit = _cache.get(key)
    if hit and time.time() - hit[0] < (LIVE_TTL_S if live else HIST_TTL_S):
        rows = hit[1]
    else:
        rows = (fetch or _fetch)(symbol(pair), INTERVAL[tf], None if live else int(end_ms), limit)
        with _lock:
            if len(_cache) >= CACHE_MAX:
                for k in sorted(_cache, key=lambda k: _cache[k][0])[: CACHE_MAX // 4]:
                    _cache.pop(k, None)
            _cache[key] = (time.time(), rows)
    return {"pair": pair, "timeframe": tf, "candles": rows, "more": len(rows) >= limit}


# ---------------------------------------------------------------------------- trades on a coin
def _ms(v) -> int | None:
    d = parse_dt(v) if v is not None else None
    return int(d.timestamp() * 1000) if d else None


def demo_trades(reg: Registry, pair: str, status: list[dict] | None = None, since: str | None = None) -> list[dict]:
    """Every demo trade on the coin (closed from the registry, open from the bot), oldest first."""
    out = []
    for t in reg.q("SELECT trade_id, sleeve_id, is_short, open_date, close_date, open_rate, close_rate, profit_abs, "
                   "profit_ratio, exit_reason FROM live_trades WHERE pair=? ORDER BY open_date", (pair,)):
        if str(t.get("sleeve_id") or "").startswith("exec-test"):
            continue
        out.append({"id": t.get("trade_id"), "sid": t.get("sleeve_id"), "short": bool(t.get("is_short")),
                    "t0": _ms(t.get("open_date")), "t1": _ms(t.get("close_date")), "p0": t.get("open_rate"),
                    "p1": t.get("close_rate"), "pnl": t.get("profit_abs"), "ret": t.get("profit_ratio"),
                    "why": t.get("exit_reason"), "open": False})
    for t in status or []:
        if not isinstance(t, dict) or t.get("pair") != pair or str(t.get("enter_tag") or "").startswith("exec-test"):
            continue
        if float(t.get("amount") or 0) <= 0:
            continue  # an entry order still working: no position yet
        out.append({"id": t.get("trade_id"), "sid": t.get("enter_tag"), "short": bool(t.get("is_short")),
                    "t0": _ms(t.get("open_date")), "t1": None, "p0": t.get("open_rate"), "p1": t.get("current_rate"),
                    "pnl": t.get("profit_abs"), "ret": t.get("profit_ratio"), "why": None, "open": True,
                    "stop": t.get("stop_loss_abs")})
    if since:
        s = _ms(since) or 0
        for t in out:
            t["before_experiment"] = bool(t["t0"] and t["t0"] < s)
    return out


def history_trades(reg: Registry, pair: str, sids: list[str]) -> dict:
    """The lab's backtest trades of these strategies on the coin (`history_trades`): what each
    strategy, with its frozen parameters, would have done on this coin's history."""
    store = reg.kv_get(HISTORY_KEY) or {}
    out = {}
    for sid in sids:
        h = store.get(sid) or {}
        rows = (h.get("pairs") or {}).get(pair) or []
        out[sid] = {"from": h.get("from"), "to": h.get("to"), "ts": h.get("ts"),
                    "trades": [{"sid": sid, "short": bool(r[2]), "t0": r[0], "t1": r[1], "p0": r[3], "p1": r[4],
                                "ret": r[5], "why": r[6] if len(r) > 6 else None, "hist": True} for r in rows]}
    return out


def coin_strategies(reg: Registry, pair: str, sleeve_pairs: dict[str, list[str]] | None = None) -> list[str]:
    """The strategies that trade this coin now: its desk strategies first, then the guests."""
    from aitrader import desks as D
    d = ((reg.kv_get("desks") or {}).get("coins") or {}).get(pair) or {}
    own = [x["strategy"] for x in D.picks(d)]
    guests = sorted(sid for sid, ps in (sleeve_pairs or {}).items() if pair in (ps or []) and sid not in own)
    return own + guests


def coin_trades(reg: Registry, pair: str, status: list[dict] | None, sleeve_pairs: dict[str, list[str]] | None,
                extra: list[str] | None = None) -> dict:
    """Everything the chart draws on one coin, with each strategy's code and method."""
    sids = coin_strategies(reg, pair, sleeve_pairs)
    for s in extra or []:
        if s and s not in sids:
            sids.append(s)
    since = (reg.kv_get("desks") or {}).get("created")
    demo = demo_trades(reg, pair, status, since)
    nm = names.names(reg)
    every = sorted(set(sids) | {t["sid"] for t in demo if t.get("sid")})
    return {"pair": pair, "experiment_since": since, "strategies": sids,
            "labels": {s: {"code": (nm.get(s) or {}).get("code"), "method": (nm.get(s) or {}).get("method") or s} for s in every},
            "demo": demo, "history": history_trades(reg, pair, sids)}


def store_history(reg: Registry, results: list[dict] | None) -> int:
    """Lab import: keep each strategy's backtest trades per coin (`shadow.history`), replacing
    its previous record. Compact rows: [open ms, close ms, short, open rate, close rate, return, reason]."""
    if not results:
        return 0
    store = reg.kv_get(HISTORY_KEY) or {}
    n = 0
    for r in results:
        if not isinstance(r, dict) or not r.get("id") or not r.get("ok"):
            continue
        store[r["id"]] = {"ts": iso(datetime.now(UTC)), "from": r.get("from"), "to": r.get("to"),
                          "params_key": r.get("params_key"), "pairs": r.get("pairs") or {}}
        n += 1
    if n:
        reg.kv_set(HISTORY_KEY, store)
    return n
