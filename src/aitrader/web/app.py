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

from aitrader import lab as labsync
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
            r["summary"] = {k: res.get(k) for k in ("verdict", "score", "dsr", "wfe", "robust_frac", "n_trials")}
            r["oos"] = res.get("oos")
            r["gates"] = res.get("gates")
            r["variant"] = res.get("variant")
            r["folds"] = [{"test": f.get("test"), "trades": (f.get("oos") or {}).get("trades"),
                           "ret": (f.get("oos") or {}).get("total_return"),
                           "pf": (f.get("oos") or {}).get("profit_factor")} for f in (res.get("folds") or [])]
        r["pairs"] = len(spec.get("pairs", [])) if isinstance(spec, dict) else 0
        if isinstance(spec, dict):
            r["info"] = {k: spec.get(k) for k in ("refines", "revalidates", "remote", "epochs")} | {
                "pair_list": (spec.get("pairs") or [])[:12]}
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
        "lab": reg().kv_get("lab"),
        "mode": S.research.mode,
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


# ---------------------------------------------------------------------------- research lab
def lab_auth(request: Request) -> dict:
    """GitHub Actions OIDC token of this repository's main branch (no shared secret)."""
    tok = request.headers.get("authorization", "")
    tok = tok[7:].strip() if tok.lower().startswith("bearer ") else ""
    try:
        return labsync.verify_oidc(tok, S.lab_repository)
    except labsync.LabAuthError as e:
        raise HTTPException(401, f"lab auth: {e}") from e


@app.get("/api/lab/state")
def lab_state(claims: dict = Depends(lab_auth)) -> dict:  # noqa: ARG001
    return labsync.build_state(S, reg())


@app.post("/api/lab/progress")
async def lab_progress(request: Request, claims: dict = Depends(lab_auth)) -> dict:  # noqa: ARG001
    labsync.record_progress(reg(), await request.json())
    return {"ok": True}


@app.post("/api/lab/run")
async def lab_run(request: Request, claims: dict = Depends(lab_auth)) -> dict:  # noqa: ARG001
    labsync.record_run(reg(), await request.json())
    return {"ok": True}


@app.post("/api/lab/import")
async def lab_import(request: Request, claims: dict = Depends(lab_auth)) -> dict:  # noqa: ARG001
    data = await request.json()
    import asyncio
    res = await asyncio.to_thread(labsync.apply_import, S, reg(), data)
    return {"ok": True, **res}


@app.get("/api/lab/proxy")
def lab_proxy(request: Request, claims: dict = Depends(lab_auth)) -> dict:  # noqa: ARG001
    """Relay endpoint + short-lived token for Bybit public market data (research lab)."""
    from aitrader import labrelay
    if not os.environ.get("LAB_PROXY_SECRET"):
        raise HTTPException(404, "relay not configured")
    dom = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    base = f"https://{dom}" if dom else str(request.base_url).rstrip("/")
    return {"relay": f"{base}/relay/", "token": labrelay.issue_token(), "ttl_s": labrelay.TOKEN_TTL_S}


@app.get("/relay/{rest:path}")
def relay(rest: str, request: Request) -> Response:
    """GET-only relay of Bybit *public market data* for the research lab (see labrelay)."""
    import requests as rq

    from aitrader import labrelay
    if not labrelay.verify_token(request.headers.get("x-lab-token")):
        raise HTTPException(401, "relay token required")
    url = labrelay.target_url(rest, request.url.query)
    if url is None:
        raise HTTPException(403, "only Bybit /v5/market/ GET requests are relayed")
    try:
        r = rq.get(url, timeout=20, headers={"User-Agent": "aitrader-lab-relay"})
    except rq.RequestException as e:
        raise HTTPException(502, f"upstream error: {e}") from e
    return Response(r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type", "application/json"))


@app.get("/api/lab/backup")
def lab_backup(claims: dict = Depends(lab_auth)) -> Response:  # noqa: ARG001
    """Consistent gzip snapshot of the registry (the lab stores it as a 30-day artifact)."""
    import gzip
    import sqlite3
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d) / "registry.sqlite"
        src, dst = sqlite3.connect(S.registry_path), sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
        data = gzip.compress(tmp.read_bytes(), 6)
    return Response(data, media_type="application/gzip",
                    headers={"Content-Disposition": "attachment; filename=registry.sqlite.gz"})


