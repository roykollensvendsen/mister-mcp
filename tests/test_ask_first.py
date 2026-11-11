# SPDX-License-Identifier: GPL-3.0-or-later
"""A running game is never ended without the owner's clear yes (the owner's standing rule).

Starting another game or core while one runs is a request: the question names
what is running, and a one-time token that expires confirms it. From the menu,
a launch starts at once, as before.
"""

import asyncio

from mister_mcp.server import build_server
from mister_mcp.service import ASK_WITHIN, MisterService
from mister_mcp.simulator import SimulatedMister
from mister_mcp.tv import SimulatedTvPlugin


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _playing(system="NES", name="Micro Mages"):
    mister = SimulatedMister()
    mister.play(system, name)
    return mister


def _runs(mister):
    return [r["params"]["text"] for r in mister.sent if r["method"] == "run"]


def _service(mister, **options):
    return MisterService(mister, **options)


def test_a_running_game_is_never_ended_without_a_yes():
    mister = _playing()
    answer = asyncio.run(_service(mister).launch(game="Tanglewood"))
    assert _runs(mister) == []
    assert answer["outcome"] == "ask"
    assert answer["success"] is False
    assert answer["token"]
    assert answer["say"] == (
        "The MiSTer is playing Micro Mages on the Nintendo Entertainment System. "
        "Do you want me to end it and start Tanglewood?"
    )


def test_a_running_core_is_asked_about_too():
    mister = _playing("SNES", None)
    answer = asyncio.run(_service(mister).launch(system="Genesis"))
    assert _runs(mister) == []
    assert answer["outcome"] == "ask"
    assert "Super Nintendo Entertainment System core" in answer["say"]
    assert answer["say"].endswith("start the Sega Genesis core?")


def test_from_the_menu_a_launch_starts_at_once():
    mister = SimulatedMister()
    answer = asyncio.run(_service(mister).launch(game="Tanglewood"))
    assert answer["outcome"] == "done"
    assert _runs(mister) == ["@Genesis/Tanglewood"]


def test_the_yes_starts_what_was_asked_and_shows_it_on_the_tv():
    mister, tv = _playing(), SimulatedTvPlugin()
    service = _service(mister, tv=tv)

    async def ask_then_confirm():
        asked = await service.launch(game="Tanglewood")
        return await service.confirm(asked["token"])

    answer = asyncio.run(ask_then_confirm())
    assert answer["outcome"] == "done"
    assert answer["game"] == "Tanglewood"
    assert _runs(mister) == ["@Genesis/Tanglewood"]
    assert [tool for tool, _ in tv.calls] == ["tv_status", "tv_input"]


def test_a_token_works_once_and_only_while_fresh():
    clock = _Clock()
    mister = _playing()
    service = _service(mister, clock=clock)

    async def scenario():
        asked = await service.launch(game="Tanglewood")
        clock.now += ASK_WITHIN + 1
        late = await service.confirm(asked["token"])
        asked = await service.launch(game="Tanglewood")
        first = await service.confirm(asked["token"])
        second = await service.confirm(asked["token"])
        return late, first, second

    late, first, second = asyncio.run(scenario())
    assert late["outcome"] == "refused"
    assert "Ask me to start it again" in late["say"]
    assert first["outcome"] == "done"
    assert second["outcome"] == "refused"
    assert _runs(mister) == ["@Genesis/Tanglewood"]


def test_a_made_up_token_starts_nothing():
    mister = _playing()
    answer = asyncio.run(_service(mister).confirm("guessed"))
    assert answer["outcome"] == "refused"
    assert _runs(mister) == []


def test_a_token_is_kept_when_the_start_never_reached_the_mister():
    mister = _playing()
    service = _service(mister)

    async def scenario():
        asked = await service.launch(game="Tanglewood")
        mister.on = False
        lost = await service.confirm(asked["token"])
        mister.on = True
        again = await service.confirm(asked["token"])
        return lost, again

    lost, again = asyncio.run(scenario())
    assert lost["outcome"] == "unreachable"
    assert again["outcome"] == "done"


def test_the_question_is_asked_only_once_the_game_is_known():
    mister = _playing()
    answer = asyncio.run(_service(mister).launch(game="zzz"))
    assert answer["outcome"] == "not_found"
    assert "token" not in answer


def test_the_voice_confirms_through_its_own_tool():
    mister = _playing()
    server = build_server(MisterService(mister), simulated=True)

    async def scenario():
        asked = (await server.call_tool("mister_launch", {"game": "Tanglewood"})).structured_content
        done = (await server.call_tool("mister_launch_confirm", {"token": asked["token"]})).structured_content
        return asked, done

    asked, done = asyncio.run(scenario())
    assert asked["outcome"] == "ask"
    assert asked["say"].startswith("Simulated: The MiSTer is playing Micro Mages")
    assert done["outcome"] == "done"
    assert _runs(mister) == ["@Genesis/Tanglewood"]
