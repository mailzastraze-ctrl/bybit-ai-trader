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
        assert out["exit_mode"] == 1 and out["sl_atr"] == 2.5 and out["lab_tp"] == 0 and out["lab_trail"] == 3.0
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
    subprocess.run(["node", str(ROOT / "screener" / "screen.js"), "--mode", "pair", "--data", str(data), "--out", str(out),
                    "--combos", "40", "--workers", "1"], check=True, timeout=300)
    res = json.loads(out.read_text())
    assert res["evaluated"] > 300 and res["series"] == 1 and res["holdout_tests"] > 0 and res["fdr_q"] == 0.2
    for sv in res["survivors"]:
        assert sv["pair"] == "SOL/USDT:USDT" and sv["B"]["pf"] >= 1.15 and sv["r2"] >= 0.5 and 0 <= sv["p"] < 0.2
        assert screen.to_params(sv) is not None
    assert screen.summary(res)["n_survivors"] == len(res["survivors"])


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_benjamini_hochberg_threshold():
    out = subprocess.run(["node", "-e", "const S=require(process.argv[1]);console.log(S.bhThreshold([0.001,0.01,0.03,0.2,0.5,0.9],0.2))",
                          str(ROOT / "screener" / "screen.js")], capture_output=True, text=True, check=True)
    assert float(out.stdout) == 0.03


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_pooled_screener_one_config_across_coins(tmp_path):
    data = tmp_path / "candles"
    data.mkdir()
    for i in range(6):  # six coins sharing a slow cycle → a trend config can work on all of them
        rng = np.random.default_rng(10 + i)
        n = 5000
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.005, n) + 0.002 * np.sin(np.arange(n) / (250 + 20 * i))))
        o = np.r_[c[0], c[:-1]]
        (data / f"C{i}_USDT_USDT__1h.json").write_text(json.dumps({
            "t": (1_700_000_000_000 + np.arange(n) * 3_600_000).tolist(), "o": o.tolist(),
            "h": (np.maximum(o, c) * 1.002).tolist(), "l": (np.minimum(o, c) * 0.998).tolist(), "c": c.tolist(), "v": [1] * n}))
    out = tmp_path / "screen-results.json"
    subprocess.run(["node", str(ROOT / "screener" / "screen.js"), "--data", str(data), "--out", str(out),
                    "--combos", "30", "--workers", "1"], check=True, timeout=300)
    res = json.loads(out.read_text())
    assert res["mode"] == "pooled" and res["tasks"] == 10 and res["holdout_tests"] <= 10 * 4
    assert res["survivors"], "a planted cross-coin trend must survive"
    sv = res["survivors"][0]
    assert sv["pooled"] and len(sv["pairs"]) >= 4 and sv["B"]["breadth"] >= 0.55 and sv["B"]["trades"] >= 90
    spec = screen.to_specs(res, 0, 1)[0]
    assert spec["pairs"] == sv["pairs"][:8] and spec["fixed_params"]


