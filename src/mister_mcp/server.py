# SPDX-License-Identifier: GPL-3.0-or-later
"""The MCP server: the MiSTer's tools, over stdio for a voice session.

Run with ``mister-mcp serve``; ``mister-mcp serve --simulate`` answers the same
tools from a pretend MiSTer (mister_mcp.simulator), and every answer then says
"Simulated:" first.
"""

from __future__ import annotations

import asyncio
import functools
from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mister_mcp.service import MisterService
    from mister_mcp.updater import UpdateService

INSTRUCTIONS = (
    "Says what the owner's MiSTer FPGA is playing and finds its games by name. "
    "Read each 'say' aloud as it is. "
    "Start a game only when the owner asks for it now. When a game is running, mister_launch asks first: "
    "read its question, and call mister_launch_confirm with its token only if the owner clearly says yes. "
    "update_all is the same: mister_update_request asks, and only the owner's clear yes goes to "
    "mister_update_confirm; mister_update_status says how it is going. "
    "Only update_all changes files on the MiSTer, and no tool switches a TV on."
)
SIMULATED = "A SIMULATED MiSTer, not a real one: say so. "
#: The Claude app gives up on a call after about 15 seconds; every tool answers before then.
ANSWER_WITHIN = 12.0
#: What the voice hears when a tool is still working by then; the work carries on.
WORKING = "That is taking a while, and it carries on. Ask again in a moment to hear how it went."
#: What the voice hears when update_all's start is still going by then. A second yes now could
#: start it twice, so it says to ask how it is going instead.
UPDATE_WORKING = (
    "The start of update_all is taking a while, and it carries on. "
    "Ask me how the update is going in a moment. Do not start it again."
)
#: What the voice hears when a start is still going by then. Asking again would start it twice.
LAUNCH_WORKING = "The start is taking a while, and it carries on. Ask what it is playing in a moment."
#: What the voice hears when mister-mcp itself fails, so it never hears only that the tool failed.
#: The command that shows what is wrong, as typed: mister-mcp is not on the PATH, so uv runs it.
MISTER_STATUS = "uv run --directory ~/mister-mcp mister-mcp status"
BROKE = (
    "That went wrong inside mister-mcp. Try again. "
    f"If it fails again, run {MISTER_STATUS} in a terminal to see what is wrong."
)

READ_ONLY = ToolAnnotations(read_only_hint=True)
CHANGES = ToolAnnotations(read_only_hint=False)


class _Guarded:
    """Registers each tool so a failure or a slow MiSTer is still an answer the voice can read."""

    def __init__(self, server: MCPServer[Any], *, simulated: bool) -> None:
        self._server, self._simulated = server, simulated
        #: Work still running after its answer was given, kept until it ends.
        self.running: set[asyncio.Future[Any]] = set()

    def tool(
        self,
        *,
        working: str = WORKING,
        **options: Any,  # noqa: ANN401
    ) -> Callable[[Callable[..., Awaitable[Any]]], Any]:
        """Register a tool; `working` is what the voice hears if it is still going at the deadline."""
        register = self._server.tool(**options)

        def guard(tool: Callable[..., Awaitable[dict[str, Any]]]) -> Any:  # noqa: ANN401
            @functools.wraps(tool)
            async def answered(*args: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
                work = asyncio.ensure_future(tool(*args, **kwargs))
                try:
                    # RULE: a tool still working at the deadline says it carries on
                    answer = await asyncio.wait_for(asyncio.shield(work), ANSWER_WITHIN)
                except TimeoutError:
                    self.running.add(work)
                    work.add_done_callback(_ended)
                    work.add_done_callback(self.running.discard)
                    answer = {"success": False, "outcome": "working", "say": working}
                except Exception:  # noqa: BLE001 - whatever broke, the voice gets a sentence
                    # RULE: every tool answers with a sentence, even when it fails
                    answer = {"success": False, "outcome": "refused", "say": BROKE}
                answer["simulated"] = self._simulated
                # RULE: every simulated answer says simulated first
                if self._simulated:
                    answer["say"] = "Simulated: " + answer["say"]
                return answer

            return register(answered)

        return guard


def _ended(work: asyncio.Future[Any]) -> None:
    """Collect what work left running ended with, so a failure there is not left unread."""
    if not work.cancelled():
        work.exception()


def build_server(
    service: MisterService, *, updater: UpdateService | None = None, simulated: bool = False
) -> MCPServer[Any]:
    """The MCP server with the MiSTer's tools; the update_all tools only with an `updater`."""
    server: MCPServer[Any] = MCPServer(
        name="mister-simulated" if simulated else "mister",
        instructions=(SIMULATED + INSTRUCTIONS) if simulated else INSTRUCTIONS,
    )
    guarded = _Guarded(server, simulated=simulated)

    @guarded.tool(
        annotations=READ_ONLY,
        description="What is it playing?\nWhether the MiSTer is on, and the system and game it runs.",
    )
    async def mister_status() -> dict[str, Any]:
        return await service.status()

    @guarded.tool(
        annotations=READ_ONLY,
        description="Find a game by its name.\nName: words from the game's title, as the owner said them.",
    )
    async def mister_search(name: str) -> dict[str, Any]:
        return await service.search(name)

    # RULE: a slow launch is never asked for again
    @guarded.tool(
        working=LAUNCH_WORKING,
        annotations=CHANGES,
        description=(
            "Start a game or a core.\nGame: words of its title. System: its name, alone to start its core"
            " with no game. Then the TV it is plugged into shows it, only if that TV is already on."
        ),
    )
    async def mister_launch(game: str | None = None, system: str | None = None) -> dict[str, Any]:
        return await service.launch(game=game, system=system)

    @guarded.tool(
        working=LAUNCH_WORKING,
        annotations=CHANGES,
        description=(
            "Say yes to a start.\nOnly after the owner clearly said yes to the question mister_launch"
            " asked. Token: the one that question gave."
        ),
    )
    async def mister_launch_confirm(token: str) -> dict[str, Any]:
        return await service.confirm(token)

    if updater is not None:
        _update_tools(guarded, updater)
    return server


def _update_tools(guarded: _Guarded, updater: UpdateService) -> None:
    """update_all by voice (ADR-MM-004): ask, the owner's yes, then how it is going."""

    @guarded.tool(
        annotations=READ_ONLY,
        description=(
            "Update the MiSTer with update_all.\nAsks first and starts nothing: checks the free space"
            " and names a running game. Read its question aloud."
        ),
    )
    async def mister_update_request() -> dict[str, Any]:
        return await updater.request()

    @guarded.tool(
        working=UPDATE_WORKING,
        annotations=CHANGES,
        description=(
            "Go ahead with update_all.\nOnly after the owner clearly said yes to the question"
            " mister_update_request asked. Token: the one that question gave."
        ),
    )
    async def mister_update_confirm(token: str) -> dict[str, Any]:
        return await updater.confirm(token)

    @guarded.tool(
        annotations=READ_ONLY,
        description="How is the update going?\nWhether update_all runs, its current step, and how it ended.",
    )
    async def mister_update_status() -> dict[str, Any]:
        return await updater.status()
