"""What every test shares."""

import signal
from collections.abc import Iterator

import pytest

from mister_mcp import pairing, simulator


class _Clock:
    """Time that moves only when something waits, so no test sleeps for real."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


@pytest.fixture(autouse=True)
def _no_real_waiting(monkeypatch):
    """The pairing's wait for Zaparoo's rate limit moves this clock, and the simulator reads it."""
    clock = _Clock()
    monkeypatch.setattr(pairing, "_sleep", clock.sleep)
    monkeypatch.setattr(simulator, "time", clock)


STOPS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


@pytest.fixture(autouse=True)
def _stop_handlers_as_the_run_began() -> Iterator[None]:
    """Put back SIGINT, SIGTERM and SIGHUP after each test, as the runners install their own.

    Left behind, a later test stops differently, and the rule check could report a rule
    killed by another test. Proven by `tests/test_signal_handlers_are_restored.py`.
    """
    began = {each: signal.getsignal(each) for each in STOPS}
    yield
    for each, handler in began.items():
        signal.signal(each, handler)
