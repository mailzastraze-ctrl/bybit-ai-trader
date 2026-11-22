"""Audit 2026-11-22, C9: only the trading bot gets the Bybit keys."""

import os

from aitrader.supervisor import take_exchange_keys


def test_exchange_keys_leave_the_shared_environment(monkeypatch):
    monkeypatch.setenv("BYBIT_API_KEY", "k-test")
    monkeypatch.setenv("BYBIT_API_SECRET", "s-test")
    assert take_exchange_keys() == ("k-test", "s-test")
    child = {**os.environ}  # what web, manager, research and the self-test are started with
    assert "BYBIT_API_KEY" not in child and "BYBIT_API_SECRET" not in child


def test_missing_keys_stay_missing(monkeypatch):
    monkeypatch.delenv("BYBIT_API_KEY", raising=False)
    monkeypatch.delenv("BYBIT_API_SECRET", raising=False)
    assert take_exchange_keys() == ("", "")
