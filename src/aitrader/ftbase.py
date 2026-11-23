"""Freqtrade integration: base strategy shared by research and live strategies.

Requires the freqtrade package (present in the Docker image). Everything that can be
tested without Freqtrade lives in `families`, `riskcore` and `manifest`.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from freqtrade.enums import RunMode
from freqtrade.exceptions import OperationalException
from freqtrade.exchange import timeframe_to_minutes
from freqtrade.persistence import Trade
from freqtrade.strategy import (
    DecimalParameter,
    IntParameter,
    IStrategy,
    merge_informative_pair,
    stoploss_from_absolute,
)

from aitrader import indicators as ta
from aitrader import oi as oimod
from aitrader import tradfi
from aitrader.families import (
    EXIT_PARAMS,
    MARKET_PAIR,
    NEEDS_FUNDING,
    NEEDS_MARKET,
    NEEDS_OI,
    NEEDS_PEER,
    get_family,
)
from aitrader.manifest import ManifestWatcher, Sleeve
from aitrader.riskcore import EntryContext, bars_held, signal_row, size_multiplier, stake_for_risk
from aitrader.settings import MAX_LEVERAGE

logger = logging.getLogger(__name__)

_FALLBACK_EXIT = {p.name: p.default for p in EXIT_PARAMS}
EXEC_TEST_TAG = "exec-test"


class AIBase(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1h"
    can_short = True
    # Hard cap on loss per trade (relative to stake incl. leverage). The real stop is the
    # ATR-based custom stop; this only guards against data glitches.
    stoploss = -0.30
    use_custom_stoploss = True
    trailing_stop = False
    minimal_roi = {"0": 100.0}  # exits are handled by custom logic
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    process_only_new_candles = True
    # 30 days of 1h warm-up: long-lookback families (time-series momentum, funding z-scores)
    startup_candle_count = 720

    # ------------------------------------------------------------------ hooks for subclasses
    def sleeve_for_pair(self, pair: str) -> Sleeve | None:  # entry owner
        raise NotImplementedError

    def sleeve_for_trade(self, trade: Trade) -> Sleeve | None:
        raise NotImplementedError

    def sleeves_for_pair(self, pair: str) -> list[Sleeve]:
        s = self.sleeve_for_pair(pair)
        return [s] if s else []

    def sleeve_by_tag(self, pair: str, entry_tag: str | None) -> Sleeve | None:
        """The sleeve that generated this entry (enter_tag = sleeve id)."""
        for s in self.sleeves_for_pair(pair):
            if not entry_tag or s.id == entry_tag:
                return s
        return None

    def _live(self) -> bool:
        return self.config.get("runmode") in (RunMode.LIVE, RunMode.DRY_RUN)

    def _open_trade(self, pair: str):
        """The open trade on this pair (live/dry-run only; one trade per pair)."""
        if not self._live():
            return None
        try:
            trades = Trade.get_trades_proxy(pair=pair, is_open=True)
        except Exception:  # noqa: BLE001
            return None
        return trades[0] if trades else None

    def _open_tag(self, pair: str) -> str | None:
        t = self._open_trade(pair)
        return t.enter_tag if t is not None else None

    def _exit_sleeve(self, pair: str, sleeves: list[Sleeve]) -> Sleeve | None:
        """The strategy of the open trade on this pair when it no longer takes entries here
        (rotated out → `closing`, or the coin went to another strategy). Its signals are still
        computed – for the exit only – so the trade leaves on its own rules, never on another
        strategy's exit signal."""
        t = self._open_trade(pair)
        if t is None or not t.enter_tag or t.enter_tag.startswith(EXEC_TEST_TAG):
            return None
        if t.enter_tag in {s.id for s in sleeves}:
            return None
        return self.sleeve_for_trade(t)

    def entries_paused(self) -> bool:
        return False

    def families_in_use(self) -> set[str]:
        return set()

    # ------------------------------------------------------------------ the trade's own plan
    # Each trade keeps a snapshot of the strategy that opened it (family, parameters,
    # timeframe) and of its entry ATR: in memory, and in Freqtrade's per-trade custom data in
    # live/dry-run so it survives restarts. Stops, targets and time exits are then computed
    # from the trade's own plan even when the strategy has left the manifest.
    PLAN_KEY = "aitrader_plan"

    def _plan(self, trade) -> dict | None:
        if not self._live():  # backtests: static manifest, and trade ids repeat across runs
            return None
        tid = getattr(trade, "id", None)
        mem = self.__dict__.setdefault("_plans", {}).get(tid)
        if mem:
            return mem
        if hasattr(trade, "get_custom_data"):
            try:
                v = trade.get_custom_data(self.PLAN_KEY)
            except Exception:  # noqa: BLE001 – a storage problem must never break trading
                v = None
            if isinstance(v, dict):
                self._plans[tid] = v
                return v
        return None

    def _remember_plan(self, trade, sleeve: Sleeve | None = None, atr: float | None = None) -> None:
        tid = getattr(trade, "id", None)
        if tid is None or not self._live():
            return
        old = self._plan(trade) or {}
        new = dict(old)
        if sleeve is not None and not old.get("sleeve"):  # written once: the plan at entry
            new["sleeve"] = {"id": sleeve.id, "family": sleeve.family, "params": sleeve.params,
                             "timeframe": sleeve.timeframe, "sides": list(sleeve.sides),
                             "leverage": sleeve.leverage, "pairs": [], "stage": "closing", "risk": 0.0}
        if atr is not None and not old.get("atr"):
            new["atr"] = float(atr)
        if new == old:
            return
        self.__dict__.setdefault("_plans", {})[tid] = new
        if hasattr(trade, "set_custom_data"):
            try:
                trade.set_custom_data(self.PLAN_KEY, new)
            except Exception as e:  # noqa: BLE001
                logger.debug("trade plan not stored: %s", e)

    # ------------------------------------------------------------------ funding data
    def _funding_tf(self) -> str:
        try:
            return self.dp._exchange.get_option("funding_fee_timeframe") or "8h"
        except Exception:  # noqa: BLE001
            return "8h"

    def _needs_funding(self) -> bool:
        return self.config.get("trading_mode") == "futures" and bool(self.families_in_use() & NEEDS_FUNDING)

    # ------------------------------------------------------------------ timeframes
    def _tf(self, sleeve: Sleeve | None) -> str:
        return (getattr(sleeve, "timeframe", "") or self.timeframe) if sleeve else self.timeframe

    def all_sleeves(self) -> list[Sleeve]:
        return []

    def informative_pairs(self):
        if not self.dp:
            return []
        out = []
        wl = set(self.dp.current_whitelist())
        for sl in self.all_sleeves():  # strategies researched on another (higher) timeframe
            tf = self._tf(sl)
            if tf != self.timeframe:
                out += [(p, tf) for p in sl.pairs if p in wl]
            if sl.family in NEEDS_PEER:  # TradFi rotation: the other instrument's candles
                out += [(q, tf) for p in sl.pairs if (q := tradfi.peer_of(p, sl.pairs)) and q in wl]
        if self._needs_funding():
            ftf = self._funding_tf()
            out += [(p, ftf, "funding_rate") for p in wl]
        if self._needs_market() or self.config.get("runmode") in (RunMode.LIVE, RunMode.DRY_RUN):
            out.append((MARKET_PAIR, self.timeframe))  # also the live market-shock guard
            out += [(MARKET_PAIR, self._tf(sl)) for sl in self.all_sleeves()
                    if sl.family in NEEDS_MARKET and self._tf(sl) != self.timeframe]
        out += self._open_trade_informatives(wl)
        return list(dict.fromkeys(out))

    def _open_trade_informatives(self, wl: set[str]) -> list[tuple]:
        """Higher-timeframe candles for open trades whose strategy no longer lists the coin
        (`closing` sleeves have no pairs): without them its exit signal and its own ATR are
        missing and the trade would be managed on the bot's 15m ATR."""
        if not self._live():
            return []
        try:
            trades = Trade.get_trades_proxy(is_open=True)
        except Exception:  # noqa: BLE001
            return []
        out = []
        for t in trades:
            if not t.enter_tag or t.enter_tag.startswith(EXEC_TEST_TAG):
                continue
            sl = self.sleeve_for_trade(t)
            tf = self._tf(sl)
            if sl is None or tf == self.timeframe:
                continue
            if t.pair in wl:
                out.append((t.pair, tf))
            if sl.family in NEEDS_MARKET:
                out.append((MARKET_PAIR, tf))
            if sl.family in NEEDS_PEER and (q := tradfi.peer_of(t.pair)) and q in wl:
                out.append((q, tf))
        return out

    def _needs_oi(self) -> bool:
        return bool(self.families_in_use() & NEEDS_OI)

    def _merge_oi(self, dataframe: pd.DataFrame, pair: str, tf: str) -> pd.DataFrame:
        """Open interest as of each candle's start. Backtests read the lab's downloaded
        history; the live bot fetches recent OI (cached for 20 minutes per pair)."""
        try:
            if self.config.get("runmode") in (RunMode.LIVE, RunMode.DRY_RUN):
                cache = self.__dict__.setdefault("_oi_cache", {})
                hit = cache.get((pair, tf))
                if hit is None or (datetime.now().timestamp() - hit[0]) > 1200:
                    api = getattr(getattr(self.dp, "_exchange", None), "_api", None)
                    hit = (datetime.now().timestamp(), oimod.fetch_live(api, pair, tf) if api else None)
                    cache[(pair, tf)] = hit
                return oimod.merge(dataframe, hit[1])
            return oimod.merge(dataframe, oimod.load(Path(self.config.get("datadir") or "."), pair, tf))
        except Exception as e:  # noqa: BLE001 – missing OI must never break trading
            logger.warning("open interest unavailable for %s: %s", pair, e)
            dataframe["oi"] = float("nan")
            return dataframe

    def _needs_market(self) -> bool:
        return bool(self.families_in_use() & NEEDS_MARKET)

    def _merge_market(self, dataframe: pd.DataFrame, tf: str) -> pd.DataFrame:
        """BTC close of the same candle (known at the same moment: no look-ahead)."""
        try:
            m = self.dp.get_pair_dataframe(MARKET_PAIR, tf) if self.dp else None
            if m is None or m.empty:
                dataframe["mkt_close"] = float("nan")
                return dataframe
            mk = m[["date", "close"]].rename(columns={"close": "mkt_close"})
            out = dataframe.drop(columns=["mkt_close"], errors="ignore").merge(mk, on="date", how="left")
            dataframe["mkt_close"] = out["mkt_close"].values
        except Exception as e:  # noqa: BLE001 – missing market data must never break trading
            logger.warning("market (BTC) data unavailable: %s", e)
            dataframe["mkt_close"] = float("nan")
        return dataframe

    def _merge_peer(self, dataframe: pd.DataFrame, pair: str, sleeve: Sleeve, tf: str) -> pd.DataFrame:
        """TradFi rotation: the other instrument's close of the same candle (`peer_close`; known
        at the same moment, no look-ahead). Missing data → NaN → the family stays silent."""
        dataframe = dataframe.copy()
        try:
            peer = tradfi.peer_of(pair, sleeve.pairs)
            m = self.dp.get_pair_dataframe(peer, tf) if (self.dp and peer) else None
            if m is None or m.empty:
                dataframe["peer_close"] = float("nan")
                return dataframe
            pk = m[["date", "close"]].rename(columns={"close": "peer_close"})
            out = dataframe.drop(columns=["peer_close"], errors="ignore").merge(pk, on="date", how="left")
            dataframe["peer_close"] = out["peer_close"].values
        except Exception as e:  # noqa: BLE001 – missing peer data must never break trading
            logger.warning("peer data unavailable for %s: %s", pair, e)
            dataframe["peer_close"] = float("nan")
        return dataframe

    def _sleeve_signals(self, dataframe: pd.DataFrame, pair: str, sleeve: Sleeve, cols: list[str]) -> pd.DataFrame | None:
        """Signals of one sleeve aligned to the bot's candles. A sleeve researched on a higher
        timeframe is computed on those candles and merged without look-ahead: the higher
        candle becomes visible when it has closed, and its entry signal fires once (on the
        first bot candle after that close) – exactly when a bot on that timeframe would act."""
        fam = get_family(sleeve.family)
        tf = self._tf(sleeve)
        if tf == self.timeframe:
            d = dataframe[cols]
            if sleeve.family in NEEDS_PEER:
                d = self._merge_peer(d, pair, sleeve, tf)
            # TradFi pairs: entries only while the underlying market is open (crypto unchanged)
            return tradfi.gate_entries(fam.populate(d, sleeve.params), pair)
        if not self.dp:
            return None
        inf = self.dp.get_pair_dataframe(pair, tf)
        if inf is None or inf.empty:
            return None
        inf = inf[["date", "open", "high", "low", "close", "volume"]].copy()
        if "funding" in cols:
            inf = self._merge_funding(inf, pair)
        if sleeve.family in NEEDS_MARKET:
            inf = self._merge_market(inf, tf)
        if sleeve.family in NEEDS_OI:
            inf = self._merge_oi(inf, pair, tf)
        if sleeve.family in NEEDS_PEER:
            inf = self._merge_peer(inf, pair, sleeve, tf)
        res = tradfi.gate_entries(fam.populate(inf, sleeve.params), pair)  # TradFi: underlying session only
        keep = res[["date", "atr", "long_sig", "short_sig", "exit_long_sig", "exit_short_sig", "conviction"]].copy()
        m = merge_informative_pair(dataframe[["date"]].copy(), keep, self.timeframe, tf, ffill=True)
        fresh = (m[f"date_{tf}"] != m[f"date_{tf}"].shift(1)).to_numpy()
        out = pd.DataFrame(index=dataframe.index)
        for c in ("long_sig", "short_sig"):
            out[c] = m[f"{c}_{tf}"].fillna(False).astype(bool).to_numpy() & fresh
        if self._live():
            self._htf_catch_up(out, m, tf, sleeve.id, pair)
        for c in ("exit_long_sig", "exit_short_sig"):
            out[c] = m[f"{c}_{tf}"].fillna(False).astype(bool).to_numpy()
        out["conviction"] = m[f"conviction_{tf}"].fillna(1.0).to_numpy()
        out["atr"] = m[f"atr_{tf}"].to_numpy()
        return out

    HTF_GRACE_ROWS = 2  # bot candles after a higher candle's close in which its late-arriving signal still counts

    def _htf_catch_up(self, out: pd.DataFrame, m: pd.DataFrame, tf: str, sid: str, pair: str) -> None:
        """Live only. A higher-timeframe signal fires on the first bot candle after that candle's
        close. If the higher candle reached the bot a moment late, that first bot candle was
        analysed without it, and the next analysis finds the signal one row back – it would never
        be acted on. Here the newest higher candle's signal still fires on the last row within
        `HTF_GRACE_ROWS` bot candles, once per (strategy, coin, candle): a signal the bot already
        acted on is never repeated.

        Only for a candle THIS process analysed on time and found without the higher candle: the
        "already fired" memory lives in this process, so after a restart a signal of the minutes
        before it (acted on by the previous process) used to fire a second time (23.11: after the
        deploys at 18:23/18:27/18:37 the 18:00 signals of 9 coins fired again; a trade that had
        already closed could have been re-entered on its old signal)."""
        try:
            fired = self.__dict__.setdefault("_htf_fired", set())
            ds = m[f"date_{tf}"]
            n = len(ds)
            if n < 2 or pd.isna(ds.iloc[-1]):
                return
            last = ds.iloc[-1]
            same = (ds == last).to_numpy()[::-1]
            run = int(same.argmin()) if not same.all() else n  # bot candles that already show the newest higher candle
            late = run - 1  # how many of them came after the one it should have fired on
            # the first bot candle this process analysed for this coin: a higher candle due before
            # it was the previous process's to act on – never repeated here
            first = self.__dict__.setdefault("_first_row", {}).setdefault(pair, m["date"].iloc[-1])
            due = m["date"].iloc[n - run] if run <= n else None
            mine = due is not None and not pd.isna(due) and due >= first
            for c in ("long_sig", "short_sig"):
                key = (sid, pair, str(last), c)
                if bool(out[c].iloc[-1]):
                    fired.add(key)  # fired on time
                elif mine and 0 < late <= self.HTF_GRACE_ROWS and key not in fired \
                        and bool(m[f"{c}_{tf}"].fillna(False).astype(bool).iloc[-1]):
                    out.iloc[-1, out.columns.get_loc(c)] = True  # late candle: act on it now
                    fired.add(key)
                    logger.info("late %s candle for %s on %s: %s acted on %d bot candle(s) after its close",
                                tf, sid, pair, c, late)
            if len(fired) > 20000:
                fired.clear()
        except Exception as e:  # noqa: BLE001 – never break signal computation
            logger.debug("htf catch-up: %s", e)

    def _merge_funding(self, dataframe: pd.DataFrame, pair: str) -> pd.DataFrame:
        """Last known funding rate at each candle (backward as-of join: no look-ahead)."""
        try:
            fr = self.dp.get_pair_dataframe(pair, self._funding_tf(), candle_type="funding_rate")
            if fr is None or fr.empty:
                dataframe["funding"] = float("nan")
                return dataframe
            fr = fr[["date", "open"]].rename(columns={"open": "funding"}).sort_values("date")
            out = pd.merge_asof(dataframe.sort_values("date"), fr, on="date", direction="backward")
            dataframe["funding"] = out["funding"].values
        except Exception as e:  # noqa: BLE001 – missing funding data must never break trading
            logger.warning("funding data unavailable for %s: %s", pair, e)
            dataframe["funding"] = float("nan")
        return dataframe

    # ------------------------------------------------------------------ safety
    def bot_start(self, **kwargs) -> None:
        self._entry_atr: dict[tuple, float] = {}
        self._tf_min = timeframe_to_minutes(self.timeframe)
        runmode = self.config.get("runmode")
        if runmode == RunMode.LIVE and not self.config.get("exchange", {}).get("demo_trading"):
            raise OperationalException(
                "aitrader refuses to trade real money: exchange.demo_trading must be true."
            )

    # ------------------------------------------------------------------ signals
    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe["atr"] = ta.atr(dataframe, 14)
        if self._needs_funding():
            dataframe = self._merge_funding(dataframe, metadata["pair"])
        if self._needs_market():
            dataframe = self._merge_market(dataframe, self.timeframe)
        here = self.sleeves_for_pair(metadata["pair"])
        ex = self._exit_sleeve(metadata["pair"], here)
        here = here + ([ex] if ex is not None else [])
        if ex is not None and ex.family in NEEDS_MARKET and self._tf(ex) == self.timeframe \
                and "mkt_close" not in dataframe:
            dataframe = self._merge_market(dataframe, self.timeframe)
        if any(s.family in NEEDS_OI and self._tf(s) == self.timeframe for s in here) \
                and (self._needs_oi() or ex is not None):
            dataframe = self._merge_oi(dataframe, metadata["pair"], self.timeframe)
        return dataframe

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # Signals are computed here (not in populate_indicators) so hyperopt re-evaluates
        # entry parameters every epoch.
        sleeves = self.sleeves_for_pair(metadata["pair"])
        exit_only = self._exit_sleeve(metadata["pair"], sleeves)
        if not sleeves and exit_only is None:
            return dataframe
        cols = ["date", "open", "high", "low", "close", "volume"] + [c for c in ("funding", "mkt_close", "oi") if c in dataframe]
        if exit_only is not None:  # the open trade's own strategy: exit columns and ATR, never entries
            res = self._sleeve_signals(dataframe, metadata["pair"], exit_only, cols)
            if res is not None:
                dataframe[f"xl:{exit_only.id}"] = res["exit_long_sig"].values
                dataframe[f"xs:{exit_only.id}"] = res["exit_short_sig"].values
                dataframe[f"at:{exit_only.id}"] = res["atr"].values
        paused = self.entries_paused()
        # live: the strategy of the coin's open trade (one trade per coin). Another strategy's
        # entry flag on the trade's side would veto that trade's exit signal in Freqtrade
        # (`should_exit`: exit only without an entry) – a veto its backtest never had.
        held = self._open_tag(metadata["pair"]) if self._live() else None
        free = pd.Series(True, index=dataframe.index)  # rows not yet claimed by a higher-priority sleeve
        for i, sleeve in enumerate(sleeves):
            res = self._sleeve_signals(dataframe, metadata["pair"], sleeve, cols)
            if res is None:
                continue
            if i == 0:  # primary sleeve columns (single-sleeve research/backtests read these)
                for col in ("long_sig", "short_sig", "exit_long_sig", "exit_short_sig", "conviction"):
                    dataframe[col] = res[col].values
            dataframe[f"xl:{sleeve.id}"] = res["exit_long_sig"].values
            dataframe[f"xs:{sleeve.id}"] = res["exit_short_sig"].values
            dataframe[f"cv:{sleeve.id}"] = res["conviction"].values
            dataframe[f"at:{sleeve.id}"] = res["atr"].values  # ATR on the sleeve's own timeframe
            ls = pd.Series(res["long_sig"].values, index=dataframe.index).fillna(False).astype(bool)
            ss = pd.Series(res["short_sig"].values, index=dataframe.index).fillna(False).astype(bool)
            xl = pd.Series(res["exit_long_sig"].values, index=dataframe.index).fillna(False).astype(bool)
            xs = pd.Series(res["exit_short_sig"].values, index=dataframe.index).fillna(False).astype(bool)
            ls, ss = self._own_entry_rule(sleeve, ls, ss, xl, xs)
            if paused:
                self._journal_signals(dataframe, metadata["pair"], sleeve, ls, ss, free, paused=True)
                continue
            self._journal_signals(dataframe, metadata["pair"], sleeve, ls, ss, free)
            if held is not None and held != sleeve.id:
                continue  # the coin is busy with another strategy's trade (journalled as pair_busy)
            if "long" in sleeve.sides:
                take = ls & free
                dataframe.loc[take, ["enter_long", "enter_tag"]] = (1, sleeve.id)
                free &= ~take
            if "short" in sleeve.sides and self.can_short:
                take = ss & free
                dataframe.loc[take, ["enter_short", "enter_tag"]] = (1, sleeve.id)
                free &= ~take
        return dataframe

    def _own_entry_rule(self, sleeve: Sleeve, ls: pd.Series, ss: pd.Series, xl: pd.Series,
                        xs: pd.Series) -> tuple[pd.Series, pd.Series]:
        """Freqtrade's entry rule, applied to each strategy with its OWN columns: no entry on a
        candle that also carries the same side's exit or the opposite entry (backtesting
        `check_for_trade_entry`, live `get_entry_signal`). Freqtrade checks the dataframe's exit
        columns, and on a coin with several strategies those were the coin owner's: on 23.11 a
        guest (RSI reversion, 1h) shorted BTC on an hourly candle that already carried its own
        exit – a candle its backtest never trades – and left on the next 15m candle (−3 USDT).
        Backtests are unchanged (single strategy: Freqtrade applies the same rule)."""
        off = pd.Series(False, index=ls.index)
        lo = ls if "long" in sleeve.sides else off
        sh = ss if ("short" in sleeve.sides and self.can_short) else off
        return lo & ~xl & ~sh, sh & ~xs & ~lo

    # ------------------------------------------------------------------ signal journal
    # Observation only (aitrader.observe): what happened to each new entry signal of the live
    # book. Nothing here changes a decision; any failure is swallowed.
    def _journal(self, kind: str, sleeve_id: str | None, pair: str, side: str, outcome: str,
                 candle: str | None = None) -> None:
        if self.config.get("runmode") not in (RunMode.LIVE, RunMode.DRY_RUN) or not sleeve_id:
            return
        try:
            now = datetime.now(UTC)
            # one line per signal and candle, one per decision and 15 minutes (a declined signal
            # is offered to the bot every few seconds while its candle lasts)
            seen = self.__dict__.setdefault("_journal_seen", set())
            key = (kind, sleeve_id, pair, side, candle if kind == "sig" else (outcome, int(now.timestamp()) // 900))
            if key in seen:
                return
            if len(seen) > 20000:
                seen.clear()
            seen.add(key)
            mpath = self.config.get("aitrader", {}).get("manifest_path") or os.environ.get(
                "AITRADER_MANIFEST", "/data/aitrader/manifest.json")
            line = json.dumps({"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "k": kind, "s": sleeve_id,
                               "p": pair, "d": side, "o": outcome, "c": candle}, separators=(",", ":"))
            with (Path(mpath).parent / "signals.jsonl").open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:  # noqa: BLE001
            logger.debug("signal journal: %s", e)

    def _journal_signals(self, dataframe: pd.DataFrame, pair: str, sleeve: Sleeve, ls: pd.Series, ss: pd.Series,
                         free: pd.Series, paused: bool = False) -> None:
        """A new signal = true on the last closed candle and not on the one before (state-type
        signals count once per episode)."""
        if self.config.get("runmode") not in (RunMode.LIVE, RunMode.DRY_RUN) or len(dataframe) < 2:
            return
        try:
            candle = pd.Timestamp(dataframe["date"].iloc[-1]).strftime("%Y-%m-%dT%H:%M:%SZ")
            for side, sig in (("long", ls), ("short", ss)):
                if side not in sleeve.sides or (side == "short" and not self.can_short):
                    continue
                if not (bool(sig.iloc[-1]) and not bool(sig.iloc[-2])):
                    continue
                if paused:
                    outcome = "paused"
                else:
                    held = self._open_tag(pair)
                    if held == sleeve.id:
                        continue  # already in this position: not a missed signal
                    outcome = "pair_busy" if held else ("same_candle" if not bool(free.iloc[-1]) else "emitted")
                self._journal("sig", sleeve.id, pair, side, outcome, candle)
        except Exception as e:  # noqa: BLE001
            logger.debug("signal journal: %s", e)

    def _decline(self, entry_tag: str | None, pair: str, side: str, reason: str) -> bool:
        self._journal("cfm", entry_tag, pair, side, reason)
        return False

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # Exit signals belong to the sleeve that opened the position (pairs can be shared).
        # A tagged trade only ever gets its own strategy's exit columns; if they are missing
        # (data not there yet) it gets no signal exit at all – never another strategy's.
        pair = metadata["pair"]
        tag = self._open_tag(pair)
        owners = self.__dict__.setdefault("_exit_owner", {})
        if tag and not tag.startswith(EXEC_TEST_TAG):
            cl, cs, owner = f"xl:{tag}", f"xs:{tag}", tag
        elif tag:
            cl, cs, owner = "", "", None
        elif self._live():
            # live without an open trade there is nothing to exit: Freqtrade would read these
            # columns only to veto an entry – with the coin owner's exit even for a guest's entry.
            # Each strategy's entries already respect its own exit (`_own_entry_rule`). A trade
            # that opens before the next analysis gets its own exit columns from that analysis.
            cl, cs, owner = "", "", None
        else:  # a backtest: the primary sleeve's columns
            first = self.sleeves_for_pair(pair)
            cl, cs, owner = "exit_long_sig", "exit_short_sig", (first[0].id if first else None)
        if cl and cl in dataframe:
            dataframe.loc[dataframe[cl].fillna(False).astype(bool), "exit_long"] = 1
            dataframe.loc[dataframe[cs].fillna(False).astype(bool), "exit_short"] = 1
            owners[pair] = owner
        else:
            owners[pair] = None
        return dataframe

    # ------------------------------------------------------------------ helpers
    def _params(self, trade: Trade) -> dict:
        if (trade.enter_tag or "").startswith(EXEC_TEST_TAG):
            return dict(_FALLBACK_EXIT)
        sleeve = self.sleeve_for_trade(trade)
        if sleeve is None:
            return dict(_FALLBACK_EXIT)
        return get_family(sleeve.family).normalize(sleeve.params)

    def _ctx(self, pair: str, trade: Trade) -> EntryContext | None:
        if not hasattr(self, "_entry_atr"):
            self.bot_start()
        key = (trade.id, pair, str(trade.open_date_utc))
        atr = self._entry_atr.get(key)
        exec_test = (trade.enter_tag or "").startswith(EXEC_TEST_TAG)
        if trade.enter_tag and not exec_test and self.sleeve_for_trade(trade) is None:
            # neither in the manifest nor in the trade's own record: no rules of ours apply –
            # keep the stop where it is (Freqtrade's exchange stop stays) rather than guess
            seen = self.__dict__.setdefault("_planless_logged", set())
            if trade.id not in seen:
                seen.add(trade.id)
                logger.warning("trade %s (%s, %s): its strategy is unknown – stop kept as it is", trade.id,
                               trade.enter_tag, pair)
            return None
        if atr is None and not exec_test:
            atr = (self._plan(trade) or {}).get("atr")  # the entry ATR remembered with the trade
            if atr:
                self._entry_atr[key] = float(atr)
        if atr is None:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            sl = None if exec_test else self.sleeve_for_trade(trade)
            own = f"at:{sl.id}" if sl is not None else None
            col = own if own and df is not None and own in df else "atr"
            if col == "atr" and sl is not None and self._tf(sl) != self.timeframe:
                # a higher-timeframe strategy without its own ATR yet: the bot's 15m ATR would
                # put the stop far too close (and Freqtrade never widens it again) – leave the
                # stop as it is until the strategy's candles are there
                return None
            row = signal_row(df, trade.open_date_utc, self._tf_min)
            if row is None or pd.isna(row.get(col)) or row[col] <= 0:
                if df is None or df.empty or pd.isna(df[col].iloc[-1]):
                    return None
                atr = float(df[col].iloc[-1])
            else:
                atr = float(row[col])
                self._entry_atr[key] = atr
                if not exec_test:
                    self._remember_plan(trade, atr=atr)
        return EntryContext(entry=float(trade.open_rate), atr=atr, is_short=bool(trade.is_short))

    def _cur_atr(self, pair: str, trade: Trade, current_time: datetime) -> float | None:
        """ATR of the last closed candle of the trade's strategy (for the vol-shock rule)."""
        try:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            sl = None if (trade.enter_tag or "").startswith(EXEC_TEST_TAG) else self.sleeve_for_trade(trade)
            col = f"at:{sl.id}" if sl is not None and df is not None and f"at:{sl.id}" in df else "atr"
            row = signal_row(df, current_time, self._tf_min)
            v = None if row is None else row.get(col)
            return float(v) if v is not None and v == v and v > 0 else None
        except Exception:  # noqa: BLE001 – optional input
            return None

    def _stop(self, pair: str, trade: Trade, ctx: EntryContext, p: dict, current_time: datetime) -> float:
        best = trade.min_rate if trade.is_short else trade.max_rate
        lab_trail = int(p.get("exit_mode") or 0) == 1 and float(p.get("lab_trail") or 0) > 0
        cur_atr = self._cur_atr(pair, trade, current_time) if (int(p.get("vol_shock") or 0) or lab_trail) else None
        stop = ctx.managed_stop(p, float(best or trade.open_rate), now=current_time, cur_atr=cur_atr)
        shock = self._market_shock(current_time) if self.MARKET_SHOCK_GUARD else 0
        # live portfolio guard (off since 23.11, owner: trades follow their strategy only): BTC lurched against this side – a profitable position is moved to
        # break-even (protective only; losing positions keep their stop, nothing is opened)
        if shock and (shock > 0) == bool(trade.is_short) and ctx.r_multiple(float(best or trade.open_rate), p) >= 0.5:
            be = ctx.break_even()
            stop = min(stop, be) if trade.is_short else max(stop, be)
            if trade.id not in self._shock_logged:
                self._shock_logged.add(trade.id)
                logger.info("market shock guard: BTC %+.1f%% in 1h, %s %s stop to break-even", 100 * self._shock_move,
                            "short" if trade.is_short else "long", pair)
        return stop

    SHOCK_MOVE = 0.025  # BTC move in one hour that counts as a market shock
    # Off (owner, 23.11: "strictly the strategy's entry and exit, no exceptions"): the guard is live
    # only and part of no tested strategy, so it changed exits the strategies were never tested with.
    MARKET_SHOCK_GUARD = False

    def _market_shock(self, current_time: datetime) -> int:
        """+1 / −1 when BTC moved ≥ SHOCK_MOVE up / down over the last hour (live only)."""
        if self.config.get("runmode") not in (RunMode.LIVE, RunMode.DRY_RUN) or not self.dp:
            return 0
        if not hasattr(self, "_shock_logged"):
            self._shock_logged, self._shock_at, self._shock, self._shock_move = set(), None, 0, 0.0
        if self._shock_at and (current_time - self._shock_at).total_seconds() < 30:
            return self._shock
        self._shock_at, self._shock = current_time, 0
        try:
            df = self.dp.get_pair_dataframe(MARKET_PAIR, self.timeframe)
            n = max(1, int(60 / max(self._tf_min, 1)))
            if df is not None and len(df) > n:
                c = df["close"].to_numpy()
                self._shock_move = float(c[-1] / c[-1 - n] - 1)
                if abs(self._shock_move) >= self.SHOCK_MOVE:
                    self._shock = 1 if self._shock_move > 0 else -1
        except Exception:  # noqa: BLE001
            pass
        return self._shock

    # ------------------------------------------------------------------ exits
    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, after_fill: bool,
                        **kwargs) -> float | None:
        ctx = self._ctx(pair, trade)
        if ctx is None:
            return None
        stop = self._stop(pair, trade, ctx, self._params(trade), current_time)
        return stoploss_from_absolute(stop, current_rate, is_short=trade.is_short,
                                      leverage=trade.leverage or 1.0)

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs) -> str | None:
        ctx = self._ctx(pair, trade)
        if ctx is None:
            return None
        p = self._params(trade)
        if ctx.tp_hit(current_rate, p):
            return "take_profit"
        stop = self._stop(pair, trade, ctx, p, current_time)
        if (trade.is_short and current_rate >= stop) or (not trade.is_short and current_rate <= stop):
            return "managed_stop"
        sl = None if (trade.enter_tag or "").startswith(EXEC_TEST_TAG) else self.sleeve_for_trade(trade)
        if bars_held(trade.open_date_utc, current_time, timeframe_to_minutes(self._tf(sl))) >= int(p["max_hold"]):
            return "time_exit"
        return None

    def confirm_trade_exit(self, pair: str, trade: Trade, order_type: str, amount: float,
                           rate: float, time_in_force: str, exit_reason: str,
                           current_time: datetime, **kwargs) -> bool:
        # A signal exit counts only when the exit columns were computed for this trade's own
        # strategy (`populate_exit_trend` records whose they were). An unknown strategy, or
        # columns of another strategy (e.g. computed before this trade opened), never close it.
        if exit_reason == "exit_signal":
            mine = self.sleeve_for_trade(trade)
            if mine is None:
                return False
            owner = self.__dict__.get("_exit_owner", {}).get(pair, mine.id)
            if trade.enter_tag and owner != trade.enter_tag:
                return False
        return True

    # ------------------------------------------------------------------ execution
    MAKER_WAIT_S = 180  # rest on our side of the book this long (maker fee), then cross

    def adjust_entry_price(self, trade: Trade, order, pair: str, current_time: datetime,
                           proposed_rate: float, current_order_rate: float, entry_tag: str | None,
                           side: str, **kwargs) -> float | None:
        """Maker-first entries: the limit order rests at the best bid (long) / ask (short)
        and follows the touch; after MAKER_WAIT_S it crosses the spread so the signal is
        never missed. Maker fee 0.02% vs taker 0.055% on Bybit perps."""
        if (entry_tag or "").startswith(EXEC_TEST_TAG) or self.config.get("runmode") not in (RunMode.LIVE, RunMode.DRY_RUN):
            return current_order_rate
        placed = getattr(order, "order_date_utc", None) if order is not None else None
        age = (current_time - placed).total_seconds() if placed else 0.0
        long = side == "long"
        if age < self.MAKER_WAIT_S:
            if proposed_rate and current_order_rate and abs(proposed_rate / current_order_rate - 1) > 0.0005:
                return proposed_rate  # follow the touch, stay passive
            return current_order_rate
        px = self._cross_price(pair, closing_long=not long)  # opening a long crosses like closing a short
        if px is None:  # no quote at all: cross by a fixed 0.2% (a protected marketable limit)
            px = (proposed_rate or current_order_rate) * (1.002 if long else 0.998)
        crossing = current_order_rate >= px / 1.0005 if long else current_order_rate <= px / 0.9995
        return current_order_rate if crossing else px

    MAKER_EXIT_WAIT_S = 90   # exits rest passively this long, then cross
    URGENT_EXITS = ("managed_stop", "stop_loss", "stoploss", "emergency_exit", "liquidation", "force_exit")

    def _cross_price(self, pair: str, closing_long: bool) -> float | None:
        """A price that crosses the spread: just below the bid (selling) / above the ask
        (buying). The ticker's best bid/ask is used (the order-book websocket on Bybit demo
        can fail with 'already subscribed'); the order book is only a fallback."""
        for get in (lambda: self.dp.ticker(pair), lambda: self.dp.orderbook(pair, 1)):
            try:
                q = get()
                bid = q.get("bid") if "bid" in q else q["bids"][0][0]
                ask = q.get("ask") if "ask" in q else q["asks"][0][0]
                if bid and ask:
                    return float(bid) * 0.9995 if closing_long else float(ask) * 1.0005
            except Exception:  # noqa: BLE001
                continue
        return None

    def custom_exit_price(self, pair: str, trade: Trade, current_time: datetime, proposed_rate: float,
                          current_profit: float, exit_tag: str | None, **kwargs) -> float:
        """Lower fees: planned exits (take profit, signal, time) rest on our side of the book
        as maker orders (0.02% vs 0.055% taker); a stop-type exit crosses immediately."""
        if self.config.get("runmode") not in (RunMode.LIVE, RunMode.DRY_RUN):
            return proposed_rate
        if (exit_tag or "") in self.URGENT_EXITS or self._take_cross(pair, "exit", current_time):
            return self._cross_price(pair, not trade.is_short) or proposed_rate
        return self._not_below_tp(pair, trade, proposed_rate, exit_tag)

    def _not_below_tp(self, pair: str, trade: Trade, rate: float, exit_tag: str | None) -> float:
        """A resting take-profit order never sells below (buys above) the take-profit level:
        after a wick to the target the order waits there instead of chasing the price away."""
        if (exit_tag or "") != "take_profit" or not rate:
            return rate
        try:
            ctx = self._ctx(pair, trade)
            if ctx is None:
                return rate
            tp = ctx.take_profit(self._params(trade))
        except Exception:  # noqa: BLE001 – never block an exit on a lookup problem
            return rate
        return min(rate, tp) if trade.is_short else max(rate, tp)

    def adjust_exit_price(self, trade: Trade, order, pair: str, current_time: datetime,
                          proposed_rate: float, current_order_rate: float, entry_tag: str | None,
                          side: str, **kwargs) -> float | None:
        if self.config.get("runmode") not in (RunMode.LIVE, RunMode.DRY_RUN):
            return current_order_rate
        placed = getattr(order, "order_date_utc", None) if order is not None else None
        age = (current_time - placed).total_seconds() if placed else 0.0
        if age < self.MAKER_EXIT_WAIT_S:
            tag = getattr(order, "ft_order_tag", None) if order is not None else None
            if proposed_rate and current_order_rate and abs(proposed_rate / current_order_rate - 1) > 0.0005:
                return self._not_below_tp(pair, trade, proposed_rate, tag)  # follow the touch, stay passive
            return current_order_rate
        px = self._cross_price(pair, not trade.is_short)
        if px is None:
            px = (proposed_rate or current_order_rate) * (0.998 if not trade.is_short else 1.002)
        return px

    # The two hooks above run only when a new bot candle arrives (Freqtrade `replace_order`): on
    # the 15m bot up to 15 minutes after the order, after the 12-minute unfilled timeout. So the
    # "cross after 3 min / 90 s" never happened: on 23.11 a BTC short entry rested 12 min, was
    # cancelled and re-entered 0.53 % lower. Now a resting order is cancelled when its maker wait
    # is over; Freqtrade re-places it in the same loop (the signal / exit still stands) and
    # `custom_entry_price` / `custom_exit_price` put the new order across the spread.
    CROSS_MARK_S = 600  # a cross mark is used by the next order on that coin within 10 minutes

    def check_entry_timeout(self, pair: str, trade: Trade, order, current_time: datetime, **kwargs) -> bool:
        return self._maker_wait_over(pair, trade, order, current_time, "entry")

    def check_exit_timeout(self, pair: str, trade: Trade, order, current_time: datetime, **kwargs) -> bool:
        return self._maker_wait_over(pair, trade, order, current_time, "exit")

    def _maker_wait_over(self, pair: str, trade, order, current_time: datetime, kind: str) -> bool:
        if not self._live() or (getattr(trade, "enter_tag", None) or "").startswith(EXEC_TEST_TAG):
            return False
        placed = getattr(order, "order_date_utc", None) if order is not None else None
        if placed is None:
            return False
        wait = self.MAKER_WAIT_S if kind == "entry" else self.MAKER_EXIT_WAIT_S
        if (current_time - placed).total_seconds() < wait:
            return False
        if float(getattr(order, "filled", 0) or 0) > 0:
            return False  # partly filled: the rest keeps resting (Freqtrade's unfilled timeout still applies)
        self.__dict__.setdefault("_cross_next", {})[(pair, kind)] = current_time
        logger.info("maker wait over: %s order on %s rested %ds unfilled – re-placed across the spread",
                    kind, pair, int((current_time - placed).total_seconds()))
        return True

    def _take_cross(self, pair: str, kind: str, current_time: datetime) -> bool:
        at = (self.__dict__.get("_cross_next") or {}).pop((pair, kind), None)
        return at is not None and (current_time - at).total_seconds() <= self.CROSS_MARK_S

    def custom_entry_price(self, pair: str, trade: Trade | None, current_time: datetime, proposed_rate: float,
                           entry_tag: str | None, side: str, **kwargs) -> float:
        if not self._live() or not self._take_cross(pair, "entry", current_time):
            return proposed_rate
        long = side == "long"
        px = self._cross_price(pair, closing_long=not long)  # opening a long buys like closing a short
        return px if px is not None else proposed_rate * (1.002 if long else 0.998)

    # ------------------------------------------------------------------ portfolio limits
    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time: datetime, entry_tag: str | None,
                            side: str, **kwargs) -> bool:
        """Account-level limits (live/dry-run): crypto pairs are highly correlated, so the
        book as a whole is capped, not just each trade."""
        if (entry_tag or "").startswith(EXEC_TEST_TAG):
            return True
        if self.config.get("runmode") not in (RunMode.LIVE, RunMode.DRY_RUN):
            return True
        cfg = self.config.get("aitrader", {})
        max_risk = float(cfg.get("max_open_risk", 0.03))
        max_side = int(cfg.get("max_same_side", 7))
        trades = Trade.get_open_trades()
        short = side == "short"
        if sum(1 for t in trades if bool(t.is_short) == short) >= max_side:
            logger.info("portfolio limit: %s %s skipped (%d %s positions already open)", side, pair, max_side, side)
            return self._decline(entry_tag, pair, side, "side_count")
        # The weak cannot crowd out the strong: unproven exploration sleeves share a sub-budget
        # (positions and open risk), so proven strategies always find room for their entries.
        new_sleeve = self.sleeve_by_tag(pair, entry_tag)
        explore = [t for t in trades if self._trade_stage(t) == "exploration"]
        if new_sleeve is not None and new_sleeve.stage == "exploration":
            max_ex = int(cfg.get("max_explore_trades", 24))
            if len(explore) >= max_ex:
                logger.info("portfolio limit: %s %s skipped (%d exploration positions open, cap %d – room kept for "
                            "proven strategies)", side, pair, len(explore), max_ex)
                return self._decline(entry_tag, pair, side, "explore_count")
        equity = float(self.wallets.get_total_stake_amount()) if self.wallets else 0.0
        if equity > 0:
            open_risk = sum(self._trade_risk(t, equity) for t in trades)
            sleeve = self.sleeve_by_tag(pair, entry_tag)
            new_risk = self._entry_risk(pair, sleeve, amount, equity)
            if open_risk + new_risk > max_risk * equity:
                logger.info("portfolio limit: %s %s skipped (open risk %.2f%% of equity, cap %.1f%%)", side, pair,
                            100 * open_risk / equity, 100 * max_risk)
                return self._decline(entry_tag, pair, side, "open_risk")
            # one direction is close to one bet (crypto moves together): cap the risk per side too
            side_risk = sum(self._trade_risk(t, equity) for t in trades if bool(t.is_short) == short)
            max_side_risk = float(cfg.get("max_side_risk", max_risk / 2))
            if side_risk + new_risk > max_side_risk * equity:
                logger.info("portfolio limit: %s %s skipped (%s risk %.2f%% of equity, cap %.1f%% per side)", side, pair,
                            side, 100 * side_risk / equity, 100 * max_side_risk)
                return self._decline(entry_tag, pair, side, "side_risk")
            if new_sleeve is not None and new_sleeve.stage == "exploration":
                max_ex_risk = float(cfg.get("max_explore_risk", max_risk * 0.375))
                ex_risk = sum(self._trade_risk(t, equity) for t in explore)
                if ex_risk + new_risk > max_ex_risk * equity:
                    logger.info("portfolio limit: %s %s skipped (exploration risk %.2f%% of equity, cap %.1f%% – room "
                                "kept for proven strategies)", side, pair, 100 * ex_risk / equity, 100 * max_ex_risk)
                    return self._decline(entry_tag, pair, side, "explore_risk")
        if tradfi.is_tradfi(pair):  # TradFi lane: its own, stricter limits on top of the account caps
            why = self._tradfi_check(pair, side, entry_tag, amount, trades, equity, current_time)
            if why:
                return self._decline(entry_tag, pair, side, why)
        self._journal("cfm", entry_tag, pair, side, "accepted")
        return True

    # ------------------------------------------------------------------ TradFi lane (gold, S&P 500)
    TRADFI_PAUSE_S = 24 * 3600

    def _tradfi_check(self, pair: str, side: str, entry_tag: str | None, amount: float, trades: list,
                      equity: float, current_time: datetime | None) -> str | None:
        """Extra limits for gold and the S&P 500 (`aitrader.tradfi`); each can only refuse:
          * the underlying market must be open now (no fills on a stale off-hours price);
          * at most `max_tradfi_trades` TradFi positions and `max_tradfi_risk` of equity at their stops;
          * circuit breaker: entries pause for 24 h on a pair whose orders or exchange stops Bybit
            refuses (≥ 2 emergency exits in 24 h, or ≥ 3 attempts in 24 h without a fill) –
            Freqtrade would otherwise retry the refused order on every candle."""
        cfg = self.config.get("aitrader", {})
        now = current_time or datetime.now(UTC)
        if not tradfi.is_open_now(pair, now):
            return "tradfi_closed"
        # a trade on this pair is the entry being placed/replaced (one trade per pair): not counted
        mine = [t for t in trades if tradfi.is_tradfi(getattr(t, "pair", None)) and t.pair != pair]
        if len(mine) >= int(cfg.get("max_tradfi_trades", 2)):
            logger.info("TradFi limit: %s %s skipped (%d TradFi positions open)", side, pair, len(mine))
            return "tradfi_count"
        if equity > 0:
            risk = sum(self._trade_risk(t, equity) for t in mine)
            new_risk = self._entry_risk(pair, self.sleeve_by_tag(pair, entry_tag), amount, equity)
            cap = float(cfg.get("max_tradfi_risk", 0.005))
            if risk + new_risk > cap * equity:
                logger.info("TradFi limit: %s %s skipped (TradFi risk %.2f%% of equity, cap %.1f%%)", side, pair,
                            100 * risk / equity, 100 * cap)
                return "tradfi_risk"
        ts = now.timestamp()
        paused = self.__dict__.setdefault("_tradfi_paused", {})
        if paused.get(pair, 0) > ts:
            return "tradfi_breaker"
        attempts = self.__dict__.setdefault("_tradfi_attempts", {}).setdefault(pair, [])
        closed = []
        try:
            for t in Trade.get_trades_proxy(pair=pair, is_open=False) or []:
                cd = getattr(t, "close_date_utc", None) or getattr(t, "close_date", None)
                closed.append({"exit_reason": getattr(t, "exit_reason", None),
                               "close_ts": cd.timestamp() if cd is not None else 0})
        except Exception:  # noqa: BLE001 – the breaker is an extra guard; a lookup problem is no reason to trade blind
            closed = []
        why = tradfi.breaker_state(closed, attempts, ts)
        if why:
            paused[pair] = ts + self.TRADFI_PAUSE_S
            attempts.clear()
            logger.warning("TradFi circuit breaker: no new %s entries for 24 h – %s", pair, why)
            return "tradfi_breaker"
        if not attempts or ts - attempts[-1] >= 1800:  # an order replacement re-confirms: one attempt per 30 min
            attempts.append(ts)  # cleared when an entry order fills (order_filled)
        return None

    def order_filled(self, pair: str, trade: Trade, order, current_time: datetime, **kwargs) -> None:
        if tradfi.is_tradfi(pair):
            self.__dict__.setdefault("_tradfi_attempts", {}).pop(pair, None)

    GUARD_STOP_FRAC = 0.25  # a stop this far away is Freqtrade's −30 % guard, not the strategy's stop

    def _trade_risk(self, t, equity: float) -> float:
        """Money at the stop of an open trade, for the account caps. An entry still working
        (nothing filled yet) and a fresh position before its own stop is set carry Freqtrade's
        −30 % guard as their stop; counted at that, one pending entry weighed ~0.6 % of equity
        instead of ~0.1 % (23.11) and a few at the top of the hour could block every other entry
        on that side. Such a trade counts like a new entry: at its strategy's sized risk, never
        less than nominal (`_entry_risk`). With its strategy unknown, the guard stays (stricter)."""
        try:
            o, sl = float(t.open_rate or 0), float(t.stop_loss or 0)
        except (TypeError, ValueError):
            return 0.0
        if o <= 0 or sl <= 0:
            return 0.0
        frac = max(((sl - o) / o) if t.is_short else ((o - sl) / o), 0.0)
        stake, lev = float(t.stake_amount or 0), float(t.leverage or 1)
        at_stop = frac * stake * lev
        amount = getattr(t, "amount", None)
        pending = amount is not None and float(amount or 0) <= 0
        if not (pending or frac >= self.GUARD_STOP_FRAC) or equity <= 0:
            return at_stop
        try:
            sleeve = self.sleeve_for_trade(t)
        except Exception:  # noqa: BLE001 – a lookup problem keeps the stricter guard
            sleeve = None
        if sleeve is None:
            return at_stop
        return min(at_stop, self._entry_risk(t.pair, sleeve, stake * lev / o, equity))

    def _entry_risk(self, pair: str, sleeve: Sleeve | None, amount: float, equity: float) -> float:
        """Money at the initial stop for a new entry, for the account caps: the larger of the
        sleeve's nominal risk and the risk the order is actually sized to (conviction can scale
        it up to 1.5× and the exchange minimum by up to another 1.5×; audit 22.11). Never less
        than the nominal, so the caps can only get stricter."""
        nominal = (sleeve.risk if sleeve else 0.0) * equity
        if sleeve is None or not amount:
            return nominal
        try:
            p = get_family(sleeve.family).normalize(sleeve.params)
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if df is None or df.empty:
                return nominal
            last = df.iloc[-1]
            atr = float(last.get(f"at:{sleeve.id}", last.get("atr", float("nan"))))
            if not atr or atr != atr or atr <= 0:
                return nominal
            return max(nominal, float(amount) * float(p["sl_atr"]) * atr)  # notional × stop distance
        except Exception:  # noqa: BLE001 – a sizing lookup must never let an entry through unchecked
            return nominal

    def _trade_stage(self, trade) -> str | None:
        """Lifecycle stage of the sleeve that owns an open trade (None if unknown/closing)."""
        try:
            sl = self.sleeve_for_trade(trade)
        except Exception:  # noqa: BLE001 – a lookup problem must never block or break entries
            return None
        return getattr(sl, "stage", None)

    # ------------------------------------------------------------------ sizing
    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: float | None, max_stake: float,
                            leverage: float, entry_tag: str | None, side: str,
                            **kwargs) -> float:
        if entry_tag and entry_tag.startswith(EXEC_TEST_TAG):
            # execution self-test (forced entry via REST API): use the requested small stake
            return float(max(min(proposed_stake, max_stake), min_stake or 0.0))
        sleeve = self.sleeve_by_tag(pair, entry_tag)
        if sleeve is None:
            return 0.0
        p = get_family(sleeve.family).normalize(sleeve.params)
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty:
            return 0.0
        last = df.iloc[-1]
        atr = float(last.get(f"at:{sleeve.id}", last.get("atr", float("nan"))))
        if not atr or atr != atr or current_rate <= 0:
            return 0.0
        conviction = float(last.get(f"cv:{sleeve.id}", last.get("conviction", 1.0)) or 1.0)
        equity = float(self.wallets.get_total_stake_amount())
        return stake_for_risk(
            equity=equity,
            risk=sleeve.risk,
            sl_distance_pct=float(p["sl_atr"]) * atr / current_rate,
            leverage=max(leverage, 1.0),
            multiplier=size_multiplier(conviction, p["conv_w"]),
            min_stake=min_stake,
            max_stake=max_stake,
            max_notional_frac=0.5 * max(leverage, 1.0),  # notional ≤ 50% of equity per trade
        )

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str | None,
                 side: str, **kwargs) -> float:
        # Owner's rule: no leverage. Every position is fully margined (1x); risk is set by the
        # stop distance and position size, which leverage never changed anyway.
        cap = min(float(self.config.get("aitrader", {}).get("max_leverage", MAX_LEVERAGE)), MAX_LEVERAGE)
        if entry_tag and entry_tag.startswith(EXEC_TEST_TAG):
            return 1.0
        sleeve = self.sleeve_by_tag(pair, entry_tag)
        lev = sleeve.leverage if sleeve else 1.0
        return float(max(1.0, min(lev, max_leverage, cap)))


