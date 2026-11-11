# SPDX-License-Identifier: GPL-3.0-or-later
"""The TV's screen is read from tv-mcp's answer as tv-mcp really gives it: one entry per TV under "tvs".

A tv_status answer has no top-level "screen". Reading only the top level took
every TV for off, so the MiSTer was never shown.
"""

import asyncio

import pytest

from mister_mcp.tv import TvSwitch, screen_of


def real_answer(tv="the den", **entry):
    """tv_status as tv-mcp answered it by day, 2026-11-11, with the names made neutral."""
    return {
        "success": True,
        "say": "The den is reachable, the TV itself is off, volume 1.",
        "simulated": False,
        "tvs": [
            {
                "tv": tv,
                "model": "Chromecast",
                "state": "reachable",
                "volume": 1,
                "muted": False,
                "screen": "off",
                "inputs": [{"input": "HDMI 3", "device": "Game box", "from": "set by hand"}],
            }
            | entry
        ],
    }


@pytest.mark.parametrize(
    ("answer", "screen"),
    [
        (real_answer(screen="on"), "on"),
        (real_answer(), "off"),
        (real_answer(screen=None, state="on"), "on"),
        (real_answer(tv="the hall", screen="on"), None),
        ({"success": False, "say": "No TV called that."}, None),
    ],
    ids=["screen on", "screen off, reachable", "state alone", "another tv", "no tvs"],
)
def test_the_screen_is_read_from_the_tvs_own_entry(answer, screen):
    assert screen_of(answer, "the den") == screen


class _Answers(TvSwitch):
    def __init__(self, answer):
        super().__init__(tv="the den", device="Game box")
        self.answer, self.sent = answer, []

    async def _offered(self):
        return {"tv_status", "tv_input"}

    async def _send(self, tool, arguments):
        self.sent.append(tool)
        if tool == "tv_status":
            return self.answer
        return {"success": True, "outcome": "done", "say": "The den shows the Game box now."}


def test_a_tv_whose_screen_is_on_in_the_real_answer_is_switched():
    tv = _Answers(real_answer(screen="on"))
    answer = asyncio.run(tv.show_mister())
    assert tv.sent == ["tv_status", "tv_input"]
    assert answer["outcome"] == "done"


def test_a_reachable_tv_with_its_screen_off_is_left_alone():
    tv = _Answers(real_answer())
    assert asyncio.run(tv.show_mister())["outcome"] == "left_alone"
    assert tv.sent == ["tv_status"]
