# SPDX-License-Identifier: GPL-3.0-or-later
"""update_all by voice (ADR-MM-004): asked, then confirmed, then followed.

The request checks first and asks; nothing changes on the MiSTer until the
owner's yes comes back with its one-time token. A run takes minutes, so it is
started detached and followed through its own live log. Every SSH command is
one of mister_mcp.ssh's fixed list.
"""

from __future__ import annotations

import json
import re
import secrets
import statistics
import time
from typing import TYPE_CHECKING, Any

from mister_mcp.service import describe
from mister_mcp.ssh import NO_ANSWER, Reply, Shell, explain
from mister_mcp.zaparoo import UnreachableError, Zaparoo

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable

    from mister_mcp.zaparoo import Transport

#: The free space update_all's Downloader needs on /media/fat.
MIN_FREE_MB = 512
#: Seconds the MiSTer is given after it starts before update_all may run on it.
BOOT_SETTLE = 120.0
#: Seconds a question about running update_all stays open for its yes.
ASK_WITHIN = 60.0
#: Where update_all keeps its full log on the MiSTer, as the owner would look for it.
SAVED_LOG = "Scripts/.config/update_all/update_all.log"
#: What the voice hears when the SD card is too full, in the owner's words.
SD_FULL = "The SD card is full; ask the manager what can be deleted."
FAILED = f"update_all failed. Its log on the MiSTer is {SAVED_LOG}; ask the manager to read it."
STOPPED = "update_all stopped before it finished. Ask me to start it again."
NONE_KNOWN = "No update_all run is known since the MiSTer started. Ask me to start one."
STALE = "That question has run out, or was already answered. Ask me to run update_all again."
#: A start cut off at the time limit, after which update_all was found not running.
NOT_STARTED = (
    "The MiSTer took too long to answer the start, and update_all is not running. "
    "Ask to start update_all again."
)
STARTED = (
    "Started update_all. It may take several minutes, and may restart the MiSTer at the end. "
    "Ask how the update is going."
)

_COLOUR = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_STEP_LENGTH = 60


def _lines(reply: Reply) -> list[str] | None:
    """A log's lines without colour codes, or None when the log is not there."""
    if reply.code != 0:
        return None
    return [_COLOUR.sub("", line).strip() for line in reply.out.splitlines()]


def _free_mb(out: str) -> int | None:
    """The megabytes free on /media/fat, from ``df -Pk``."""
    rows = [line.split() for line in out.splitlines()[1:] if line.strip()]
    try:
        return int(rows[-1][3]) // 1024
    except (IndexError, ValueError):
        return None


def _step(lines: list[str]) -> str | None:
    """What update_all is doing now: its last line that says anything, kept short."""
    said = [line for line in lines if line]
    return said[-1][:_STEP_LENGTH] if said else None


def _verdict(lines: list[str], *, last: bool) -> tuple[str, str] | None:
    """How a run ended, from its log: (outcome, what the voice hears), or None while unknown."""
    text = "\n".join(lines)
    # RULE: a full sd card is said in plain words
    if "is FULL" in text:
        return "failed", SD_FULL
    if "failed" in text.casefold():
        return "failed", FAILED
    if "Success!" not in text:
        return None
    say = "The last update_all run finished well." if last else "update_all is done."
    if "Rebooting" in text:
        say += " It is restarting the MiSTer."
    elif "You should reboot" in text:
        say += " Restart the MiSTer to finish it."
    return "done", say