# ---------------------------------------------------------------------------- research
def _space_overrides(family: str) -> dict:
    """Search-space adjustments produced by the learning loop (per research job)."""
    path = os.environ.get("AITRADER_SPACE_FILE")
    if not path or not Path(path).is_file():
        return {}
    try:
        return json.loads(Path(path).read_text()).get(family, {})
    except (OSError, json.JSONDecodeError):
        return {}


def build_parameters(cls: type, family_name: str) -> type:
    """Attach hyperoptable Parameters for every family parameter to a strategy class."""
    fam = get_family(family_name)
    space = fam.space(_space_overrides(family_name))
    for p in fam.params:
        lo, hi = space[p.name]
        default = min(max(p.default, lo), hi)
        pinned = hi - lo < (1 if p.kind == "int" else 10 ** -p.decimals)
        if pinned:  # fixed value: keep the full valid range, don't optimise
            lo, hi = p.low, p.high
        if p.kind == "int":
            param = IntParameter(int(lo), int(hi), default=int(round(default)), space=p.space,
                                 optimize=not pinned)
        else:
            param = DecimalParameter(lo, hi, default=default, decimals=p.decimals,
                                     space=p.space, optimize=not pinned)
        setattr(cls, p.name, param)
    cls.family_name = family_name
    return cls


