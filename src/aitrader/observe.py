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

# ---------------------------------------------------------------------- post-mortem ("работа над ошибками")
STOP_EXITS = ("managed_stop", "stoploss_on_exchange", "stop_loss", "stoploss", "trailing_stop_loss", "liquidation")
PM_KEEP_DAYS = 30   # results kept
PM_WINDOW_DAYS = 10  # the bot keeps ~10 days of 15m candles: a trade is judged on what followed within it


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def judge_exit(trade: dict, params: dict, candles: list[list], now=None) -> dict | None:
    """What happened after one closed trade, in R (its initial risk):
    - stop: the planned stop. 'reversed' if price then reached the target (or +1 R without
      one) before going another 0.5 R against – a wider stop would have won; 'confirmed' if it
      went the 0.5 R against first.
    - protective / rule (stop moved to break-even/profit, exit signal, time exit, locks): the
      trade is replayed with its original stop and target – `hold_r` – and the money the early
      exit saved (> 0) or cost (< 0): `saved_usd` = (exit − hold) × risk.
    - take_profit: how much further price went in the next 3 days (`further_r`).
    Candles: [[ts_ms, open, high, low, close], ...]; 'open' while neither level has been hit."""
    raw = trade.get("raw") if isinstance(trade.get("raw"), dict) else {}
    o, isl = _f(trade.get("open_rate")), _f(raw.get("initial_stop_loss_abs"))
    c, amt = _f(trade.get("close_rate")), _f(raw.get("amount"))
    closed = parse_dt(trade.get("close_date"))
    if not o or not isl or not c or not closed or abs(o - isl) <= 0:
        return None
    short = bool(trade.get("is_short"))
    sgn = -1.0 if short else 1.0
    risk = abs(o - isl)
    r_exit = sgn * (c - o) / risk
    reason = str(trade.get("exit_reason") or "")
    p = params or {}
    rr = _f(p.get("tp_rr")) or 2.0
    if int(p.get("exit_mode") or 0) == 1:
        rr = _f(p.get("lab_tp")) or 0.0  # Strategy Lab: no target when 0
    tp = o + sgn * rr * risk if rr > 0 else None
    if reason == "take_profit":
        kind = "take_profit"
    elif reason in STOP_EXITS and r_exit <= -0.8:
        kind = "stop"
    elif reason in STOP_EXITS:
        kind = "protective"  # the stop had been moved (break-even, profit lock, trail, market shock)
    else:
        kind = "rule"        # exit signal, time exit, event/profit locks
    out = {"trade_id": trade.get("trade_id"), "sleeve": trade.get("sleeve_id"), "pair": trade.get("pair"),
           "kind": kind, "reason": reason, "r_exit": round(r_exit, 2), "close_date": trade.get("close_date"),
           "status": "open"}
    usd_per_r = risk * amt if amt else None
    if kind == "stop" and r_exit < -1.05 and usd_per_r:  # filled beyond the stop (gap, market stop, restart)
        out["slip_usd"] = round((-1.0 - r_exit) * usd_per_r, 2)
    t0 = closed.timestamp() * 1000
    after = [x for x in candles or [] if _f(x[0]) is not None and float(x[0]) > t0]
    if not after:
        return out
    if kind == "take_profit":
        horizon = t0 + 3 * 86400e3
        best = max((sgn * ((x[3] if short else x[2]) - o) / risk for x in after if float(x[0]) <= horizon), default=None)
        if best is not None:
            out["further_r"] = round(max(best - r_exit, 0.0), 2)
            out["status"] = "done" if after[-1][0] >= horizon else "open"
        return out
    if kind == "stop":
        target = tp if tp is not None else o + sgn * risk
        worse = isl + sgn * -0.5 * risk  # another half R against
        for x in after:
            hi, lo = float(x[2]), float(x[3])
            hit_worse = hi >= worse if short else lo <= worse
            hit_target = lo <= target if short else hi >= target
            if hit_worse:  # conservative: a candle touching both counts as the stop being right
                out["status"] = "confirmed"
                return out
            if hit_target:
                out["status"] = "reversed"
                return out
        return out
    # protective / rule: replay with the original stop and target
    hold = None
    for x in after:
        hi, lo = float(x[2]), float(x[3])
        if (hi >= isl) if short else (lo <= isl):
            hold = -1.0
            break
        if tp is not None and ((lo <= tp) if short else (hi >= tp)):
            hold = rr
            break
    if hold is None:
        last = float(after[-1][4])
        out["hold_r_now"] = round(sgn * (last - o) / risk, 2)
        return out
    out["status"] = "done"
    out["hold_r"] = round(hold, 2)
    if usd_per_r:
        out["saved_usd"] = round((r_exit - hold) * usd_per_r, 2)
    return out


