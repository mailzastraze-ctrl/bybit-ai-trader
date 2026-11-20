"""The *manifest* is the contract between the brain and the trading bot.

It lists the active strategy sleeves. Each sleeve = family + parameters + the pairs it
owns + its risk budget. A pair is owned by at most one entry-accepting sleeve at a time.
The trading strategy (AIPortfolio) re-reads the file whenever it changes.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from aitrader.util import iso, read_json, write_json_atomic

STAGES_TRADING = ("production", "incubation", "exploration")
STAGE_PRIORITY = {"production": 3, "incubation": 2, "exploration": 1, "closing": 0}


@dataclass
class Sleeve:
    id: str
    family: str
    params: dict
    pairs: list[str]
    stage: str = "exploration"  # production | incubation | exploration | closing
    risk: float = 0.001
    leverage: float = 3.0
    sides: list[str] = field(default_factory=lambda: ["long", "short"])
    score: float = 0.0
    note: str = ""

    @property
    def accept_entries(self) -> bool:
        return self.stage in STAGES_TRADING

    @classmethod
    def from_dict(cls, d: dict) -> Sleeve:
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


@dataclass
class Manifest:
    sleeves: list[Sleeve] = field(default_factory=list)
    updated: str = ""
    version: int = 1
    entries_paused: bool = False  # global kill-switch (account drawdown)

    # ------------------------------------------------------------------ queries
    def by_id(self, sleeve_id: str | None) -> Sleeve | None:
        if not sleeve_id:
            return None
        for s in self.sleeves:
            if s.id == sleeve_id:
                return s
        return None

    def owner_of(self, pair: str) -> Sleeve | None:
        """Entry-accepting sleeve owning the pair (highest stage priority wins)."""
        best = None
        for s in self.sleeves:
            if s.accept_entries and pair in s.pairs:
                if best is None or (STAGE_PRIORITY[s.stage], s.score) > (
                    STAGE_PRIORITY[best.stage], best.score
                ):
                    best = s
        return best

    def all_pairs(self) -> list[str]:
        seen: dict[str, None] = {}
        for s in sorted(self.sleeves, key=lambda x: -STAGE_PRIORITY.get(x.stage, 0)):
            for p in s.pairs:
                seen.setdefault(p, None)
        return list(seen)

    # ------------------------------------------------------------------ io
    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "updated": self.updated,
            "entries_paused": self.entries_paused,
            "sleeves": [asdict(s) for s in self.sleeves],
        }

    @classmethod
    def from_dict(cls, d: dict | None) -> Manifest:
        d = d or {}
        return cls(
            sleeves=[Sleeve.from_dict(x) for x in d.get("sleeves", [])],
            updated=d.get("updated", ""),
            version=int(d.get("version", 1)),
            entries_paused=bool(d.get("entries_paused", False)),
        )

    @classmethod
    def load(cls, path: Path) -> Manifest:
        return cls.from_dict(read_json(path, {}))

    def save(self, path: Path) -> None:
        self.version += 1
        self.updated = iso()
        write_json_atomic(path, self.to_dict())


def write_pairlist(path: Path, pairs: list[str], refresh_period: int = 300) -> None:
    """File consumed by Freqtrade's RemotePairList (file:/// URL)."""
    write_json_atomic(path, {"pairs": list(pairs), "refresh_period": refresh_period})


class ManifestWatcher:
    """Cheap mtime-based reloader used inside the trading strategy."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._mtime = -1.0
        self.manifest = Manifest()

    def refresh(self) -> bool:
        try:
            mtime = os.stat(self.path).st_mtime
        except FileNotFoundError:
            return False
        if mtime != self._mtime:
            self.manifest = Manifest.load(self.path)
            self._mtime = mtime
            return True
        return False
