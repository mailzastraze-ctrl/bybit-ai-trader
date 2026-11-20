"""Central, environment-driven settings. Every knob has a safe default."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _i(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass
class Gates:
    """Validation thresholds a candidate must pass (all on walk-forward out-of-sample data)."""

    min_trades: int = 25
    min_profit_factor: float = 1.15
    min_sharpe: float = 0.75
    max_drawdown: float = 0.20
    min_wfe: float = 0.30  # walk-forward efficiency (OOS annual return / IS annual return)
    min_stress_pf: float = 1.0  # PF with doubled costs
    min_robust_frac: float = 0.6  # share of parameter perturbations that stay profitable
    min_mc_prob_profit: float = 0.80  # Monte-Carlo bootstrap probability of profit
    min_dsr: float = 0.80  # Deflated Sharpe Ratio probability
    # relaxed gates for the exploration (tiny-risk) lane
    explore_min_trades: int = 10
    explore_min_pf: float = 1.0
    explore_min_stress_pf: float = 0.95


@dataclass
class Lifecycle:
    risk_production: float = 0.0075  # fraction of equity risked per trade (at stop)
    risk_incubation: float = 0.0025
    risk_exploration: float = 0.001
    max_production: int = 4
    max_incubation: int = 3
    max_exploration: int = 3
    max_pairs_per_sleeve: int = 8
    leverage: float = 3.0
    incubation_min_trades: int = 15
    incubation_min_days: float = 7.0
    incubation_max_days: float = 30.0
    exploration_min_trades: int = 20
    exploration_max_days: float = 21.0
    promote_min_pf: float = 1.05
    retire_max_pf: float = 0.80
    production_window: int = 30  # rolling trades for production health check
    production_retire_pf: float = 0.85
    sleeve_max_dd: float = 0.15  # drawdown of sleeve PnL relative to equity
    account_kill_dd: float = 0.25  # account drawdown that pauses all entries
    kill_cooldown_hours: float = 48.0


@dataclass
class Research:
    timeframe: str = "1h"
    train_days: int = 300
    holdout_days: int = 120
    wf_folds: int = 2
    epochs: int = 120
    hyperopt_jobs: int = 2
    universe_size: int = 24
    pairs_per_experiment: int = 10
    base_fee: float = 0.00075  # Bybit taker 0.055% + ~2bp slippage per side
    stress_fee: float = 0.0012
    perturbations: int = 6
    mc_samples: int = 2000
    idle_sleep_s: int = 300  # pause between experiments (keeps CPU bill in check)
    min_history_days: int = 400


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("AITRADER_DATA", "/data")))
    app_dir: Path = field(default_factory=lambda: Path(_env("AITRADER_APP", "/app")))
    ft_api_url: str = field(default_factory=lambda: _env("FT_API_URL", "http://127.0.0.1:8080"))
    ft_api_user: str = field(default_factory=lambda: _env("FT_API_USER", "aitrader"))
    ft_api_password: str = field(default_factory=lambda: _env("FT_API_PASSWORD", "change-me"))
    web_user: str = field(default_factory=lambda: _env("WEB_USER", "admin"))
    web_password: str = field(default_factory=lambda: _env("WEB_PASSWORD", ""))
    freqtrade_bin: str = field(default_factory=lambda: _env("FREQTRADE_BIN", "freqtrade"))
    gates: Gates = field(default_factory=Gates)
    lifecycle: Lifecycle = field(default_factory=Lifecycle)
    research: Research = field(default_factory=Research)

    def __post_init__(self) -> None:
        r = self.research
        if os.environ.get("AITRADER_PROFILE", "").lower() == "lite":
            # Small instances (≈1 GB RAM, e.g. Railway trial): fewer/lighter experiments.
            r.epochs, r.hyperopt_jobs, r.pairs_per_experiment = 60, 1, 6
            r.universe_size, r.perturbations, r.mc_samples, r.idle_sleep_s = 16, 4, 1000, 900
        r.epochs = _i("RESEARCH_EPOCHS", r.epochs)
        r.hyperopt_jobs = _i("RESEARCH_JOBS", r.hyperopt_jobs)
        r.idle_sleep_s = _i("RESEARCH_IDLE_SECONDS", r.idle_sleep_s)
        r.universe_size = _i("RESEARCH_UNIVERSE", r.universe_size)
        lc = self.lifecycle
        lc.leverage = _f("AITRADER_LEVERAGE", lc.leverage)
        lc.risk_production = _f("RISK_PRODUCTION", lc.risk_production)
        lc.risk_incubation = _f("RISK_INCUBATION", lc.risk_incubation)
        lc.risk_exploration = _f("RISK_EXPLORATION", lc.risk_exploration)

    # ---- derived paths -------------------------------------------------
    @property
    def state_dir(self) -> Path:
        return self.data_dir / "aitrader"

    @property
    def user_data(self) -> Path:
        return self.data_dir / "user_data"

    @property
    def registry_path(self) -> Path:
        return self.state_dir / "registry.sqlite"

    @property
    def manifest_path(self) -> Path:
        return self.state_dir / "manifest.json"

    @property
    def pairlist_path(self) -> Path:
        return self.state_dir / "pairlist.json"

    @property
    def jobs_dir(self) -> Path:
        return self.state_dir / "jobs"

    @property
    def market_data_dir(self) -> Path:
        return self.user_data / "data" / "bybit"

    @property
    def strategies_dir(self) -> Path:
        return self.app_dir / "ft" / "strategies"

    @property
    def hyperopts_dir(self) -> Path:
        return self.app_dir / "ft" / "hyperopts"

    @property
    def config_dir(self) -> Path:
        return self.app_dir / "config"

    def ensure_dirs(self) -> None:
        for p in (self.state_dir, self.user_data, self.jobs_dir, self.market_data_dir,
                  self.user_data / "logs"):
            p.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
