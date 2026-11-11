# SPDX-License-Identifier: GPL-3.0-or-later
"""Show the MiSTer on the TV it is plugged into, through the TV plugin's own tools.

ADR-MM-002: the TV plugin (tv-mcp) owns the TVs and their guards. This module
starts its MCP server for a moment, asks ``tv_status`` whether that TV's screen
is on, and only then asks ``tv_input`` to show the MiSTer by its device name.
It never calls any other TV tool, so it can never switch a TV on or off.

:class:`TvSwitch` is the small interface the rest of the plugin sees, so the
stdio child can later give way to the bridge calling ``tv_input`` itself.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import shutil
from typing import Any, ClassVar, Self

#: Seconds the TV step may take inside a launch, starting the TV plugin included.
TV_WITHIN = 6.0


def _entries(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The per-TV entries of a tv_status answer, under ``tvs``."""
    entries = report.get("tvs")
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def screen_of(report: dict[str, Any], tv: str) -> str | None:
    """`tv`'s own screen in a tv_status answer: its entry under ``tvs``, ``screen`` or else ``state``."""
    entry = next((e for e in _entries(report) if e.get("tv") == tv), {})
    value = entry.get("screen") or entry.get("state")
    return value if isinstance(value, str) else None


class TvSwitch:
    """Shows the MiSTer on one TV, only when that TV is already on."""

    #: The only TV tools this plugin ever calls.
    TOOLS: ClassVar[tuple[str, ...]] = ("tv_status", "tv_input")

    def __init__(self, *, tv: str, device: str) -> None:
        """Switch the TV the owner calls `tv` to the input whose device is called `device`."""
        self.tv, self.device = tv, device

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """The TV plugin's answer to `tool`; None, and nothing sent, for a tool not listed."""
        # RULE: only the tv status and input tools are ever called
        if tool not in self.TOOLS:
            return None
        return await self._send(tool, arguments)

    async def _send(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    async def _offered(self) -> set[str]:
        raise NotImplementedError

    async def show_mister(self) -> dict[str, Any]:
        """Switch the TV to the MiSTer if its screen is on; otherwise leave it alone."""
        if "tv_input" not in await self._offered():
            return _alone(
                "The TV plugin does not offer to change inputs, so I left the TV alone. "
                "Switch it to the MiSTer by hand, or turn on input in the TV plugin's settings."
            )
        report = await self.call("tv_status", {"tv": self.tv}) or {}
        # RULE: a tv that is not on is never sent an input
        if screen_of(report, self.tv) != "on":
            return _alone(
                f"{self.tv.capitalize()} is not on, so I left it alone. "
                f"Switch it on yourself and choose {self.device}."
            )
        answer = await self.call("tv_input", {"source": self.device, "tv": self.tv}) or {}
        return {
            "success": bool(answer.get("success")),
            "outcome": str(answer.get("outcome", "refused")),
            "say": str(answer.get("say", "The TV did not say what it shows. Ask it what it shows.")),
        }

    def status_command(self) -> str:
        """The command that shows what is wrong with the TV plugin, as the owner types it."""
        return "uv run --directory ~/tv-mcp tv-mcp status"

    async def __aenter__(self) -> Self:
        """Nothing to open."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Nothing to close."""


def _alone(say: str) -> dict[str, Any]:
    return {"success": False, "outcome": "left_alone", "say": say}


class SimulatedTvPlugin(TvSwitch):
    """A pretend TV plugin, answering as tv-mcp does, that records what it was asked."""

    def __init__(
        self,
        *,
        screen: str | None = "on",
        offers_input: bool = True,
        tv: str = "the den",
        device: str = "Game box",
    ) -> None:
        """A TV whose screen reads `screen`."""
        super().__init__(tv=tv, device=device)
        self.screen, self.offers_input = screen, offers_input
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def _offered(self) -> set[str]:
        return {"tv_status", "tv_input"} if self.offers_input else {"tv_status"}

    async def _send(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, arguments))
        if tool == "tv_status":
            entry = {"tv": self.tv, "state": "reachable", "screen": self.screen}
            return {"success": True, "say": "...", "tvs": [entry]}
        if self.screen != "on":
            say = f"{self.tv.capitalize()} is not on, so its input was left alone."
            return {"success": False, "outcome": "refused", "say": say}
        say = f"{self.tv.capitalize()} shows HDMI 3, the {self.device}, now."
        return {"success": True, "outcome": "done", "say": say}


class TvPlugin(TvSwitch):
    """The TV plugin's own MCP server, started over stdio for one launch and closed after it."""

    def __init__(self, *, command: list[str], tv: str, device: str) -> None:
        """Start the TV plugin with `command`, such as ``uv run --directory ~/tv-mcp tv-mcp serve``."""
        super().__init__(tv=tv, device=device)
        self._typed = list(command)
        self._command = [
            str(pathlib.Path(part).expanduser()) if part.startswith("~") else part for part in command
        ]
        self._local_bin = str(pathlib.Path("~/.local/bin").expanduser())
        self._stack: Any = None
        self._session: Any = None

    async def __aenter__(self) -> Self:
        """Start the TV plugin and open an MCP session with it."""
        from contextlib import AsyncExitStack  # noqa: PLC0415 - only when a TV is used

        from mcp import ClientSession, StdioServerParameters  # noqa: PLC0415
        from mcp.client.stdio import stdio_client  # noqa: PLC0415

        program = shutil.which(self._command[0]) or shutil.which(self._command[0], path=self._local_bin)
        params = StdioServerParameters(command=program or self._command[0], args=self._command[1:])
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    def status_command(self) -> str:
        """The settings' own command for the TV plugin, asking for its status instead of serving."""
        typed = [*self._typed[:-1], "status"] if self._typed[-1:] == ["serve"] else [*self._typed, "status"]
        return " ".join(typed)

    @property
    def is_open(self) -> bool:
        """Whether the TV plugin is running for this plugin now."""
        return self._session is not None or self._stack is not None

    async def __aexit__(self, *_: object) -> None:
        """Close the session and stop the TV plugin, after every use."""
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = self._session = None

    async def _offered(self) -> set[str]:
        listed = await self._session.list_tools()
        return {tool.name for tool in listed.tools}

    async def _send(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._session.call_tool(tool, arguments)
        if isinstance(result.structured_content, dict):
            return dict(result.structured_content)
        for part in result.content:
            text = getattr(part, "text", None)
            if text:
                try:
                    loaded = json.loads(text)
                except ValueError:
                    return {"say": text}
                return loaded if isinstance(loaded, dict) else {"say": text}
        return {}


async def show_mister(tv: TvSwitch) -> dict[str, Any]:
    """The TV step of a launch, inside its own deadline, the TV plugin closed afterwards."""
    try:
        async with asyncio.timeout(TV_WITHIN):
            async with tv:
                return await tv.show_mister()
    except TimeoutError:
        return {
            "success": False,
            "outcome": "working",
            "say": "The TV did not answer in time; ask it what it shows.",
        }
    except Exception:  # noqa: BLE001 - the game started; a TV failure is said, not raised
        return {
            "success": False,
            "outcome": "refused",
            "say": (
                "I could not reach the TV plugin, so I could not switch the TV. "
                f"Switch it to the MiSTer by hand, and run {tv.status_command()} to see what is wrong."
            ),
        }
