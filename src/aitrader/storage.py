"""Keeps the /data volume from filling up during weeks of unattended running.

What grows without bound otherwise:
  * the registry: every lab run stores ~60 experiment results (equity curve, per-fold
    detail, per-pair stats, ~8–10 KB each), 8–9 runs a day;
  * Freqtrade's log: its rotating handler keeps 10 × 10 MB.

Since 2026-11-22 the janitor (bottom of this file) owns everything else that grows: hourly
rotated logs, stale temp files, half-written atomic files, research leftovers (remote mode),
the WAL; daily events (30 days, 7 on a low disk); on a very low disk candidates' charts too.
The lab keeps 14 days of batch files in the repository (research.yml).

What this does (daily, from the manager's housekeeping):
  * slims *rejected* experiments older than SLIM_AFTER_DAYS: drops the equity curve, the
    per-pair and exit-reason tables and the per-fold parameter detail. Everything the
    system reads later stays: verdict, gates, score, params, pairs, the OOS/stress/MC
    summaries (Deflated Sharpe, bandit, learner, forward book) and each fold's test window
    and return (the persistence indicator, the cards). Candidates (validated/exploratory)
    are never slimmed – their curves are shown on the cards;
  * keeps only LOG_BACKUPS_KEEP rotated Freqtrade log files;
  * reports disk usage (kv `disk`, shown in the control room) and, when free space drops
    below LOW_FREE, slims harder (rejected results after 1 day) so trading never stops on
    a full disk.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
from datetime import timedelta
from pathlib import Path

from aitrader.registry import Registry
from aitrader.util import iso, utcnow

log = logging.getLogger(__name__)
SLIM_AFTER_DAYS = 3
LOW_FREE = 0.20          # below this share of free space: warn and slim harder
LOG_BACKUPS_KEEP = 2
DROP_KEYS = ("curve", "pair_stats", "exit_reasons")


def slim_result(res: dict) -> dict:
    out = {k: v for k, v in res.items() if k not in DROP_KEYS}
    if isinstance(res.get("folds"), list):
        out["folds"] = [{"fold": f.get("fold"), "test": f.get("test"),
                         "oos": {"total_return": (f.get("oos") or {}).get("total_return")}}
                        for f in res["folds"] if isinstance(f, dict)]
    out["slim"] = True
    return out


def slim_experiments(reg: Registry, days: float = SLIM_AFTER_DAYS, now=None) -> int:
    """Slim rejected experiment results finished more than `days` ago. Returns rows changed."""
    cutoff = iso((now or utcnow()) - timedelta(days=days))
    # experiments behind a live strategy (e.g. a near-miss now trading on demo) keep their card chart
    alive = {r["experiment_id"] for r in reg.q("SELECT experiment_id FROM strategies WHERE stage != 'retired'")
             if r.get("experiment_id")}
    n = 0
    for r in reg.q("SELECT id, result FROM experiments WHERE status='done' AND finished < ?", (cutoff,)):
        res = r.get("result")
        if not isinstance(res, dict) or res.get("slim") or res.get("verdict") in ("validated", "exploratory") \
                or r["id"] in alive:
            continue
        reg.update("experiments", r["id"], {"result": slim_result(res)})
        n += 1
    return n


def trim_logs(log_dir: Path, keep: int = LOG_BACKUPS_KEEP) -> int:
    """Delete rotated logs beyond `keep` (freqtrade.log.3 … .10). The live log is untouched."""
    n = 0
    for f in Path(log_dir).glob("*.log.*"):
        m = re.search(r"\.log\.(\d+)$", f.name)
        if m and int(m.group(1)) > keep:
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
    return n


def disk_status(path: Path) -> dict:
    u = shutil.disk_usage(path)
    return {"ts": iso(), "total_mb": round(u.total / 2**20), "used_mb": round(u.used / 2**20),
            "free_mb": round(u.free / 2**20), "free_pct": round(u.free / u.total, 4) if u.total else None}


def maintain(reg: Registry, data_dir: Path, log_dir: Path | None) -> dict:
    """One maintenance pass; returns what it did (also stored in kv `disk`)."""
    st = disk_status(data_dir)
    low = st["free_pct"] is not None and st["free_pct"] < LOW_FREE
    slimmed = slim_experiments(reg, days=1 if low else SLIM_AFTER_DAYS)
    logs = trim_logs(log_dir) if log_dir else 0
    st.update(low=low, slimmed=slimmed, logs_removed=logs)
    reg.kv_set("disk", {**(reg.kv_get("disk") or {}), **st})  # keep the breakdown and growth
    if low:
        reg.event("manager", f"disk almost full: {st['free_mb']} MB free ({st['free_pct']:.0%}) – old research "
                  "detail slimmed harder", "warning")
    return st


# ---------------------------------------------------------------------------- what fills the disk
def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def disk_breakdown(data_dir: Path, registry_path: Path, top: int = 8) -> dict:
    """Where the volume's bytes are (2026-11-22: the disk grew ~145 MB/day while the registry
    could explain only ~10–15): every top-level folder, the largest files, and the registry's
    own parts (main file, WAL, free pages). Observation only."""
    data_dir, registry_path = Path(data_dir), Path(registry_path)
    folders: dict[str, int] = {}
    files: list[tuple[int, str]] = []
    for root, _dirs, names in os.walk(data_dir):
        rel = Path(root).relative_to(data_dir)
        key = rel.parts[0] if rel.parts else "."
        if len(rel.parts) >= 2 and rel.parts[0] in ("aitrader", "user_data"):
            key = "/".join(rel.parts[:2])
        for n in names:
            sz = _size(Path(root) / n)
            folders[key] = folders.get(key, 0) + sz
            files.append((sz, str(rel / n)))
    files.sort(reverse=True)
    reg = {"main_mb": round(_size(registry_path) / 2**20, 1),
           "wal_mb": round(_size(registry_path.with_name(registry_path.name + "-wal")) / 2**20, 1)}
    try:
        with sqlite3.connect(registry_path, timeout=10) as c:
            page = c.execute("PRAGMA page_size").fetchone()[0]
            reg["free_mb"] = round(c.execute("PRAGMA freelist_count").fetchone()[0] * page / 2**20, 1)
    except sqlite3.Error:
        pass
    import tempfile
    tmp = sum(_size(Path(dp) / n) for dp, _d, ns in os.walk(tempfile.gettempdir()) for n in ns)
    try:
        root = shutil.disk_usage("/")
        container = {"used_mb": round(root.used / 2**20), "free_mb": round(root.free / 2**20),
                     "tmp_mb": round(tmp / 2**20, 1)}
    except OSError:
        container = {"tmp_mb": round(tmp / 2**20, 1)}
    return {"ts": iso(), "folders_mb": {k: round(v / 2**20, 1) for k, v in sorted(folders.items(), key=lambda kv: -kv[1])},
            "largest": [{"file": f, "mb": round(s / 2**20, 1)} for s, f in files[:top]], "registry": reg,
            "container": container}


def table_sizes(registry_path: Path) -> dict[str, float]:
    """MB per registry table (SQLite dbstat when compiled in; otherwise the length of the stored
    text, which is what this registry is made of). Run a few times a day, not every loop."""
    out: dict[str, float] = {}
    try:
        with sqlite3.connect(registry_path, timeout=10) as c:
            try:
                for name, b in c.execute("SELECT name, SUM(pgsize) FROM dbstat GROUP BY name"):
                    out[name] = round(b / 2**20, 2)
                return dict(sorted(out.items(), key=lambda kv: -kv[1]))
            except sqlite3.Error:
                pass
            tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            for t in tables:
                cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
                expr = " + ".join(f"COALESCE(LENGTH({col}), 0)" for col in cols) or "0"
                b = c.execute(f"SELECT SUM({expr}) FROM {t}").fetchone()[0] or 0
                out[t] = round(b / 2**20, 2)
    except sqlite3.Error:
        return {}
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def checkpoint_wal(registry_path: Path) -> None:
    """Fold the WAL back into the database and truncate it (a WAL only shrinks this way)."""
    try:
        with sqlite3.connect(registry_path, timeout=30) as c:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error as e:
        log.info("WAL checkpoint skipped: %s", e)


def growth(hist: list[dict], st: dict) -> dict:
    """MB/day over the recorded history (one point per hour, last 7 days) and the days until
    the volume is full at that pace."""
    pts = [h for h in hist if h.get("used_mb") is not None and h.get("ts")]
    if len(pts) < 2:
        return {}
    from aitrader.util import parse_dt
    t0, t1 = parse_dt(pts[0]["ts"]), parse_dt(pts[-1]["ts"])
    days = (t1 - t0).total_seconds() / 86400 if t0 and t1 else 0
    if days < 0.25:
        return {}
    rate = (pts[-1]["used_mb"] - pts[0]["used_mb"]) / days
    left = (st.get("free_mb") or 0) / rate if rate > 0 else None
    return {"mb_per_day": round(rate, 1), "days_to_full": round(left, 1) if left is not None else None,
            "over_days": round(days, 2)}


def disk_tick(reg: Registry, data_dir: Path, registry_path: Path, now=None) -> dict:
    """Every 15 min (manager): usage, hourly history → growth and days to full; the folder
    breakdown hourly; table sizes and a WAL checkpoint every 6 hours."""
    now = now or utcnow()
    st = disk_status(data_dir)
    old = reg.kv_get("disk") or {}
    hist = [h for h in (reg.kv_get("disk_hist") or []) if h.get("ts")]
    if not hist or (now - (parse_iso(hist[-1]["ts"]) or now)).total_seconds() >= 3600:
        hist = (hist + [{"ts": iso(now), "used_mb": st["used_mb"]}])[-24 * 7:]
        reg.kv_set("disk_hist", hist)
    out = {**old, **st, "growth": growth(hist, st)}
    last_b = parse_iso((old.get("breakdown") or {}).get("ts"))
    if last_b is None or (now - last_b).total_seconds() >= 3600:
        out["breakdown"] = disk_breakdown(data_dir, registry_path)
    last_t = parse_iso(old.get("tables_ts"))
    if last_t is None or (now - last_t).total_seconds() >= 6 * 3600:
        checkpoint_wal(registry_path)
        out["tables_mb"], out["tables_ts"] = table_sizes(registry_path), iso(now)
    reg.kv_set("disk", out)
    return out


def parse_iso(v):
    from aitrader.util import parse_dt
    return parse_dt(v) if v else None


# ---------------------------------------------------------------------------- janitor
# Everything that grows by itself has an owner here, so the system can run for months
# without anyone cleaning up (owner's rule, 2026-11-22: "мусор нужно удалять").
#   hourly: rotated logs, stale temp files, the registry WAL;
#   daily (housekeeping): old events, slimmed research detail, the signal journal, VACUUM;
#   remote research mode: leftovers of research that used to run on the server;
#   low disk: everything above, harder.
TMP_MAX_AGE_H = 24
LEFTOVER_AGE_D = 2
EVENTS_KEEP_D = 30
EVENTS_KEEP_LOW_D = 7
VERY_LOW_FREE = 0.10


def _delete_old_files(root: Path, max_age_s: float, now_ts: float, keep_root: bool = True) -> tuple[int, int]:
    """Delete regular files older than `max_age_s` under `root`, then empty sub-folders.
    Never follows symlinks; only files this process owns. Returns (files, bytes)."""
    n = b = 0
    root = Path(root)
    if not root.is_dir():
        return 0, 0
    uid = os.getuid() if hasattr(os, "getuid") else None
    for dirpath, _dirs, filenames in os.walk(root, topdown=False, followlinks=False):
        for name in filenames:
            p = Path(dirpath) / name
            try:
                st = p.lstat()
            except OSError:
                continue
            if p.is_symlink() or not p.is_file() or (uid is not None and st.st_uid != uid):
                continue
            if now_ts - st.st_mtime < max_age_s:
                continue
            try:
                p.unlink()
                n += 1
                b += st.st_size
            except OSError:
                pass
        d = Path(dirpath)
        if d != root or not keep_root:
            try:
                d.rmdir()  # only succeeds when empty
            except OSError:
                pass
    return n, b


def clean_tmp(tmp_dir: Path | None = None, max_age_h: float = TMP_MAX_AGE_H, now_ts: float | None = None) -> dict:
    """Stale temp files (the container's /tmp: Freqtrade, pandas, registry snapshots)."""
    import tempfile
    import time
    n, b = _delete_old_files(Path(tmp_dir or tempfile.gettempdir()), max_age_h * 3600, now_ts or time.time())
    return {"files": n, "mb": round(b / 2**20, 1)}


def clean_stale_atomic(state_dir: Path, max_age_s: float = 3600, now_ts: float | None = None) -> int:
    """Half-written `.name.xxxx.tmp` files of atomic writes interrupted by a restart."""
    import time
    now_ts = now_ts or time.time()
    n = 0
    for p in Path(state_dir).glob(".*.tmp"):
        try:
            if p.is_file() and not p.is_symlink() and now_ts - p.stat().st_mtime > max_age_s:
                p.unlink()
                n += 1
        except OSError:
            pass
    return n


def research_leftovers(s) -> list[Path]:
    """Folders only local research writes to. With research on GitHub (mode `remote`) nothing
    current lives there: hyperopt/backtest jobs, downloaded candles, Freqtrade result folders."""
    if getattr(s.research, "mode", "local") != "remote":
        return []
    u = s.user_data
    return [s.jobs_dir, u / "data", u / "backtest_results", u / "hyperopt_results", u / "plot"]


def clean_research_leftovers(s, age_d: float = LEFTOVER_AGE_D, now_ts: float | None = None) -> dict:
    import time
    n = b = 0
    for d in research_leftovers(s):
        fn, fb = _delete_old_files(d, age_d * 86400, now_ts or time.time())
        n, b = n + fn, b + fb
    return {"files": n, "mb": round(b / 2**20, 1)}


def janitor_hourly(reg: Registry, s, now=None) -> dict:
    """Cheap, safe, every hour: rotated logs, stale temp files, research leftovers (remote
    mode only), and the registry WAL folded back. Returns what it freed (kv `janitor`)."""
    now = now or utcnow()
    out = {"ts": iso(now), "logs": trim_logs(s.user_data / "logs")}
    out["tmp"] = clean_tmp()
    out["leftovers"] = clean_research_leftovers(s)
    out["stale_atomic"] = clean_stale_atomic(s.state_dir)
    s.ensure_dirs()  # the folders themselves stay (Freqtrade and the manager expect them)
    checkpoint_wal(s.registry_path)
    prev = reg.kv_get("janitor") or {}
    freed = float(out["tmp"]["mb"]) + float(out["leftovers"]["mb"])
    out["freed_total_mb"] = round(float(prev.get("freed_total_mb") or 0.0) + freed, 1)
    reg.kv_set("janitor", out)
    if freed >= 50:
        reg.event("manager", f"janitor freed {freed:.0f} MB (temp files, old research leftovers)")
    return out


def prune_registry(reg: Registry, free_pct: float | None, now=None) -> dict:
    """Daily: events older than 30 days (7 when the disk is low); when the disk is very low,
    also the charts of every experiment that no live strategy shows."""
    now = now or utcnow()
    low = free_pct is not None and free_pct < LOW_FREE
    very_low = free_pct is not None and free_pct < VERY_LOW_FREE
    keep = EVENTS_KEEP_LOW_D if low else EVENTS_KEEP_D
    with reg.conn() as c:
        ev = c.execute("DELETE FROM events WHERE ts < ?", (iso(now - timedelta(days=keep)),)).rowcount
        c.execute("DELETE FROM equity WHERE ts < ?", (iso(now - timedelta(days=365))[:16],))
    hard = 0
    if very_low:  # last resort before trading could stop: candidates' charts too (verdicts, params stay)
        alive = {r["experiment_id"] for r in reg.q("SELECT experiment_id FROM strategies WHERE stage NOT IN "
                                                   "('retired','rejected')") if r.get("experiment_id")}
        for r in reg.q("SELECT id, result FROM experiments WHERE status='done'"):
            res = r.get("result")
            if isinstance(res, dict) and not res.get("slim") and r["id"] not in alive:
                reg.update("experiments", r["id"], {"result": slim_result(res)})
                hard += 1
    return {"events_deleted": ev, "events_keep_days": keep, "candidates_slimmed": hard}