def summarize_postmortem(results: list[dict]) -> dict:
    """Totals over the kept results: is the early-exit logic paying for itself, are stops too
    tight, is the target too close? Small numbers are anecdotes – the learner needs ≥ 30."""
    s = {"stop": {"n": 0, "reversed": 0, "confirmed": 0, "open": 0, "slipped": 0, "slip_usd": 0.0},
         "protective": {"n": 0, "done": 0, "saved_usd": 0.0, "better": 0, "worse": 0, "open": 0},
         "rule": {"n": 0, "done": 0, "saved_usd": 0.0, "better": 0, "worse": 0, "open": 0},
         "take_profit": {"n": 0, "done": 0, "further_r_sum": 0.0}}
    for r in results:
        k = r.get("kind")
        if k not in s:
            continue
        b = s[k]
        b["n"] += 1
        st = r.get("status")
        if k == "stop":
            b[st if st in ("reversed", "confirmed") else "open"] += 1
            if r.get("slip_usd"):
                b["slipped"] += 1
                b["slip_usd"] = round(b["slip_usd"] + r["slip_usd"], 2)
        elif k == "take_profit":
            if r.get("further_r") is not None:
                b["done"] += 1
                b["further_r_sum"] += r["further_r"]
        elif st == "done":
            b["done"] += 1
            v = r.get("saved_usd") or 0.0
            b["saved_usd"] += v
            b["better" if v > 0 else "worse"] += 1 if v != 0 else 0
        else:
            b["open"] += 1
    tp = s["take_profit"]
    tp["avg_further_r"] = round(tp.pop("further_r_sum") / tp["done"], 2) if tp["done"] else None
    for k in ("protective", "rule"):
        s[k]["saved_usd"] = round(s[k]["saved_usd"], 2)
    return s


def postmortem(reg, ft, now=None) -> dict:
    """Judge trades closed in the last PM_WINDOW_DAYS days (finished verdicts are kept for
    PM_KEEP_DAYS days) → kv 'postmortem'."""
    now = now or utcnow()
    prev = (reg.kv_get("postmortem") or {}).get("trades") or {}
    keep = {k: v for k, v in prev.items() if (parse_dt(v.get("close_date")) or now) >= now - timedelta(days=PM_KEEP_DAYS)}
    rows = reg.q("SELECT trade_id, sleeve_id, pair, is_short, open_rate, close_rate, close_date, exit_reason, profit_abs, raw "
                 "FROM live_trades WHERE close_date >= ?", (iso(now - timedelta(days=PM_WINDOW_DAYS)),))
    params = {r["id"]: r.get("params") or {} for r in reg.q("SELECT id, params FROM strategies")}
    todo = [r for r in rows if (keep.get(str(r["trade_id"])) or {}).get("status") in (None, "open")]
    candles: dict[str, list] = {}
    for p in sorted({r["pair"] for r in todo}):
        try:
            d = ft.pair_candles(p, "15m", 1000) or {}
            cols = d.get("columns") or []
            ts = cols.index("__date_ts") if "__date_ts" in cols else None
            ix = [cols.index(k) for k in ("open", "high", "low", "close")]
            rows_ = []
            for x in d.get("data") or []:
                t = _f(x[ts]) if ts is not None else (parse_dt(x[cols.index("date")]).timestamp() * 1000)
                vals = [_f(x[i]) for i in ix]
                if t is not None and all(v is not None for v in vals):
                    rows_.append([t, *vals])
            candles[p] = rows_
        except Exception:  # noqa: BLE001 – a coin the bot no longer follows stays 'open'
            candles[p] = []
    for r in todo:
        res = judge_exit(r, params.get(r["sleeve_id"]) or {}, candles.get(r["pair"]) or [], now)
        if res:
            keep[str(r["trade_id"])] = res
    out = {"ts": iso(now), "trades": keep, "summary": summarize_postmortem(list(keep.values()))}
    reg.kv_set("postmortem", out)
    return out


