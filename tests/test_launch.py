# SPDX-License-Identifier: GPL-3.0-or-later
"""mister_launch starts a game or a core, says what the MiSTer then runs, and only then shows it on the TV."""

import asyncio

import pytest

from mister_mcp.service import MAX_RESULTS, READ_BACK_GAP, READ_BACK_TRIES, MisterService
from mister_mcp.simulator import SimulatedMister, release
from mister_mcp.tv import SimulatedTvPlugin, TvSwitch


def _launch(mister=None, tv=None, region_order=None, **said):
    service = MisterService(
        mister or SimulatedMister(), tv=tv, **({"region_order": region_order} if region_order else {})
    )
    return asyncio.run(service.launch(**said))


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
    refusing = SimulatedMister()
    refusing.extra_result = {
        "name": "Lost Cart",
        "zapScript": "@NES/Lost Cart",
        "system": {"id": "NES", "name": "Nintendo Entertainment System"},
    }
    ignoring = SimulatedMister()
    ignoring.ignores_runs = True
    for mister, said in ((None, "no such game"), (refusing, "lost cart"), (ignoring, "micro mages")):
        tv = SimulatedTvPlugin(screen="on")
        answer = _launch(mister, tv=tv, game=said)
        assert answer["success"] is False, said
        assert tv.calls == [], said


def test_a_hands_off_tv_is_never_sent_an_input():
    # tv-mcp answers for a TV the owner marked to be left alone without a screen state.
    class HandsOff(SimulatedTvPlugin):
        async def _send(self, tool, arguments):
            self.calls.append((tool, arguments))
            return {"success": False, "outcome": "refused", "say": "The den is left alone."}

    tv = HandsOff()
    answer = _launch(tv=tv, game="micro mages")
    assert [name for name, _ in tv.calls] == ["tv_status"]
    assert answer["tv"]["outcome"] == "left_alone"


class _Pauses:
    """Stands in for asyncio.sleep, keeping each pause instead of waiting."""

    def __init__(self):
        self.taken = []

    async def __call__(self, seconds):
        self.taken.append(seconds)


def _reads_after_the_start(mister):
    methods = [r["method"] for r in mister.sent]
    return methods[methods.index("run") + 1 :].count("media.active")


def test_a_game_that_loads_slowly_is_still_said_as_started():
    mister = SimulatedMister()
    mister.loads_after = 2
    pauses = _Pauses()
    answer = asyncio.run(MisterService(mister, pause=pauses).launch(game="Micro Mages"))
    assert answer["outcome"] == "done"
    assert _reads_after_the_start(mister) == 3
    assert pauses.taken == [READ_BACK_GAP, READ_BACK_GAP]


def test_the_read_back_stops_after_its_tries():
    mister = SimulatedMister()
    mister.loads_after = 10
    pauses = _Pauses()
    answer = asyncio.run(MisterService(mister, pause=pauses).launch(game="Micro Mages"))
    assert answer["outcome"] == "unverified"
    assert _reads_after_the_start(mister) == READ_BACK_TRIES
    assert len(pauses.taken) == READ_BACK_TRIES - 1


def test_a_start_shown_at_once_is_not_waited_for():
    mister = SimulatedMister()
    pauses = _Pauses()
    asyncio.run(MisterService(mister, pause=pauses).launch(game="Micro Mages"))
    assert pauses.taken == []


def _versions(*files):
    """A MiSTer that also has these NES files."""
    mister = SimulatedMister()
    mister.library = [release("NES", file) for file in files]
    return mister


EUROPE_FIRST, USA_FIRST = ("eu", "world", "us", "jp"), ("us", "world", "eu", "jp")
MARIO = ("Super Mario Bros (E).nes", "Super Mario Bros (E) [a1].nes", "Super Mario Bros (JU) [h1].nes")


def test_a_launch_for_a_region_starts_only_that_regions_file():
    mister = _versions(*MARIO, "Super Mario Bros (U).nes")
    answer = _launch(mister, region_order=USA_FIRST, game="super mario bros", system="nes", region="eu")
    assert _runs(mister) == ["@NES/Super Mario Bros (E)"]
    assert answer["outcome"] == "done"


def test_a_launch_for_one_system_finds_its_game_behind_many_on_others():
    mister = _versions("Super Mario Bros (E).nes")
    mister.library += [release("GBA", f"Super Mario Bros {n} (USA).gba") for n in range(MAX_RESULTS + 1)]
    answer = _launch(mister, game="super mario bros", system="nes")
    assert _runs(mister) == ["@NES/Super Mario Bros (E)"]
    assert answer["outcome"] == "done"