def _swing_series(data, n_coins, tf_min, days, seed, trend):
    rng = np.random.default_rng(seed)
    n = int(days * 1440 / tf_min)
    common = np.repeat(rng.choice([-1, 1], size=n // max(1, int(45 * 1440 / tf_min)) + 2), int(45 * 1440 / tf_min))[:n]
    for i in range(n_coins):
        r = trend * common * 0.0016 * (tf_min / 360) + rng.normal(0, 0.012 * np.sqrt(tf_min / 360), n)
        c = 100 * np.exp(np.cumsum(r))
        o = np.r_[c[0], c[:-1]]
        tf = {240: "4h", 360: "6h", 720: "12h"}[tf_min]
        (data / f"C{i}_USDT_USDT__{tf}.json").write_text(json.dumps({
            "t": (1_600_000_000_000 + np.arange(n) * tf_min * 60_000).tolist(), "o": o.tolist(),
            "h": (np.maximum(o, c) * 1.003).tolist(), "l": (np.minimum(o, c) * 0.997).tolist(), "c": c.tolist(), "v": [1] * n}))


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_swing_autopilot_rejects_pure_noise(tmp_path):
    """Random walks have no edge: whatever passes the seven checks by luck must not beat the
    shuffled-history decoys (the search would otherwise 'find' perfect strategies in noise)."""
    data = tmp_path / "candles"
    data.mkdir()
    _swing_series(data, 6, 720, 1200, 5, trend=0.0)
    out = tmp_path / "screen-results.json"
    subprocess.run(["node", str(ROOT / "screener" / "screen.js"), "--mode", "swing", "--data", str(data), "--out", str(out),
                    "--swing-combos", "150", "--top", "3", "--workers", "2"], check=True, timeout=600)
    res = json.loads(out.read_text())
    assert res["swing_tested"] > 0 and res["swing_survivors"] == 0 and res["survivors"] == []


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_swing_autopilot_keeps_a_planted_trend_and_lists_its_coins(tmp_path):
    data = tmp_path / "candles"
    data.mkdir()
    _swing_series(data, 6, 720, 1200, 9, trend=1.0)
    out = tmp_path / "screen-results.json"
    subprocess.run(["node", str(ROOT / "screener" / "screen.js"), "--mode", "swing", "--data", str(data), "--out", str(out),
                    "--swing-combos", "150", "--top", "3", "--workers", "2"], check=True, timeout=600)
    res = json.loads(out.read_text())
    assert res["survivors"], "a trend shared by all coins must beat the decoys"
    sv = res["survivors"][0]
    assert sv["mode"] == "swing" and sv["timeframe"] == "12h" and sv["robust"] >= 0.7 and sv["wf"]["net"] > 0
    assert sv["B"]["net"] >= 0 and sv["mc"]["dd95"] <= 35 and 0.5 <= sv["A"]["tpm"] <= 12 and sv["pairs"][0] == sv["pair"]
    assert len(sv["pairs"]) == sv["coins"]["pass"] >= 2
    specs = screen.to_specs(res, 0, 1)
    assert specs[0]["timeframe"] == "12h" and specs[0]["pairs"] == sv["pairs"] and specs[0]["screen_holdout"]["mode"] == "swing"
    assert screen.to_specs(res, 0, 1, skip={screen.survivor_id(x) for x in res["survivors"]}) == []
    top = screen.summary(res)["top"][0]
    assert top["wf"] and top["coins"] and top["holdout_from"]


def test_warmup_covers_the_indicator_history_of_each_timeframe():
    assert screen.warmup_days("1h") == 35 and screen.warmup_days("6h") >= 180 and screen.warmup_days("12h") >= 360
    assert screen.min_bars("6h") == 3600 and screen.min_bars("1h") == 2000


TWIN_CASES = [  # engine rule, its parameters (incl. symmetric levels), as the screener tries them
    ("ema_cross", {"fast": 9, "slow": 40, "trend": 0}), ("ema_cross", {"fast": 12, "slow": 50, "trend": 200}),
    ("macd", {"fast": 8, "slow": 30, "signal": 7, "zero": 0}), ("macd", {"fast": 12, "slow": 26, "signal": 9, "zero": 1}),
    ("rsi_revert", {"len": 10, "lower": 30, "upper": 70, "exitL": 55, "exitS": 45, "trend": 0}),
    ("rsi_revert", {"len": 5, "lower": 40, "upper": 60, "exitL": 55, "exitS": 45, "trend": 50}),
    ("supertrend", {"len": 10, "mult": 3}), ("adx_di", {"len": 14, "thr": 20}), ("hma_trend", {"len": 40}),
    ("stoch", {"k": 14, "smooth": 3, "dl": 3, "lo": 20, "hi": 80}), ("bb_revert", {"len": 20, "mult": 2}),
    ("donchian", {"entry": 20, "exit": 10}), ("zscore", {"len": 60, "entry": 2.0, "exit": 0.5}),
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("rule,params", TWIN_CASES)
def test_twin_signals_match_the_owner_engine_bar_for_bar(tmp_path, rule, params):
    """A configuration found by the screener must trade exactly what the engine tested: same
    entries and exits on every bar (after indicator warm-up)."""
    import pandas as pd

    from aitrader.families import FAMILIES
    n = 1500
    rng = np.random.default_rng(21)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, n) + 0.0012 * np.sin(np.arange(n) / 60)))
    o = np.r_[c[0], c[:-1]]
    h, low = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n))), np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"t": list(range(n)), "o": o.tolist(), "h": h.tolist(), "l": low.tolist(), "c": c.tolist(), "v": [1] * n}))
    out = subprocess.run(["node", str(ROOT / "screener" / "parity.js"), str(f), rule, json.dumps(params)],
                         check=True, capture_output=True, text=True, timeout=60)
    eng = json.loads(out.stdout)
    sv = {"strategy": rule, "family": {"macd": "macd_cross", "hma_trend": "hull_turn", "stoch": "stoch_cross",
                                       "donchian": "turtle", "zscore": "zscore_revert"}.get(rule, rule),
          "params": params, "exits": {"sl": 2, "tp": 0, "tr": 0}}
    p = screen.to_params(sv)
    df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"), "open": o, "high": h,
                       "low": low, "close": c, "volume": 1.0})
    ours = FAMILIES[sv["family"]].populate(df, p)
    warm = 450
    assert sum(eng["le"][warm:]) + sum(eng["se"][warm:]) > 3, f"{rule}: the sample produced no entries"
    for key, col in (("le", "long_sig"), ("se", "short_sig"), ("lx", "exit_long_sig"), ("sx", "exit_short_sig")):
        a = np.array(eng[key][warm:], dtype=bool)
        b = ours[col].fillna(False).to_numpy(dtype=bool)[warm:]
        mism = np.flatnonzero(a != b)
        assert len(mism) == 0, f"{rule} {key}: {len(mism)} bars differ, first at {warm + mism[0]} (engine {a[mism[0]]})"


