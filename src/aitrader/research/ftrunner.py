"""Thin wrapper around the Freqtrade CLI. We reuse Freqtrade for data download,
backtesting (fees, funding, leverage, liquidation), hyperopt and pairlist evaluation."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from aitrader import memguard
from aitrader.settings import Settings
from aitrader.util import write_json_atomic

log = logging.getLogger(__name__)

PAIR_BLACKLIST = [
    "USDC/.*", "USDE/.*", "FDUSD/.*", "DAI/.*", "TUSD/.*", "BUSD/.*", "USD1/.*",
    ".*(BULL|BEAR|UP|DOWN)/.*", "PAXG/.*", "XAUT/.*",
]


CCXT_LINEAR_ONLY = {"options": {"fetchMarkets": {"types": ["linear"]}}}


def ccxt_config(settings: Settings) -> dict:
    cfg = dict(CCXT_LINEAR_ONLY) if settings.research.exchange == "bybit" else {}
    if settings.research.relay:
        # freqtrade hands ccxt_config to the sync and async ccxt instances
        cfg["proxyUrl"] = settings.research.relay
        cfg["headers"] = {"X-Lab-Token": settings.research.relay_token}
    return cfg


class FreqtradeError(RuntimeError):
    pass


class FreqtradeOOM(FreqtradeError):
    """The freqtrade subprocess was killed by the kernel OOM killer (SIGKILL)."""


HEAVY = {"hyperopt", "backtesting", "download-data", "test-pairlist"}
STALL_CHECK = {"hyperopt", "backtesting"}  # CPU-bound: no CPU progress for long = hung


class FreqtradeStalled(FreqtradeOOM):
    """No CPU progress for too long (typically a worker killed under memory pressure while
    the parent waits forever). Treated like OOM so the research load is reduced."""


def _tree_cpu(pid: int) -> float:
    try:
        import psutil
    except ImportError:
        return -1.0
    try:
        root = psutil.Process(pid)
        procs = [root, *root.children(recursive=True)]
    except psutil.Error:
        return -1.0
    total = 0.0
    for p in procs:
        try:
            t = p.cpu_times()
            total += t.user + t.system
        except psutil.Error:
            continue
    return total


def run_supervised(cmd: list[str], *, env: dict, cwd: Path, log_file, timeout: float,
                   stall_s: float | None, poll_s: float = 15.0) -> tuple[int, str]:
    """Run a command with a watchdog. Returns (returncode, stdout).
    Kills the whole process group on timeout or when CPU time stops increasing."""
    import signal
    import tempfile
    import time as _t
    with tempfile.TemporaryFile(mode="w+") as out:
        proc = subprocess.Popen(cmd, stdout=out, stderr=log_file, env=env, cwd=cwd,
                                start_new_session=True, text=True)
        start = last_progress = _t.monotonic()
        last_cpu = 0.0
        reason = None
        while True:
            try:
                rc = proc.wait(timeout=poll_s)
                break
            except subprocess.TimeoutExpired:
                pass
            now = _t.monotonic()
            cpu = _tree_cpu(proc.pid)
            if cpu < 0 or cpu > last_cpu + 1.0:
                last_cpu, last_progress = max(cpu, last_cpu), now
            if now - start > timeout:
                reason = f"timeout after {timeout:.0f}s"
            elif stall_s and now - last_progress > stall_s:
                reason = f"stalled: no CPU progress for {now - last_progress:.0f}s"
            if reason:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
                proc.wait()
                rc = -999
                break
        out.seek(0)
        stdout = out.read()
    if reason:
        raise FreqtradeStalled(f"{cmd[1] if len(cmd) > 1 else cmd[0]} killed by watchdog ({reason})")
    return rc, stdout


def research_config(settings: Settings, pairs: list[str], **aitrader: object) -> dict:
    lc = settings.lifecycle
    return {
        "bot_name": "aitrader-research",
        "trading_mode": "futures",
        "margin_mode": "isolated",
        "stake_currency": "USDT",
        "stake_amount": "unlimited",
        "tradable_balance_ratio": 0.95,
        "dry_run": True,
        "dry_run_wallet": 10000,
        "max_open_trades": max(4, min(len(pairs), 8)),
        "timeframe": settings.research.timeframe,
        "dataformat_ohlcv": "feather",
        "entry_pricing": {"price_side": "other", "use_order_book": True, "order_book_top": 1},
        "exit_pricing": {"price_side": "other", "use_order_book": True, "order_book_top": 1},
        "order_types": {"entry": "market", "exit": "market", "stoploss": "market",
                        "stoploss_on_exchange": False},
        "exchange": {"name": settings.research.exchange, "key": "", "secret": "",
                     "pair_whitelist": list(pairs), "pair_blacklist": PAIR_BLACKLIST,
                     # only USDT linear perps are traded; skipping spot/inverse/option markets
                     # cuts memory per freqtrade process substantially
                     "ccxt_config": ccxt_config(settings)},
        "pairlists": [{"method": "StaticPairList"}],
        "aitrader": {"risk": 0.01, "leverage": lc.leverage, "min_trades_is": 30,
                     "dd_limit": settings.gates.max_drawdown, **aitrader},
    }


def scan_config(settings: Settings) -> dict:
    cfg = research_config(settings, [])
    cfg["dry_run"] = True
    cfg["pairlists"] = [
        {"method": "VolumePairList", "number_assets": settings.research.universe_size * 2,
         "sort_key": "quoteVolume", "min_value": 5_000_000, "refresh_period": 1800},
        {"method": "AgeFilter", "min_days_listed": settings.research.min_history_days},
        {"method": "PriceFilter", "low_price_ratio": 0.002},
        {"method": "SpreadFilter", "max_spread_ratio": 0.002},
    ]
    return cfg


@dataclass
class Job:
    root: Path

    @property
    def userdir(self) -> Path:
        return self.root / "ud"

    def path(self, name: str) -> Path:
        return self.root / name


class FreqtradeRunner:
    def __init__(self, settings: Settings):
        self.s = settings

    def _run(self, args: list[str], job: Job, env: dict | None = None,
             timeout: int = 6 * 3600) -> subprocess.CompletedProcess:
        cmd = [self.s.freqtrade_bin, *args]
        full_env = {**os.environ, **(env or {})}
        # Research must never see live credentials.
        for k in list(full_env):
            if k.startswith("FREQTRADE__"):
                full_env.pop(k)
        job.root.mkdir(parents=True, exist_ok=True)
        job.userdir.mkdir(parents=True, exist_ok=True)  # freqtrade refuses a missing --userdir
        if args[0] in HEAVY:
            need = float(os.environ.get("RESEARCH_MIN_HEADROOM_MB", "300"))
            if not memguard.wait_for_headroom(need):
                raise FreqtradeOOM(f"not enough free memory for freqtrade {args[0]} (need {need:.0f} MB)")
        log.info("freqtrade %s", " ".join(args[:3]))
        stall = float(os.environ.get("RESEARCH_STALL_SECONDS", "600")) if args[0] in STALL_CHECK else None
        with open(job.path("freqtrade.log"), "a") as logf:
            logf.write(f"\n$ {' '.join(cmd)}\n")
            logf.flush()
            try:
                rc, stdout = run_supervised(cmd, env=full_env, cwd=job.root, log_file=logf,
                                            timeout=timeout, stall_s=stall)
            finally:
                memguard.release()
            logf.write(stdout[-20000:])
        if rc in (-9, 137):
            raise FreqtradeOOM(f"freqtrade {args[0]} was OOM-killed (rc={rc})")
        if rc != 0:
            tail = job.path("freqtrade.log").read_text()[-2500:]
            raise FreqtradeError(f"freqtrade {args[0]} failed (rc={rc}): {tail}")
        return subprocess.CompletedProcess(cmd, rc, stdout=stdout, stderr="")

    def _common(self, job: Job, config_files: list[Path]) -> list[str]:
        args = []
        for c in config_files:
            args += ["--config", str(c)]
        args += ["--userdir", str(job.userdir), "--datadir", str(self.s.market_data_dir)]
        return args

    def write_config(self, job: Job, name: str, cfg: dict) -> Path:
        p = job.path(name)
        write_json_atomic(p, cfg)
        return p

    # ------------------------------------------------------------------ commands
    def download(self, job: Job, config: Path, pairs: list[str], timerange: str) -> None:
        self._run(["download-data", *self._common(job, [config]), "--timerange", timerange,
                   "--timeframes", self.s.research.timeframe, "--trading-mode", "futures",
                   "--pairs", *pairs], job, timeout=3 * 3600)

    def test_pairlist(self, job: Job, config: Path) -> list[str]:
        proc = self._run(["test-pairlist", "--config", str(config), "--userdir",
                          str(job.userdir), "--print-json"], job, timeout=900)
        for line in reversed(proc.stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("["):
                return [p for p in json.loads(line) if isinstance(p, str)]
        raise FreqtradeError("test-pairlist produced no JSON output")

    def hyperopt(self, job: Job, configs: list[Path], strategy: str, timerange: str,
                 epochs: int, fee: float, seed: int, min_trades: int,
                 space_file: Path | None) -> Path:
        env = {"AITRADER_SPACE_FILE": str(space_file)} if space_file else {}
        self._run(["hyperopt", *self._common(job, configs), "--strategy", strategy,
                   "--strategy-path", str(self.s.strategies_dir),
                   "--hyperopt-path", str(self.s.hyperopts_dir),
                   "--hyperopt-loss", "AIRobustLoss", "--spaces", "buy", "sell",
                   "--epochs", str(epochs), "--timerange", timerange, "--fee", str(fee),
                   "-j", str(self.s.research.hyperopt_jobs), "--random-state", str(seed),
                   "--min-trades", str(min_trades), "--disable-param-export", "--no-color"],
                  job, env=env, timeout=max(1800, epochs * 60))
        return job.userdir / "hyperopt_results"

    def backtest(self, job: Job, configs: list[Path], strategy: str, timerange: str,
                 fee: float, out_name: str) -> Path:
        out = job.path(out_name)
        out.mkdir(parents=True, exist_ok=True)
        self._run(["backtesting", *self._common(job, configs), "--strategy", strategy,
                   "--strategy-path", str(self.s.strategies_dir), "--timerange", timerange,
                   "--fee", str(fee), "--export", "trades", "--backtest-directory", str(out),
                   "--cache", "none"], job, timeout=1200)
        return out
