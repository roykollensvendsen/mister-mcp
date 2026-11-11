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
