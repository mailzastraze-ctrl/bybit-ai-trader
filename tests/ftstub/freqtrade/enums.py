from enum import StrEnum


class RunMode(StrEnum):
    LIVE = "live"
    DRY_RUN = "dry_run"
    BACKTEST = "backtest"
    HYPEROPT = "hyperopt"
