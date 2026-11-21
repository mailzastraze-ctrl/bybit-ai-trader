"""Strategy explorer (owner's page /explorer): every strategy with its research, forward and
demo numbers side by side, and one strategy in full – idea, why it is where it is, research
equity curve, every check, parameters, forward trades and the demo trades on real candles.
Pure read-only views over the registry; nothing here changes trading."""

from __future__ import annotations

from aitrader.registry import Registry
from aitrader.util import iso, parse_dt
from aitrader.web import cards

STAGE_ORDER = {"production": 0, "eligible": 1, "incubation": 2, "exploration": 3, "closing": 4, "validated": 5,
               "exploratory": 6, "rejected": 7, "retired": 8}
LIVE_STAGES = ("production", "eligible", "incubation", "exploration")
WAITING = ("validated", "exploratory")


def _pf(xs: list[float]) -> float | None:
    g, lo = sum(x for x in xs if x > 0), -sum(x for x in xs if x < 0)
    return round(g / lo, 2) if lo > 0 else (None if not g else 99.0)


def _forward(fwd: dict, st: dict) -> dict:
    r = fwd.get(st.get("experiment_id") or "") or fwd.get(st["id"]) or {}
    xs = [float(t[1]) for t in r.get("trades", []) if isinstance(t, (list, tuple)) and len(t) == 2]
    return {"trades": len(xs), "pf": _pf(xs), "pnl_pct": round(sum(xs) * 100, 2) if xs else None,
            "win_rate": round(sum(1 for x in xs if x > 0) / len(xs), 3) if xs else None}


def _board(reg: Registry) -> dict:
    return {b["id"]: b for b in ((reg.kv_get("forward") or {}).get("best") or [])}


def _row(st: dict, fwd: dict, board: dict) -> dict:
    o, live = st.get("oos") or {}, st.get("live") or {}
    hist = st.get("history") or []
    b = board.get(st.get("experiment_id") or "") or board.get(st["id"]) or {}
    alpha = live.get("alpha") or {}
    return {
        "id": st["id"], "title": cards.TITLE.get(st["family"], st["family"]), "family": st["family"],
        "variant": o.get("variant") or st["family"], "stage": st["stage"],
        "status": cards.STATUS_RU.get(st["stage"], st["stage"]), "timeframe": o.get("timeframe") or "1h",
        "pairs": st.get("pairs") or [], "score": round(float(st.get("score") or 0), 3),
        "autopilot": bool(o.get("autopilot")), "benchmark": bool(o.get("benchmark")), "external": bool(o.get("external")),
        "why": (hist[-1].get("reason") if hist else st.get("note")) or "",
        "since": st.get("stage_since"),
        "research": {"trades": o.get("trades"), "pf": o.get("profit_factor"), "sharpe": o.get("sharpe"),
                     "dd": o.get("max_drawdown"), "ret": o.get("total_return")},
        "forward": {**_forward(fwd, st), "p_pos": b.get("p_pos")},
        "demo": {"trades": live.get("trades", 0), "pf": live.get("profit_factor"), "pnl": live.get("pnl"),
                 "win_rate": live.get("win_rate"), "alpha_ann": alpha.get("alpha_ann"), "beta": alpha.get("beta")},
    }


def listing(reg: Registry, show: str = "active") -> dict:
    fwd = reg.kv_get("forward_results") or {}
    board = _board(reg)
    rows = []
    for st in reg.strategies():
        if show == "active" and st["stage"] in ("rejected", "retired"):
            continue
        if show == "retired" and st["stage"] != "retired":
            continue
        rows.append(_row(st, fwd, board))
    rows.sort(key=lambda r: (STAGE_ORDER.get(r["stage"], 9), -(r["demo"]["trades"] or 0), -r["score"]))
    counts: dict[str, int] = {}
    for st in reg.strategies():
        counts[st["stage"]] = counts.get(st["stage"], 0) + 1
    return {"strategies": rows, "counts": counts,
            "groups": {"live": sum(counts.get(s, 0) for s in LIVE_STAGES), "waiting": sum(counts.get(s, 0) for s in WAITING),
                       "retired": counts.get("retired", 0)}}


# Neutral names for the research checks (cards.GATE_RU names the *failure*, which reads oddly next to a ✅).
CHECK_RU = {"trades": "Достаточно сделок", "profit_factor": "Profit factor", "sharpe": "Шарп", "max_drawdown": "Макс. просадка",
            "stress_pf": "PF при двойных комиссиях", "wfe": "Новые данные не хуже обучения", "robustness": "Соседние параметры тоже работают",
            "monte_carlo": "Монте-Карло: вероятность прибыли", "deflated_sharpe": "Не удача перебора (дефлированный Шарп)",
            "fold_consistency": "Прибыльна в разных окнах", "clean_oos": "Чистая проверка вне выборки",
            "market_alpha": "Прибыль не из движения BTC (альфа, t)"}
LOWER_IS_BETTER = {"max_drawdown"}
FLAG_CHECKS = {"clean_oos"}  # yes/no checks: the stored number means nothing to a reader


