"""Central, environment-driven settings. Every knob has a safe default."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MAX_LEVERAGE = 1.0  # owner's rule (2026-11-20): never trade with leverage


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _i(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _on(name: str, default: bool) -> bool:
    return os.environ.get(name, "1" if default else "0").strip().lower() not in ("0", "false", "no", "off", "")


@dataclass
class Gates:
    """Validation thresholds a candidate must pass (all on walk-forward out-of-sample data)."""

    min_trades: int = 40  # "many trades" (was 25; owner's criterion, 2026-11-21)
    min_profit_factor: float = 1.15
    min_sharpe: float = 0.75
    max_drawdown: float = 0.20
    min_wfe: float = 0.30  # walk-forward efficiency (OOS annual return / IS annual return)
    min_stress_pf: float = 1.0  # PF with doubled costs
    min_robust_frac: float = 0.6  # share of parameter perturbations that stay profitable
    min_mc_prob_profit: float = 0.80  # Monte-Carlo bootstrap probability of profit
    min_dsr: float = 0.80  # Deflated Sharpe Ratio probability
    min_fold_consistency: float = 0.75  # share of walk-forward test slices that are profitable
    min_alpha_t: float = 1.0  # OOS alpha over BTC (Newey–West t): the profit is not just market beta
    # relaxed gates for the exploration (tiny-risk) lane
    explore_min_trades: int = 15
    explore_min_pf: float = 1.05
    explore_min_stress_pf: float = 1.0
    explore_min_sharpe: float = 0.3
    explore_min_mc: float = 0.6
    explore_min_fold_consistency: float = 0.5


@dataclass
class Lifecycle:
    risk_production: float = 0.0075  # fraction of equity risked per trade (at stop)
    risk_incubation: float = 0.0025
    risk_exploration: float = 0.001
    # Demo account → evidence first (owner, 2026-11-20): run every promising strategy at
    # tiny risk in parallel so trade statistics accumulate fast; capital-at-risk is bounded
    # by the per-trade risk (0.1% exploration) and the portfolio open-risk cap, not by slots.
    # Every strategy that has proven itself trades at the same time on the coins it passed on
    # (owner, 2026-11-21): slots for proven stages are wide, their risk is scaled to a shared
    # budget (lifecycle.proven_scale) and unproven exploration cannot crowd them out (ftbase).
    max_production: int = 20
    max_incubation: int = 20
    max_exploration: int = 24
    # the lane is split by trading frequency (owner, 2026-11-22: test both at once): this share of the
    # slots for active strategies (15m/1h candles, frequent trades), the rest for precise ones (2h–12h,
    # rare trades); a lane without enough candidates lends its free slots to the other
    explore_active_share: float = 0.5
    max_family_sleeves: int = 12   # deployed sleeves per strategy family …
    max_family_per_coin: int = 2   # … and at most this many of one family on the same coin
    proven_risk_budget: float = 0.05  # open risk at stops for proven sleeves if half their coins are in a trade
    rotate_idle_days: float = 7.0  # an exploration sleeve with < 3 trades after this long can be rotated out
    max_pairs_per_sleeve: int = 15  # an autopilot strategy trades every top coin it passed on
    max_sleeves_per_pair: int = 4  # independent strategies that may trade the same pair
    max_whitelist: int = 45        # pairs the bot follows (Hobby plan memory)
    leverage: float = 1.0  # owner's rule: no leverage (fees scale with position size, not leverage)
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
    # loss vs the UTC day's first equity reading that pauses entries until 00:00 UTC. Off (0) on demo –
    # owner's decision 2026-11-22: a pause only loses observations there. Must be on (e.g. 0.03) before
    # real money (claude/PLAN.md, stage D); env DAILY_LOSS_LIMIT.
    daily_loss_limit: float = 0.0
    kill_cooldown_hours: float = 48.0
    # TradFi lane (owner, 2026-11-23): gold and the S&P 500 perpetuals with pre-registered strategies
    # (research/tradfi/*.json) at exploration risk; env TRADFI_ENABLED=0 switches the lane off
    tradfi_enabled: bool = True
    # … and its configurations as hypothesis TF1 in the lab's forward book (env TRADFI_FORWARD_BOOK=1).
    # Off by default: under DECISIONS §3 any failed forward test marks the whole v3 recording `partial`
    # (red flag), and the lab's Bybit candles for these contracts are unproven – switch on after the
    # observation period, once the lane has traded on demo.
    tradfi_forward_book: bool = False


@dataclass
class Research:
    timeframe: str = "1h"
    train_days: int = 365   # each fold re-optimises on the previous year
    holdout_days: int = 360  # one full year of out-of-sample data …
    wf_folds: int = 4        # … tested as four unseen 90-day slices
    # A fixed configuration (owner's, autopilot's) has nothing to train, so on 2h–12h candles it
    # is replicated over ~3 years in 12 quarterly slices: 3× the trades of a slow strategy and
    # its stability over a long distance (owner's criterion), not just the last year.
    replication_days: int = 1080
    replication_folds: int = 12
    replication_train_days: int = 90  # only for the in-sample side of the WFE ratio
    epochs: int = 120
    hyperopt_jobs: int = 2
    universe_size: int = 24
    pairs_per_experiment: int = 10
    base_fee: float = 0.00075  # Bybit taker 0.055% + ~2bp slippage per side
    stress_fee: float = 0.0012
    perturbations: int = 6
    mc_samples: int = 2000
    idle_sleep_s: int = 300  # pause between experiments (keeps CPU bill in check)
    min_history_days: int = 760
    # Exchange whose public data research uses. Live trading is always Bybit Demo; offline
    # bulk research on GitHub runners (US IPs, Bybit geo-blocked) uses OKX perps as a proxy.
    exchange: str = "bybit"
    # "remote": heavy research runs on GitHub Actions (research lab) and only results are
    # sent to this server; "local": research runs inside this container.
    mode: str = "local"
    relay: str = ""  # research lab → Bybit public data via the live server (ccxt proxyUrl)
    relay_token: str = ""


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("AITRADER_DATA", "/data")))
    app_dir: Path = field(default_factory=lambda: Path(_env("AITRADER_APP", "/app")))
    ft_api_url: str = field(default_factory=lambda: _env("FT_API_URL", "http://127.0.0.1:8080"))
    ft_api_user: str = field(default_factory=lambda: _env("FT_API_USER", "aitrader"))
    ft_api_password: str = field(default_factory=lambda: _env("FT_API_PASSWORD", "change-me"))
    web_user: str = field(default_factory=lambda: _env("WEB_USER", "admin"))
    web_password: str = field(default_factory=lambda: _env("WEB_PASSWORD", ""))
    # GitHub repository whose Actions OIDC tokens may talk to the research-lab sync API
    lab_repository: str = field(default_factory=lambda: _env("LAB_REPOSITORY", "mailzastraze-ctrl/bybit-ai-trader"))
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
        r.exchange = _env("RESEARCH_EXCHANGE", r.exchange)

        lite = os.environ.get("AITRADER_PROFILE", "").lower() == "lite"
        r.mode = _env("RESEARCH_MODE", "remote" if lite else r.mode).lower()
        lc = self.lifecycle
        lc.leverage = min(_f("AITRADER_LEVERAGE", lc.leverage), MAX_LEVERAGE)
        lc.risk_production = _f("RISK_PRODUCTION", lc.risk_production)
        lc.risk_incubation = _f("RISK_INCUBATION", lc.risk_incubation)
        lc.risk_exploration = _f("RISK_EXPLORATION", lc.risk_exploration)
        lc.daily_loss_limit = _f("DAILY_LOSS_LIMIT", lc.daily_loss_limit)
        lc.tradfi_enabled = _on("TRADFI_ENABLED", lc.tradfi_enabled)
        lc.tradfi_forward_book = _on("TRADFI_FORWARD_BOOK", lc.tradfi_forward_book)

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
        return self.user_data / "data" / self.research.exchange

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
