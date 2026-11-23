import sys
from pathlib import Path

try:
    import freqtrade.strategy  # noqa: F401
    REAL_FREQTRADE = True
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent / "ftstub"))
    REAL_FREQTRADE = False

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _lanes_mode_for_legacy_tests(monkeypatch):
    """Production trades coin desks without the monthly core (owner, 23.11.2026). The lane and
    core tests describe the earlier mode, which stays available (DEMO_MODE=lanes, DEMO_CORE=1);
    the desk tests switch the mode explicitly."""
    monkeypatch.setenv("DEMO_MODE", "lanes")
    monkeypatch.setenv("DEMO_CORE", "1")