def _answer(outcome: str, say: str, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    return {"success": outcome == "done", "outcome": outcome, "say": say, **fields}


def _unreached(reply: Reply) -> dict[str, Any]:
    say = explain(reply.err, reply.address)
    return _answer("unreachable" if say == NO_ANSWER else "refused", say)


class UpdateService:
    """Runs update_all on the MiSTer after the owner's yes, and says how it is going."""

    def __init__(
        self,
        shell: Shell,
        transport: Transport,
        *,
        history: pathlib.Path | None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Reach the MiSTer through `shell` and Zaparoo; keep past run lengths in `history`."""
        self._shell, self._zaparoo, self._history, self._clock = shell, Zaparoo(transport), history, clock
        self._asked: dict[str, float] = {}
        self._started_at: float | None = None
        self._kept = False

    async def request(self) -> dict[str, Any]:
        """Check that update_all may run, and ask; nothing is started."""
        refusal = await self._not_ready()
        if refusal:
            return refusal
        now = self._clock()
        self._asked = {t: until for t, until in self._asked.items() if until >= now}
        token = secrets.token_urlsafe(12)
        self._asked[token] = now + ASK_WITHIN
        return _answer("ask", await self._question(), token=token, expires_in=ASK_WITHIN)

    async def confirm(self, token: str) -> dict[str, Any]:
        """The owner's yes: check once more, then start update_all detached."""
        until = self._asked.get(token)
        # RULE: an update token works once and only while fresh
        if until is None or self._clock() > until:
            self._asked.pop(token, None)
            return _answer("refused", STALE)
        refusal = await self._not_ready()
        if refusal:
            self._asked.pop(token, None)
            return refusal
        started = await self._shell.run("start")
        if started.cut_off:
            self._asked.pop(token, None)
            return await self._after_cut_off()
        if not started.reached:
            return _unreached(started)
        self._asked.pop(token, None)
        return self._started()

    async def _after_cut_off(self) -> dict[str, Any]:
        """A start that may have run: what `running` says, never a second start."""
        # RULE: a start that did not answer is checked as running before anything is said
        still = await self._shell.run("running")
        if still.code == 0:
            return self._started()
        return _answer("unreachable", NOT_STARTED)

    def _started(self) -> dict[str, Any]:
        self._started_at, self._kept = self._clock(), False
        return _answer("done", STARTED)

    async def status(self) -> dict[str, Any]:
        """How update_all is going: running and its step, done, or failed with the next step."""
        running = await self._shell.run("running")
        if not running.reached:
            return _unreached(running)
        lines = _lines(await self._shell.run("live_log"))
        if running.code == 0:
            return _answer("working", self._progress(lines or []))
        last = lines is None
        if last:
            lines = _lines(await self._shell.run("saved_log"))
        if not lines:
            return _answer("not_found", NONE_KNOWN)
        verdict = _verdict(lines, last=last)
        if verdict is None:
            return _answer("failed", STOPPED)
        if verdict[0] == "done":
            self._keep_length()
        return _answer(*verdict)

    async def _not_ready(self) -> dict[str, Any] | None:
        """Why update_all may not start now, or None when it may."""
        free = await self._shell.run("free_space")
        if not free.reached:
            return _unreached(free)
        mb = _free_mb(free.out) or 0
        # RULE: too little free space is refused naming how much is free
        if mb < MIN_FREE_MB:
            say = f"The SD card has {mb} MB free, and update_all needs {MIN_FREE_MB} MB. {SD_FULL}"
            return _answer("refused", say, free_mb=mb)
        # RULE: a run already going is not started again
        if (await self._shell.run("running")).code == 0:
            return _answer("refused", "update_all is already running. Ask how the update is going.")
        uptime = await self._shell.run("uptime")
        up = float((uptime.out.split() or ["0"])[0])
        if up < BOOT_SETTLE:
            say = f"The MiSTer started {int(up)} seconds ago. Wait two minutes, then ask again."
            return _answer("refused", say)
        return None

    async def _question(self) -> str:
        """The question read aloud: what a run does, and the game it would end."""
        try:
            active = await self._zaparoo.active()
        except UnreachableError:
            active = None
        ask = "Do you want me to start update_all?"
        # RULE: a running game is named in the question
        if active:
            return f"The MiSTer is {describe(active)}. update_all ends it, and may restart the MiSTer. {ask}"
        return f"update_all may take several minutes, and may restart the MiSTer at the end. {ask}"

    def _progress(self, lines: list[str]) -> str:
        """What a running update_all is doing, how long it has run, and about how long is left."""
        say = "update_all is running"
        if self._started_at is not None:
            ran = self._clock() - self._started_at
            say += f", for {int(ran // 60)} minutes"
            left = self._typical() - ran if self._typical() else 0
            if left > 0:
                say += f". About {round(left / 60)} minutes left"
        step = _step(lines)
        return f"{say}. Now: {step}." if step else f"{say}."

    def _typical(self) -> float:
        """The usual length of a run, from the ones kept; 0 with none."""
        runs = self._runs()
        return float(statistics.median(runs)) if runs else 0.0

    def _runs(self) -> list[int]:
        if self._history is None or not self._history.is_file():
            return []
        try:
            kept = json.loads(self._history.read_text())
        except ValueError:
            return []
        return [int(n) for n in kept if isinstance(n, int | float)] if isinstance(kept, list) else []

    def _keep_length(self) -> None:
        """Keep how long the run this plugin started took, once, for the next estimate."""
        if self._started_at is None or self._kept or self._history is None:
            return
        self._kept = True
        self._history.parent.mkdir(parents=True, exist_ok=True)
        self._history.write_text(json.dumps([*self._runs(), int(self._clock() - self._started_at)]))
