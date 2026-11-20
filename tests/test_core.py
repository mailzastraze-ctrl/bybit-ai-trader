import math
import random
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from helpers import ohlcv

from aitrader import indicators as ta
from aitrader.families import FAMILIES, get_family
from aitrader.manifest import Manifest, ManifestWatcher, Sleeve
from aitrader.riskcore import EntryContext, bars_held, signal_row, size_multiplier, stake_for_risk


# ------------------------------------------------------------------ indicators
def test_indicators_basic_properties():
    df = ohlcv(600)
    r = ta.rsi(df["close"], 14).dropna()
    assert r.between(0, 100).all()
    a = ta.atr(df, 14).dropna()
    assert (a > 0).all()
    adx = ta.adx(df, 14)["adx"].dropna()
    assert adx.between(0, 100).all()
    bb = ta.bollinger(df["close"], 20, 2).dropna()
    assert (bb["bb_upper"] >= bb["bb_lower"]).all()


def test_donchian_excludes_current_bar():
    df = ohlcv(200)
    dc = ta.donchian_prev(df, 10)
    i = 50
    assert dc["dc_high"].iloc[i] == df["high"].iloc[i - 10:i].max()


@pytest.mark.parametrize("name", list(FAMILIES))
def test_family_signals_have_no_lookahead(name):
    """Signals at bar t must not change when future bars are appended/changed."""
    fam = get_family(name)
    df = ohlcv(1500, seed=3)
    full = fam.populate(df, fam.defaults())
    cut = 1200
    part = fam.populate(df.iloc[:cut].copy(), fam.defaults())
    for col in ("long_sig", "short_sig", "exit_long_sig", "exit_short_sig"):
        assert (full[col].iloc[:cut].values == part[col].values).all(), col
    assert np.allclose(full["atr"].iloc[:cut].fillna(0), part["atr"].fillna(0))


@pytest.mark.parametrize("name", list(FAMILIES))
def test_family_produces_signals_and_bounded_conviction(name):
    fam = get_family(name)
    out = fam.populate(ohlcv(3000, seed=5, vol=0.012), fam.defaults())
    assert out["long_sig"].sum() + out["short_sig"].sum() > 0
    assert out["conviction"].between(0.5, 1.5).all()
    assert not out.loc[out["atr"].isna(), ["long_sig", "short_sig"]].any().any()


def test_family_normalize_and_perturb_stay_in_bounds():
    fam = get_family("trend_ema")
    p = fam.normalize({"fast": 999, "sl_atr": -5})
    assert p["fast"] == 30 and p["sl_atr"] == 1.0
    rng = random.Random(1)
    for _ in range(50):
        q = fam.perturb(fam.defaults(), 0.3, rng)
        for prm in fam.params:
            assert prm.low <= q[prm.name] <= prm.high


def test_space_overrides_are_clipped():
    fam = get_family("meanrev_bb")
    sp = fam.space({"tp_rr": [2.0, 99.0], "bb_k": [5.0, 1.0]})
    assert sp["tp_rr"] == (2.0, 5.0)
    assert sp["bb_k"] == (1.5, 3.0)  # invalid → default range


# ------------------------------------------------------------------ riskcore
def test_entry_context_long_and_short():
    p = {"sl_atr": 2.0, "tp_rr": 2.0, "trail_rr": 1.0, "trail_atr": 1.5}
    L = EntryContext(entry=100, atr=1, is_short=False)
    assert L.initial_stop(p) == 98 and L.take_profit(p) == 104
    assert L.managed_stop(p, 101) == 98  # below trail trigger
    assert L.managed_stop(p, 103) == pytest.approx(101.5)  # trailing
    assert L.managed_stop(p, 102.1) == 100.6  # trail, still ≥ break-even
    S = EntryContext(entry=100, atr=1, is_short=True)
    assert S.initial_stop(p) == 102 and S.take_profit(p) == 96
    assert S.managed_stop(p, 97) == pytest.approx(98.5)
    assert S.tp_hit(95.9, p) and not S.tp_hit(96.5, p)


def test_signal_row_live_and_backtest():
    df = ohlcv(50)
    # backtest: trade opens exactly at candle open of bar 10 → signal = bar 9
    od = df["date"].iloc[10].to_pydatetime()
    assert signal_row(df, od, 60)["date"] == df["date"].iloc[9]
    # live: opened a few seconds later
    assert signal_row(df, od + pd.Timedelta(seconds=7), 60)["date"] == df["date"].iloc[9]


def test_bars_held():
    a = datetime(2025, 1, 1, tzinfo=UTC)
    assert bars_held(a, a + pd.Timedelta(hours=5, minutes=59), 60) == 5


def test_stake_for_risk():
    # 10k equity, 1% risk, 2% stop, 3x leverage → margin 1666.67 (notional 5000, loss 100)
    s = stake_for_risk(equity=10_000, risk=0.01, sl_distance_pct=0.02, leverage=3)
    assert s == pytest.approx(1666.6667, rel=1e-4)
    assert s * 3 * 0.02 == pytest.approx(100)
    assert stake_for_risk(equity=10_000, risk=0.01, sl_distance_pct=0.02, leverage=3,
                          max_notional_frac=0.3) == pytest.approx(1000)
    assert stake_for_risk(equity=100, risk=0.001, sl_distance_pct=0.05, leverage=3, min_stake=5) == 0.0
    assert stake_for_risk(equity=0, risk=0.01, sl_distance_pct=0.02, leverage=3) == 0.0
    assert size_multiplier(1.5, 1.0) == 1.5 and size_multiplier(1.5, 0.0) == 1.0


# ------------------------------------------------------------------ manifest
def test_manifest_owner_priority_and_roundtrip(tmp_path):
    m = Manifest(sleeves=[
        Sleeve(id="a", family="trend_ema", params={}, pairs=["BTC", "ETH"], stage="exploration"),
        Sleeve(id="b", family="meanrev_bb", params={}, pairs=["ETH"], stage="production", score=1),
        Sleeve(id="c", family="meanrev_bb", params={}, pairs=["SOL"], stage="closing"),
    ])
    assert m.owner_of("ETH").id == "b"
    assert m.owner_of("BTC").id == "a"
    assert m.owner_of("SOL") is None  # closing sleeves accept no entries
    path = tmp_path / "m.json"
    m.save(path)
    w = ManifestWatcher(path)
    assert w.refresh() and not w.refresh()
    assert w.manifest.by_id("b").stage == "production"
    assert w.manifest.all_pairs()[0] == "ETH"


def test_metrics_are_finite_for_edge_cases():
    from aitrader.research.metrics import summarize
    s = summarize([], 10_000)
    assert s["trades"] == 0
    assert all(not (isinstance(v, float) and math.isnan(v)) for v in s.values())


@pytest.mark.parametrize("name", list(FAMILIES))
def test_genes_filter_signals_without_lookahead(name):
    fam = get_family(name)
    df = ohlcv(2500, seed=9, vol=0.012)
    base = fam.populate(df, fam.defaults())
    p = {**fam.defaults(), "htf_trend": 1, "htf_len": 150, "vol_regime": 2}
    gened = fam.populate(df, p)
    # genes only ever remove entries
    assert not (gened["long_sig"] & ~base["long_sig"]).any()
    assert gened["long_sig"].sum() + gened["short_sig"].sum() <= base["long_sig"].sum() + base["short_sig"].sum()
    part = fam.populate(df.iloc[:2000].copy(), p)
    assert (gened["long_sig"].iloc[:2000].values == part["long_sig"].values).all()
    assert fam.variant(p) == f"{name} +HTF-trend(150) +low-vol"
