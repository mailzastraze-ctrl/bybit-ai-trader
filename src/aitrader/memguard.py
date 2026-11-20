"""Memory management so continuous research never starves (or kills) the trading bot.

* container memory from cgroup (v2, fallback v1) → headroom before starting heavy work
* release(): gc + glibc malloc_trim returns freed heap pages to the OS
* adaptive research scale: shrinks after an OOM kill, grows back after successes
"""

from __future__ import annotations

import ctypes
import gc
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

CG2 = Path("/sys/fs/cgroup")
SCALE_STEPS = [  # (pairs_per_experiment, epochs_factor, hyperopt_jobs)
    (3, 0.4, 1),
    (4, 0.6, 1),
    (6, 0.8, 1),
    (8, 1.0, 1),
    (10, 1.0, 2),
]


def _read_int(p: Path) -> int | None:
    try:
        v = p.read_text().strip()
        return None if v in ("max", "") else int(v)
    except (OSError, ValueError):
        return None


def container_memory(root: Path = CG2) -> tuple[int | None, int | None]:
    """(used_bytes, limit_bytes) for this container; None when unknown."""
    used, limit = _read_int(root / "memory.current"), _read_int(root / "memory.max")
    if used is None:  # cgroup v1
        used = _read_int(root / "memory" / "memory.usage_in_bytes")
        limit = _read_int(root / "memory" / "memory.limit_in_bytes")
        if limit and limit > 1 << 60:
            limit = None
    if used is not None:
        # page cache is reclaimable: subtract inactive file pages when available
        try:
            stat = (root / "memory.stat").read_text()
            for line in stat.splitlines():
                k, _, v = line.partition(" ")
                if k == "inactive_file":
                    used = max(0, used - int(v))
                    break
        except OSError:
            pass
    return used, limit


def headroom_mb(root: Path = CG2) -> float | None:
    used, limit = container_memory(root)
    env_limit = os.environ.get("AITRADER_MEMORY_LIMIT_MB")
    if env_limit:
        limit = int(float(env_limit) * 1e6)
    if used is None or not limit:
        return None
    return (limit - used) / 1e6


def wait_for_headroom(need_mb: float, timeout_s: float = 1800, poll_s: float = 15,
                      root: Path = CG2, sleep=time.sleep) -> bool:
    """Block until `need_mb` is free (True) or the timeout passes (False). Unknown → True."""
    deadline = time.monotonic() + timeout_s
    waited = False
    while True:
        h = headroom_mb(root)
        if h is None or h >= need_mb:
            if waited:
                log.info("memory headroom %.0f MB ≥ %.0f MB – continuing", h or -1, need_mb)
            return True
        if time.monotonic() >= deadline:
            log.warning("memory headroom %.0f MB < %.0f MB after waiting – giving up", h, need_mb)
            return False
        if not waited:
            log.info("waiting for memory headroom: %.0f MB free, need %.0f MB", h, need_mb)
            waited = True
        release()
        sleep(poll_s)


def release() -> None:
    """Free unreachable objects and hand freed heap memory back to the OS."""
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


class AdaptiveScale:
    """Research load level persisted in the registry kv store."""

    KEY = "research_scale"

    def __init__(self, reg, default_level: int):
        self.reg = reg
        self.default = max(0, min(default_level, len(SCALE_STEPS) - 1))

    def level(self) -> int:
        st = self.reg.kv_get(self.KEY) or {}
        return int(st.get("level", self.default))

    def params(self) -> tuple[int, float, int]:
        return SCALE_STEPS[self.level()]

    def on_oom(self) -> int:
        lvl = max(0, self.level() - 1)
        self.reg.kv_set(self.KEY, {"level": lvl, "successes": 0})
        self.reg.event("memory", f"research OOM-killed → scale reduced to level {lvl} "
                       f"(pairs/epochs/jobs = {SCALE_STEPS[lvl]})", "warning")
        return lvl

    def on_success(self, promote_after: int = 3) -> int:
        st = self.reg.kv_get(self.KEY) or {}
        lvl, ok = int(st.get("level", self.default)), int(st.get("successes", 0)) + 1
        if ok >= promote_after and lvl < self.default:
            lvl, ok = lvl + 1, 0
            self.reg.event("memory", f"research stable → scale raised to level {lvl}")
        self.reg.kv_set(self.KEY, {"level": lvl, "successes": ok})
        return lvl
