
import pytest

from aitrader import memguard
from aitrader.registry import Registry
from aitrader.settings import Settings


def _cg(tmp_path, current, limit, inactive_file=0):
    (tmp_path / "memory.current").write_text(str(current))
    (tmp_path / "memory.max").write_text(str(limit))
    (tmp_path / "memory.stat").write_text(f"anon 1\ninactive_file {inactive_file}\n")
    return tmp_path


def test_headroom_cgroup_v2_subtracts_reclaimable_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("AITRADER_MEMORY_LIMIT_MB", raising=False)
    root = _cg(tmp_path, 900_000_000, 1_000_000_000, inactive_file=200_000_000)
    assert memguard.headroom_mb(root) == pytest.approx(300.0)
    (tmp_path / "memory.max").write_text("max")
    assert memguard.headroom_mb(root) is None  # unlimited → unknown → never block


def test_wait_for_headroom(tmp_path, monkeypatch):
    monkeypatch.delenv("AITRADER_MEMORY_LIMIT_MB", raising=False)
    root = _cg(tmp_path, 950_000_000, 1_000_000_000)
    calls = []

    def fake_sleep(s):
        calls.append(s)
        (tmp_path / "memory.current").write_text("500000000")  # memory freed meanwhile

    assert memguard.wait_for_headroom(300, timeout_s=60, poll_s=1, root=root, sleep=fake_sleep)
    assert calls == [1]
    (tmp_path / "memory.current").write_text("990000000")
    assert not memguard.wait_for_headroom(300, timeout_s=0, poll_s=1, root=root, sleep=lambda s: None)


def test_adaptive_scale(tmp_path):
    reg = Registry(tmp_path / "r.sqlite")
    sc = memguard.AdaptiveScale(reg, default_level=2)
    assert sc.params() == memguard.SCALE_STEPS[2]
    assert sc.on_oom() == 1 and sc.on_oom() == 0 and sc.on_oom() == 0
    for _ in range(3):
        sc.on_success()
    assert sc.level() == 1  # recovers one step after 3 successes, never above default
    for _ in range(9):
        sc.on_success()
    assert sc.level() == 2


def test_runner_raises_oom_on_sigkill(tmp_path, monkeypatch):
    from aitrader.research.ftrunner import FreqtradeOOM, FreqtradeRunner, Job
    s = Settings(data_dir=tmp_path)
    monkeypatch.setattr(memguard, "wait_for_headroom", lambda need: True)
    from aitrader.research import ftrunner
    monkeypatch.setattr(ftrunner, "run_supervised", lambda cmd, **kw: (-9, ""))
    with pytest.raises(FreqtradeOOM):
        FreqtradeRunner(s).backtest(Job(tmp_path / "j"), [tmp_path / "c.json"], "AIPortfolio", "20250101-", 0.001, "bt")
    monkeypatch.setattr(memguard, "wait_for_headroom", lambda need: False)
    with pytest.raises(FreqtradeOOM):
        FreqtradeRunner(s).download(Job(tmp_path / "j"), tmp_path / "c.json", ["BTC/USDT:USDT"], "20250101-")


def test_housekeeping_prunes_old_rows(tmp_path):
    from aitrader.manager import housekeeping
    reg = Registry(tmp_path / "r.sqlite")
    with reg.conn() as c:
        c.execute("INSERT INTO events (ts, level, source, message, data) VALUES ('2020-01-01T00:00:00Z','info','x','old','{}')")
    reg.event("x", "new")
    housekeeping(reg)
    msgs = [r["message"] for r in reg.q("SELECT message FROM events")]
    assert "old" not in msgs and "new" in msgs
    assert reg.kv_get("vacuum_ts")


def test_watchdog_kills_stalled_and_timed_out_processes(tmp_path):
    import sys
    import time

    from aitrader.research.ftrunner import FreqtradeStalled, run_supervised
    env = dict(__import__("os").environ)
    with open(tmp_path / "log", "w") as lf:
        t0 = time.monotonic()
        with pytest.raises(FreqtradeStalled, match="stalled"):
            run_supervised([sys.executable, "-c", "import time; time.sleep(30)"], env=env, cwd=tmp_path,
                           log_file=lf, timeout=60, stall_s=1.5, poll_s=0.5)
        assert time.monotonic() - t0 < 10
        with pytest.raises(FreqtradeStalled, match="timeout"):
            run_supervised([sys.executable, "-c", "while True: pass"], env=env, cwd=tmp_path,
                           log_file=lf, timeout=2, stall_s=None, poll_s=0.5)
        rc, out = run_supervised([sys.executable, "-c", "print('[1,2]')"], env=env, cwd=tmp_path,
                                 log_file=lf, timeout=30, stall_s=5, poll_s=0.2)
        assert rc == 0 and out.strip() == "[1,2]"