# ---------------------------------------------------------------------------- health line
STOP_GRACE_S = 180  # a fresh position gets its exchange stop within a minute or two
ENTRY_STUCK_S = 15 * 60  # config/trade.json unfilledtimeout entry 12 min + the stop grace


def _has_exchange_stop(t: dict) -> bool:
    return any(o.get("ft_order_side") == "stoploss" and o.get("status") in ("open", "new", None)
               for o in t.get("orders") or [])


def _entry_state(t: dict) -> tuple[bool, object]:
    """(entry working with nothing filled, time the position began). A limit entry can wait up to 12
    minutes (unfilledtimeout) and Freqtrade places the exchange stop once it has filled, so while
    nothing is filled there is no position to protect (audit 22.11, A2). Any filled amount is a
    position: the grace runs from the first fill. Without Freqtrade's entry flags: as before."""
    entries = [o for o in t.get("orders") or [] if o.get("ft_is_entry")]
    filled = [o for o in entries if (o.get("filled") or 0) > 0]
    # only an entry with nothing filled yet is "no position": a partial fill is a position to protect
    working = not filled and any(o.get("is_open") or o.get("status") in ("open", "new") for o in entries)
    fills = [parse_dt(o.get("order_filled_date") or o.get("order_filled_timestamp") or o.get("order_date")
                      or o.get("order_timestamp")) for o in filled]
    began = parse_dt(t.get("open_fill_date") or t.get("open_fill_timestamp")) or \
        min((f for f in fills if f is not None), default=None) or parse_dt(t.get("open_date") or t.get("open_timestamp"))
    return working, began


def health(open_trades: list[dict], equity: float | None, now=None) -> dict:
    """Positions, how many lack a stop order on the exchange (after a short grace period), and
    the money at risk to the stops as % of equity. Observation only."""
    now = now or utcnow()
    bare = []
    for t in open_trades or []:
        od = parse_dt(t.get("open_date") or t.get("open_timestamp"))
        working, began = _entry_state(t)
        if working and not (od is not None and (now - od).total_seconds() > ENTRY_STUCK_S):
            continue  # the entry order is still working: no position yet (or a stuck one after 15 min)
        young = began is not None and (now - began).total_seconds() < STOP_GRACE_S
        if not young and not _has_exchange_stop(t):
            bare.append(t.get("pair"))
    risk = sum(_risk(t) for t in open_trades or [])
    return {"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "positions": len(open_trades or []), "no_exchange_stop": bare,
            "risk_pct": round(100 * risk / equity, 2) if equity else None}


def red_flags(reg, now=None) -> list[str]:
    """The owner's red flags (PLAN §5) from what the registry already knows."""
    now = now or utcnow()
    out = []
    hb = {h["service"]: h for h in reg.q("SELECT service, status, ts FROM heartbeats")}
    m = hb.get("manager")
    if m is None or m.get("status") != "ok":
        out.append(f"manager {m.get('status') if m else 'missing'}")
    elif (age := parse_dt(m.get("ts"))) is not None and (now - age).total_seconds() > 900:
        out.append("manager silent > 15 min")
    h = reg.kv_get("health") or {}
    if h.get("no_exchange_stop"):
        out.append("no exchange stop: " + ",".join(str(p).split("/")[0] for p in h["no_exchange_stop"]))
    lab = reg.kv_get("lab") or {}
    li = parse_dt(lab.get("last_import"))
    if li is None or (now - li).total_seconds() > 24 * 3600:
        out.append("lab import > 24h")
    if lab.get("last_batch_total") and lab.get("last_batch_failed", 0) > 0.2 * lab["last_batch_total"]:
        out.append(f"lab failures {lab['last_batch_failed']}/{lab['last_batch_total']}")
    fw = reg.kv_get("forward") or {}
    fa = parse_dt(fw.get("last_accepted") or fw.get("ts"))  # imports can be fresh while the forward test stalls
    if fa is not None and (now - fa).total_seconds() > 24 * 3600:
        out.append("forward > 24h")
    try:
        from aitrader import forward3
        out += forward3.status_flags(reg, now)  # the v3 recording can stop while v2 still arrives
    except Exception:  # noqa: BLE001
        out.append("v3 status unreadable")
    d = reg.kv_get("disk") or {}
    if d.get("free_pct") is not None and d["free_pct"] < 0.2:
        out.append(f"disk free {d['free_pct']:.0%}")
    left = (d.get("growth") or {}).get("days_to_full")
    if left is not None and left < 14:
        out.append(f"disk full in ~{left:.0f} d")
    if reg.kv_get("kill_since"):
        out.append("kill-switch")
    day = reg.kv_get("day_open") or {}
    if day.get("hit") and day.get("day") == now.strftime("%Y-%m-%d"):
        out.append("daily loss limit")
    p = reg.kv_get("parity") or {}
    if p.get("alarm") and p.get("like_for_like"):
        out.append("PARITY ALARM")
    return out