#: A big GoodNES-style collection's every kind of "Super Mario Bros" file, as Zaparoo lists them.
REAL_NES_SET = (
    "NESroms/Europe/Super Mario Bros (E).nes",
    "NESroms/Europe/Super Mario Bros (E) [a1].nes",
    "NESroms/PC10/Super Mario Bros (PC10).nes",
    "NESroms/Hacks M-Z/Super Mario Bros (FDS Hack) (J).nes",
    "NESroms/Hacks M-Z/Super Mario Bros (JU) [h1].nes",
    "NESroms/Hacks M-Z/Super Mario Bros (JU) [h2].nes",
    "NESroms/Hacks M-Z/Super Mario Bros (JU) (No Title Hack).nes",
    "NESroms/Pirate/Super Mario Bros (JU) [p1].nes",
    "NESroms/Pirate/Super Mario Bros (JU) (PRG 1) [p1].nes",
    "NESroms/Trained Hacks/Super Mario Bros (JU) (PRG 0) [t1].nes",
    "NESroms/Trained Hacks/Super Mario Bros (JU) [t1].nes",
    "NESroms/Translated/Super Mario Bros (JU) (PRG 0) [T-Polish1.02].nes",
    "NESroms/Translated/Super Mario Bros (JU) (PRG 0) [T-Port].nes",
    "NESroms/Translated/Super Mario Bros (JU) (PRG 0) [T-Swed].nes",
    "NESroms/Translated/Super Mario Bros (JU) (PRG 1) [T-Norwegian_Just4Fun].nes",
    "NESroms/Translated/Super Mario Bros (JU) (PRG 1) [T-Polish1.02].nes",
    "NESroms/Translated/Super Mario Bros (JU) (PRG 1) [T-Swed].nes",
    "NESroms/Hacks M-Z/Super Mario Bros 1.5 (SMB1 Hack).nes",
    "NESroms/Europe/Super Mario Bros - Duck Hunt (E).nes",
    "NESroms/Pirate/All Night Nippon Super Mario Bros [p1].nes",
)


@pytest.mark.parametrize("order", [EUROPE_FIRST, USA_FIRST])
def test_a_plain_title_starts_the_clean_cartridge_in_the_owners_region_order(order):
    mister = _versions(*REAL_NES_SET)  # its only clean cartridge is the European one
    answer = _launch(mister, region_order=order, game="super mario bros", system="nes")
    assert _runs(mister) == ["@NES/Super Mario Bros (E)"]
    assert answer["outcome"] == "done"
    mister = _versions(*REAL_NES_SET, "NESroms/USA/Super Mario Bros (U).nes")
    _launch(mister, region_order=order, game="super mario bros", system="nes")
    assert _runs(mister) == ["@NES/Super Mario Bros (E)" if order[0] == "eu" else "@NES/Super Mario Bros (U)"]


def test_a_launch_for_a_region_the_mister_lacks_says_so():
    mister = _versions(*MARIO)
    answer = _launch(mister, game="super mario bros", system="nes", region="world")
    assert _runs(mister) == []
    assert answer["outcome"] == "not_found"
    assert "no World version" in answer["say"]


@pytest.mark.parametrize(
    ("file", "said", "region"),
    [
        ("NESroms/Hacks M-Z/Super Mario Bros 1.5 (SMB1 Hack).nes", "(hack)", None),
        ("NESroms/Hacks M-Z/Super Mario Bros 1.5 (E) [h1].nes", "(Europe, hack)", None),
        ("NESroms/Europe/Super Mario Bros 1.5 (E).nes", "(Europe)", "eu"),
    ],
)
def test_a_start_names_the_version_it_started(file, said, region):
    mister = _versions(file)
    answer = _launch(mister, game="super mario bros 1.5", system="nes", region=region)
    assert answer["outcome"] == "done"
    assert answer["say"].startswith(
        f"Started. The MiSTer is playing Super Mario Bros 1.5 on the Nintendo Entertainment System {said}."
    )


def test_a_clean_cartridge_with_no_region_is_started_with_no_version_said():
    answer = _launch(game="micro mages")
    assert answer["say"].startswith(
        "Started. The MiSTer is playing Micro Mages on the Nintendo Entertainment System."
    )


def test_the_question_before_ending_a_game_names_the_version_it_would_start():
    mister = _versions("NESroms/Hacks M-Z/Super Mario Bros 1.5 (E) [h1].nes")
    mister.play("NES", "Micro Mages")
    answer = _launch(mister, game="super mario bros 1.5", system="nes")
    assert answer["outcome"] == "ask"
    assert answer["say"].endswith("Do you want me to end it and start Super Mario Bros 1.5 (Europe, hack)?")
