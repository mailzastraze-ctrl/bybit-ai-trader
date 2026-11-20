"""Continuous research loop: scan → generate → run pipeline → learn → repeat (24/7)."""

from __future__ import annotations

import time
import traceback

from aitrader.learner import Learner
from aitrader.registry import Registry
from aitrader.research.generator import Generator
from aitrader.research.pipeline import Pipeline
from aitrader.scanner import Scanner
from aitrader.settings import get_settings
from aitrader.util import iso, parse_dt, setup_logging, utcnow

log = setup_logging("research")
UNIVERSE_MAX_AGE_H = 12
KEEP_JOBS = 12


def prune_jobs(jobs_dir) -> None:
    """Keep disk usage bounded: results live in the registry, job folders are scratch."""
    import shutil
    dirs = sorted((d for d in jobs_dir.iterdir() if d.is_dir() and not d.name.startswith("_")),
                  key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs[KEEP_JOBS:]:
        shutil.rmtree(d, ignore_errors=True)


def universe(reg: Registry, scanner: Scanner) -> list[str]:
    u = reg.kv_get("universe") or {}
    ts = parse_dt(u.get("ts"))
    if not u.get("pairs") or ts is None or (utcnow() - ts).total_seconds() > UNIVERSE_MAX_AGE_H * 3600:
        reg.heartbeat("research", "busy", {"stage": "market scan"})
        return scanner.refresh()
    return u["pairs"]


def main() -> None:
    s = get_settings()
    s.ensure_dirs()
    reg = Registry(s.registry_path)
    pipeline, scanner, gen, learner = Pipeline(s, reg), Scanner(s, reg), Generator(s, reg), Learner(s, reg)
    # experiments left "running" by a crash/redeploy are marked failed
    for r in reg.q("SELECT id FROM experiments WHERE status='running'"):
        reg.update("experiments", r["id"], {"status": "failed", "error": "interrupted (restart)",
                                            "finished": iso()})
    reg.event("research", "research worker started")
    while True:
        try:
            if reg.kv_get("research_paused", False):
                reg.heartbeat("research", "paused")
                time.sleep(60)
                continue
            pairs = universe(reg, scanner)
            if len(pairs) < 4:
                reg.heartbeat("research", "waiting", {"reason": "universe too small", "pairs": pairs})
                time.sleep(600)
                continue
            spec = gen.next_spec(pairs)
            eid = reg.new_experiment(spec["family"], spec)
            reg.update("experiments", eid, {"status": "running", "started": iso()})
            log.info("experiment %s: %s on %d pairs", eid, spec["family"], len(spec["pairs"]))
            try:
                result = pipeline.run(eid, spec)
                reg.update("experiments", eid, {"status": "done", "finished": iso(), "result": result,
                                                "progress": {"stage": "done"}})
            except Exception as e:  # noqa: BLE001
                log.error("experiment %s failed: %s", eid, e)
                reg.update("experiments", eid, {"status": "failed", "finished": iso(),
                                                "error": f"{e}\n{traceback.format_exc()[-1500:]}"[:4000]})
                reg.event("research", f"experiment {eid} failed: {str(e)[:300]}", "error")
            learner.learn_from_research()
            prune_jobs(s.jobs_dir)
            reg.heartbeat("research", "idle", {"last_experiment": eid})
            time.sleep(s.research.idle_sleep_s)
        except Exception as e:  # noqa: BLE001 – never die
            log.exception("research loop error")
            reg.heartbeat("research", "error", {"error": str(e)[:500]})
            time.sleep(120)


if __name__ == "__main__":
    main()
