"""Stage-1 screener: owner's engine in Node → survivors → fixed-config walk-forward specs."""

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from aitrader.families import FAMILIES
from aitrader.research import screen

ROOT = Path(__file__).resolve().parents[1]
ENGINE_PARAMS = {
    "zscore": {"len": 50, "entry": 2.0, "exit": 0.5}, "supertrend": {"len": 10, "mult": 3},
    "macd": {"fast": 12, "slow": 26, "signal": 9, "zero": 1}, "adx_di": {"len": 14, "thr": 25},
    "hma_trend": {"len": 55}, "rsi_revert": {"len": 14, "lower": 30, "upper": 70, "exitL": 55, "exitS": 45, "trend": 200},
    "stoch": {"k": 14, "smooth": 3, "dl": 3, "lo": 20, "hi": 80}, "ema_cross": {"fast": 12, "slow": 26, "trend": 0},
    "bb_revert": {"len": 20, "mult": 2}, "donchian": {"entry": 20, "exit": 10},
}


def test_every_screened_strategy_maps_onto_a_twin_family():
    fam_of = {"zscore": "zscore_revert", "supertrend": "supertrend", "macd": "macd_cross", "adx_di": "adx_di",
              "hma_trend": "hull_turn", "rsi_revert": "rsi_revert", "stoch": "stoch_cross", "ema_cross": "ema_cross",
              "bb_revert": "bb_revert", "donchian": "turtle"}
    for sid, p in ENGINE_PARAMS.items():
        sv = {"strategy": sid, "family": fam_of[sid], "params": p, "exits": {"sl": 2.5, "tp": 0, "tr": 3}, "pair": "SOL/USDT:USDT"}
        out = screen.to_params(sv)
        assert out is not None, sid
        assert out == FAMILIES[fam_of[sid]].normalize(out)  # inside the family's ranges
        assert out["sl_atr"] == 2.5 and out["tp_rr"] == 5.0 and out["trail_atr"] == 3.0 and out["trail_rr"] == 0.5
    assert screen.to_params({"strategy": "macd", "family": "macd_cross", "params": ENGINE_PARAMS["macd"]})["macd_gap"] == 14


def test_specs_round_robin_over_runners():
    sv = [{"strategy": "supertrend", "family": "supertrend", "pair": f"P{i}/USDT:USDT", "timeframe": "15m",
           "params": {"len": 10 + i, "mult": 3}, "exits": {"sl": 2, "tp": 2, "tr": 0}} for i in range(9)]
    a, b = screen.to_specs({"survivors": sv}, 0, 4), screen.to_specs({"survivors": sv}, 1, 4)
    assert [x["pairs"][0] for x in a] == ["P0/USDT:USDT", "P4/USDT:USDT", "P8/USDT:USDT"]
    assert b[0]["fixed_params"]["st_len"] == 11 and b[0]["timeframe"] == "15m" and b[0]["screen"].startswith("scr-")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_node_screener_end_to_end(tmp_path):
    data = tmp_path / "candles"
    data.mkdir()
    rng = np.random.default_rng(5)
    n = 6000
    r = rng.normal(0, 0.004, n) + 0.002 * np.sin(np.arange(n) / 300)
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    (data / "SOL_USDT_USDT__1h.json").write_text(json.dumps({
        "t": (1_700_000_000_000 + np.arange(n) * 3_600_000).tolist(), "o": o.tolist(),
        "h": (np.maximum(o, c) * 1.002).tolist(), "l": (np.minimum(o, c) * 0.998).tolist(), "c": c.tolist(), "v": [1] * n}))
    out = tmp_path / "screen-results.json"
    subprocess.run(["node", str(ROOT / "screener" / "screen.js"), "--data", str(data), "--out", str(out),
                    "--combos", "40", "--workers", "1"], check=True, timeout=300)
    res = json.loads(out.read_text())
    assert res["evaluated"] > 300 and res["series"] == 1
    for sv in res["survivors"]:
        assert sv["pair"] == "SOL/USDT:USDT" and sv["B"]["pf"] >= 1.15 and sv["r2"] >= 0.5
        assert screen.to_params(sv) is not None
    assert screen.summary(res)["n_survivors"] == len(res["survivors"])
