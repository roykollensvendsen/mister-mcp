# SPDX-License-Identifier: GPL-3.0-or-later
"""The TV step through a real stdio child, as ADR-MM-002 describes, against a stand-in for tv-mcp."""

import asyncio
import json
import pathlib
import subprocess
import sys
import threading
import time

import pytest
from bounded import WITHIN

from mister_mcp.cli import tv_from
from mister_mcp.settings import SettingsError
from mister_mcp.tv import TvPlugin, show_mister

FAKE = pathlib.Path(__file__).with_name("fake_tv_mcp.py")
#: Seconds a TV step may take here before the TV plugin counts as left running.
LEFT_RUNNING = WITHIN


def _bounded(work, log):
    """Run `work()` to its end, or fail when a TV plugin left running keeps it from ending.

    An unclosed stand-in keeps asyncio.run waiting for ever; stopping it by its
    own log path lets the test fail and say so instead of hanging the suite.
    """
    box = {}
    thread = threading.Thread(target=lambda: box.setdefault("answer", asyncio.run(work())), daemon=True)
    thread.start()
    thread.join(LEFT_RUNNING)
    if thread.is_alive():
        subprocess.run(["pkill", "-f", str(log)], check=False, timeout=WITHIN)
        thread.join(LEFT_RUNNING)
        pytest.fail("the TV plugin was left running")
    return box["answer"]


def _show(tmp_path, screen):
    log = tmp_path / "calls.log"
    log.touch()
    plugin = TvPlugin(command=[sys.executable, str(FAKE), screen, str(log)], tv="the den", device="Game box")
    answer = _bounded(lambda: show_mister(plugin), log)
    return answer, [json.loads(line)[0] for line in log.read_text().splitlines()], plugin


def test_an_on_tv_is_switched_through_the_tv_plugins_own_tools(tmp_path):
    answer, calls, _ = _show(tmp_path, "on")
    assert calls == ["tv_status", "tv_input"]
    assert answer["outcome"] == "done"
    assert "Game box" in answer["say"]


def test_an_off_tv_gets_only_a_status_question(tmp_path):
    answer, calls, _ = _show(tmp_path, "off")
    assert calls == ["tv_status"]
    assert answer["outcome"] == "left_alone"


def test_the_tv_plugin_is_closed_after_each_use(tmp_path):
    _, _, plugin = _show(tmp_path, "on")
    assert not plugin.is_open


def test_a_tv_plugin_that_cannot_start_is_said_not_raised(tmp_path):
    plugin = TvPlugin(command=[str(tmp_path / "no-such-program")], tv="the den", device="Game box")
    answer = asyncio.run(show_mister(plugin))
    assert answer["success"] is False
    assert "TV" in answer["say"]


def test_the_tv_table_needs_a_command_and_a_name():
    assert tv_from({}) is None
    with pytest.raises(SettingsError):
        tv_from({"name": "the den"})
    plugin = tv_from({"command": ["tv-mcp", "serve"], "name": "the den"})
    assert plugin.device == "MiSTer"


def test_the_tv_plugin_is_closed_after_every_use_even_a_slow_one(tmp_path, monkeypatch):
    """The TV's time runs out while it answers, after its plugin has started."""
    monkeypatch.setattr("mister_mcp.tv.TV_WITHIN", 3.0)
    log = tmp_path / "calls.log"
    log.touch()
    command = [sys.executable, str(FAKE), "on", str(log), "60", "answer"]
    plugin = TvPlugin(command=command, tv="the den", device="Game box")
    # A plugin left open keeps the step from ending, which _bounded turns into a failure.
    answer = _bounded(lambda: show_mister(plugin), log)
    assert answer["outcome"] == "working"
    assert not plugin.is_open


def _running_with(marker, within=10.0):
    """The processes, zombies aside, still running with `marker` in their command after `within` s."""
    deadline = time.monotonic() + within
    while True:
        found = []
        for proc in pathlib.Path("/proc").glob("[0-9]*"):
            try:
                if marker in proc.joinpath("cmdline").read_text() and "State:\tZ" not in (
                    proc.joinpath("status").read_text()
                ):
                    found.append(proc.name)
            except OSError:
                continue
        if not found or time.monotonic() >= deadline:
            return found
        time.sleep(0.05)


async def _start_cut_short(plugin):
    """Enter the plugin as any caller would, with a limit that runs out while it starts."""
    try:
        async with asyncio.timeout(0.5), plugin:
            pass
    except TimeoutError:
        return "cut short"
    return "started"


@pytest.mark.skipif(not pathlib.Path("/proc").is_dir(), reason="reads running processes from /proc")
@pytest.mark.parametrize("caller", ["launch", "any"])
def test_a_tv_plugin_whose_start_is_cut_short_is_still_stopped(tmp_path, monkeypatch, caller):
    """The TV's time runs out while its plugin is still starting, as on a busy machine."""
    monkeypatch.setattr("mister_mcp.tv.TV_WITHIN", 0.5)
    log = tmp_path / "calls.log"
    log.touch()
    command = [sys.executable, str(FAKE), "on", str(log), "60"]
    plugin = TvPlugin(command=command, tv="the den", device="Game box")
    try:
        if caller == "launch":
            assert _bounded(lambda: show_mister(plugin), log)["outcome"] == "working"
        else:
            assert _bounded(lambda: _start_cut_short(plugin), log) == "cut short"
        assert not plugin.is_open
        left = _running_with(str(log))
        assert not left, f"the TV plugin was left running after its start was cut short: {left}"
    finally:
        # Whatever failed above, no stand-in is left sleeping out its 60 s.
        subprocess.run(["pkill", "-f", str(log)], check=False, timeout=WITHIN)
