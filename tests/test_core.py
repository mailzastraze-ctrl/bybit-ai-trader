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
    df = ohlcv(3000, seed=5, vol=0.012)
    if name == "funding_reversal":  # synthetic 8h funding that swings between crowded regimes
        import numpy as np
        f = 0.0001 + 0.0006 * np.sin(np.arange(len(df)) / 90.0) + np.random.default_rng(3).normal(0, 0.0001, len(df))
        df["funding"] = np.where(np.arange(len(df)) % 8 == 0, f, np.nan)
    if name == "oi_flow":  # open interest that rises with trends and drops on reversals
        import numpy as np
        df["oi"] = 1e6 * np.exp(np.cumsum(np.random.default_rng(4).normal(0, 0.01, len(df))) + 0.3 * np.sin(np.arange(len(df)) / 40))
    if name == "rel_strength":  # a market (BTC) series the coin drifts against
        df["mkt_close"] = ohlcv(3000, seed=9, vol=0.008)["close"].values
    out = fam.populate(df, fam.defaults())
    assert out["long_sig"].sum() + out["short_sig"].sum() > 0
    assert out["conviction"].between(0.5, 1.5).all()
    assert not out.loc[out["atr"].isna(), ["long_sig", "short_sig"]].any().any()


def test_funding_family_is_silent_without_funding_data():
    fam = get_family("funding_reversal")
    out = fam.populate(ohlcv(1500, seed=2), fam.defaults())
    assert out["long_sig"].sum() + out["short_sig"].sum() == 0


def test_tsmom_follows_persistent_trend():
    import numpy as np
    import pandas as pd
    fam = get_family("tsmom")
    n = 2000
    close = 100 * np.exp(np.cumsum(np.r_[np.full(1000, 0.002), np.full(1000, -0.002)] + np.random.default_rng(1).normal(0, 0.004, n)))
    df = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC"), "open": close, "high": close * 1.002,
                       "low": close * 0.998, "close": close, "volume": 1000.0})
    out = fam.populate(df, fam.defaults())
    assert out["long_sig"][:1000].sum() > out["short_sig"][:1000].sum()
    assert out["short_sig"][1300:].sum() > out["long_sig"][1300:].sum()


def test_profit_protection_breakeven_and_ratchet():
    from aitrader.riskcore import EntryContext
    p = {"sl_atr": 2.0, "tp_rr": 5.0, "trail_rr": 3.0, "trail_atr": 1.5, "be_rr": 0.5, "lock_rr": 1.0, "lock_frac": 0.5}
    L = EntryContext(entry=100.0, atr=1.0, is_short=False)  # R = 2.0
    assert L.managed_stop(p, 100.5) == 98.0  # 0.25R: initial stop
    be = L.managed_stop(p, 101.2)  # 0.6R: break-even + fee buffer, still below best
    assert 100.0 < be < 101.2
    assert L.managed_stop(p, 103.0) == pytest.approx(101.5)  # 1.5R: half of +3 locked
    S = EntryContext(entry=100.0, atr=1.0, is_short=True)
    assert S.managed_stop(p, 97.0) == pytest.approx(98.5)
    assert 98.8 < S.managed_stop(p, 98.8) < 100.0  # short break-even


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


def test_ported_strategy_lab_families_signal_and_stay_causal():
    import numpy as np
    import pandas as pd

    from aitrader.families import FAMILIES
    rng = np.random.default_rng(3)
    n = 1500
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)) + 0.3 * np.sin(np.arange(n) / 60))
    df = pd.DataFrame({"open": c, "high": c * 1.004, "low": c * 0.996, "close": c, "volume": 1.0})
    for name in ("supertrend", "macd_cross", "adx_di", "hull_turn", "rsi_revert", "stoch_cross", "zscore_revert"):
        fam = FAMILIES[name]
        prm = fam.defaults() | ({"z_entry": 2.0} if name == "zscore_revert" else {})
        full = fam.populate(df, prm)
        assert full["long_sig"].sum() > 0 and full["short_sig"].sum() > 0, name
        cut = fam.populate(df.iloc[:1000], prm)  # no look-ahead: past signals don't change
        assert (cut["long_sig"].to_numpy() == full["long_sig"].iloc[:1000].to_numpy()).all(), name


def test_relative_strength_is_silent_without_market_data():
    fam = get_family("rel_strength")
    out = fam.populate(ohlcv(1500, seed=2), fam.defaults())
    assert out["long_sig"].sum() + out["short_sig"].sum() == 0


def test_oi_family_is_silent_without_open_interest():
    fam = get_family("oi_flow")
    out = fam.populate(ohlcv(1500, seed=2), fam.defaults())
    assert out["long_sig"].sum() + out["short_sig"].sum() == 0


def test_careful_trader_exit_rules_are_off_by_default_and_only_tighten():
    from datetime import datetime, timezone

    from aitrader.families import FAMILIES
    from aitrader.riskcore import EntryContext

    p = FAMILIES["ema_cross"].normalize({"sl_atr": 2.0, "tp_rr": 3.0, "be_rr": 1.0, "lock_rr": 1.5, "lock_frac": 0.4,
                                          "trail_rr": 3.0, "trail_atr": 2.5})
    ctx = EntryContext(entry=100.0, atr=1.0, is_short=False)       # R = 2, TP = 106
    calm = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)          # no US release within 8 h
    base = ctx.managed_stop(p, 105.4)                              # 2.7 R: ratchet locks 40% of 5.4
    assert base == pytest.approx(102.16)
    assert ctx.managed_stop(p, 105.4, now=calm, cur_atr=3.0) == base  # genes off: identical to before
    # near the take profit (90% of the way): keep 75% of the best open profit
    assert ctx.managed_stop({**p, "tp_near": 0.85, "tp_lock": 0.75}, 105.4) == pytest.approx(104.05)
    assert ctx.managed_stop({**p, "tp_near": 0.95, "tp_lock": 0.75}, 105.4) == base   # not that close yet
    # 1 h before the 10 Nov 2026 CPI release (13:30 UTC): lock half of the profit
    before_cpi = datetime(2026, 11, 10, 12, 30, tzinfo=timezone.utc)
    assert ctx.managed_stop({**p, "event_lock": 1}, 105.4, now=before_cpi) == pytest.approx(102.7)
    assert ctx.managed_stop({**p, "event_lock": 1}, 105.4, now=calm) == base
    # volatility shock: ATR doubled → trail 2.5 ATR(entry) from the best price
    assert ctx.managed_stop({**p, "vol_shock": 2}, 105.4, cur_atr=2.1) == pytest.approx(102.9)
    assert ctx.managed_stop({**p, "vol_shock": 2}, 105.4, cur_atr=1.5) == base
    # a short mirrors everything, and nothing ever loosens the initial stop
    s = EntryContext(entry=100.0, atr=1.0, is_short=True)
    assert s.managed_stop({**p, "tp_near": 0.85}, 94.6) == pytest.approx(95.95)
    assert ctx.managed_stop({**p, "tp_near": 0.5, "event_lock": 2, "vol_shock": 1}, 99.0, now=before_cpi, cur_atr=9) == 98.0
    assert ctx.break_even() == pytest.approx(100.12) and s.break_even() == pytest.approx(99.88)
