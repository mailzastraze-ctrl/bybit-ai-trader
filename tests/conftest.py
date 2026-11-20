import sys
from pathlib import Path

try:
    import freqtrade.strategy  # noqa: F401
    REAL_FREQTRADE = True
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent / "ftstub"))
    REAL_FREQTRADE = False
