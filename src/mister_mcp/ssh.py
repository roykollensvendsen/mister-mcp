# SPDX-License-Identifier: GPL-3.0-or-later
"""How the plugin reaches the MiSTer over SSH: by key only, and only with a command from a fixed list.

ADR-MM-004. Every call runs with these options: key only, never a password,
so a key the MiSTer lost (update_all can rebuild its Linux) fails at once
rather than waiting for someone to type. The command is picked by name from
ALLOWED_COMMANDS; no tool, and no word the voice heard, ever becomes part of
one.
"""

from __future__ import annotations

import asyncio
import pathlib
from dataclasses import dataclass
from typing import Protocol

#: What the voice hears when the MiSTer refuses this computer's key, in the owner's words. No password
#: is ever tried instead, not even the MiSTer's factory default: none is written anywhere.
KEY_MISSING = "The MiSTer does not accept this computer's key. Run ssh-copy-id root@{address} in a terminal."
#: What the voice hears when the MiSTer's host key changed, as after a fresh SD card.
HOST_CHANGED = (
    "The MiSTer's identity has changed, as it does after a fresh SD card. "
    "If that is so, run ssh-keygen -R {address} in a terminal, then ask again."
)
#: What the voice hears when the MiSTer does not answer over SSH.
NO_ANSWER = "The MiSTer did not answer over SSH. Check that it is on and on the network, then ask again."
#: Seconds to open the SSH connection.
CONNECT_WAIT = 5
#: The exit code ssh itself gives when it could not reach the MiSTer or log in.
SSH_FAILED = 255
#: Seconds a whole SSH call may take, from connecting to its answer.
CALL_WITHIN = 8.0

#: The only commands the plugin ever sends over SSH, by name (ADR-MM-004).
ALLOWED_COMMANDS: dict[str, str] = {
    "free_space": "df -Pk /media/fat",
    "running": "pgrep -f '[u]pdate_all'",
    "uptime": "cat /proc/uptime",
    "live_log": "tail -n 40 /tmp/update_all_print.log",
    "saved_log": "tail -n 40 /media/fat/Scripts/.config/update_all/update_all.log",
    "start": (
        "UPDATE_ALL_NON_INTERACTIVE=true setsid nohup /media/fat/Scripts/update_all.sh"
        " >/dev/null 2>&1 </dev/null &"
    ),
}

_ASKS_FOR_A_PASSWORD = ("permission denied", "password:")


def ssh_options(key_file: str) -> list[str]:
    """The options every SSH call to the MiSTer runs with: the key in `key_file`, never a password."""
    # RULE: every ssh call runs in batch mode
    batch = ["-o", "BatchMode=yes"]
    # RULE: never a password login
    key_only = [
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "KbdInteractiveAuthentication=no",
        "-o",
        "PreferredAuthentications=publickey",
        "-o",
        "NumberOfPasswordPrompts=0",
    ]
    return [
        *batch,
        *key_only,
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"ConnectTimeout={CONNECT_WAIT}",
        "-i",
        str(pathlib.Path(key_file).expanduser()),
    ]


def key_missing(stderr: str, address: str) -> str | None:
    """The owner's sentence when SSH's `stderr` says the key is missing; None for any other failure."""
    said = stderr.casefold()
    # RULE: a missing key is said in the owners words
    if any(sign in said for sign in _ASKS_FOR_A_PASSWORD):
        return KEY_MISSING.format(address=address)
    return None


_HOST_KEY_SIGNS = ("identification has changed", "host key verification failed")


def explain(stderr: str, address: str) -> str:
    """What the voice hears when an SSH call to `address` failed with `stderr`, with the next step."""
    return _host_changed(stderr, address) or key_missing(stderr, address) or NO_ANSWER


def _host_changed(stderr: str, address: str) -> str | None:
    said = stderr.casefold()
    if any(sign in said for sign in _HOST_KEY_SIGNS):
        return HOST_CHANGED.format(address=address)
    return None


class NotAllowedCommandError(ValueError):
    """A command that is not on the fixed list."""


@dataclass(frozen=True)
class Reply:
    """What one SSH call gave back."""

    code: int
    out: str
    err: str
    address: str

    @property
    def reached(self) -> bool:
        """Whether the MiSTer answered: ssh itself fails with SSH_FAILED."""
        return self.code != SSH_FAILED


class Shell(Protocol):
    """Runs one command from the fixed list on the MiSTer."""

    async def run(self, name: str) -> Reply:
        """The MiSTer's reply to the command called `name`."""
        ...


class SshShell:
    """The MiSTer over SSH, at the first of its addresses that answers."""

    def __init__(self, addresses: list[str], *, key_file: str) -> None:
        """Reach the MiSTer at `addresses`, in order, with the key in `key_file`."""
        self._addresses, self._key_file = list(addresses), key_file

    def argv(self, address: str, name: str) -> list[str]:
        """The whole ssh command line for the command called `name`."""
        # RULE: only a command from the fixed list is ever sent over ssh
        if name not in ALLOWED_COMMANDS:
            msg = f"{name!r} is not a command this plugin sends"
            raise NotAllowedCommandError(msg)
        return ["ssh", *ssh_options(self._key_file), f"root@{address}", ALLOWED_COMMANDS[name]]

    async def run(self, name: str) -> Reply:
        """Run the command called `name` at the first address that answers."""
        reply = Reply(SSH_FAILED, "", "no address", next(iter(self._addresses), ""))
        for address in self._addresses:
            reply = await self.call(address, self.argv(address, name))
            if reply.reached:
                return reply
        return reply

    @staticmethod
    async def call(address: str, argv: list[str]) -> Reply:
        """Run `argv`, one ssh call to `address`, and give back its reply."""
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            return Reply(SSH_FAILED, "", str(error), address)
        return await _answer(process, address)


async def _answer(process: asyncio.subprocess.Process, address: str) -> Reply:
    """What `process`, one ssh call to `address`, gave back within CALL_WITHIN."""
    try:
        async with asyncio.timeout(CALL_WITHIN):
            out, err = await process.communicate()
    except TimeoutError:
        process.kill()
        await process.wait()
        return Reply(SSH_FAILED, "", "timed out", address)
    code = process.returncode or 0
    return Reply(code, out.decode(errors="replace"), err.decode(errors="replace"), address)
