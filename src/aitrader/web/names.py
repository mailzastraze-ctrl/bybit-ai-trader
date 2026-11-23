"""One strategy base for every page (owner, 2026-11-23): each strategy has a short numeric code
(its name, e.g. 1047) and a method (what it does, e.g. "RSI: возврат к среднему · 2h"). Codes are
assigned once, in the order strategies were created, and never change."""

from __future__ import annotations

import threading

from aitrader.registry import Registry
from aitrader.web import cards

FIRST_CODE = 1001
_lock = threading.Lock()


def codes(reg: Registry) -> dict[str, int]:
    """Stable codes for every strategy; new strategies get the next free number."""
    with _lock:
        kv = reg.kv_get("strategy_codes") or {}
        ids: dict[str, int] = dict(kv.get("ids") or {})
        nxt = int(kv.get("next") or FIRST_CODE)
        new = [r["id"] for r in reg.q("SELECT id FROM strategies ORDER BY created, id") if r["id"] not in ids]
        for sid in new:
            ids[sid] = nxt
            nxt += 1
        if new:
            reg.kv_set("strategy_codes", {"next": nxt, "ids": ids})
        return ids


def method(family: str, timeframe: str | None = None) -> str:
    t = cards.TITLE.get(family, family or "—")
    return f"{t} · {timeframe}" if timeframe else t


def names(reg: Registry) -> dict[str, dict]:
    """Code and method for every id that can appear on a page: research strategies, the TradFi
    lane and the (former) demo core."""
    out: dict[str, dict] = {}
    cs = codes(reg)
    for r in reg.q("SELECT id, family, oos FROM strategies"):
        tf = (r.get("oos") or {}).get("timeframe") or "1h"
        out[r["id"]] = {"code": cs.get(r["id"]), "method": method(r["family"], tf), "family": r["family"], "tf": tf}
    for kind in ("tradfi_cfg", "core"):
        for sid, c in (reg.kv_get(kind) or {}).items():
            title = c.get("title") or cards.TITLE.get(c.get("family"), c.get("family"))
            out.setdefault(sid, {"code": None, "method": f"{title} · {c.get('timeframe') or '4h'}",
                                 "family": c.get("family"), "tf": c.get("timeframe"),
                                 "lane": "TradFi" if kind == "tradfi_cfg" else "ядро (выкл.)"})
    return out
