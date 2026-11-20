"""Continuous research loop: scan → generate → run pipeline → learn → repeat (24/7)."""

from __future__ import annotations

import os
import time
import traceback

from aitrader import memguard
from aitrader.learner import Learner
from aitrader.registry import Registry
from aitrader.research.ftrunner import FreqtradeOOM
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
        log.info("market scan: refreshing universe")
        pairs = scanner.refresh()
        log.info("market scan done: %d pairs with enough history: %s", len(pairs), pairs)
        return pairs
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
    lite = os.environ.get("AITRADER_PROFILE", "").lower() == "lite"
    scale = memguard.AdaptiveScale(reg, default_level=2 if lite else 4)
    base_epochs = s.research.epochs
    reg.event("research", "research worker started")
    while True:
        try:
            log.debug("research loop tick")
            if reg.kv_get("research_paused", False):
                reg.heartbeat("research", "paused")
                time.sleep(60)
                continue
            pairs = universe(reg, scanner)
            if len(pairs) < 4:
                log.warning("universe too small (%d pairs: %s) – forcing a rescan in 10 min", len(pairs), pairs)
                reg.kv_set("universe", None)
                reg.heartbeat("research", "waiting", {"reason": "universe too small", "pairs": pairs})
                time.sleep(600)
                continue
            n_pairs, epoch_factor, jobs = scale.params()
            s.research.hyperopt_jobs = jobs
            spec = gen.revalidation_spec(pairs) or gen.next_spec(pairs)
            spec["pairs"] = spec["pairs"][:n_pairs]
            spec["epochs"] = max(30, int(base_epochs * epoch_factor))
            spec["scale_level"] = scale.level()
            eid = reg.new_experiment(spec["family"], spec)
            reg.update("experiments", eid, {"status": "running", "started": iso()})
            log.info("experiment %s: %s on %d pairs", eid, spec["family"], len(spec["pairs"]))
            try:
                result = pipeline.run(eid, spec)
                reg.update("experiments", eid, {"status": "done", "finished": iso(), "result": result,
                                                "progress": {"stage": "done"}})
                scale.on_success()
            except FreqtradeOOM as e:
                log.error("experiment %s hit the memory limit: %s", eid, e)
                reg.update("experiments", eid, {"status": "failed", "finished": iso(),
                                                "error": f"memory: {e}"[:4000]})
                scale.on_oom()
            except Exception as e:  # noqa: BLE001
                log.error("experiment %s failed: %s", eid, e)
                reg.update("experiments", eid, {"status": "failed", "finished": iso(),
                                                "error": f"{e}\n{traceback.format_exc()[-1500:]}"[:4000]})
                reg.event("research", f"experiment {eid} failed: {str(e)[:300]}", "error")
            learner.learn_from_research()
            prune_jobs(s.jobs_dir)
            memguard.release()
            reg.heartbeat("research", "idle", {"last_experiment": eid})
            log.info("experiment %s finished; sleeping %ss", eid, s.research.idle_sleep_s)
            time.sleep(s.research.idle_sleep_s)
        except Exception as e:  # noqa: BLE001 – never die
            log.exception("research loop error")
            reg.heartbeat("research", "error", {"error": str(e)[:500]})
            time.sleep(120)


if __name__ == "__main__":
    main()
