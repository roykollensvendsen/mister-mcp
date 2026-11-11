# SPDX-License-Identifier: GPL-3.0-or-later
"""What each tool does, as answers the voice can read aloud.

Every answer has ``say``, read aloud as it is, and ``success`` with ``outcome``
for a program: ``done``, ``unreachable`` (the MiSTer did not answer),
``not_found``, ``refused``, ``working`` (still going after the voice's time),
``ask`` (a question to read aloud, confirmed with its ``token``).
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mister_mcp.tv import TvSwitch, show_mister
from mister_mcp.zaparoo import (
    NotAllowedError,
    Transport,
    UnreachableError,
    Zaparoo,
    ZaparooError,
    ZaparooNotRunningError,
    game_text,
    system_text,
)

if TYPE_CHECKING:
    from collections.abc import Callable

#: Seconds a question about ending a running game stays open for its yes.
ASK_WITHIN = 60.0
#: What the voice hears for a token that ran out, was used, or was never given.
STALE = "That question has run out, or was already answered. Ask me to start it again."

#: What the voice hears when Zaparoo on the MiSTer does not answer.
UNREACHABLE = (
    "The MiSTer is not answering, so it is off or not on the network. "
    "Switch it on, wait a minute, and ask again."
)
#: What the voice hears when the MiSTer is on but Zaparoo on it is not running.
NOT_RUNNING = (
    "The MiSTer is on, but Zaparoo isn't running on it. "
    "Start Zaparoo from the MiSTer's Scripts menu, and ask again."
)
#: The most games one answer reads out; the voice cannot list a hundred.
MAX_RESULTS = 5


def not_found(tried: tuple[str, ...]) -> str:
    """What the voice hears when none of the addresses `tried` answered, in the owner's words."""
    where = tried[0] if len(tried) == 1 else ", ".join(tried[:-1]) + " eller " + tried[-1]
    return (
        f"Fant ikke MiSTer-en på {where}. Sjekk at den er på og koblet til nettet. "
        "Har den fått ny adresse, si den til meg."
    )


