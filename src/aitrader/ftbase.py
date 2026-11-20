"""Freqtrade integration: base strategy shared by research and live strategies.

Requires the freqtrade package (present in the Docker image). Everything that can be
tested without Freqtrade lives in `families`, `riskcore` and `manifest`.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from freqtrade.enums import RunMode
from freqtrade.exceptions import OperationalException
from freqtrade.exchange import timeframe_to_minutes
from freqtrade.persistence import Trade
from freqtrade.strategy import DecimalParameter, IntParameter, IStrategy, stoploss_from_absolute

from aitrader import indicators as ta
from aitrader.families import EXIT_PARAMS, NEEDS_FUNDING, get_family
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

    def _open_tag(self, pair: str) -> str | None:
        if self.config.get("runmode") not in (RunMode.LIVE, RunMode.DRY_RUN):
            return None
        try:
            trades = Trade.get_trades_proxy(pair=pair, is_open=True)
        except Exception:  # noqa: BLE001
            return None
        return trades[0].enter_tag if trades else None

    def entries_paused(self) -> bool:
        return False

    def families_in_use(self) -> set[str]:
        return set()

    # ------------------------------------------------------------------ funding data
    def _funding_tf(self) -> str:
        try:
            return self.dp._exchange.get_option("funding_fee_timeframe") or "8h"
        except Exception:  # noqa: BLE001
            return "8h"

    def _needs_funding(self) -> bool:
        return self.config.get("trading_mode") == "futures" and bool(self.families_in_use() & NEEDS_FUNDING)

    def informative_pairs(self):
        if not self._needs_funding() or not self.dp:
            return []
        tf = self._funding_tf()
        return [(p, tf, "funding_rate") for p in self.dp.current_whitelist()]

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
        return dataframe

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # Signals are computed here (not in populate_indicators) so hyperopt re-evaluates
        # entry parameters every epoch.
        sleeves = self.sleeves_for_pair(metadata["pair"])
        if not sleeves:
            return dataframe
        cols = ["date", "open", "high", "low", "close", "volume"] + (["funding"] if "funding" in dataframe else [])
        paused = self.entries_paused()
        free = pd.Series(True, index=dataframe.index)  # rows not yet claimed by a higher-priority sleeve
        for i, sleeve in enumerate(sleeves):
            res = fam_res = get_family(sleeve.family).populate(dataframe[cols], sleeve.params)  # noqa: F841
            if i == 0:  # primary sleeve columns (single-sleeve research/backtests read these)
                for col in ("long_sig", "short_sig", "exit_long_sig", "exit_short_sig", "conviction"):
                    dataframe[col] = res[col].values
            dataframe[f"xl:{sleeve.id}"] = fam_res["exit_long_sig"].values
            dataframe[f"xs:{sleeve.id}"] = fam_res["exit_short_sig"].values
            dataframe[f"cv:{sleeve.id}"] = fam_res["conviction"].values
            if paused:
                continue
            ls = pd.Series(res["long_sig"].values, index=dataframe.index).fillna(False).astype(bool)
            ss = pd.Series(res["short_sig"].values, index=dataframe.index).fillna(False).astype(bool)
            if "long" in sleeve.sides:
                take = ls & free
                dataframe.loc[take, ["enter_long", "enter_tag"]] = (1, sleeve.id)
                free &= ~take
            if "short" in sleeve.sides and self.can_short:
                take = ss & free
                dataframe.loc[take, ["enter_short", "enter_tag"]] = (1, sleeve.id)
                free &= ~take
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # Exit signals belong to the sleeve that opened the position (pairs can be shared).
        tag = self._open_tag(metadata["pair"])
        cl, cs = (f"xl:{tag}", f"xs:{tag}") if tag and f"xl:{tag}" in dataframe else ("exit_long_sig", "exit_short_sig")
        if cl in dataframe:
            dataframe.loc[dataframe[cl].fillna(False).astype(bool), "exit_long"] = 1
            dataframe.loc[dataframe[cs].fillna(False).astype(bool), "exit_short"] = 1
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
        if atr is None:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            row = signal_row(df, trade.open_date_utc, self._tf_min)
            if row is None or pd.isna(row.get("atr")) or row["atr"] <= 0:
                if df is None or df.empty or pd.isna(df["atr"].iloc[-1]):
                    return None
                atr = float(df["atr"].iloc[-1])
            else:
                atr = float(row["atr"])
                self._entry_atr[key] = atr
        return EntryContext(entry=float(trade.open_rate), atr=atr, is_short=bool(trade.is_short))

    # ------------------------------------------------------------------ exits
    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, after_fill: bool,
                        **kwargs) -> float | None:
        ctx = self._ctx(pair, trade)
        if ctx is None:
            return None
        p = self._params(trade)
        best = trade.min_rate if trade.is_short else trade.max_rate
        stop = ctx.managed_stop(p, float(best or trade.open_rate))
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
        best = trade.min_rate if trade.is_short else trade.max_rate
        stop = ctx.managed_stop(p, float(best or trade.open_rate))
        if (trade.is_short and current_rate >= stop) or (not trade.is_short and current_rate <= stop):
            return "managed_stop"
        if bars_held(trade.open_date_utc, current_time, self._tf_min) >= int(p["max_hold"]):
            return "time_exit"
        return None

    def confirm_trade_exit(self, pair: str, trade: Trade, order_type: str, amount: float,
                           rate: float, time_in_force: str, exit_reason: str,
                           current_time: datetime, **kwargs) -> bool:
        # Signal exits only count when the trade's own sleeve still runs (or the exit columns
        # were computed for it); a sleeve that was removed exits via stops / time instead.
        if exit_reason == "exit_signal":
            mine = self.sleeve_for_trade(trade)
            if mine is None or mine.id not in {x.id for x in self.sleeves_for_pair(pair)}:
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
        try:
            ob = self.dp.orderbook(pair, 1)
            px = float(ob["asks"][0][0]) * 1.0005 if long else float(ob["bids"][0][0]) * 0.9995
        except Exception:  # noqa: BLE001
            return current_order_rate
        crossing = current_order_rate >= px / 1.0005 if long else current_order_rate <= px / 0.9995
        return current_order_rate if crossing else px

    MAKER_EXIT_WAIT_S = 90   # exits rest passively this long, then cross
    URGENT_EXITS = ("managed_stop", "stop_loss", "stoploss", "emergency_exit", "liquidation", "force_exit")

    def _cross_price(self, pair: str, closing_long: bool) -> float | None:
        try:
            ob = self.dp.orderbook(pair, 1)
            return float(ob["bids"][0][0]) * 0.9995 if closing_long else float(ob["asks"][0][0]) * 1.0005
        except Exception:  # noqa: BLE001
            return None

    def custom_exit_price(self, pair: str, trade: Trade, current_time: datetime, proposed_rate: float,
                          current_profit: float, exit_tag: str | None, **kwargs) -> float:
        """Lower fees: planned exits (take profit, signal, time) rest on our side of the book
        as maker orders (0.02% vs 0.055% taker); a stop-type exit crosses immediately."""
        if self.config.get("runmode") not in (RunMode.LIVE, RunMode.DRY_RUN):
            return proposed_rate
        if (exit_tag or "") in self.URGENT_EXITS:
            return self._cross_price(pair, not trade.is_short) or proposed_rate
        return proposed_rate

    def adjust_exit_price(self, trade: Trade, order, pair: str, current_time: datetime,
                          proposed_rate: float, current_order_rate: float, entry_tag: str | None,
                          side: str, **kwargs) -> float | None:
        if self.config.get("runmode") not in (RunMode.LIVE, RunMode.DRY_RUN):
            return current_order_rate
        placed = getattr(order, "order_date_utc", None) if order is not None else None
        age = (current_time - placed).total_seconds() if placed else 0.0
        if age < self.MAKER_EXIT_WAIT_S:
            if proposed_rate and current_order_rate and abs(proposed_rate / current_order_rate - 1) > 0.0005:
                return proposed_rate  # follow the touch, stay passive
            return current_order_rate
        px = self._cross_price(pair, not trade.is_short)
        return px or current_order_rate

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
            return False
        equity = float(self.wallets.get_total_stake_amount()) if self.wallets else 0.0
        if equity > 0:
            open_risk = 0.0
            for t in trades:
                if not t.open_rate or not t.stop_loss:
                    continue
                loss_frac = (t.stop_loss - t.open_rate) / t.open_rate if t.is_short else (t.open_rate - t.stop_loss) / t.open_rate
                open_risk += max(loss_frac, 0.0) * float(t.stake_amount or 0) * float(t.leverage or 1)
            sleeve = self.sleeve_by_tag(pair, entry_tag)
            new_risk = (sleeve.risk if sleeve else 0.0) * equity
            if open_risk + new_risk > max_risk * equity:
                logger.info("portfolio limit: %s %s skipped (open risk %.2f%% of equity, cap %.1f%%)", side, pair,
                            100 * open_risk / equity, 100 * max_risk)
                return False
        return True

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
        atr = float(last.get("atr", float("nan")))
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

    def sleeve_for_pair(self, pair: str) -> Sleeve | None:
        return self._watcher().manifest.owner_of(pair)

    def sleeves_for_pair(self, pair: str) -> list[Sleeve]:
        return self._watcher().manifest.sleeves_for(pair)

    def sleeve_for_trade(self, trade: Trade) -> Sleeve | None:
        m = self._watcher().manifest
        return m.by_id(trade.enter_tag) or m.owner_of(trade.pair)
