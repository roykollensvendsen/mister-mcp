# SPDX-License-Identifier: GPL-3.0-or-later
"""Only the calls ADR-MM-001 lists ever reach the MiSTer, and only texts built here start anything."""

import asyncio
import socket

import pytest

from mister_mcp.simulator import SimulatedMister
from mister_mcp.zaparoo import (
    ALLOWED_METHODS,
    NotAllowedError,
    UnreachableError,
    WebSocketTransport,
    Zaparoo,
    ZaparooNotRunningError,
    game_text,
    system_text,
)


def _run(coro):
    return asyncio.run(coro)


def test_only_an_allow_listed_call_is_ever_sent():
    mister = SimulatedMister()
    client = Zaparoo(mister)
    for method in ("settings.update", "media.generate", "input.keyboard", "mappings.delete", "stop"):
        with pytest.raises(NotAllowedError):
            _run(client.call(method))
    assert mister.sent == []


def test_the_allow_list_is_the_one_the_decision_record_names():
    assert frozenset({"version", "media.active", "media.search", "systems", "run"}) == ALLOWED_METHODS


def test_a_core_is_started_only_by_a_system_zaparoo_listed():
    assert system_text("SNES", ["SNES", "Genesis"]) == "**launch.system:SNES"
    for said in ("snes; **execute:rm", "Amiga", "SNES||**mister.ini:2"):
        with pytest.raises(NotAllowedError):
            system_text(said, ["SNES", "Genesis"])


def test_a_game_is_started_only_by_the_text_its_search_result_gave():
    assert game_text("@SNES/Super Boss Gaiden") == "@SNES/Super Boss Gaiden"
    for text in (
        "**execute:reboot",
        "@SNES/A||**mister.script:x.sh",
        "@SNES/A **mister.ini:1",
        "SNES/game.sfc",
        "**launch.search:*",
        "@SNES/A\n**execute:x",
    ):
        with pytest.raises(NotAllowedError):
            game_text(text)


def test_every_start_is_sent_as_from_a_remote_source():
    mister = SimulatedMister()
    _run(Zaparoo(mister).run("**launch.system:SNES"))
    (request,) = [r for r in mister.sent if r["method"] == "run"]
    assert request["params"] == {"text": "**launch.system:SNES", "unsafe": True}


def test_run_refuses_a_text_it_did_not_build():
    mister = SimulatedMister()
    with pytest.raises(NotAllowedError):
        _run(Zaparoo(mister).run("**execute:reboot"))
    assert mister.sent == []


def test_a_refused_connection_means_zaparoo_is_not_running():
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
    transport = WebSocketTransport("127.0.0.1", port=port)
    with pytest.raises(ZaparooNotRunningError) as raised:
        asyncio.run(transport.send({"jsonrpc": "2.0", "id": 1, "method": "version"}, wait=1.0))
    assert isinstance(raised.value, UnreachableError)
