"""What every test shares."""

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
