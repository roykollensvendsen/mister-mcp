# SPDX-License-Identifier: GPL-3.0-or-later
"""What each tool does, as answers the voice can read aloud.

Every answer has ``say``, read aloud as it is, and ``success`` with ``outcome``
for a program: ``done``, ``unreachable`` (the MiSTer did not answer),
``not_found``, ``refused``, ``working`` (still going after the voice's time).
"""

from __future__ import annotations

from typing import Any

from mister_mcp.zaparoo import Transport, UnreachableError, Zaparoo

#: What the voice hears when Zaparoo on the MiSTer does not answer.
UNREACHABLE = (
    "The MiSTer is not answering, so it is off or not on the network. "
    "Switch it on, wait a minute, and ask again."
)
#: The most games one answer reads out; the voice cannot list a hundred.
MAX_RESULTS = 5


def _unreachable(**fields: Any) -> dict[str, Any]:  # noqa: ANN401
    return {"success": False, "outcome": "unreachable", "say": UNREACHABLE, **fields}


def _game(result: dict[str, Any]) -> dict[str, str]:
    """A search result as the voice needs it: its name and its system's name."""
    system = result.get("system") or {}
    return {"name": str(result.get("name", "")), "system": str(system.get("name") or system.get("id") or "")}


def _listed(games: list[dict[str, str]]) -> str:
    named = [f"{g['name']} on the {g['system']}" for g in games]
    return named[0] if len(named) == 1 else ", ".join(named[:-1]) + ", and " + named[-1]


def describe(active: dict[str, Any] | None) -> str:
    """What the MiSTer is running, as a phrase: "playing X on Y", or "at its menu"."""
    if not active:
        return "at its menu"
    system = active.get("systemName") or active.get("systemId") or "an unknown system"
    game = active.get("mediaName")
    return f"playing {game} on the {system}" if game else f"running the {system} core, with no game"


class MisterService:
    """The MiSTer, reached through Zaparoo Core."""

    def __init__(self, transport: Transport) -> None:
        """Reach the MiSTer through `transport`."""
        self.zaparoo = Zaparoo(transport)

    async def status(self) -> dict[str, Any]:
        """Whether the MiSTer answers, and what it is running."""
        try:
            active = await self.zaparoo.active()
        except UnreachableError:
            # RULE: a mister that does not answer is not called on or off
            return _unreachable(on=None, system=None, game=None)
        return {
            "success": True,
            "outcome": "done",
            "say": f"The MiSTer is on, {describe(active)}.",
            "on": True,
            "system": (active or {}).get("systemName") or None,
            "game": (active or {}).get("mediaName") or None,
        }

    async def search(self, name: str) -> dict[str, Any]:
        """The games whose names hold every word of `name`, at most MAX_RESULTS of them."""
        try:
            results = await self.zaparoo.search(name, max_results=MAX_RESULTS + 1)
        except UnreachableError:
            return _unreachable(games=[])
        games = [_game(r) for r in results]
        if not games:
            return {
                "success": False,
                "outcome": "not_found",
                "say": f"The MiSTer has no game called {name}. Try fewer words, or another name.",
                "games": [],
            }
        more = len(games) > MAX_RESULTS
        games = games[:MAX_RESULTS]
        say = f"I found {_listed(games)}."
        if more:
            say += " There are more; say more of the name to narrow it down."
        return {"success": True, "outcome": "done", "say": say, "games": games}
