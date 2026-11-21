"""Keeps the /data volume from filling up during weeks of unattended running.

What grows without bound otherwise:
  * the registry: every lab run stores ~60 experiment results (equity curve, per-fold
    detail, per-pair stats, ~8–10 KB each), 8–9 runs a day;
  * Freqtrade's log: its rotating handler keeps 10 × 10 MB.

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
import re
import shutil
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
    n = 0
    for r in reg.q("SELECT id, result FROM experiments WHERE status='done' AND finished < ?", (cutoff,)):
        res = r.get("result")
        if not isinstance(res, dict) or res.get("slim") or res.get("verdict") in ("validated", "exploratory"):
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
    reg.kv_set("disk", st)
    if low:
        reg.event("manager", f"disk almost full: {st['free_mb']} MB free ({st['free_pct']:.0%}) – old research "
                  "detail slimmed harder", "warning")
    return st
