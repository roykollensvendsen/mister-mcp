# SPDX-License-Identifier: GPL-3.0-or-later
"""mister_status says whether the MiSTer is on, and what it is running, from what Zaparoo reports."""

import asyncio

from mister_mcp.service import MisterService
from mister_mcp.simulator import SimulatedMister


def _status(mister):
    return asyncio.run(MisterService(mister).status())


def test_a_mister_at_its_menu_is_on_and_playing_nothing():
    answer = _status(SimulatedMister())
    assert answer["success"] is True
    assert answer["on"] is True
    assert answer["game"] is None
    assert "menu" in answer["say"]


def test_a_mister_playing_a_game_names_the_game_and_the_system():
    mister = SimulatedMister()
    mister.play("SNES", "Super Boss Gaiden")
    answer = _status(mister)
    assert answer["on"] is True
    assert answer["game"] == "Super Boss Gaiden"
    assert answer["system"] == "Super Nintendo Entertainment System"
    assert "Super Boss Gaiden" in answer["say"]
    assert "Super Nintendo" in answer["say"]


def test_a_mister_that_does_not_answer_is_not_called_on_or_off():
    mister = SimulatedMister(on=False)
    answer = _status(mister)
    assert answer["success"] is False
    assert answer["outcome"] == "unreachable"
    assert answer["on"] is None
    assert "off" in answer["say"]
    assert "network" in answer["say"]


def test_a_mister_that_answers_without_zaparoo_is_called_on():
    mister = SimulatedMister(zaparoo=False)
    answer = _status(mister)
    assert answer["success"] is False
    assert answer["outcome"] == "unreachable"
    assert answer["on"] is True
    assert answer["say"].startswith("The MiSTer is on, but Zaparoo isn't running on it.")
    assert "off" not in answer["say"]


def test_search_and_launch_say_zaparoo_is_not_running_too():
    mister = SimulatedMister(zaparoo=False)
    service = MisterService(mister)
    for answer in (asyncio.run(service.search("mages")), asyncio.run(service.launch(game="Micro Mages"))):
        assert answer["outcome"] == "unreachable"
        assert "Zaparoo isn't running" in answer["say"]
