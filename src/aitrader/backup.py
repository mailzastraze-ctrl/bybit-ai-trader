"""Write bounded, consistent SQLite backups to the private Railway volume."""

from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from aitrader.util import utcnow


def backup_databases(state: Path, keep: int = 7) -> dict[str, str]:
    target = state / "backups"
    target.mkdir(mode=0o700, exist_ok=True)
    today = utcnow().date().isoformat()
    saved = {}
    for name in ("registry", "trades"):
        source = state / f"{name}.sqlite"
        if not source.is_file():
            continue
        snapshot = target / f"{name}-{today}.sqlite.gz"
        if not snapshot.is_file():
            if shutil.disk_usage(target).free < 3 * source.stat().st_size + 16 * 1024**2:
                raise OSError("Insufficient free volume space for SQLite backup")
            with tempfile.TemporaryDirectory(dir=target) as tmp:
                db = Path(tmp) / "snapshot.sqlite"
                with closing(sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True, timeout=15)) as src:
                    with closing(sqlite3.connect(db)) as dst:
                        src.backup(dst)
                        if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                            raise OSError(f"{name} snapshot failed SQLite quick_check")
                archive = Path(tmp) / "snapshot.sqlite.gz"
                with db.open("rb") as inp, gzip.open(archive, "wb", compresslevel=4) as out:
                    shutil.copyfileobj(inp, out)
                archive.chmod(0o600)
                os.replace(archive, snapshot)
        for old in sorted(target.glob(f"{name}-????-??-??.sqlite.gz"), reverse=True)[keep:]:
            old.unlink()
        saved[name] = snapshot.name
    return saved
