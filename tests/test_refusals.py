# SPDX-License-Identifier: GPL-3.0-or-later
"""When Zaparoo refuses a start, the voice says why in plain words and what to do.

Zaparoo's own message is never read aloud.
"""

import asyncio

import pytest
from test_next_steps import names_a_next_step

from mister_mcp.service import REFUSALS, MisterService
from mister_mcp.simulator import SimulatedMister

#: The categories Zaparoo Core documents for a failed run (zaparoo.org/docs/core/api/methods, 2.22.1).
DOCUMENTED = {
    "busy",
    "media_not_found",
    "disabled",
    "invalid_script",
    "blocked",
    "playtime_limit",
    "timeout",
    "cancelled",
    "unavailable",
    "launch_repair",
    "execution_failed",
}
RAW = "zaparoo internal text 42"


def _refused_with(category):
    mister = SimulatedMister()
    mister.run_error = (RAW, category)
    return asyncio.run(MisterService(mister).launch(game="Micro Mages"))


def test_every_documented_category_has_its_own_sentence():
    assert set(REFUSALS) == DOCUMENTED


@pytest.mark.parametrize("category", [*sorted(DOCUMENTED), None, "something_new"])
def test_zaparoos_own_words_are_never_read_aloud(category):
    answer = _refused_with(category)
    assert answer["success"] is False
    assert RAW not in answer["say"]
    assert names_a_next_step(answer["say"]), answer["say"]
    assert answer["reason"] == category


@pytest.mark.parametrize("category", ["timeout", "cancelled"])
def test_a_start_that_may_still_go_through_is_not_called_refused(category):
    answer = _refused_with(category)
    assert answer["outcome"] == "unverified"
    assert "Ask what it is playing" in answer["say"]


def test_a_missing_file_says_to_search_again():
    assert "Search for it again" in _refused_with("media_not_found")["say"]
