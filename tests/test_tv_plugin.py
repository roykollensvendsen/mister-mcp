# SPDX-License-Identifier: GPL-3.0-or-later
"""The TV step through a real stdio child, as ADR-MM-002 describes, against a stand-in for tv-mcp."""

import asyncio
import json
import pathlib
import sys

import pytest

from mister_mcp.cli import tv_from
from mister_mcp.settings import SettingsError
from mister_mcp.tv import CLOSE_WITHIN, TvPlugin, show_mister

FAKE = pathlib.Path(__file__).with_name("fake_tv_mcp.py")


def _show(tmp_path, screen):
    log = tmp_path / "calls.log"
    log.touch()
    plugin = TvPlugin(command=[sys.executable, str(FAKE), screen, str(log)], tv="the den", device="Game box")
    answer = asyncio.run(show_mister(plugin))
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
    monkeypatch.setattr("mister_mcp.tv.TV_WITHIN", 0.05)
    log = tmp_path / "calls.log"
    log.touch()
    plugin = TvPlugin(command=[sys.executable, str(FAKE), "on", str(log)], tv="the den", device="Game box")

    async def timed():
        loop = asyncio.get_running_loop()
        began = loop.time()
        answer = await show_mister(plugin)
        return answer, loop.time() - began

    answer, took = asyncio.run(timed())
    assert answer["outcome"] == "working"
    assert not plugin.is_open
    assert took <= 0.05 + CLOSE_WITHIN + 0.5
