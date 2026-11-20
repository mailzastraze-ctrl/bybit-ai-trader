"""Parsers for Freqtrade output files (backtest zip/json, hyperopt .fthypt)."""

from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path


def _load_last(directory: Path, key: str) -> Path | None:
    marker = directory / ".last_result.json"
    if not marker.is_file():
        return None
    name = json.loads(marker.read_text()).get(key)
    return directory / name if name else None


def load_backtest(directory: Path) -> dict:
    """Return the `strategy` section of the latest backtest export in `directory`."""
    fn = _load_last(Path(directory), "latest_backtest")
    if fn is None or not fn.exists():
        raise FileNotFoundError(f"no backtest result in {directory}")
    if fn.suffix == ".zip":
        with zipfile.ZipFile(fn) as zf:
            inner = fn.with_suffix(".json").name
            data = json.loads(zf.read(inner).decode())
    else:
        data = json.loads(fn.read_text())
    return data


def strategy_stats(data: dict, strategy: str | None = None) -> dict:
    strategies = data.get("strategy", {})
    if not strategies:
        raise ValueError("backtest result has no strategy section")
    if strategy and strategy in strategies:
        return strategies[strategy]
    return next(iter(strategies.values()))


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def load_hyperopt_epochs(results_dir: Path) -> list[dict]:
    fn = _load_last(Path(results_dir), "latest_hyperopt")
    if fn is None or not fn.exists():
        raise FileNotFoundError(f"no hyperopt results in {results_dir}")
    epochs = []
    with fn.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ep = json.loads(line.replace("NaN", "null").replace("Infinity", "1e308"))
            except json.JSONDecodeError:
                continue
            if _finite(ep.get("loss")):
                epochs.append(ep)
    return epochs


def best_epochs(epochs: list[dict], min_trades: int, top: int = 5) -> list[dict]:
    ok = [e for e in epochs
          if (e.get("results_metrics") or {}).get("total_trades", 0) >= min_trades]
    ok.sort(key=lambda e: e["loss"])
    return ok[:top]


def epoch_sharpes(epochs: list[dict], min_trades: int = 10) -> list[float]:
    out = []
    for e in epochs:
        m = e.get("results_metrics") or {}
        s = m.get("sharpe")
        if m.get("total_trades", 0) >= min_trades and _finite(s):
            out.append(float(s))
    return out
