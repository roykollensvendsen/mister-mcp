# SPDX-License-Identifier: GPL-3.0-or-later
"""mister_search finds games by name among those Zaparoo has indexed."""

import asyncio

from mister_mcp.service import MAX_RESULTS, MisterService
from mister_mcp.simulator import SimulatedMister


def _search(name, mister=None):
    return asyncio.run(MisterService(mister or SimulatedMister()).search(name))


def test_a_name_finds_the_game_and_its_system():
    answer = _search("micro mages")
    assert answer["success"] is True
    assert answer["games"] == [{"name": "Micro Mages", "system": "Nintendo Entertainment System"}]
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


def test_a_search_asks_zaparoo_for_no_more_than_it_reads_out():
    mister = SimulatedMister()
    _search("girl", mister)
    (request,) = mister.sent
    assert request["method"] == "media.search"
    assert request["params"]["maxResults"] == MAX_RESULTS + 1


def test_a_search_of_a_mister_that_does_not_answer_says_so():
    answer = _search("tanglewood", SimulatedMister(on=False))
    assert answer["outcome"] == "unreachable"