class ResearchBase(AIBase):
    """Single-family strategy whose parameters are optimised by Freqtrade hyperopt."""

    family_name = ""

    def _current_sleeve(self) -> Sleeve:
        fam = get_family(self.family_name)
        params = {p.name: getattr(self, p.name).value for p in fam.params}
        cfg = self.config.get("aitrader", {})
        return Sleeve(
            id=f"rs-{self.family_name}",
            family=self.family_name,
            params=params,
            pairs=[],
            stage="exploration",
            risk=float(cfg.get("risk", 0.01)),
            leverage=float(cfg.get("leverage", 1.0)),
            sides=list(cfg.get("sides", ["long", "short"])),
        )

    def sleeve_for_pair(self, pair: str) -> Sleeve | None:
        return self._current_sleeve()

    def sleeve_for_trade(self, trade: Trade) -> Sleeve | None:
        return self._current_sleeve()

    def families_in_use(self) -> set[str]:
        return {self.family_name}


# ---------------------------------------------------------------------------- portfolio
class PortfolioBase(AIBase):
    """Live host: runs every sleeve from the manifest, each on the pairs it owns."""

    def _watcher(self) -> ManifestWatcher:
        w = getattr(self, "_mwatch", None)
        if w is None:
            path = self.config.get("aitrader", {}).get("manifest_path") or os.environ.get(
                "AITRADER_MANIFEST", "/data/aitrader/manifest.json"
            )
            w = ManifestWatcher(Path(path))
            w.refresh()
            self._mwatch = w
        return w

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        if self._watcher().refresh():
            m = self._watcher().manifest
            logger.info("Manifest v%s loaded: %d sleeves", m.version, len(m.sleeves))

    def entries_paused(self) -> bool:
        return self._watcher().manifest.entries_paused

    def families_in_use(self) -> set[str]:
        return {s.family for s in self._watcher().manifest.sleeves}

    def all_sleeves(self) -> list[Sleeve]:
        return list(self._watcher().manifest.sleeves)

    def sleeve_for_pair(self, pair: str) -> Sleeve | None:
        return self._watcher().manifest.owner_of(pair)

    def sleeves_for_pair(self, pair: str) -> list[Sleeve]:
        return self._watcher().manifest.sleeves_for(pair)

    def sleeve_for_trade(self, trade: Trade) -> Sleeve | None:
        """The strategy that opened this trade – for its whole life. Taken from the manifest
        while the strategy is there (and remembered with the trade), from the trade's own
        snapshot when it is not (manager restart, bot API down, rotation). A tagged trade never
        borrows another strategy's stop, target or holding time; with no record at all it gets
        None and its stop is left where it is."""
        m = self._watcher().manifest
        tag = getattr(trade, "enter_tag", None)
        if not tag:
            return m.owner_of(trade.pair)  # untagged (manual) trade: as before
        s = m.by_id(tag)
        if s is not None:
            self._remember_plan(trade, sleeve=s)
            return s
        snap = (self._plan(trade) or {}).get("sleeve")
        return Sleeve.from_dict(snap) if isinstance(snap, dict) and snap.get("id") == tag else None