def status_line(reg, now=None) -> str:
    """Compact health for the supervisor's STATUS log line (readable without passwords)."""
    now = now or utcnow()
    h, d, lab, fw = (reg.kv_get(k) or {} for k in ("health", "disk", "lab", "forward"))
    li = parse_dt(lab.get("last_import"))
    imp = f"{(now - li).total_seconds() / 3600:.1f}h" if li else "never"
    g = d.get("growth") or {}
    disk = (f"{d.get('free_pct', 0):.0%} free" if d.get("free_pct") is not None else "?") + \
        (f", {g['mb_per_day']:+.0f} MB/d, full in {g['days_to_full']:.0f} d" if g.get("days_to_full") else "")
    bench = (fw.get("benchmark") or {}).get("trades")
    vs = (fw.get("vs_benchmark") or {}).get("p_top_better")
    v3 = fw.get("v3") or {}
    v3st = v3.get("status") or {}
    ok = parse_dt(v3st.get("last_ok"))
    age = f"{(now - ok).total_seconds() / 3600:.1f}h" if ok else "never"
    part = f", failed {v3st['last_failures']}" if v3st.get("last_failures") else ""  # this import only
    v3s = ("error" if v3.get("error") else
           f"records {v3.get('records', 0)}, q1 {v3.get('q1_members', 0)}, cov {v3.get('coverage_q1')}, "
           f"rev {v3.get('revisions', 0)}, ok {age}{part}") if v3 else "none"
    flags = red_flags(reg, now)
    return (f"HEALTH positions={h.get('positions', '?')} no_exchange_stop={len(h.get('no_exchange_stop') or [])} "
            f"risk={h.get('risk_pct', '?')}% import_age={imp} disk=[{disk}] "
            f"forward=[{fw.get('verdict', '?')}, days {fw.get('forward_days', '?')}, benchmark trades {bench}, "
            f"P(top>bench) {vs}] v3=[{v3s}] tradfi=[{tradfi_part(reg)}] flags={flags or 'none'}")


def tradfi_part(reg) -> str:
    """TradFi lane in the HEALTH line: per instrument tradable on the account (ok / n/a / ?) and
    whether its underlying market is open now; 'off' when the lane is switched off."""
    t = reg.kv_get("tradfi") or {}
    if not t:
        return "?"
    if not t.get("enabled"):
        return "off"
    out = []
    for p in t.get("pairs") or []:
        a = (t.get("available") or {}).get(p)
        st = "ok" if a else ("n/a" if a is False else "?")
        out.append(f"{p.split('/')[0]} {st}{' open' if (t.get('open_now') or {}).get(p) else ''}")
    return ", ".join(out) or "none"


def disk_line(reg) -> str:
    """Hourly DISK log line: what fills the volume and what the janitor freed."""
    d, j = reg.kv_get("disk") or {}, reg.kv_get("janitor") or {}
    b = d.get("breakdown") or {}
    top = ", ".join(f"{k} {v}" for k, v in list((b.get("folders_mb") or {}).items())[:5])
    big = ", ".join(f"{x['file']} {x['mb']}" for x in (b.get("largest") or [])[:3])
    tabs = ", ".join(f"{k} {v}" for k, v in list((d.get("tables_mb") or {}).items())[:4])
    g = d.get("growth") or {}
    return (f"DISK used={d.get('used_mb')}MB of {d.get('total_mb')}MB growth={g.get('mb_per_day')}MB/d "
            f"full_in={g.get('days_to_full')}d folders_mb=[{top}] largest_mb=[{big}] registry_mb={b.get('registry')} "
            f"tables_mb=[{tabs}] container={b.get('container')} janitor_freed_mb={j.get('freed_total_mb', 0)}")
