# SPDX-License-Identifier: GPL-3.0-or-later
"""No two tool names the voice could mix up (the plugin standard's rule 1).

Names that look or sound alike are listed here on purpose; each pair opens its
description with different words, which is what the voice chooses by.
"""

import asyncio
import difflib

from mister_mcp.server import build_server
from mister_mcp.service import MisterService
from mister_mcp.simulator import SimulatedMister, SimulatedShell
from mister_mcp.updater import UpdateService

#: Pairs that look or sound alike: search and launch share most letters, and
#: status and search both open with "s" when said aloud.
CONFUSABLE = {
    frozenset({"mister_search", "mister_launch"}),
    frozenset({"mister_launch", "mister_launch_confirm"}),
    frozenset({"mister_status", "mister_search"}),
    frozenset({"mister_status", "mister_update_status"}),
    frozenset({"mister_launch_confirm", "mister_update_confirm"}),
    frozenset({"mister_update_request", "mister_update_status"}),
}
#: How alike two names may be, as difflib reckons it, before the pair must be listed.
ALIKE = 0.75


def _tools():
    mister = SimulatedMister()
    updater = UpdateService(SimulatedShell(), mister, history=None)
    return asyncio.run(build_server(MisterService(mister), updater=updater).list_tools())


def test_no_two_tool_names_can_be_confused():
    tools = _tools()
    for i, one in enumerate(tools):
        for other in tools[i + 1 :]:
            alike = difflib.SequenceMatcher(None, one.name, other.name).ratio()
            if alike >= ALIKE:
                assert frozenset({one.name, other.name}) in CONFUSABLE, (one.name, other.name, alike)


def test_the_names_that_sound_alike_open_with_different_words():
    openings = {t.name: (t.description or "").split()[0] for t in _tools()}
    for pair in CONFUSABLE:
        one, other = sorted(pair)
        assert openings[one] != openings[other], pair


def test_no_tool_switches_power():
    # Power through a smart plug is not built; it will be a request and a confirm
    # (decisions/deferred.md). The confirms today end a running game, and start update_all.
    assert not [t.name for t in _tools() if "power" in t.name]
    confirms = sorted(t.name for t in _tools() if "confirm" in t.name)
    assert confirms == ["mister_launch_confirm", "mister_update_confirm"]
