# SPDX-License-Identifier: GPL-3.0-or-later
"""A stand-in for tv-mcp's server: tv_status, tv_input and a power tool, answering as tv-mcp does.

Run as ``python fake_tv_mcp.py <screen> <log file> [<seconds> [answer]]``; each call is appended
to the log. With seconds, it waits that long before it starts, as a TV plugin starting on a busy
machine does; with ``answer`` too, it starts at once and waits that long before each answer.
"""

import asyncio
import json
import pathlib
import sys
import time

from mcp.server.mcpserver import MCPServer

SCREEN, LOG = sys.argv[1], pathlib.Path(sys.argv[2])
server = MCPServer(name="tv")


def _log(tool, **arguments):
    with LOG.open("a") as log:
        log.write(json.dumps([tool, arguments]) + "\n")


@server.tool()
async def tv_status(tv: str) -> dict:
    _log("tv_status", tv=tv)
    if sys.argv[4:] == ["answer"]:
        await asyncio.sleep(float(sys.argv[3]))
    entry = {"tv": tv, "state": "reachable", "screen": SCREEN}
    return {"success": True, "say": "...", "tvs": [entry]}


@server.tool()
async def tv_input(source: str, tv: str) -> dict:
    _log("tv_input", source=source, tv=tv)
    return {"success": True, "outcome": "done", "say": f"{tv} shows HDMI 3, the {source}, now."}


@server.tool()
async def tv_power_request(tv: str) -> dict:
    _log("tv_power_request", tv=tv)
    return {"success": True, "outcome": "asked", "say": "Switch it on?"}


if sys.argv[3:4] and sys.argv[4:] != ["answer"]:
    time.sleep(float(sys.argv[3]))
server.run()
