"""Single-container process supervisor (Railway allows one volume per service, so all
processes share one container and the /data volume).

Processes: freqtrade bot (Bybit Demo) · manager · research worker · web terminal.
Crashed processes are restarted with exponential backoff.
"""

from __future__ import annotations

import os
import secrets
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

from aitrader import observe
from aitrader.lifecycle import Lifecycle
from aitrader.registry import Registry
from aitrader.settings import get_settings
from aitrader.util import iso, parse_dt, setup_logging, utcnow

log = setup_logging("supervisor")


def persistent_secret(path, env_name: str) -> str:
    val = os.environ.get(env_name)
    if val:
        return val
    if path.exists():
        return path.read_text().strip()
    val = secrets.token_urlsafe(24)
    path.write_text(val)
    os.chmod(path, 0o600)
    return val


def _oom_adj(score: int):
    """Raise a child's OOM score so the kernel kills research before the trading bot
    when the container hits its memory limit (raising is always permitted)."""
    def fn():
        try:
            with open("/proc/self/oom_score_adj", "w") as fh:
                fh.write(str(score))
        except OSError:
            pass
    return fn


def _rss_by_proc(procs) -> dict:
    """Resident memory (MB) of each supervised process including its children."""
    try:
        import psutil
    except ImportError:
        return {}
    out = {}
    for p in procs:
        if not p.popen or p.popen.poll() is not None:
            continue
        try:
            root = psutil.Process(p.popen.pid)
            tree = [root, *root.children(recursive=True)]
            out[p.name] = int(sum(x.memory_info().rss for x in tree if x.is_running()) / 1e6)
        except psutil.Error:
            continue
    return out


@dataclass
class Proc:
    name: str
    cmd: list[str]
    env: dict = field(default_factory=dict)
    oom_score: int = 0
    popen: subprocess.Popen | None = None
    restarts: int = 0
    started: float = 0.0
    next_start: float = 0.0


