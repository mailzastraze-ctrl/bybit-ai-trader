"""F2 (audit 22.11): every pre-registered hypothesis, benchmark and owner system says which data it
has already seen. Re-reading history that chose a configuration never makes that history clean:
TSMOM became the core because it was the only family not losing on the lab's OOS (the last 360 days),
so a one-off read of "the last 12 months" would confirm what it was selected on."""

import json
from pathlib import Path

from aitrader.lifecycle import Lifecycle
from aitrader.registry import Registry
from aitrader.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
RETIRED = {"owner-sol15m-zscore"}  # superseded by -x2, no longer tested


def _needs_provenance(f: Path) -> bool:
    d = json.loads(f.read_text())
    return f.stem not in RETIRED and bool(d.get("benchmark") or d.get("owner"))


FILES = sorted((ROOT / "research" / "hypotheses").glob("*.json")) + [
    f for f in sorted((ROOT / "research" / "external").glob("*.json")) if _needs_provenance(f)]


def test_every_hypothesis_benchmark_and_owner_system_declares_what_it_has_seen():
    assert len(FILES) >= 5
    for f in FILES:
        p = json.loads(f.read_text()).get("provenance")
        assert p, f"{f.name}: no provenance"
        assert p.get("selected_on") and p.get("frozen"), f.name
        assert p.get("seen_data") and all(s.get("what") and s.get("from") and s.get("to") for s in p["seen_data"]), f.name
        assert "forward test from the freeze only" in p["clean_evidence"] and "never confirm" in p["clean_evidence"]


def test_provenance_changes_nothing_the_system_imports(tmp_path):
    """The block is documentation: the hypothesis records, the demo core and the frozen ids stay as they were."""
    s = Settings(data_dir=tmp_path, app_dir=ROOT)
    s.ensure_dirs()
    reg = Registry(s.registry_path)
    life = Lifecycle(s, reg)
    life.import_hypotheses(ROOT / "research" / "hypotheses")
    life.import_core(ROOT / "research" / "external", ROOT / "research" / "hypotheses")
    for rec in list((reg.kv_get("hypotheses") or {}).values()) + list((reg.kv_get("core") or {}).values()):
        assert "provenance" not in rec
