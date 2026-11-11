# SPDX-License-Identifier: GPL-3.0-or-later
"""Every failure says what is wrong and what the owner does next, with the exact command where there is one.

A bare "not answering" with no next step is a bug (write-plugin checklist, item 10).
"""

import asyncio
import pathlib
import re

import pytest

from mister_mcp import cli
from mister_mcp.server import BROKE, WORKING
from mister_mcp.service import MisterService
from mister_mcp.settings import SettingsError, load_settings
from mister_mcp.simulator import ADDRESS, SimulatedMister
from mister_mcp.ssh import key_missing
from mister_mcp.tv import SimulatedTvPlugin, TvSwitch, show_mister

#: Words a next step starts with, in English and in the owner's Norwegian.
STEPS = {
    "try",
    "say",
    "ask",
    "switch",
    "start",
    "run",
    "check",
    "turn",
    "fix",
    "set",
    "use",
    "which",
    "wait",
    "search",
    "change",
    "kjør",
    "sjekk",
    "si",
    "har",
}


def names_a_next_step(say: str) -> bool:
    """Whether some sentence or clause of `say` starts by telling the owner what to do."""
    parts = re.split(r"[.;:?!,]\s+", say)
    return any(part.split()[0].casefold() in STEPS for part in parts if part.split())


def _says(coro):
    return asyncio.run(coro)["say"]


def _bad_text_mister():
    mister = SimulatedMister()
    mister.extra_result = {
        "name": "Trap",
        "zapScript": "**execute:reboot",
        "system": {"id": "NES", "name": "Nintendo Entertainment System"},
    }
    return mister


def _unknown_game_mister():
    mister = SimulatedMister()
    mister.extra_result = {
        "name": "Lost Cart",
        "zapScript": "@NES/Lost Cart",
        "system": {"id": "NES", "name": "Nintendo Entertainment System"},
    }
    return mister


def _ignoring_mister():
    mister = SimulatedMister()
    mister.ignores_runs = True
    return mister


FAILURES = {
    "status, mister off": lambda: MisterService(SimulatedMister(on=False)).status(),
    "status, zaparoo down": lambda: MisterService(SimulatedMister(zaparoo=False)).status(),
    "search, nothing found": lambda: MisterService(SimulatedMister()).search("zzz"),
    "launch, nothing said": lambda: MisterService(SimulatedMister()).launch(),
    "launch, unknown system": lambda: MisterService(SimulatedMister()).launch(system="Amiga"),
    "launch, two games fit": lambda: MisterService(SimulatedMister()).launch(game="o"),
    "launch, no such game": lambda: MisterService(SimulatedMister()).launch(game="zzz"),
    "launch, a text it may not send": lambda: MisterService(_bad_text_mister()).launch(game="trap"),
    "launch, zaparoo refuses": lambda: MisterService(_unknown_game_mister()).launch(game="lost cart"),
    "launch, not shown after": lambda: MisterService(_ignoring_mister()).launch(game="Micro Mages"),
}


@pytest.mark.parametrize("case", FAILURES)
def test_every_tool_failure_names_a_next_step(case):
    answer = asyncio.run(FAILURES[case]())
    assert answer["success"] is False
    assert names_a_next_step(answer["say"]), answer["say"]


def test_an_unknown_system_is_answered_with_the_systems_it_has():
    say = _says(MisterService(SimulatedMister()).launch(system="Amiga"))
    assert "Amiga" in say
    assert "Gameboy" in say


class _Unreachable(TvSwitch):
    async def _offered(self):
        raise OSError


@pytest.mark.parametrize(
    "tv",
    [
        SimulatedTvPlugin(screen="off"),
        SimulatedTvPlugin(offers_input=False),
        _Unreachable(tv="the den", device="Game box"),
    ],
    ids=["tv off", "no input tool", "tv plugin down"],
)
def test_every_tv_failure_names_a_next_step(tv):
    say = _says(show_mister(tv))
    assert names_a_next_step(say), say


def test_the_servers_own_failures_name_a_next_step():
    assert names_a_next_step(BROKE)
    assert names_a_next_step(WORKING)
    assert "mister-mcp status" in BROKE


def test_a_missing_ssh_key_names_its_command():
    say = key_missing("Permission denied (publickey).", ADDRESS)
    assert names_a_next_step(say)
    assert f"ssh-copy-id root@{ADDRESS}" in say


def test_a_settings_file_that_is_not_toml_names_the_fix(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[mister\naddress = 1\n")
    with pytest.raises(SettingsError) as raised:
        load_settings(path)
    assert str(path) in str(raised.value)
    assert names_a_next_step(str(raised.value).split(";", 1)[1]), raised.value


def test_settings_errors_name_a_next_step(tmp_path):
    empty = tmp_path / "config.toml"
    empty.write_text("")
    with pytest.raises(SettingsError) as raised:
        cli._service(simulate=False, settings_file=str(empty))  # noqa: SLF001
    assert names_a_next_step(str(raised.value)), raised.value
    with pytest.raises(SettingsError) as raised:
        cli.tv_from({"name": "the den"})
    assert names_a_next_step(str(raised.value)), raised.value


def test_the_step_checker_refuses_a_bare_failure():
    assert not names_a_next_step("The MiSTer is not answering.")
    assert not names_a_next_step(str(pathlib.Path("x")))