def main() -> None:
    # glibc gives every thread its own malloc arena; freqtrade (async + threads) and uvicorn
    # then hold far more RSS than they use. Two arenas cut resident memory noticeably.
    os.environ.setdefault("MALLOC_ARENA_MAX", "2")
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    s = get_settings()
    s.ensure_dirs()
    reg = Registry(s.registry_path)
    sd = s.state_dir

    web_pw = persistent_secret(sd / "web_password", "WEB_PASSWORD")
    if not os.environ.get("WEB_PASSWORD"):
        log.warning("WEB_PASSWORD not set – generated one, stored in %s: %s", sd / "web_password", web_pw)
    api_pw = persistent_secret(sd / "ft_api_password", "FT_API_PASSWORD")
    jwt = persistent_secret(sd / "ft_jwt_secret", "FT_JWT_SECRET")
    ws = persistent_secret(sd / "ft_ws_token", "FT_WS_TOKEN")
    proxy_secret = persistent_secret(sd / "lab_proxy_secret", "LAB_PROXY_SECRET")
    common = {"WEB_PASSWORD": web_pw, "FT_API_PASSWORD": api_pw, "FT_API_USER": s.ft_api_user,
              "LAB_PROXY_SECRET": proxy_secret,
              "AITRADER_DATA": str(s.data_dir), "AITRADER_APP": str(s.app_dir)}
    os.environ.update(common)

    # manifest + pairlist must exist before the bot starts
    life = Lifecycle(s, reg)
    life.bootstrap()
    if not s.manifest_path.exists():
        life.write(life.build_manifest([], set(), False), [])

    key, secret = os.environ.get("BYBIT_API_KEY", ""), os.environ.get("BYBIT_API_SECRET", "")
    py = sys.executable
    procs: list[Proc] = []
    if key and secret:
        procs.append(Proc("freqtrade", [
            s.freqtrade_bin, "trade", "--config", str(s.config_dir / "trade.json"),
            "--userdir", str(s.user_data), "--strategy-path", str(s.strategies_dir),
            "--db-url", f"sqlite:///{s.state_dir / 'trades.sqlite'}",
            "--logfile", str(s.user_data / "logs" / "freqtrade.log")],
            env={"FREQTRADE__EXCHANGE__KEY": key, "FREQTRADE__EXCHANGE__SECRET": secret,
                 "FREQTRADE__API_SERVER__USERNAME": s.ft_api_user,
                 "FREQTRADE__API_SERVER__PASSWORD": api_pw,
                 "FREQTRADE__API_SERVER__JWT_SECRET_KEY": jwt,
                 "FREQTRADE__API_SERVER__WS_TOKEN": ws}))
    else:
        reg.event("supervisor", "BYBIT_API_KEY / BYBIT_API_SECRET not set – trading bot NOT started", "error")
    lite = os.environ.get("AITRADER_PROFILE", "").lower() == "lite"
    if not lite:  # in lite mode the manager loop runs as a thread inside the web process
        procs.append(Proc("manager", [py, "-m", "aitrader.manager"], oom_score=300))
    if s.research.mode == "remote":
        log.info("research mode: remote – heavy research runs on GitHub Actions (research lab); "
                 "this server only receives results")
        reg.event("supervisor", "research mode: remote (GitHub research lab) – no heavy compute on this server")
        reg.heartbeat("research", "idle", {"remote": True})
    elif os.environ.get("RESEARCH_ENABLED", "1") != "0":
        # research (and every freqtrade hyperopt/backtest it spawns) is the first OOM victim
        procs.append(Proc("research", ["nice", "-n", "10", py, "-m", "aitrader.research.worker"],
                          oom_score=1000))
    port = os.environ.get("PORT", "8000")
    procs.append(Proc("web", [py, "-m", "uvicorn", "aitrader.web.app:app", "--host", "0.0.0.0",
                              "--port", port, "--log-level", "warning", "--proxy-headers"],
                     env={"AITRADER_EMBED_MANAGER": "1" if lite else "0"}, oom_score=300))

    stopping = threading.Event()

    def _stop(signum, frame):  # noqa: ARG001
        stopping.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    def start(p: Proc) -> None:
        log.info("starting %s", p.name)
        p.popen = subprocess.Popen(p.cmd, env={**os.environ, **p.env},
                                   preexec_fn=_oom_adj(p.oom_score) if p.oom_score else None)
        p.started = time.time()

    for p in procs:
        start(p)
    reg.event("supervisor", "started: " + ", ".join(p.name for p in procs))

    if key and secret:
        def _selftest():
            time.sleep(60)
            subprocess.run([py, "-m", "aitrader.selftest", "240"], env=os.environ.copy())
        threading.Thread(target=_selftest, daemon=True).start()

    last_status = 0.0
    while not stopping.is_set():
        now = time.time()
        if now - last_status > 300:
            last_status = now
            try:
                hb = {h["service"]: f"{h['status']}" for h in reg.q("SELECT service, status FROM heartbeats")}
                u = reg.kv_get("universe") or {}
                ex = {r["status"]: r["n"] for r in reg.q("SELECT status, COUNT(*) n FROM experiments GROUP BY status")}
                st = {r["stage"]: r["n"] for r in reg.q("SELECT stage, COUNT(*) n FROM strategies GROUP BY stage")}
                nt = reg.one("SELECT COUNT(*) n FROM live_trades")["n"]
                log.info("STATUS heartbeats=%s universe=%d experiments=%s strategies=%s closed_trades=%s rss_mb=%s",
                         hb, len(u.get("pairs") or []), ex, st, nt, _rss_by_proc(procs))
                log.info("%s", observe.status_line(reg))  # positions, stops, risk, lab, disk, forward, red flags
            except Exception as e:  # noqa: BLE001
                log.warning("status line failed: %s", e)
        for p in procs:
            rc = p.popen.poll() if p.popen else None
            if p.popen and rc is not None:
                if now - p.started > 600:
                    p.restarts = 0
                delay = min(300, 5 * 2 ** p.restarts)
                p.restarts += 1
                p.popen = None
                p.next_start = now + delay
                log.error("%s exited rc=%s – restart in %ss", p.name, rc, delay)
                reg.event("supervisor", f"{p.name} exited (rc={rc}); restarting in {delay}s", "error")
            elif p.popen is None and now >= p.next_start:
                start(p)
        # Research liveness: a heartbeat older than 2 h means the worker is stuck → restart it.
        rp = next((p for p in procs if p.name == "research"), None)
        if rp and rp.popen and rp.popen.poll() is None and now - rp.started > 7200:
            hb = reg.one("SELECT ts FROM heartbeats WHERE service='research'")
            hb_ts = parse_dt(hb["ts"]) if hb else None
            if hb_ts and (utcnow() - hb_ts).total_seconds() > 7200:
                log.error("research heartbeat stale since %s – restarting research worker", hb["ts"])
                reg.event("supervisor", f"research heartbeat stale since {hb['ts']} – worker restarted", "error")
                rp.popen.kill()
        reg.kv_set("supervisor", {"ts": iso(), "processes": {
            p.name: {"running": p.popen is not None and p.popen.poll() is None, "restarts": p.restarts,
                     "uptime_s": int(now - p.started) if p.popen else 0} for p in procs}})
        stopping.wait(10)

    log.info("stopping children")
    for p in procs:
        if p.popen and p.popen.poll() is None:
            p.popen.terminate()
    deadline = time.time() + 25
    for p in procs:
        if p.popen:
            try:
                p.popen.wait(timeout=max(1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                p.popen.kill()


if __name__ == "__main__":
    main()