def detail(reg: Registry, sid: str) -> dict | None:
    st = reg.one("SELECT * FROM strategies WHERE id=?", (sid,))
    if not st:
        return None
    exp = reg.one("SELECT id, spec, result, finished FROM experiments WHERE id=?", (st.get("experiment_id") or "",))
    res = (exp or {}).get("result") if isinstance((exp or {}).get("result"), dict) else None
    card = cards._card("strategy", st, res)
    gates = (res or {}).get("gates") or st.get("gates") or {}
    gate_rows = [{"id": k, "name": CHECK_RU.get(k, cards.GATE_RU.get(k, k)),
                  "value": None if k in FLAG_CHECKS else v.get("value"), "need": None if k in FLAG_CHECKS else v.get("threshold"),
                  "cmp": "≤" if k in LOWER_IS_BETTER else "≥", "pass": bool(v.get("pass"))}
                 for k, v in gates.items() if isinstance(v, dict)]
    fwd_all = reg.kv_get("forward_results") or {}
    f = fwd_all.get(st.get("experiment_id") or "") or fwd_all.get(sid) or {}
    trades = [_norm_trade(t) for t in reg.q(
        "SELECT trade_id, pair, is_short, open_date, close_date, open_rate, close_rate, profit_abs, "
        "profit_ratio, exit_reason, stake_amount, leverage FROM live_trades WHERE sleeve_id=? ORDER BY open_date", (sid,))]
    return {"row": _row(st, fwd_all, _board(reg)), "card": card, "gates": gate_rows,
            "history": (st.get("history") or [])[-12:],
            "research": {k: (res or {}).get(k) for k in ("oos", "stress", "mc", "market", "wfe", "robust_frac", "fold_pos",
                                                         "dsr", "clean_oos", "verdict", "replication", "parity")} if res else {"oos": st.get("oos")},
            "forward_trades": f.get("trades", []), "forward_freeze": f.get("freeze"),
            "trades": trades, "params": st.get("params") or {}}


# ---------------------------------------------------------------------- trades and candles for the chart
TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480, "12h": 720, "1d": 1440}


def _iso(value) -> str | None:
    """One date format for the browser ('2026-11-21T10:00:00Z'): Freqtrade's '2026-11-21 10:00:00'
    is read as local time by some browsers and is invalid in Safari."""
    try:
        d = parse_dt(value)
    except (TypeError, ValueError):
        return None
    return iso(d) if d else None


def _norm_trade(t: dict) -> dict:
    return {**t, "open_date": _iso(t.get("open_date")), "close_date": _iso(t.get("close_date")), "is_open": False}


def open_trades(status: list[dict] | None, sid: str) -> list[dict]:
    """The strategy's positions open right now (from the bot), in the same shape as closed ones."""
    out = []
    for t in status or []:
        if not isinstance(t, dict) or (t.get("enter_tag") or "") != sid:
            continue
        out.append({"trade_id": t.get("trade_id"), "pair": t.get("pair"), "is_short": int(bool(t.get("is_short"))),
                    "open_date": _iso(t.get("open_date")), "close_date": None, "open_rate": t.get("open_rate"),
                    "close_rate": None, "current_rate": t.get("current_rate"), "profit_abs": t.get("profit_abs"),
                    "profit_ratio": t.get("profit_ratio"), "exit_reason": None, "stake_amount": t.get("stake_amount"),
                    "leverage": t.get("leverage"), "stop": t.get("stop_loss_abs"), "is_open": True})
    return out


def candle_rows(data: dict | None) -> list[list]:
    """Freqtrade /pair_candles payload → [[iso, open, high, low, close], ...]."""
    cols = (data or {}).get("columns") or []
    want = ["open", "high", "low", "close"]
    if not all(k in cols for k in want) or ("__date_ts" not in cols and "date" not in cols):
        return []
    ts_i = cols.index("__date_ts") if "__date_ts" in cols else cols.index("date")
    idx = [cols.index(k) for k in want]
    out = []
    for r in (data or {}).get("data") or []:
        try:
            d = _iso(r[ts_i])
            vals = [float(r[i]) for i in idx]
        except (TypeError, ValueError, IndexError):
            continue
        if d and all(v == v for v in vals):  # skip NaN rows
            out.append([d, *vals])
    return out


def resample(rows: list[list], minutes: int) -> list[list]:
    """Build candles of the strategy's timeframe from 15m ones (the bot keeps only its base
    timeframe analysed). The first bucket is dropped if it is incomplete."""
    out: list[list] = []
    counts: list[int] = []
    step = minutes * 60
    for d, o, h, lo, c in rows:
        ts = int(parse_dt(d).timestamp())
        b = ts - ts % step
        if out and out[-1][0] == b:
            x = out[-1]
            x[2], x[3], x[4] = max(x[2], h), min(x[3], lo), c
            counts[-1] += 1
        else:
            out.append([b, o, h, lo, c])
            counts.append(1)
    if len(out) > 1 and counts[0] < minutes // 15:
        out, counts = out[1:], counts[1:]
    from datetime import UTC, datetime
    return [[iso(datetime.fromtimestamp(b, UTC)), o, h, lo, c] for b, o, h, lo, c in out]