def _unreachable(error: UnreachableError, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    if isinstance(error, ZaparooNotRunningError):
        say = NOT_RUNNING
    else:
        say = not_found(error.tried) if error.tried else UNREACHABLE
    return {"success": False, "outcome": "unreachable", "say": say, **fields}


def _game(result: dict[str, Any]) -> dict[str, str]:
    """A search result as the voice needs it: its name and its system's name."""
    system = result.get("system") or {}
    return {"name": str(result.get("name", "")), "system": str(system.get("name") or system.get("id") or "")}


def _listed(games: list[dict[str, str]]) -> str:
    named = [f"{g['name']} on the {g['system']}" for g in games]
    return named[0] if len(named) == 1 else ", ".join(named[:-1]) + ", and " + named[-1]


def _refused(say: str, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    return {"success": False, "outcome": "refused", "say": say, **fields}


def _plain(text: str) -> str:
    return " ".join(text.casefold().split())


def _system_said(said: str, systems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The systems `said` names: the whole id or name, or else words of the name."""
    wanted = _plain(said)
    exact = [s for s in systems if wanted in (_plain(str(s.get("id", ""))), _plain(str(s.get("name", ""))))]
    if exact:
        return exact
    return [s for s in systems if wanted and wanted in _plain(str(s.get("name", "")))]


def _which_system(said: str, fits: list[dict[str, Any]], systems: list[dict[str, Any]]) -> str:
    """The question back when `said` names no system, or more than one."""
    if fits:
        return f"The MiSTer has {' and '.join(str(s.get('name')) for s in fits)}. Say which system."
    names = [str(s.get("id")) for s in systems]
    shown = ", ".join(names[:MAX_RESULTS]) + (
        f", and {len(names) - MAX_RESULTS} more" if len(names) > MAX_RESULTS else ""
    )
    return f"The MiSTer has no system called {said}. It has {shown}. Say one of those."


@dataclass(frozen=True)
class _Start:
    """A start worked out but not yet sent: the text Zaparoo runs, and what it starts."""

    text: str
    game: str | None
    system: str | None

    def named(self) -> str:
        return self.game or f"the {self.system} core"


def describe(active: dict[str, Any] | None) -> str:
    """What the MiSTer is running, as a phrase: "playing X on Y", or "at its menu"."""
    if not active:
        return "at its menu"
    system = active.get("systemName") or active.get("systemId") or "an unknown system"
    game = active.get("mediaName")
    return f"playing {game} on the {system}" if game else f"running the {system} core, with no game"


class MisterService:
    """The MiSTer, reached through Zaparoo Core."""

    def __init__(
        self,
        transport: Transport,
        *,
        tv: TvSwitch | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Reach the MiSTer through `transport`; show it on `tv` after a start, when one is set."""
        self.zaparoo = Zaparoo(transport)
        self._transport = transport
        self.tv = tv
        self._clock = clock
        #: Starts waiting for the owner's yes, by token, with the time each one expires.
        self._asked: dict[str, tuple[_Start, float]] = {}

    async def status(self) -> dict[str, Any]:
        """Whether the MiSTer answers, and what it is running."""
        try:
            active = await self.zaparoo.active()
        except ZaparooNotRunningError as error:
            # RULE: a mister that answers without zaparoo is called on
            return _unreachable(error, on=True, system=None, game=None)
        except UnreachableError as error:
            # RULE: a mister that does not answer is not called on or off
            return _unreachable(error, on=None, system=None, game=None)
        address = getattr(self._transport, "used", None)
        at = f"at {address}, " if address else ""
        return {
            "success": True,
            "outcome": "done",
            "say": f"The MiSTer is on, {at}{describe(active)}.",
            "on": True,
            "address": address,
            "system": (active or {}).get("systemName") or None,
            "game": (active or {}).get("mediaName") or None,
        }

    async def search(self, name: str) -> dict[str, Any]:
        """The games whose names hold every word of `name`, at most MAX_RESULTS of them."""
        try:
            results = await self.zaparoo.search(name, max_results=MAX_RESULTS + 1)
        except UnreachableError as error:
            return _unreachable(error, games=[])
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

    async def launch(self, game: str | None = None, system: str | None = None) -> dict[str, Any]:
        """Start a game by its name, or a system's core alone; then show the MiSTer on the TV."""
        try:
            start = await self._start(game, system)
            if not isinstance(start, _Start):
                return start
            active = await self.zaparoo.active()
        except UnreachableError as error:
            return _unreachable(error, game=None, system=None)
        # RULE: a running game is never ended without a yes
        if active:
            return self._ask(start, active)
        return await self._go(start)

    async def confirm(self, token: str) -> dict[str, Any]:
        """The owner's yes to the start a launch asked about: start it now."""
        asked = self._asked.get(token)
        # RULE: a token works once and only while fresh
        if asked is None or self._clock() > asked[1]:
            self._asked.pop(token, None)
            return _refused(STALE, game=None, system=None)
        return await self._go(asked[0], token=token)

    def _ask(self, start: _Start, active: dict[str, Any]) -> dict[str, Any]:
        now = self._clock()
        self._asked = {t: a for t, a in self._asked.items() if a[1] >= now}
        token = secrets.token_urlsafe(12)
        self._asked[token] = (start, now + ASK_WITHIN)
        say = f"The MiSTer is {describe(active)}. Do you want me to end it and start {start.named()}?"
        return {
            "success": False,
            "outcome": "ask",
            "say": say,
            "token": token,
            "expires_in": ASK_WITHIN,
            "game": None,
            "system": None,
        }

    async def _go(self, start: _Start, *, token: str | None = None) -> dict[str, Any]:
        """Send `start`, then show the MiSTer on the TV once the MiSTer shows it."""
        try:
            started = await self._run(start, token=token)
        except UnreachableError as error:
            return _unreachable(error, game=None, system=None)
        if not started["success"] or self.tv is None:
            return started
        # RULE: the tv is touched only once the game started
        tv = await show_mister(self.tv)
        return started | {"say": f"{started['say']} {tv['say']}", "tv": tv}

    async def _start(self, game: str | None, system: str | None) -> dict[str, Any] | _Start:
        systems = await self.zaparoo.systems()
        chosen: dict[str, Any] | None = None
        if system:
            fits = _system_said(system, systems)
            if len(fits) != 1:
                return _refused(_which_system(system, fits, systems), game=None, system=None)
            chosen = fits[0]
        if game:
            return await self._start_game(game, chosen)
        if chosen is None:
            return _refused("Say a game, or a system to start with no game.", game=None, system=None)
        text = system_text(str(chosen["id"]), [str(s.get("id")) for s in systems])
        return _Start(text, None, str(chosen.get("name")))

    async def _start_game(self, game: str, system: dict[str, Any] | None) -> dict[str, Any] | _Start:
        results = await self.zaparoo.search(game, max_results=MAX_RESULTS + 1)
        if system is not None:
            results = [r for r in results if (r.get("system") or {}).get("id") == system.get("id")]
        exact = [r for r in results if _plain(str(r.get("name", ""))) == _plain(game)]
        picked = exact if len(exact) == 1 else results
        if not picked:
            say = f"The MiSTer has no game called {game}. Try fewer words, or another name."
            return {"success": False, "outcome": "not_found", "say": say, "game": None, "system": None}
        if len(picked) > 1:
            games = [_game(r) for r in picked[:MAX_RESULTS]]
            return _refused(f"Which one: {_listed(games)}?", game=None, system=None, games=games)
        found = _game(picked[0])
        try:
            text = game_text(str(picked[0].get("zapScript", "")))
        except NotAllowedError:
            say = (
                f"I may not start {found['name']} the way the MiSTer lists it. "
                "Start it from the MiSTer's own menu."
            )
            return _refused(say, game=None, system=None)
        return _Start(text, found["name"], found["system"])

    async def _run(self, start: _Start, *, token: str | None) -> dict[str, Any]:
        game, system = start.game, start.system
        try:
            await self.zaparoo.run(start.text)
        except ZaparooError as error:
            self._asked.pop(token or "", None)
            say = f"The MiSTer did not start it: {error}. Try again, or ask what it is playing."
            return _refused(say, game=None, system=None, reason=error.category)
        # The token is spent only once the start was sent, so a lost confirm can be tried again.
        self._asked.pop(token or "", None)
        # RULE: a start is said as done only once the mister shows it
        active = await self.zaparoo.active()
        shows = (active or {}).get("mediaName") or None
        if active and shows == game and (game or active.get("systemName") == system):
            say = f"Started. The MiSTer is {describe(active)}."
            return {"success": True, "outcome": "done", "say": say, "game": game, "system": system}
        say = (
            f"I sent the start, but the MiSTer is {describe(active)}. "
            "Ask what it is playing in a moment, or start it from the MiSTer's own menu."
        )
        return {"success": False, "outcome": "unverified", "say": say, "game": shows, "system": system}
