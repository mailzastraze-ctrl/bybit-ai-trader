"""Web terminal: one page + JSON API over the registry and the Freqtrade REST API."""

from __future__ import annotations

import os
import secrets
import shutil
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from aitrader.ftclient import FtClient
from aitrader.manifest import Manifest
from aitrader.registry import Registry
from aitrader.research.generator import Generator
from aitrader.settings import get_settings
from aitrader.util import parse_dt, utcnow

S = get_settings()
STATIC = Path(__file__).parent / "static"
app = FastAPI(title="aitrader terminal", docs_url=None, redoc_url=None, openapi_url=None)
security = HTTPBasic()
app.mount("/static", StaticFiles(directory=STATIC), name="static")
_reg: Registry | None = None


def reg() -> Registry:
    global _reg
    if _reg is None:
        S.ensure_dirs()
        _reg = Registry(S.registry_path)
    return _reg


def ft() -> FtClient:
    return FtClient(S.ft_api_url, S.ft_api_user, S.ft_api_password, timeout=6)


def auth(creds: HTTPBasicCredentials = Depends(security)) -> str:
    pw = S.web_password
    ok = bool(pw) and secrets.compare_digest(creds.username.encode(), S.web_user.encode()) \
        and secrets.compare_digest(creds.password.encode(), pw.encode())
    if not ok:
        raise HTTPException(401, "unauthorized", headers={"WWW-Authenticate": "Basic"})
    return creds.username


if os.environ.get("AITRADER_EMBED_MANAGER") == "1":
    # Small instances: run the manager loop in this process instead of a separate interpreter.
    import threading

    from aitrader import manager as _manager
    threading.Thread(target=_manager.main, name="manager", daemon=True).start()


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return default


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/", dependencies=[Depends(auth)])
def hq() -> Response:
    """3D company headquarters view (live data)."""
    return FileResponse(STATIC / "hq.html", headers={"Cache-Control": "no-store"})


@app.get("/terminal", dependencies=[Depends(auth)])
def index() -> Response:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/overview", dependencies=[Depends(auth)])
def overview() -> dict:
    c = ft()
    up = c.ping()
    eq = reg().q("SELECT ts, equity, open_trades FROM equity ORDER BY ts DESC LIMIT 4000")[::-1]
    man = Manifest.load(S.manifest_path)
    closed = reg().q("SELECT profit_abs, close_date FROM live_trades ORDER BY close_date")
    return {
        "bot_up": up,
        "balance": _safe(c.balance) if up else None,
        "profit": _safe(c.profit) if up else None,
        "daily": _safe(lambda: c.daily(30)) if up else None,
        "open_trades": _safe(c.status, []) if up else [],
        "equity": eq,
        "kill_switch": reg().kv_get("kill_since"),
        "entries_paused": man.entries_paused,
        "manifest": man.to_dict(),
        "closed_count": len(closed),
        "closed_pnl": round(sum(float(r["profit_abs"] or 0) for r in closed), 2),
        "events": reg().q("SELECT * FROM events ORDER BY id DESC LIMIT 12"),
    }


@app.get("/api/trades", dependencies=[Depends(auth)])
def trades(limit: int = 300) -> dict:
    rows = reg().q("SELECT trade_id, sleeve_id, pair, is_short, open_date, close_date, open_rate, "
                   "close_rate, profit_ratio, profit_abs, exit_reason, leverage, stake_amount "
                   "FROM live_trades ORDER BY close_date DESC LIMIT ?", (limit,))
    c = ft()
    return {"closed": rows, "open": _safe(c.status, []) if c.ping() else []}


@app.get("/api/strategies", dependencies=[Depends(auth)])
def strategies() -> dict:
    return {"strategies": reg().strategies(), "manifest": Manifest.load(S.manifest_path).to_dict()}


