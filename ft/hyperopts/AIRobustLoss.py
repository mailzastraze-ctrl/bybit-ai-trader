"""Hyperopt objective: trade-count-aware Sharpe with drawdown and PF penalties."""

from datetime import datetime

from freqtrade.optimize.hyperopt import IHyperOptLoss
from pandas import DataFrame

from aitrader.research.metrics import robust_loss


class AIRobustLoss(IHyperOptLoss):
    @staticmethod
    def hyperopt_loss_function(
        *,
        results: DataFrame,
        trade_count: int,
        min_date: datetime,
        max_date: datetime,
        config: dict,
        starting_balance: float,
        **kwargs,
    ) -> float:
        cfg = config.get("aitrader", {})
        df = results[["close_date", "profit_abs", "profit_ratio", "is_short"]].copy()
        return robust_loss(
            df,
            starting_balance,
            min_date,
            max_date,
            min_trades=int(cfg.get("min_trades_is", 30)),
            dd_limit=float(cfg.get("dd_limit", 0.20)),
        )
