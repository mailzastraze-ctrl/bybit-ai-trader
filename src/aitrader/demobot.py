"""Freqtrade worker extension for time-based maker-to-taker entry replacement."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from freqtrade.constants import CANCEL_REASON, NON_OPEN_EXCHANGE_STATES
from freqtrade.exceptions import DependencyException
from freqtrade.freqtradebot import FreqtradeBot

from aitrader.demo import validate_trade_config

log = logging.getLogger(__name__)
MAKER_WAIT_S = 180


class DemoTradingBot(FreqtradeBot):
    def __init__(self, config):
        # Worker also constructs this class on reload. Check before creating the exchange.
        validate_trade_config(config)
        super().__init__(config)

    def replace_order(self, order, order_obj, trade) -> None:
        if order_obj.side != trade.entry_side:
            super().replace_order(order, order_obj, trade)
            return
        if order_obj.order_type != "limit" or (trade.enter_tag or "").startswith("exec-test"):
            return
        owner = self.strategy.sleeve_for_pair(trade.pair)
        if self.strategy.entries_paused() or owner is None or owner.id != trade.enter_tag:
            self.handle_cancel_order(order, order_obj, trade, CANCEL_REASON["USER_CANCEL"])
            return
        if (datetime.now(UTC) - order_obj.order_date_utc).total_seconds() < MAKER_WAIT_S:
            return

        # The live worker calls this every cycle following an exchange status read.
        # Cancel first using Freqtrade's reconciliation, then use the confirmed remainder.
        self.handle_cancel_enter(trade, order, order_obj, CANCEL_REASON["REPLACE"], replacing=True)
        if order_obj.status not in NON_OPEN_EXCHANGE_STATES or order_obj.ft_is_open:
            return
        if order_obj.status == "closed" or order_obj.filled is None:
            return
        remaining = order_obj.safe_amount - order_obj.safe_filled
        if remaining <= 0:
            return
        try:
            book = self.exchange.fetch_l2_order_book(trade.pair, limit=1)
            levels = book.get("bids" if trade.is_short else "asks") or []
            if not levels or float(levels[0][0]) <= 0:
                self.replace_order_failed(trade, f"No taker quote for {trade.pair}")
                return
            rate = float(levels[0][0])
            # A worse taker price can only reduce the position size or keep it unchanged.
            stake = remaining * min(rate, order_obj.safe_placement_price) / trade.leverage
            if self.execute_entry(
                trade.pair, stake, price=rate, is_short=trade.is_short, ordertype="market",
                enter_tag=trade.enter_tag, trade=trade, mode="replace",
            ):
                log.info("Demo maker order %s converted to taker after 180 seconds", order_obj.order_id)
                return
        except DependencyException as exc:
            log.warning("Demo maker conversion failed for %s: %s", trade.pair, type(exc).__name__)
        self.replace_order_failed(trade, f"Could not replace maker order for {trade.pair}")
