# SPDX-License-Identifier: GPL-3.0-or-later
"""mister_search finds games by name among those Zaparoo has indexed."""

import asyncio

from mister_mcp.service import MAX_RESULTS, SEARCH_FETCH, MisterService
from mister_mcp.simulator import SimulatedMister, release


def _search(name, mister=None, **said):
    return asyncio.run(MisterService(mister or SimulatedMister()).search(name, **said))


def _mario(*files):
    """A MiSTer that also has `files`, as (system, file name)."""
    mister = SimulatedMister()
    mister.library = [release(system, file) for system, file in files]
    return mister


def test_a_name_finds_the_game_and_its_system():
    answer = _search("micro mages")
    assert answer["success"] is True
    assert answer["games"] == [
        {"name": "Micro Mages", "system": "Nintendo Entertainment System", "region": None, "kind": None}
    ]
    assert "Micro Mages" in answer["say"]


def test_a_word_found_in_several_names_lists_each():
    answer = _search("o")
    assert len(answer["games"]) == MAX_RESULTS
    assert "more" in answer["say"]


def test_a_name_with_no_game_says_what_to_try_next():
    answer = _search("no such game")
    assert answer["success"] is False
    assert answer["outcome"] == "not_found"
    assert "Try" in answer["say"]


def test_a_search_asks_zaparoo_for_a_bounded_number_of_games():
    mister = SimulatedMister()
    _search("girl", mister)
    (request,) = mister.sent
    assert request["method"] == "media.search"
    assert request["params"]["maxResults"] == SEARCH_FETCH


def test_a_search_for_one_system_asks_zaparoo_for_that_system_only():
    others = [("GBA", f"Super Mario Bros {n} (USA).gba") for n in range(MAX_RESULTS + 1)]
    mister = _mario(*others, ("NES", "Super Mario Bros (E).nes"))
    answer = _search("super mario bros", mister, system="nes")
    searched = [r for r in mister.sent if r["method"] == "media.search"]
    assert [r["params"]["systems"] for r in searched] == [["NES"]]
    assert answer["games"] == [
        {"name": "Super Mario Bros", "system": "Nintendo Entertainment System", "region": "eu", "kind": None}
    ]


def test_a_search_for_a_system_the_mister_lacks_names_what_it_has():
    answer = _search("mario", system="atari jaguar")
    assert answer["outcome"] == "refused"
    assert "no system called atari jaguar" in answer["say"]


def test_each_hit_names_its_region_and_an_alternate_only_when_it_is_shown():
    mister = _mario(("NES", "Super Mario Bros (E).nes"), ("NES", "Super Mario Bros (J) [a1].nes"))
    answer = _search("super mario bros", mister, system="nes")
    assert "Super Mario Bros on the Nintendo Entertainment System (Europe)" in answer["say"]
    assert "(Japan, alternate)" in answer["say"]
    assert answer["say"].count(".") == 1


def test_a_search_is_read_five_at_a_time_from_the_offset():
    mister = _mario(*(("NES", f"Tetris {n} (Europe).nes") for n in range(12)))
    first = _search("tetris", mister, system="nes")
    assert [g["name"] for g in first["games"]] == [f"Tetris {n}" for n in range(5)]
    assert "5 of 12 on the Nintendo Entertainment System; say more for the next five" in first["say"]
    second = _search("tetris", mister, system="nes", offset=5)
    assert [g["name"] for g in second["games"]] == [f"Tetris {n}" for n in range(5, 10)]
    last = _search("tetris", mister, system="nes", offset=10)
    assert [g["name"] for g in last["games"]] == ["Tetris 10", "Tetris 11"]
    assert "the last 2 of 12" in last["say"]
    past = _search("tetris", mister, system="nes", offset=12)
    assert past["games"] == []
    assert "all 12" in past["say"]


def test_hidden_versions_are_counted_and_all_versions_shows_them():
    mister = _mario(("NES", "Super Mario Bros (E).nes"), ("NES", "Super Mario Bros (JU) [h1].nes"))
    answer = _search("super mario bros", mister, system="nes")
    assert len(answer["games"]) == 1
    assert (
        "left out: 1 version such as hacks and translations; say all versions to hear them" in answer["say"]
    )
    every = _search("super mario bros", mister, system="nes", all_versions=True)
    assert [g["kind"] for g in every["games"]] == [None, "hack"]
    assert "(USA, hack)" in every["say"]


def test_a_name_found_only_as_hidden_versions_says_how_to_hear_them():
    mister = _mario(("NES", "Super Mario Bros (JU) [h1].nes"))
    answer = _search("super mario bros", mister, system="nes")
    assert answer["outcome"] == "not_found"
    assert "say all versions" in answer["say"]


def test_a_search_of_a_mister_that_does_not_answer_says_so():
    answer = _search("tanglewood", SimulatedMister(on=False))
    assert answer["outcome"] == "unreachable"
