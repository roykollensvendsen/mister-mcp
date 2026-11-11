# SPDX-License-Identifier: GPL-3.0-or-later
"""A command the voice suggests runs as it is typed: neither program is on the PATH, so uv runs it."""

import asyncio
import pathlib
import shlex
import subprocess

from mister_mcp.server import BROKE, MISTER_STATUS
from mister_mcp.tv import TvPlugin, TvSwitch, show_mister

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_a_broken_tool_names_a_command_that_runs_as_typed():
    assert MISTER_STATUS in BROKE
    assert MISTER_STATUS.startswith("uv run --directory ~/mister-mcp ")
    words = [*shlex.split(MISTER_STATUS.replace("~/mister-mcp", str(ROOT))), "--simulate"]
    done = subprocess.run(words, capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("Simulated: The MiSTer is on")


class _Down(TvSwitch):
    async def _offered(self):
        raise OSError


def test_an_unreachable_tv_plugin_names_its_own_status_command():
    tv = TvPlugin(
        command=["uv", "run", "--directory", "~/tv-mcp", "tv-mcp", "serve"], tv="the den", device="x"
    )
    assert tv.status_command() == "uv run --directory ~/tv-mcp tv-mcp status"


def test_the_tv_plugins_status_command_is_said_when_it_cannot_be_reached():
    say = asyncio.run(show_mister(_Down(tv="the den", device="Game box")))["say"]
    assert "uv run --directory ~/tv-mcp tv-mcp status" in say
