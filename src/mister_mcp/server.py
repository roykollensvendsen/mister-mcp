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

INSTRUCTIONS = (
    "Says what the owner's MiSTer FPGA is playing and finds its games by name. "
    "Read each 'say' aloud as it is. "
    "Start a game only when the owner asks for it now. No tool writes, deletes or changes a setting "
    "on the MiSTer, and none switches a TV on."
)
SIMULATED = "A SIMULATED MiSTer, not a real one: say so. "
#: The Claude app gives up on a call after about 15 seconds; every tool answers before then.
ANSWER_WITHIN = 12.0
#: What the voice hears when a tool is still working by then; the work carries on.
WORKING = "That is taking a while, and it carries on. Ask again in a moment to hear how it went."
#: What the voice hears when mister-mcp itself fails, so it never hears only that the tool failed.
BROKE = "That went wrong inside mister-mcp. Try again, and if it fails again, check its log."

READ_ONLY = ToolAnnotations(read_only_hint=True)
CHANGES = ToolAnnotations(read_only_hint=False)


class _Guarded:
    """Registers each tool so a failure or a slow MiSTer is still an answer the voice can read."""

    def __init__(self, server: MCPServer[Any], *, simulated: bool) -> None:
        self._server, self._simulated = server, simulated
        #: Work still running after its answer was given, kept until it ends.
        self.running: set[asyncio.Future[Any]] = set()

    def tool(self, **options: Any) -> Callable[[Callable[..., Awaitable[Any]]], Any]:  # noqa: ANN401
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
                    answer = {"success": False, "outcome": "working", "say": WORKING}
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


def build_server(service: MisterService, *, simulated: bool = False) -> MCPServer[Any]:
    """The MCP server with the MiSTer's tools."""
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

    @guarded.tool(
        annotations=CHANGES,
        description=(
            "Start a game or a core.\nGame: words of its title. System: its name, alone to start its core"
            " with no game. Then the TV it is plugged into shows it, only if that TV is already on."
        ),
    )
    async def mister_launch(game: str | None = None, system: str | None = None) -> dict[str, Any]:
        return await service.launch(game=game, system=system)

    return server
