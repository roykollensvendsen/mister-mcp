# SPDX-License-Identifier: GPL-3.0-or-later
"""mister_launch starts a game or a core, says what the MiSTer then runs, and only then shows it on the TV."""

import asyncio

from mister_mcp.service import MisterService
from mister_mcp.simulator import SimulatedMister
from mister_mcp.tv import SimulatedTvPlugin, TvSwitch


def _launch(mister=None, tv=None, **said):
    return asyncio.run(MisterService(mister or SimulatedMister(), tv=tv).launch(**said))


def _runs(mister):
    return [r["params"]["text"] for r in mister.sent if r["method"] == "run"]


def test_a_game_named_is_started_and_read_back():
    mister = SimulatedMister()
    answer = _launch(mister, game="micro mages")
    assert _runs(mister) == ["@NES/Micro Mages"]
    assert answer["outcome"] == "done"
    assert answer["game"] == "Micro Mages"
    assert "Micro Mages" in answer["say"]


def test_a_system_named_alone_starts_its_core():
    mister = SimulatedMister()
    answer = _launch(mister, system="super nintendo")
    assert _runs(mister) == ["**launch.system:SNES"]
    assert answer["outcome"] == "done"
    assert "no game" in answer["say"]


def test_a_name_that_fits_two_games_starts_neither_and_names_both():
    mister = SimulatedMister()
    answer = _launch(mister, game="t")
    assert _runs(mister) == []
    assert answer["outcome"] == "refused"
    assert "Which" in answer["say"]


def test_the_system_said_picks_between_two_games():
    mister = SimulatedMister()
    answer = _launch(mister, game="o", system="genesis")
    assert answer["outcome"] == "refused"  # Tanglewood and Xeno Crisis are both on the Genesis
    answer = _launch(mister, game="tanglewood", system="genesis")
    assert answer["outcome"] == "done"


def test_a_game_not_found_starts_nothing():
    mister = SimulatedMister()
    answer = _launch(mister, game="no such game")
    assert _runs(mister) == []
    assert answer["outcome"] == "not_found"


def test_the_voices_own_words_never_reach_a_start():
    mister = SimulatedMister()
    for said in ("**execute:reboot", "@SNES/x||**mister.script:a.sh", "**launch.search:*"):
        _launch(mister, game=said)
        _launch(mister, system=said)
    assert _runs(mister) == []


def test_a_bad_launch_text_from_zaparoo_itself_is_never_sent():
    mister = SimulatedMister()
    mister.extra_result = {
        "name": "Trap",
        "zapScript": "**execute:reboot",
        "system": {"id": "NES", "name": "Nintendo Entertainment System"},
    }
    answer = _launch(mister, game="trap")
    assert _runs(mister) == []
    assert answer["outcome"] == "refused"


def test_a_start_is_said_as_done_only_once_the_mister_shows_it():
    mister = SimulatedMister()
    mister.ignores_runs = True
    answer = _launch(mister, game="micro mages")
    assert answer["outcome"] == "unverified"
    assert "menu" in answer["say"]


def test_a_launch_on_a_mister_that_does_not_answer_says_so():
    answer = _launch(SimulatedMister(on=False), game="micro mages")
    assert answer["outcome"] == "unreachable"


def test_the_tv_is_switched_after_the_game_starts_when_it_is_on():
    tv = SimulatedTvPlugin(screen="on")
    answer = _launch(tv=tv, game="micro mages")
    assert tv.calls == [
        ("tv_status", {"tv": "the den"}),
        ("tv_input", {"source": "Game box", "tv": "the den"}),
    ]
    assert answer["tv"]["outcome"] == "done"
    assert "shows" in answer["say"]


def test_a_tv_that_is_not_on_is_never_sent_an_input():
    for screen in ("off", "standby", None):
        tv = SimulatedTvPlugin(screen=screen)
        answer = _launch(tv=tv, game="micro mages")
        assert [name for name, _ in tv.calls] == ["tv_status"]
        assert answer["tv"]["outcome"] == "left_alone"
        assert answer["outcome"] == "done"  # the game still started


def test_only_the_tv_status_and_input_tools_are_ever_called():
    assert TvSwitch.TOOLS == ("tv_status", "tv_input")
    tv = SimulatedTvPlugin(screen="on")
    asyncio.run(tv.call("tv_power_request", {"tv": "the den"}))
    assert tv.calls == []


def test_a_tv_plugin_without_tv_input_leaves_the_tv_alone():
    tv = SimulatedTvPlugin(screen="on", offers_input=False)
    answer = _launch(tv=tv, game="micro mages")
    assert answer["tv"]["outcome"] == "left_alone"
    assert "tv_input" not in [name for name, _ in tv.calls]


def test_the_tv_is_touched_only_once_the_game_started():
    tv = SimulatedTvPlugin(screen="on")
    _launch(tv=tv, game="no such game")
    assert tv.calls == []
