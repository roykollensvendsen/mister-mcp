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


def _unreachable(**fields: Any) -> dict[str, Any]:  # noqa: ANN401
    return {"success": False, "outcome": "unreachable", "say": UNREACHABLE, **fields}


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