@app.get("/api/research", dependencies=[Depends(auth)])
def research(limit: int = 60) -> dict:
    rows = reg().q("SELECT id, created, family, status, started, finished, error, progress, spec, result "
                   "FROM experiments ORDER BY created DESC LIMIT ?", (limit,))
    out = []
    fails: dict[str, int] = {}
    for r in rows:
        res = r.pop("result", None) or {}
        spec = r.pop("spec", None) or {}
        if isinstance(res, dict):
            for g, v in (res.get("gates") or {}).items():
                if not v.get("pass"):
                    fails[g] = fails.get(g, 0) + 1
            r["summary"] = {k: res.get(k) for k in ("verdict", "score", "dsr", "wfe", "robust_frac")}
            r["oos"] = res.get("oos")
            r["gates"] = res.get("gates")
        r["pairs"] = len(spec.get("pairs", [])) if isinstance(spec, dict) else 0
        r["used_learnings"] = spec.get("used_learnings", []) if isinstance(spec, dict) else []
        r["error"] = (r.get("error") or "")[:400]
        out.append(r)
    counts = reg().q("SELECT status, COUNT(*) n FROM experiments GROUP BY status")
    return {
        "experiments": out,
        "counts": {c["status"]: c["n"] for c in counts},
        "gate_failures": fails,
        "family_stats": Generator(S, reg()).family_stats(),
        "paused": bool(reg().kv_get("research_paused", False)),
        "scale": reg().kv_get("research_scale"),
        "universe": reg().kv_get("universe"),
    }


@app.get("/api/research/{eid}", dependencies=[Depends(auth)])
def research_detail(eid: str) -> dict:
    r = reg().one("SELECT * FROM experiments WHERE id=?", (eid,))
    if not r:
        raise HTTPException(404)
    return r


@app.get("/api/market", dependencies=[Depends(auth)])
def market() -> dict:
    return {"pairs": reg().q("SELECT * FROM market ORDER BY pair"), "universe": reg().kv_get("universe")}


@app.get("/api/learnings", dependencies=[Depends(auth)])
def learnings() -> dict:
    return {"learnings": reg().q("SELECT * FROM learnings ORDER BY ts DESC LIMIT 200")}


@app.get("/api/events", dependencies=[Depends(auth)])
def events(limit: int = 200) -> dict:
    return {"events": reg().q("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))}


@app.get("/api/health", dependencies=[Depends(auth)])
def health() -> dict:
    now = utcnow()
    hbs = []
    for h in reg().q("SELECT * FROM heartbeats ORDER BY service"):
        ts = parse_dt(h["ts"])
        h["age_s"] = int((now - ts).total_seconds()) if ts else None
        hbs.append(h)
    c = ft()
    up = c.ping()
    du = shutil.disk_usage(S.data_dir) if S.data_dir.exists() else None
    return {
        "heartbeats": hbs,
        "bot_up": up,
        "bot_health": _safe(c.health) if up else None,
        "bot_config": _safe(lambda: {k: v for k, v in c.show_config().items()
                                     if k in ("version", "strategy", "exchange", "trading_mode",
                                              "dry_run", "state", "max_open_trades", "timeframe",
                                              "stake_currency", "bot_name")}) if up else None,
        "selftest": reg().kv_get("selftest"),
        "exec_test": reg().kv_get("exec_test"),
        "supervisor": reg().kv_get("supervisor"),
        "disk": {"total": du.total, "used": du.used, "free": du.free} if du else None,
    }


@app.post("/api/control/{action}", dependencies=[Depends(auth)])
def control(action: str) -> JSONResponse:
    c = ft()
    if action == "pause_research":
        reg().kv_set("research_paused", True)
    elif action == "resume_research":
        reg().kv_set("research_paused", False)
    elif action == "stop_entries":
        c.stopentry()
    elif action == "start_bot":
        c.start()
    else:
        raise HTTPException(400, "unknown action")
    reg().event("web", f"control action: {action}", "warning")
    return JSONResponse({"ok": True, "action": action})


@app.exception_handler(Exception)
async def _err(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
    return JSONResponse({"error": str(exc)[:500]}, status_code=500)
