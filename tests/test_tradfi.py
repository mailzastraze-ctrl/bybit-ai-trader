"""TradFi lane: gold (XAU/USDT:USDT) and the S&P 500 (SPY/USDT:USDT) next to the crypto book
(owner's request 2026-11-23). What must hold:

1. instruments and universe: the right contracts, never SPX6900 (SPXUSDT, a memecoin), never a
   crypto research pair, never in the lab's search;
2. sessions: entries only while the underlying market is open (NYSE incl. holidays, early closes
   and DST; gold Globex hours), exits always;
3. strategies: Gold Regime, Momentum Rotation (new, causal) and Trend Following (= the TSMOM
   benchmark construction);
4. portfolio: own sleeves outside the crypto slots, exploration risk × correlation scale, 1x,
   stricter TradFi caps, circuit breaker, crypto unchanged;
5. execution and recovery: order + exchange-stop test on the lane, a TradFi trade keeps its own
   plan after a restart or when the lane is switched off, availability does not flap.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from aitrader import tradfi
from aitrader.families import FAMILIES, TRADFI_FAMILIES, get_family
from aitrader.lifecycle import Lifecycle
from aitrader.manifest import Manifest, Sleeve
from aitrader.registry import Registry
from aitrader.settings import Settings

XAU, SPY, BTC = "XAU/USDT:USDT", "SPY/USDT:USDT", "BTC/USDT:USDT"
ROOT = Path(__file__).resolve().parents[1]


def utc(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


def candles(n: int, start: str, freq: str = "4h", drift: float = 0.0, seed: int = 1, vol: float = 0.004,
            close: np.ndarray | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if close is None:
        close = 100 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    sp = np.abs(rng.normal(0, vol / 2, n)) * close
    return pd.DataFrame({"date": pd.date_range(start, periods=n, freq=freq, tz="UTC"), "open": open_,
                         "high": np.maximum(open_, close) + sp, "low": np.minimum(open_, close) - sp,
                         "close": close, "volume": rng.lognormal(10, 0.3, n)})


# ============================================================== 1. instruments and universe
def test_instruments_are_gold_and_the_sp500_etf_never_the_spx6900_memecoin():
    assert tradfi.TRADFI_PAIRS == (XAU, SPY)
    assert tradfi.INSTRUMENTS[SPY]["symbol"] == "SPYUSDT" and tradfi.INSTRUMENTS[XAU]["symbol"] == "XAUUSDT"
    assert not tradfi.is_tradfi("SPX/USDT:USDT") and "memecoin" in tradfi.NOT_TRADFI["SPX/USDT:USDT"]
    assert not tradfi.is_tradfi(BTC) and not tradfi.is_tradfi(None)
    assert tradfi.peer_of(XAU) == SPY and tradfi.peer_of(SPY, [XAU, SPY]) == XAU


def test_tradfi_families_are_resolvable_but_never_searched_by_the_lab():
    assert set(TRADFI_FAMILIES) == {"gold_regime", "tradfi_rotation"}
    assert not set(TRADFI_FAMILIES) & set(FAMILIES)  # bandit/generator/screener/explorers iterate FAMILIES
    assert len(FAMILIES) == 18  # the crypto search is unchanged
    for name in TRADFI_FAMILIES:
        assert get_family(name).name == name
    with pytest.raises(ValueError):
        get_family("no_such_family")


def test_crypto_research_universe_never_contains_tradfi_pairs(tmp_path, monkeypatch):
    from aitrader import scanner as scmod
    s = Settings(data_dir=tmp_path, app_dir=ROOT)
    s.ensure_dirs()
    reg = Registry(s.registry_path)

    class Runner:
        def write_config(self, job, name, cfg):
            return tmp_path / name

        def test_pairlist(self, job, cfg):  # VolumePairList: gold and SPY trade a lot of volume
            return [BTC, XAU, "ETH/USDT:USDT", SPY, "SPX/USDT:USDT"]

        def download(self, *a, **k):
            pass

    monkeypatch.setattr(scmod, "pairs_with_history", lambda s_, pairs, days: list(pairs))
    uni = scmod.Scanner(s, reg, runner=Runner()).refresh()
    assert XAU not in uni and SPY not in uni
    assert "SPX/USDT:USDT" in uni  # SPX6900 is a crypto coin and stays one
    reg.kv_set(tradfi.K_STATE, {"available": {XAU: True, SPY: False}})
    tu = scmod.Scanner(s, reg, runner=Runner()).tradfi_universe()
    assert tu["pairs"] == [XAU] and tu["instruments"][SPY]["available"] is False


# ============================================================== 2. sessions
@pytest.mark.parametrize("ts, pair, is_open", [
    ("2026-11-23 15:00", SPY, True),    # Monday 10:00 New York
    ("2026-11-23 14:15", SPY, False),   # 09:15, before the open
    ("2026-11-23 21:00", SPY, False),   # 16:00, the close
    ("2026-11-26 16:00", SPY, False),   # Thanksgiving
    ("2026-11-27 17:30", SPY, True),    # day after Thanksgiving, 12:30
    ("2026-11-27 18:30", SPY, False),   # early close at 13:00
    ("2026-11-28 16:00", SPY, False),   # Saturday
    ("2026-07-06 13:45", SPY, True),    # summer time: 09:45 EDT
    ("2026-07-06 20:00", SPY, False),   # 16:00 EDT
    ("2026-11-22 22:30", XAU, False),   # Sunday 17:30 New York: not yet
    ("2026-11-22 23:30", XAU, True),    # Sunday 18:30: Globex open
    ("2026-11-24 22:30", XAU, False),   # Tuesday 17:30: daily break
    ("2026-11-24 23:30", XAU, True),
    ("2026-11-27 22:30", XAU, False),   # Friday 17:30: closed for the weekend
    ("2026-11-28 12:00", XAU, False),   # Saturday
    ("2026-12-25 15:00", XAU, False),   # Christmas
    ("2026-11-28 12:00", BTC, True),    # crypto: always
])
def test_underlying_sessions(ts, pair, is_open):
    assert bool(tradfi.session_open(pd.Series([utc(ts)]), pair).iloc[0]) is is_open
    assert tradfi.is_open_now(pair, utc(ts).to_pydatetime()) is is_open


def test_next_open_after_the_weekend():
    nxt = tradfi.next_open(SPY, utc("2026-11-28 12:00").to_pydatetime())
    assert pd.Timestamp(nxt) == utc("2026-11-30 14:30")


def _sig_frame(dates, long_idx=(), exit_idx=()):
    n = len(dates)
    ls = np.zeros(n, bool)
    ls[list(long_idx)] = True
    ex = np.zeros(n, bool)
    ex[list(exit_idx)] = True
    return pd.DataFrame({"date": dates, "long_sig": ls, "short_sig": np.zeros(n, bool), "exit_long_sig": ex,
                         "exit_short_sig": np.zeros(n, bool)})


def test_entry_gate_carries_a_weekend_signal_to_the_open_unless_the_setup_is_gone():
    dates = pd.date_range("2026-11-27 12:00", periods=20, freq="4h", tz="UTC")  # Fri 12:00 → Mon 16:00 UTC
    # decision times (close): Fri 16:00 (open) … Fri 20:00 (open, 15:00 NY) … weekend (closed) … Mon 16:00 (open)
    i_sat = int(np.where(dates == utc("2026-11-28 08:00"))[0][0])
    res = tradfi.gate_entries(_sig_frame(dates, long_idx=[i_sat]), SPY)
    fired = list(res.index[res["long_sig"]])
    assert len(fired) == 1
    t_fire = res["date"].iloc[fired[0]] + pd.Timedelta(hours=4)
    assert tradfi.is_open_now(SPY, t_fire.to_pydatetime()) and t_fire > utc("2026-11-30 14:30")
    # the strategy's own exit came on before the open: the stale signal is dropped
    i_mon = fired[0]
    gone = tradfi.gate_entries(_sig_frame(dates, long_idx=[i_sat], exit_idx=[i_mon]), SPY)
    assert not gone["long_sig"].any()
    # exits are never gated; crypto passes unchanged
    assert gone["exit_long_sig"].sum() == 1
    raw = _sig_frame(dates, long_idx=[i_sat])
    assert tradfi.gate_entries(raw, BTC) is raw


def test_entry_gate_is_causal():
    df = candles(900, "2026-05-01")
    sig = _sig_frame(df["date"], long_idx=range(0, 900, 7), exit_idx=range(3, 900, 11))
    full = tradfi.gate_entries(sig, SPY)
    part = tradfi.gate_entries(sig.iloc[:600].copy(), SPY)
    assert (full["long_sig"].iloc[:600].to_numpy() == part["long_sig"].to_numpy()).all()


# ============================================================== 3. strategies
def _regime_path(n=1600, seed=4):
    """Bull regime with pullbacks, then a bear regime."""
    t = np.arange(n)
    trend = np.where(t < n // 2, 0.0012, -0.0012)
    wave = 0.03 * np.sin(t / 9.0)  # pullbacks deeper than the drift
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(trend + np.diff(np.concatenate([[0], wave])) + rng.normal(0, 0.002, n)))


def test_gold_regime_buys_pullbacks_in_a_bull_regime_and_sells_in_a_bear_regime():
    fam = get_family("gold_regime")
    df = candles(1600, "2025-06-01", close=_regime_path())
    out = fam.populate(df, fam.defaults())
    n = len(df)
    assert out["long_sig"].iloc[: n // 2 + 50].sum() > 3 and out["long_sig"].iloc[n // 2 + 200:].sum() == 0
    assert out["short_sig"].iloc[n // 2 + 200:].sum() > 3 and out["short_sig"].iloc[: n // 2].sum() == 0
    assert out["exit_long_sig"].iloc[-100:].all()
    assert out["conviction"].between(0.5, 1.5).all()


@pytest.mark.parametrize("name", sorted(TRADFI_FAMILIES))
def test_tradfi_families_are_causal(name):
    fam = get_family(name)
    df = candles(1500, "2025-06-01", close=_regime_path(1500))
    df["peer_close"] = candles(1500, "2025-06-01", seed=9, drift=0.0003)["close"].to_numpy()
    full = fam.populate(df, fam.defaults())
    part = fam.populate(df.iloc[:1100].copy(), fam.defaults())
    for col in ("long_sig", "short_sig", "exit_long_sig", "exit_short_sig"):
        assert (full[col].iloc[:1100].to_numpy() == part[col].to_numpy()).all(), col


def test_rotation_holds_the_leader_long_only_and_needs_the_other_asset():
    fam = get_family("tradfi_rotation")
    df = candles(1200, "2025-06-01", drift=0.0012, seed=2)
    silent = fam.populate(df, fam.defaults())
    assert not silent[["long_sig", "short_sig"]].any().any()  # no peer data → no signals
    df["peer_close"] = candles(1200, "2025-06-01", drift=-0.0004, seed=5)["close"].to_numpy()
    out = fam.populate(df, fam.defaults())
    assert out["long_sig"].iloc[500:].mean() > 0.5 and not out["short_sig"].any()
    # roles swapped: the asset now lags its peer → no entries, exit on
    swapped = df.assign(close=df["peer_close"], peer_close=df["close"])
    out2 = fam.populate(swapped, fam.defaults())
    assert out2["long_sig"].iloc[500:].sum() == 0 and out2["exit_long_sig"].iloc[500:].mean() > 0.5


def test_preregistered_configs_load_and_trend_following_is_the_benchmark_rule():
    cfg = {json.loads(f.read_text())["id"]: json.loads(f.read_text()) for f in (ROOT / "research" / "tradfi").glob("*.json")}
    assert {"tf-trend-4h-30d", "tf-gold-regime-4h", "tf-rotation-4h-60d"} <= set(cfg)
    bench = json.loads((ROOT / "research" / "external" / "benchmark-tsmom-4h-30d.json").read_text())
    tf = cfg["tf-trend-4h-30d"]
    assert tf["family"] == bench["family"] == "tsmom" and tf["timeframe"] == bench["timeframe"]
    fam = get_family("tsmom")
    assert fam.normalize(tf["params"]) == fam.normalize(bench["params"])
    assert cfg["tf-gold-regime-4h"]["pairs"] == [XAU]
    assert cfg["tf-rotation-4h-60d"]["sides"] == ["long"]
    for k in ("tf-trend-4h-30d", "tf-gold-regime-4h", "tf-rotation-4h-60d"):
        d = cfg[k]
        assert all(tradfi.is_tradfi(p) for p in d["pairs"]) and d["preregistration"]["decision_rule"]
        assert get_family(d["family"]).normalize(d["params"])["sl_atr"] >= 3.0  # wide stops for multi-week holds
        assert XAU not in d["demo_pairs"]  # gold on demo: only the autopilot's best


# ============================================================== 4. portfolio: lifecycle + manifest
@pytest.fixture
def env(tmp_path):
    s = Settings(data_dir=tmp_path, app_dir=ROOT)
    s.ensure_dirs()
    s.lifecycle.tradfi_enabled = True
    return s, Registry(s.registry_path)


def _crypto_row(reg, sid, pairs):
    reg.upsert("strategies", {"id": sid, "experiment_id": "", "family": "trend_ema", "params": {}, "pairs": pairs,
                              "sides": ["long", "short"], "stage": "exploration", "score": 1.0, "oos": {}, "gates": {},
                              "live": {}, "created": "2020-01-01", "updated": "2020-01-01",
                              "stage_since": "2020-01-01T00:00:00Z", "history": []})


def test_lane_sleeves_are_separate_from_crypto_and_crypto_is_unchanged(env):
    s, reg = env
    life = Lifecycle(s, reg)
    _crypto_row(reg, "c1", [BTC, XAU, "ETH/USDT:USDT"])  # a crypto strategy that somehow lists gold
    life.import_core(ROOT / "research" / "external", ROOT / "research" / "hypotheses")
    before = life.build_manifest([], set(), False).to_dict()["sleeves"]
    assert life.import_tradfi(ROOT / "research" / "tradfi") == len(list((ROOT / "research" / "tradfi").glob("*.json")))
    reg.kv_set(tradfi.K_STATE, {"available": {XAU: True, SPY: True}, "scale": {XAU: 1.0, SPY: 0.8}})
    man = life.build_manifest([], set(), False)
    after = man.to_dict()["sleeves"]
    lane = [x for x in man.sleeves if x.note == "tradfi"]
    assert [x for x in after if x["note"] != "tradfi"] == before  # crypto + core exactly as before
    c1 = man.by_id("c1")
    assert XAU not in c1.pairs and BTC in c1.pairs  # gold belongs to the lane only
    for x in lane:
        assert x.stage == "exploration" and x.leverage == 1.0 and x.timeframe in ("4h", "12h")
        assert all(tradfi.is_tradfi(p) for p in x.pairs)
    # on demo gold trades only with the autopilot's best strategy (owner, 23.11); the pre-registered
    # gold configurations stay hypotheses (`demo_pairs`)
    best = [x for x in lane if XAU in x.pairs]
    assert len(best) == 1 and best[0].id.startswith("xau-") and man.sleeves_for(XAU) == best
    assert man.by_id("tf-gold-regime-4h") is None
    assert [x.pairs for x in lane if x.id in ("tf-trend-4h-30d", "tf-rotation-4h-60d")] == [[SPY], [SPY]]
    assert man.by_id("tf-trend-4h-30d").risk == pytest.approx(s.lifecycle.risk_exploration * 0.8)  # SPY moves with BTC
    assert best[0].risk == pytest.approx(s.lifecycle.risk_exploration)
    assert XAU in man.all_pairs() and SPY in man.all_pairs()
    assert sorted(life.tradfi_pairs()) == [SPY, XAU]
    # the hypotheses keep their own instruments for the forward book
    assert reg.kv_get("tradfi_cfg")["tf-rotation-4h-60d"]["pairs"] == [XAU, SPY]


def test_lane_off_or_instrument_unavailable(env):
    s, reg = env
    life = Lifecycle(s, reg)
    life.import_tradfi(ROOT / "research" / "tradfi")
    reg.kv_set(tradfi.K_STATE, {"available": {XAU: True, SPY: False}})
    man = life.build_manifest([], set(), False)
    assert SPY not in man.all_pairs() or datetime.now(UTC).hour == 0  # daily re-probe window at 00:00 UTC
    assert tradfi.usable_pairs({"available": {SPY: False}}, [SPY], utc("2026-11-23 00:05").to_pydatetime()) == [SPY]
    assert tradfi.usable_pairs({"available": {SPY: False}}, [SPY], utc("2026-11-23 00:50").to_pydatetime()) == []
    # excluded (e.g. delisting announced) → no entries there
    assert XAU not in life.build_manifest([], {XAU}, False).all_pairs()
    # lane switched off: no sleeves, but an open gold trade is managed to the end by its own rules
    s.lifecycle.tradfi_enabled = False
    man = life.build_manifest([{"enter_tag": "tf-gold-regime-4h", "pair": XAU}], set(), False)
    sl = man.by_id("tf-gold-regime-4h")
    assert sl.stage == "closing" and sl.pairs == [] and sl.family == "gold_regime" and sl.timeframe == "4h"
    assert not [x for x in man.sleeves if x.note == "tradfi" and x.accept_entries]


def test_import_keeps_only_tradfi_pairs(env, tmp_path):
    s, reg = env
    d = tmp_path / "tf"
    d.mkdir()
    (d / "x.json").write_text(json.dumps({"id": "tf-x", "family": "tsmom", "pairs": [BTC, "SPX/USDT:USDT", SPY]}))
    (d / "y.json").write_text(json.dumps({"id": "tf-y", "family": "tsmom", "pairs": [BTC]}))
    (d / "z.json").write_text("{broken")
    life = Lifecycle(s, reg)
    assert life.import_tradfi(d) == 1
    assert reg.kv_get("tradfi_cfg")["tf-x"]["pairs"] == [SPY]


def test_hypotheses_enter_the_forward_book_only_when_tradable(env):
    from aitrader import forward
    s, reg = env
    life = Lifecycle(s, reg)
    life.import_tradfi(ROOT / "research" / "tradfi")
    assert life.register_tradfi_hypotheses({"available": {XAU: True, SPY: False}}) == 2  # the gold-only ones
    assert set(reg.kv_get("hypotheses")) == {"tf-gold-regime-4h", "xau-macd-12h"}
    freeze = reg.kv_get("hypotheses")["tf-gold-regime-4h"]["freeze"]
    assert life.register_tradfi_hypotheses({"available": {XAU: True, SPY: True}}) == 2
    assert reg.kv_get("hypotheses")["tf-gold-regime-4h"]["freeze"] == freeze  # frozen at the first registration
    book = {e["id"]: e for e in forward.book(reg)}
    assert book["tf-trend-4h-30d"]["kind"] == "hypothesis" and book["tf-trend-4h-30d"]["hypothesis"] == "TF1"
    assert book["tf-rotation-4h-60d"]["pairs"] == [XAU, SPY]


# ============================================================== 4b. the bot: signals, limits, breaker
class FakeDP:
    def __init__(self, frames, analyzed=None, wl=(XAU, SPY, BTC)):
        self.frames, self.analyzed, self.wl = frames, analyzed, list(wl)

    def get_pair_dataframe(self, pair, timeframe, candle_type=""):
        return self.frames.get((pair, timeframe), pd.DataFrame()).copy()

    def get_analyzed_dataframe(self, pair, timeframe):
        return self.analyzed, None

    def current_whitelist(self):
        return self.wl


class Wallets:
    def get_total_stake_amount(self):
        return 10_000.0


def _bot(tmp_path, sleeves, runmode="live"):
    from AIPortfolio import AIPortfolio
    path = tmp_path / "m.json"
    Manifest(sleeves=sleeves).save(path)
    st = AIPortfolio({"aitrader": {"manifest_path": str(path), "max_open_risk": 0.08, "max_side_risk": 0.04,
                                   "max_explore_risk": 0.03, "max_explore_trades": 24, "max_same_side": 25,
                                   "max_tradfi_trades": 2, "max_tradfi_risk": 0.005},
                      "runmode": runmode, "exchange": {"demo_trading": True}, "trading_mode": "futures"})
    st.bot_start()
    st.wallets = Wallets()
    st.timeframe = "15m"
    return st


def _sleeve(sid, family, pairs, sides=("long", "short"), params=None):
    return Sleeve(id=sid, family=family, params=params or {}, pairs=list(pairs), stage="exploration", risk=0.001,
                  sides=list(sides), timeframe="4h", note="tradfi")


def test_rotation_sleeve_gets_the_other_asset_and_enters_only_in_session(tmp_path):
    gold = candles(1300, "2026-03-20", drift=0.0012, seed=2)
    spy = candles(1300, "2026-03-20", drift=-0.0004, seed=5)
    sl = _sleeve("rot", "tradfi_rotation", [XAU, SPY], sides=["long"])
    st = _bot(tmp_path, [sl], runmode="backtest")
    st.dp = FakeDP({(XAU, "4h"): gold, (SPY, "4h"): spy})
    assert (SPY, "4h") in st.informative_pairs() and (XAU, "4h") in st.informative_pairs()
    bot = pd.DataFrame({"date": pd.date_range(gold["date"].iloc[400], gold["date"].iloc[-1], freq="15min", tz="UTC")})
    for c in ("open", "high", "low", "close", "volume"):
        bot[c] = 1.0
    res = st._sleeve_signals(bot, XAU, sl, ["date", "open", "high", "low", "close", "volume"])
    entries = bot["date"][res["long_sig"].to_numpy()]
    assert len(entries) > 10
    assert tradfi.session_open(entries, XAU).all()  # never while gold is closed
    res_spy = st._sleeve_signals(bot, SPY, sl, ["date", "open", "high", "low", "close", "volume"])
    assert not res_spy["long_sig"].any()  # the laggard is never bought


@pytest.fixture
def trades(monkeypatch):
    from freqtrade.persistence import Trade
    box = {"open": [], "closed": []}
    monkeypatch.setattr(Trade, "get_open_trades", staticmethod(lambda: list(box["open"])), raising=False)
    monkeypatch.setattr(Trade, "get_trades_proxy",
                        staticmethod(lambda pair=None, is_open=True, **kw: [t for t in box["open" if is_open else "closed"]
                                                                          if pair in (None, t.pair)]),
                        raising=False)
    return box


def _confirm(st, pair, when, tag, side="long", amount=1.0):
    return st.confirm_trade_entry(pair, "limit", amount, 100.0, "GTC", utc(when).to_pydatetime(), tag, side)


def _open(pair, risk_frac=0.001, tag="x", short=False):
    return SimpleNamespace(pair=pair, is_short=short, open_rate=100.0, stop_loss=98.0 if not short else 102.0,
                           stake_amount=risk_frac * 10_000 / 0.02, leverage=1.0, enter_tag=tag, id=hash(pair) % 1000)


def test_tradfi_entries_need_an_open_market_and_own_caps_crypto_untouched(tmp_path, trades):
    st = _bot(tmp_path, [_sleeve("tf", "tsmom", [XAU, SPY]), Sleeve(id="c", family="trend_ema", params={},
                                                                      pairs=[BTC], stage="exploration", risk=0.001)])
    st.dp = FakeDP({}, analyzed=pd.DataFrame({"close": [100.0], "atr": [1.0], "at:tf": [1.0]}))
    sat, mon = "2026-11-28 16:00", "2026-11-30 16:00"
    assert _confirm(st, SPY, sat, "tf") is False            # NYSE closed
    assert _confirm(st, BTC, sat, "c") is True               # crypto trades on Saturdays as before
    assert _confirm(st, SPY, mon, "tf") is True
    trades["open"] += [_open(XAU, tag="tf"), _open("SOL/USDT:USDT", tag="c")]
    assert _confirm(st, SPY, mon, "tf") is True              # 1 TradFi position open, cap 2
    trades["open"].append(_open("SPX/USDT:USDT", tag="c"))  # the memecoin is not TradFi
    assert _confirm(st, SPY, mon, "tf") is True
    trades["open"] = [_open(XAU, risk_frac=0.0045, tag="tf")]
    assert _confirm(st, SPY, mon, "tf") is False             # TradFi risk cap 0.5 % of equity
    trades["open"] = [_open(XAU, tag="tf"), _open(SPY, tag="tf")]
    assert _confirm(st, SPY, mon, "tf") is True              # the trade on SPY is this entry being replaced
    assert st.leverage(XAU, None, 100.0, 5.0, 10.0, "tf", "long") == 1.0


def test_circuit_breaker_pauses_a_pair_whose_orders_bybit_refuses(tmp_path, trades):
    st = _bot(tmp_path, [_sleeve("tf", "tsmom", [XAU, SPY])])
    st.dp = FakeDP({}, analyzed=pd.DataFrame({"close": [100.0], "atr": [1.0], "at:tf": [1.0]}))
    t0 = utc("2026-11-24 15:00")
    for k in range(3):  # three attempts, nothing ever filled
        assert _confirm(st, XAU, str(t0 + timedelta(hours=2 * k)), "tf") is True
    assert _confirm(st, XAU, str(t0 + timedelta(hours=7)), "tf") is False      # 4th: breaker
    assert _confirm(st, XAU, str(t0 + timedelta(hours=20)), "tf") is False     # paused for 24 h
    assert _confirm(st, SPY, str(t0 + timedelta(hours=1)), "tf") is True       # other pair unaffected
    st.order_filled(SPY, None, None, t0.to_pydatetime())
    assert not st._tradfi_attempts.get(SPY)                                      # a fill clears the attempts
    # replacements of one order (maker-first) count once per 30 minutes
    st2 = _bot(tmp_path, [_sleeve("tf", "tsmom", [XAU, SPY])])
    st2.dp = st.dp
    for m in range(0, 25, 3):
        assert _confirm(st2, SPY, str(t0 + timedelta(minutes=m)), "tf") is True
    assert len(st2._tradfi_attempts[SPY]) == 1
    # two emergency exits (exchange refused the stop) in 24 h → pause
    st3 = _bot(tmp_path, [_sleeve("tf", "tsmom", [XAU, SPY])])
    st3.dp = st.dp
    trades["closed"] = [SimpleNamespace(pair=XAU, exit_reason="emergency_exit",
                                        close_date_utc=(t0 - timedelta(hours=h)).to_pydatetime()) for h in (1, 3)]
    assert _confirm(st3, XAU, str(t0), "tf") is False
    assert tradfi.breaker_state([{"exit_reason": "emergency_exit", "close_ts": 0}] * 5, [], t0.timestamp()) is None


# ============================================================== 5. recovery, availability, execution test
def test_tradfi_trade_keeps_its_own_plan_after_restart_and_lane_off(tmp_path):
    from test_trade_plan import LiveTrade
    sl = _sleeve("tf-gold-regime-4h", "gold_regime", [XAU], params={"sl_atr": 3.0, "lab_trail": 4.0, "exit_mode": 1})
    st = _bot(tmp_path, [sl])
    trade = LiveTrade(id=7, pair=XAU, open_rate=4000.0, open_date_utc=datetime(2026, 11, 24, 16, tzinfo=UTC),
                      is_short=False, leverage=1.0, max_rate=4000.0, min_rate=4000.0, enter_tag=sl.id)
    assert st.sleeve_for_trade(trade).id == sl.id  # remembered with the trade (Freqtrade custom data)
    restart = tmp_path / "restart"
    restart.mkdir()
    st2 = _bot(restart, [])  # bot restart with the lane switched off: empty manifest, empty memory
    got = st2.sleeve_for_trade(trade)
    assert got is not None and got.family == "gold_regime" and got.stage == "closing"
    assert get_family(got.family).normalize(got.params)["lab_trail"] == 4.0


def test_availability_from_the_bot_whitelist_does_not_flap(tmp_path):
    reg = Registry(tmp_path / "r.db")

    class Ft:
        def __init__(self, wl):
            self.wl = wl

        def whitelist(self):
            if self.wl is None:
                raise ConnectionError("bot restarting")
            return {"whitelist": self.wl}

        def pair_candles(self, pair, tf, limit):
            raise ConnectionError

    now = utc("2026-11-24 15:00").to_pydatetime()
    # right after a restart the lane's pairs are not on the pairlist yet: no answer, still usable
    st = tradfi.refresh(reg, Ft([BTC]), [XAU, SPY], True, now - timedelta(minutes=30), listed=[BTC])
    assert st["available"] == {XAU: None, SPY: None} and tradfi.usable_pairs(st, [XAU, SPY], now) == [XAU, SPY]
    st = tradfi.refresh(reg, Ft([BTC]), [XAU, SPY], True, now - timedelta(minutes=15), listed=[BTC, XAU, SPY])
    assert st["available"] == {XAU: None, SPY: None}  # listed only just now
    st = tradfi.refresh(reg, Ft([BTC, XAU]), [XAU, SPY], True, now, listed=[BTC, XAU, SPY])
    assert st["available"] == {XAU: True, SPY: False} and st["open_now"] == {XAU: True, SPY: True}
    assert any("SPYUSDT НЕ доступен" in e["message"] for e in reg.q("SELECT message FROM events"))
    assert tradfi.refresh(reg, Ft(None), [XAU, SPY], True, now)["available"][XAU] is True  # bot down: keep
    assert tradfi.refresh(reg, Ft([BTC]), [XAU, SPY], True, now)["available"][XAU] is True  # one miss: keep
    assert tradfi.refresh(reg, Ft([BTC]), [XAU, SPY], True, now)["available"][XAU] is False  # second miss
    assert tradfi.refresh(reg, Ft([BTC, XAU, SPY]), [XAU, SPY], True, now)["available"] == {XAU: True, SPY: True}


def test_correlation_scale_only_shrinks():
    assert tradfi.corr_scale(None) == 1.0 and tradfi.corr_scale(-0.4) == 1.0
    assert tradfi.corr_scale(0.25) == 0.8 and tradfi.corr_scale(0.99) == 0.503
    rng = np.random.default_rng(0)
    b = rng.normal(0, 1, 300)
    c = tradfi.correlations({BTC: list(b), SPY: list(0.8 * b + rng.normal(0, 0.6, 300)), XAU: list(rng.normal(0, 1, 300))})
    assert c["vs_btc"][SPY] > 0.6 and abs(c["vs_btc"][XAU]) < 0.2 and abs(c["pairwise"]) < 0.2


def test_tradfi_execution_test_orders_and_exchange_stop(tmp_path):
    from test_exec import FakeFt

    from aitrader import selftest
    s = Settings(data_dir=tmp_path, app_dir=ROOT)
    s.ensure_dirs()
    reg = Registry(s.registry_path)

    class Ft(FakeFt):
        def whitelist(self):
            return {"whitelist": [BTC, XAU, SPY]}

        def forceenter(self, pair, side, stake, tag):
            self.entered = (pair, side, stake, tag)
            super().forceenter(pair, side, stake, tag)

    open_now = utc("2026-11-24 15:00").to_pydatetime()
    ft = Ft()
    assert selftest.run_tradfi_execution_test(s, reg, ft, sleep=lambda x: None, now=open_now, timeout_s=2) is None  # not confirmed yet
    reg.kv_set(tradfi.K_STATE, {"available": {XAU: True, SPY: True}})
    assert selftest.run_tradfi_execution_test(s, reg, ft, sleep=lambda x: None,
                                              now=utc("2026-11-28 12:00").to_pydatetime()) is None  # weekend
    res = selftest.run_tradfi_execution_test(s, reg, ft, sleep=lambda x: None, now=open_now, timeout_s=2)
    assert res["ok"], res
    assert ft.entered[0] == XAU and ft.entered[2] == selftest.TRADFI_EXEC_STAKE and ft.entered[3].startswith("exec-test")
    assert res["steps"]["stoploss_on_exchange"]["ok"]
    assert reg.kv_get("tradfi_exec_test")["ok"]
    assert not selftest.tradfi_execution_test_due(reg, open_now)                       # weekly when it passed
    assert selftest.tradfi_execution_test_due(reg, open_now + timedelta(days=8))
    bad = Ft(place_sl=False)
    reg.kv_set("tradfi_exec_test", {})
    res = selftest.run_tradfi_execution_test(s, reg, bad, sleep=lambda x: None, now=open_now, timeout_s=2)
    assert not res["ok"] and not res["steps"]["stoploss_on_exchange"]["ok"]           # a missing stop fails it
    assert selftest.tradfi_execution_test_due(reg, open_now + timedelta(hours=7))       # retried after 6 h


def test_tradfi_execution_test_never_closes_another_running_test(tmp_path):
    from aitrader import selftest
    s = Settings(data_dir=tmp_path, app_dir=ROOT)
    s.ensure_dirs()
    reg = Registry(s.registry_path)
    reg.kv_set(tradfi.K_STATE, {"available": {XAU: True}})

    class Busy:
        def status(self):
            return [{"enter_tag": "exec-test-123", "trade_id": 1, "pair": BTC}]

        def forceexit(self, tid):
            raise AssertionError("must not close the other test's trade")

    assert selftest.run_tradfi_execution_test(s, reg, Busy(), now=utc("2026-11-24 15:00").to_pydatetime()) is None


def test_health_line_shows_the_lane(tmp_path):
    from aitrader.observe import tradfi_part
    reg = Registry(tmp_path / "r.db")
    assert tradfi_part(reg) == "?"
    reg.kv_set("tradfi", {"enabled": True, "pairs": [XAU, SPY], "available": {XAU: True, SPY: False},
                          "open_now": {XAU: True, SPY: False}})
    assert tradfi_part(reg) == "XAU ok open, SPY n/a"
    reg.kv_set("tradfi", {"enabled": False})
    assert tradfi_part(reg) == "off"


def test_demo_only_and_no_leverage_hold_for_the_lane(monkeypatch):
    from AIPortfolio import AIPortfolio
    from freqtrade.exceptions import OperationalException
    st = AIPortfolio({"runmode": "live", "exchange": {"demo_trading": False}})
    with pytest.raises(OperationalException):
        st.bot_start()
    monkeypatch.setenv("AITRADER_LEVERAGE", "5")
    monkeypatch.setenv("TRADFI_ENABLED", "0")
    s = Settings()
    assert s.lifecycle.leverage == 1.0 and s.lifecycle.tradfi_enabled is False
    monkeypatch.delenv("TRADFI_ENABLED")
    s = Settings()
    assert s.lifecycle.tradfi_enabled is True and s.lifecycle.tradfi_forward_book is False  # forward book: opt-in
    monkeypatch.setenv("TRADFI_FORWARD_BOOK", "1")
    assert Settings().lifecycle.tradfi_forward_book is True


def test_forward_book_downloads_tradfi_candles_apart_from_the_benchmark(tmp_path):
    """A failing TradFi download never costs the benchmark / H1 / research strategies of the same
    timeframe their candles: the TradFi entry fails alone and visibly."""
    from test_forward import _FwRunner

    from aitrader.research import shadow
    from aitrader.util import iso, utcnow
    s = Settings(data_dir=tmp_path, app_dir=ROOT)
    s.ensure_dirs()

    class Runner(_FwRunner):
        downloads: list = []

        def download(self, job, cfg, pairs, timerange, timeframe=None, **kw):
            self.downloads.append(list(pairs))
            if any(tradfi.is_tradfi(p) for p in pairs):
                raise RuntimeError("TradFi pairs not available")

        def backtest(self, job, configs, strategy, timerange, fee, out_name):
            if "tf-" in str(job.root):
                raise RuntimeError("no data")
            return super().backtest(job, configs, strategy, timerange, fee, out_name)

    freeze = iso(utcnow() - timedelta(hours=50))
    bench = {"id": "benchmark-tsmom-4h-30d", "family": "tsmom", "params": {}, "pairs": [BTC], "freeze": freeze,
             "timeframe": "4h", "benchmark": True}
    tf = {"id": "tf-trend-4h-30d", "kind": "hypothesis", "hypothesis": "TF1", "family": "tsmom", "params": {},
          "pairs": [XAU, SPY], "freeze": freeze, "timeframe": "4h"}
    ft = Runner(True)
    res = {r["id"]: r for r in shadow.run(s, [bench, tf], tmp_path / "sh", workers=1, ft=ft)}
    assert ft.downloads[0] == [BTC] and ft.downloads[1] == [SPY, XAU]
    assert res["benchmark-tsmom-4h-30d"]["ok"] and res["benchmark-tsmom-4h-30d"]["trades"]
    assert res["tf-trend-4h-30d"]["ok"] is False


def test_gold_winner_is_exactly_the_autopilot_configuration():
    """XAUUSDT on demo: the Strategy Lab autopilot's best configuration by stability + return that
    also passed the decoy control and significance on unseen data, traded with the engine's own
    exits (exit_mode 1) through the twin family (bar-for-bar parity: tests/test_screen.py)."""
    from aitrader.research.screen import to_params
    cfg = json.loads((ROOT / "research" / "tradfi" / "xau-macd-12h.json").read_text())
    screen = json.loads((ROOT / "research" / "tradfi" / "screen" / "xau-screen.json").read_text())
    sig = [x for x in screen["survivors"] if x.get("significant")]
    best = max(sig, key=lambda x: x["score"])
    assert cfg["engine"] == {"strategy": best["strategy"], "params": best["params"], "exits": best["exits"]}
    assert cfg["family"] == best["family"] and cfg["timeframe"] == best["timeframe"] == "12h"
    fam = get_family(cfg["family"])
    assert fam.normalize(cfg["params"]) == to_params(best)  # no parameter clipped by the family's bounds
    p = fam.normalize(cfg["params"])
    assert (p["exit_mode"], p["sl_atr"], p["lab_tp"], p["lab_trail"]) == (1, best["exits"]["sl"], best["exits"]["tp"],
                                                                         best["exits"]["tr"])
    assert cfg["pairs"] == cfg["demo_pairs"] == [XAU] and cfg["rank"] == 0
    assert best["A"]["pf"] >= 1.4 and best["r2"] >= 0.75 and best["robust"] >= 0.7 and best["B"]["net"] >= 0