def test_strategy_lab_exits_match_the_engine():
    """exit_mode 1 = the engine's exits: ATR stop, chandelier trail on the current ATR from the
    entry, R take profit or none – no break-even, no ratchet."""
    from aitrader.riskcore import EntryContext
    p = screen.to_params({"strategy": "ema_cross", "family": "ema_cross", "params": {"fast": 9, "slow": 40, "trend": 0},
                          "exits": {"sl": 2.5, "tp": 0, "tr": 3}})
    assert p["exit_mode"] == 1 and p["lab_tp"] == 0 and p["lab_trail"] == 3
    ctx = EntryContext(entry=100.0, atr=1.0, is_short=False)
    assert ctx.managed_stop(p, 100.0) == pytest.approx(97.5)                    # initial stop: tighter of sl/trail
    assert ctx.managed_stop(p, 101.0, cur_atr=1.0) == pytest.approx(98.0)       # trail = best − 3 × current ATR
    assert ctx.managed_stop(p, 103.0, cur_atr=2.0) == pytest.approx(97.5)       # wider ATR: trail below the stop
    assert ctx.managed_stop(p, 110.0, cur_atr=1.0) == pytest.approx(107.0)      # no break-even jump, no ratchet
    assert not ctx.tp_hit(1000.0, p)                                            # no take profit
    q = {**p, "lab_tp": 2.0, "lab_trail": 0.0}
    assert ctx.managed_stop(q, 110.0) == pytest.approx(97.5) and ctx.tp_hit(105.0, q) and not ctx.tp_hit(104.9, q)
    s = EntryContext(entry=100.0, atr=1.0, is_short=True)
    assert s.managed_stop(p, 95.0, cur_atr=1.0) == pytest.approx(98.0)
