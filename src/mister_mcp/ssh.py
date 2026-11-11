# SPDX-License-Identifier: GPL-3.0-or-later
"""How the plugin will reach the MiSTer over SSH, for the later power work.

Version 1 runs no SSH command. When the clean shutdown comes, it is the only
one, and it runs with these options: key only, never a password, so a key the
MiSTer lost (update_all can rebuild its Linux) fails at once rather than
waiting for someone to type. That failure is said in the owner's own words,
in Norwegian, as the owner wrote them.
"""

from __future__ import annotations

import pathlib

#: What the voice hears when the MiSTer refuses this computer's key, in the owner's words. No password
#: is ever tried instead, not even the MiSTer's factory default: none is written anywhere.
KEY_MISSING = (
    "The MiSTer does not accept this computer's key. "
    "Run ssh-copy-id root@{address} in a terminal, then change the MiSTer's password from the default."
)
#: Seconds to open the SSH connection.
CONNECT_WAIT = 5

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
