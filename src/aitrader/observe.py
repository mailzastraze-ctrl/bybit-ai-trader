"""Observation only – nothing here changes what the bot trades.

1. Signal journal. The bot appends one line per new entry signal of a strategy and per entry
   decision (`signals.jsonl` next to the manifest). Here it is summarised per strategy: how
   many signals, how many became positions, and why the others did not (coin held by another
   strategy, two signals on one candle, portfolio limits, pause). A backtest assumes every
   signal is traded; this shows how far the live book is from that.
2. Exposure. Open positions weighted by risk at their stops and by the correlation of the
   coins: ten shorts on coins that move together are about one bet, not ten.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import timedelta
from pathlib import Path

from aitrader.util import iso, parse_dt, utcnow

log = logging.getLogger(__name__)

# why a signal did not become a position (journal codes → owner-facing Russian)
MISSED_RU = {
    "pair_busy": "монета занята другой стратегией",
    "same_candle": "два сигнала на одной свече",
    "paused": "пауза / дневной стоп",
    "side_count": "лимит позиций в одну сторону",
    "explore_count": "лимит позиций разведки",
    "open_risk": "лимит общего риска",
    "side_risk": "лимит риска на сторону",
    "explore_risk": "лимит риска разведки",
    "not_entered": "не вошёл (лимит бота, размер, заявка)",
}
REJECTS = {"side_count", "explore_count", "open_risk", "side_risk", "explore_risk"}


# ---------------------------------------------------------------------- signal journal
def read_journal(path: Path, since=None) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict) or "s" not in r:
                continue
            if since is not None:
                t = parse_dt(r.get("ts"))
                if t is None or t < since:
                    continue
            out.append(r)
    return out


def summarize_signals(path: Path, days: int = 7, now=None, window_min: int = 30) -> dict:
    """Per strategy and in total: signals, executed, missed by reason (last `days` days).
    Each new signal gets one outcome: executed if the bot accepted it within `window_min`
    minutes, else the last refusal, else 'not entered'. An accepted entry without a new signal
    (a signal state that lasted until the coin was free) counts as a signal that was executed."""
    now = now or utcnow()
    rows = read_journal(path, now - timedelta(days=days))
    sigs, seen = [], set()
    for r in rows:
        if r.get("k") != "sig":
            continue
        key = (r["s"], r.get("p"), r.get("d"), r.get("c"))  # a restart may re-log a candle
        if key not in seen:
            seen.add(key)
            sigs.append(r)
    cfm: dict[tuple, list[tuple]] = {}
    for r in rows:
        if r.get("k") == "cfm" and parse_dt(r.get("ts")):
            cfm.setdefault((r["s"], r.get("p"), r.get("d")), []).append((parse_dt(r["ts"]), r.get("o")))
    per: dict[str, dict] = {}
    used: set[tuple] = set()

    def bucket(sid: str) -> dict:
        return per.setdefault(sid, {"signals": 0, "executed": 0, "missed": {}})

    for r in sigs:
        b = bucket(r["s"])
        b["signals"] += 1
        o = r.get("o") or "emitted"
        if o == "emitted":
            t0 = parse_dt(r.get("ts"))
            hits = [(t, x) for t, x in cfm.get((r["s"], r.get("p"), r.get("d")), [])
                    if t0 and t0 - timedelta(minutes=1) <= t <= t0 + timedelta(minutes=window_min)]
            used.update((r["s"], r.get("p"), r.get("d"), t) for t, _ in hits)
            outs = [x for _, x in sorted(hits)]
            o = "executed" if "accepted" in outs else next((x for x in reversed(outs) if x in REJECTS), "not_entered")
        if o == "executed":
            b["executed"] += 1
        else:
            b["missed"][o] = b["missed"].get(o, 0) + 1
    for (sid, p, d), evs in cfm.items():  # entries the bot made on a lasting signal state
        for t, x in evs:
            if x == "accepted" and (sid, p, d, t) not in used:
                b = bucket(sid)
                b["signals"] += 1
                b["executed"] += 1
    total = {"signals": 0, "executed": 0, "missed": {}}
    for b in per.values():
        total["signals"] += b["signals"]
        total["executed"] += b["executed"]
        for k, v in b["missed"].items():
            total["missed"][k] = total["missed"].get(k, 0) + v
    first = min((r.get("ts") for r in rows if r.get("ts")), default=None)
    return {"ts": iso(now), "days": days, "since": first, "total": total, "per_sleeve": per}


def trim_journal(path: Path, keep_days: int = 30, now=None) -> int:
    """Keep the last `keep_days` days (atomic rewrite); returns the number of lines kept."""
    if not path.exists():
        return 0
    rows = read_journal(path, (now or utcnow()) - timedelta(days=keep_days))
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")
    os.replace(tmp, path)
    return len(rows)


# ---------------------------------------------------------------------- exposure
def _risk(t: dict) -> float:
    """Money at risk to the stop (≥ 0)."""
    try:
        o, sl, stake = float(t.get("open_rate") or 0), float(t.get("stop_loss_abs") or 0), float(t.get("stake_amount") or 0)
    except (TypeError, ValueError):
        return 0.0
    if o <= 0 or sl <= 0 or stake <= 0:
        return 0.0
    frac = (sl - o) / o if t.get("is_short") else (o - sl) / o
    return max(frac, 0.0) * stake * float(t.get("leverage") or 1)


def _corr(a: list[float], b: list[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 24:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True)) / math.sqrt(va * vb)


def returns(closes: list[float]) -> list[float]:
    return [math.log(b / a) for a, b in zip(closes, closes[1:], strict=False) if a > 0 and b > 0]


def exposure(open_trades: list[dict], rets: dict[str, list[float]], equity: float | None = None) -> dict:
    """Effective number of independent bets = (Σ|risk|)² / (sᵀ C s), s = risk signed by side,
    C = correlation of the coins' hourly returns (unknown pairs: 0.6, a typical crypto level).
    n equal same-side positions with correlation ρ give n / (1 + (n−1)ρ); capped at n."""
    pos = [(t.get("pair"), -1.0 if t.get("is_short") else 1.0, _risk(t)) for t in open_trades or []]
    pos = [p for p in pos if p[0] and p[2] > 0]
    n = len(pos)
    long_r = sum(r for _, s, r in pos if s > 0)
    short_r = sum(r for _, s, r in pos if s < 0)
    out = {"positions": n, "long": sum(1 for p in pos if p[1] > 0), "short": sum(1 for p in pos if p[1] < 0),
           "risk_long": round(long_r, 2), "risk_short": round(short_r, 2), "eff_bets": None, "avg_corr": None,
           "one_side_share": round(max(long_r, short_r) / (long_r + short_r), 3) if long_r + short_r > 0 else None}
    if equity:
        out["risk_pct"] = round(100 * (long_r + short_r) / equity, 2)
    if not n:
        return out
    cache: dict[tuple, float] = {}
    pairs_c = []

    def c(a: str, b: str) -> float:
        if a == b:
            return 1.0
        k = tuple(sorted((a, b)))
        if k not in cache:
            v = _corr(rets.get(a) or [], rets.get(b) or [])
            cache[k] = 0.6 if v is None else v
            if v is not None:
                pairs_c.append(v)
        return cache[k]

    var = 0.0
    for pa, sa, ra in pos:
        for pb, sb, rb in pos:
            var += sa * ra * sb * rb * c(pa, pb)
    gross = sum(r for *_, r in pos)
    eff = n if var <= 1e-12 else min(float(n), gross * gross / var)
    out["eff_bets"] = round(eff, 2)
    if pairs_c:
        out["avg_corr"] = round(sum(pairs_c) / len(pairs_c), 2)
    return out


def hourly_returns(ft, pairs: list[str], limit: int = 1000) -> dict[str, list[float]]:
    """Hourly log returns of each coin from the bot's own 15m candles (local API, no egress)."""
    out = {}
    for p in sorted(set(pairs)):
        try:
            d = ft.pair_candles(p, "15m", limit) or {}
            cols = d.get("columns") or []
            i = cols.index("close")
            closes = [float(r[i]) for r in d.get("data") or [] if r[i] is not None]
        except Exception:  # noqa: BLE001 – a coin without candles just gets the default correlation
            continue
        out[p] = returns(closes[::4])  # every 4th 15m close = hourly
    return out


def journal_path(state_dir: Path) -> Path:
    return state_dir / "signals.jsonl"