# ---------------------------------------------------------------------------- HQ helpers
@app.get("/api/candles", dependencies=[Depends(auth)])
def candles(pair: str, limit: int = 96) -> dict:
    """Recent 1h candles for a pair the bot trades (for the HQ trader screens)."""
    c = ft()
    data = _safe(lambda: c.pair_candles(pair, "1h", min(max(limit, 10), 200)), {}) or {}
    cols = data.get("columns") or []
    want = ["date", "open", "high", "low", "close", "volume"]
    idx = [cols.index(k) for k in want if k in cols]
    rows = [[r[i] for i in idx] for r in (data.get("data") or [])] if len(idx) == len(want) else []
    return {"pair": pair, "candles": rows[-limit:]}


@app.get("/api/readiness", dependencies=[Depends(auth)])
def readiness_api() -> dict:
    from aitrader import readiness
    return readiness.evaluate(reg())


@app.get("/api/goals", dependencies=[Depends(auth)])
def goals() -> dict:
    return company_goals(reg())


def company_goals(r: Registry) -> dict:
    """The company's mission, measured from real data only."""
    from datetime import timedelta

    from aitrader.util import iso
    eq = r.q("SELECT equity FROM equity ORDER BY ts")
    start = float(eq[0]["equity"]) if eq else 0.0
    now_eq = float(eq[-1]["equity"]) if eq else 0.0
    peak = max((float(x["equity"]) for x in eq), default=0.0)
    dd = (peak - now_eq) / peak if peak else 0.0
    from aitrader.realism import real_pnl
    trades = r.q("SELECT profit_abs, stake_amount, leverage FROM live_trades WHERE sleeve_id NOT LIKE 'exec-test%'")
    pnl = [real_pnl(t) for t in trades]
    gains, losses = sum(x for x in pnl if x > 0), -sum(x for x in pnl if x < 0)
    pf = gains / losses if losses else (99.0 if gains else 0.0)
    week = iso(utcnow() - timedelta(days=7))
    n_week = r.one("SELECT COUNT(*) n FROM experiments WHERE status='done' AND finished >= ?", (week,))["n"]
    ever_validated = r.one("SELECT COUNT(*) n FROM strategies WHERE stage IN ('validated','incubation','eligible','production') "
                           "OR history LIKE '%\"to\": \"validated\"%'")["n"]
    n_prod = r.one("SELECT COUNT(*) n FROM strategies WHERE stage='production'")["n"]
    ret = (now_eq / start - 1) if start else 0.0
    lab = r.kv_get("lab") or {}
    week_target = 60 if lab.get("public") else 20
    rd = r.kv_get("readiness") or {}
    items = [
        {"id": "readiness", "title": "Real-money readiness (all checks, realistic fills)",
         "value": rd.get("passed", 0), "target": rd.get("total", 8), "unit": "",
         "progress": (rd.get("passed", 0) / rd.get("total", 8)) if rd else 0.0},
        {"id": "validated", "title": "Find a strategy that passes every strict gate",
         "value": ever_validated, "target": 1, "unit": "", "progress": min(1.0, ever_validated / 1)},
        {"id": "evidence", "title": "Collect forward-test evidence on Bybit Demo",
         "value": len(pnl), "target": 100, "unit": "trades", "progress": min(1.0, len(pnl) / 100)},
        {"id": "research", "title": "Research throughput (walk-forward experiments / 7 days)",
         "value": n_week, "target": week_target, "unit": "", "progress": min(1.0, n_week / week_target)},
        {"id": "pf", "title": "Live profit factor ≥ 1.3 (after slippage haircut)",
         "value": round(pf, 2), "target": 1.3, "unit": "", "progress": min(1.0, pf / 1.3) if pnl else 0.0},
        {"id": "production", "title": "Strategies promoted to production",
         "value": n_prod, "target": 3, "unit": "", "progress": min(1.0, n_prod / 3)},
        {"id": "return", "title": "Grow demo equity +10% (without breaching 15% drawdown)",
         "value": round(ret * 100, 2), "target": 10, "unit": "%",
         "progress": max(0.0, min(1.0, ret / 0.10)), "warning": dd > 0.10},
    ]
    return {"mission": "Find, prove and scale real trading edges on Bybit Demo — no overfitting, no fake results.",
            "goals": items, "equity": now_eq, "drawdown": round(dd, 4), "lab": lab, "readiness": rd}


@app.exception_handler(Exception)
async def _err(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
    return JSONResponse({"error": str(exc)[:500]}, status_code=500)
