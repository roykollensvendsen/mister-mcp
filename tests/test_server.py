# SPDX-License-Identifier: GPL-3.0-or-later
"""The MCP tools, as the voice sees them, against the simulated MiSTer."""

import asyncio
import re

from mister_mcp import tv, zaparoo
from mister_mcp.server import ANSWER_WITHIN, build_server
from mister_mcp.service import MisterService
from mister_mcp.simulator import SimulatedMister

#: The tools that change nothing on the MiSTer or a TV (the plugin standard's rule 9).
READ_ONLY = {"mister_status", "mister_search"}
#: The characters of a description the voice saw before loading a tool, 2026-11-10 (tv-mcp).
OPENING_LIMIT = 26


def _server(mister=None, *, simulated=True):
    return build_server(MisterService(mister or SimulatedMister()), simulated=simulated)


def _tools(server):
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


def _call(server, tool, arguments=None):
    return asyncio.run(server.call_tool(tool, arguments or {})).structured_content


def test_every_tool_is_named_after_the_plugin():
    assert all(name.startswith("mister_") for name in _tools(_server()))


def test_the_tools_that_only_look_are_marked_read_only_and_no_others():
    for name, tool in _tools(_server()).items():
        assert tool.annotations is not None, name
        assert tool.annotations.read_only_hint is (name in READ_ONLY), name


def test_every_tool_opens_with_a_whole_sentence_the_voice_sees_in_full():
    openings = {}
    for name, tool in _tools(_server()).items():
        opening = (tool.description or "").split("\n", 1)[0]
        assert len(opening) <= OPENING_LIMIT, f"{name}: {opening!r}"
        assert re.fullmatch(r"[A-Z][^.?;:]*[.?]", opening), f"{name}: {opening!r}"
        start = " ".join(opening.casefold().split()[:2])
        assert openings.setdefault(start, name) == name, f"{name} and {openings[start]} open alike"


def test_every_simulated_answer_says_simulated_first():
    answer = _call(_server(), "mister_status")
    assert answer["say"].startswith("Simulated: ")
    assert answer["simulated"] is True


def test_a_real_answer_does_not_say_simulated():
    answer = _call(_server(simulated=False), "mister_status")
    assert not answer["say"].startswith("Simulated")
    assert answer["simulated"] is False


def test_mister_status_says_what_is_playing():
    mister = SimulatedMister()
    mister.play("NES", "Micro Mages")
    answer = _call(_server(mister), "mister_status")
    assert answer["outcome"] == "done"
    assert answer["game"] == "Micro Mages"


def test_every_tool_answers_with_a_sentence_even_when_it_fails():
    class Broken:
        async def send(self, request, *, wait):
            raise RuntimeError

    answer = _call(build_server(MisterService(Broken())), "mister_status")
    assert answer["success"] is False
    assert answer["say"].endswith(".")


def test_a_tool_still_working_at_the_deadline_says_it_carries_on(monkeypatch):
    class Slow:
        async def send(self, request, *, wait):
            await asyncio.sleep(1)
            return {"id": request["id"], "result": None}

    monkeypatch.setattr("mister_mcp.server.ANSWER_WITHIN", 0.01)
    answer = _call(build_server(MisterService(Slow())), "mister_status")
    assert answer["outcome"] == "working"
    assert "carries on" in answer["say"]


def test_a_slow_launch_is_never_asked_for_again(monkeypatch):
    class Slow:
        async def send(self, request, *, wait):
            await asyncio.sleep(1)
            return {"id": request["id"], "result": None}

    monkeypatch.setattr("mister_mcp.server.ANSWER_WITHIN", 0.01)
    answer = _call(build_server(MisterService(Slow())), "mister_launch", {"game": "Micro Mages"})
    assert answer["outcome"] == "working"
    assert "Ask what it is playing in a moment." in answer["say"]
    assert "again" not in answer["say"]


def test_a_tools_longest_wait_fits_in_the_voices_time():
    voice_limit, margin = 15.0, 2.0
    assert ANSWER_WITHIN + margin <= voice_limit


def test_a_launchs_longest_path_finishes_within_half_a_minute():
    each = zaparoo.CONNECT_WAIT
    longest = (
        (each + zaparoo.READ_WAIT)  # systems
        + (each + zaparoo.READ_WAIT)  # search
        + (each + zaparoo.RUN_WAIT)  # run
        + (each + zaparoo.READ_WAIT)  # read back
        + tv.TV_WITHIN
    )
    assert longest <= 30.0


def test_mister_launch_starts_the_game_and_says_so():
    answer = _call(_server(), "mister_launch", {"game": "xeno crisis"})
    assert answer["outcome"] == "done"
    assert answer["say"].startswith("Simulated: Started.")


def test_mister_search_names_the_games_it_found():
    answer = _call(_server(), "mister_search", {"name": "tanglewood"})
    assert answer["games"] == [{"name": "Tanglewood", "system": "Sega Genesis"}]
