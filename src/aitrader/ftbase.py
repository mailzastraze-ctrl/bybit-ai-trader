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
        sleeve = self.sleeve_for_pair(metadata["pair"])
        if sleeve is None:
            return dataframe
        fam = get_family(sleeve.family)
        cols = ["date", "open", "high", "low", "close", "volume"] + (["funding"] if "funding" in dataframe else [])
        res = fam.populate(dataframe[cols], sleeve.params)
        for col in ("long_sig", "short_sig", "exit_long_sig", "exit_short_sig", "conviction"):
            dataframe[col] = res[col].values
        if self.entries_paused():
            return dataframe
        if "long" in sleeve.sides:
            dataframe.loc[dataframe["long_sig"], ["enter_long", "enter_tag"]] = (1, sleeve.id)
        if "short" in sleeve.sides and self.can_short:
            dataframe.loc[dataframe["short_sig"], ["enter_short", "enter_tag"]] = (1, sleeve.id)
        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        if "exit_long_sig" in dataframe:
            dataframe.loc[dataframe["exit_long_sig"].fillna(False).astype(bool), "exit_long"] = 1
            dataframe.loc[dataframe["exit_short_sig"].fillna(False).astype(bool), "exit_short"] = 1
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
        # Signal exits only count when the pair is still owned by the sleeve that opened it.
        if exit_reason == "exit_signal":
            owner = self.sleeve_for_pair(pair)
            mine = self.sleeve_for_trade(trade)
            if owner is not None and mine is not None and owner.id != mine.id:
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
        sleeve = self.sleeve_for_pair(pair)
        if sleeve is None or (entry_tag and sleeve.id != entry_tag):
            return 0.0
        p = get_family(sleeve.family).normalize(sleeve.params)
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty:
            return 0.0
        last = df.iloc[-1]
        atr = float(last.get("atr", float("nan")))
        if not atr or atr != atr or current_rate <= 0:
            return 0.0
        conviction = float(last.get("conviction", 1.0) or 1.0)
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
        if entry_tag and entry_tag.startswith(EXEC_TEST_TAG):
            return float(max(1.0, min(2.0, max_leverage)))
        sleeve = self.sleeve_for_pair(pair)
        lev = sleeve.leverage if sleeve else 1.0
        return float(max(1.0, min(lev, max_leverage)))


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
            leverage=float(cfg.get("leverage", 3.0)),
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

    def sleeve_for_trade(self, trade: Trade) -> Sleeve | None:
        m = self._watcher().manifest
        return m.by_id(trade.enter_tag) or m.owner_of(trade.pair)
