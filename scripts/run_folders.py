# ruff: noqa: INP001 - a helper the scripts beside it load by path; scripts/ is not a package
"""One folder per run, locked while the run lasts, swept only once its run is gone.

The mutation runner and the ratchet each keep their temporary files in a folder of
their own under one base per checkout. A run holds a lock on its folder while it
lasts and removes the folder when it ends. A killed run never gets that far, so the
next start removes any such folder whose lock nobody holds. The lock, not a process
number, tells a live run: a sandbox has process numbers of its own, and they are
reused. Only a real folder of this user's, named like a run's, is ever looked at, and
a link is never followed.

The way is easee-mcp's (#9, #10), for its test runs.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import pathlib
import re
import secrets
import shutil
import stat
import tempfile
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

NAMED = re.compile(r"run-\d{12}")
#: A run's folder is made under this name, locked, and only then given its run name, so a
#: sweep never sees a run's name without its lock held. A run killed in between leaves one.
STARTING = re.compile(r"starting-\w+")
#: How old a folder with no lock, run- or starting- alike, must be before it counts as left
#: by a killed run. A guess: a run takes well under a second to start and lock its folder,
#: and nothing measured says how long a run killed while starting may sit before then.
STARTING_SECONDS = 3600
LOCK = ".lock"
#: A run's own lock is always new: a lock file someone else made first is never shared.
OPEN_NEW_LOCK = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
#: A sweep only opens a lock that is there: one it made would sit in a new run's folder
#: before that run moves in, and the run's rename onto it would then fail.
OPEN_THEIR_LOCK = os.O_RDWR | os.O_NOFOLLOW


def _open_up(place: pathlib.Path) -> None:
    """Give the owner back every right on one folder or file; a link is left alone."""
    if place.is_symlink():
        return
    with contextlib.suppress(OSError):
        place.chmod(place.stat().st_mode | stat.S_IRWXU)


def _writable_again(func: Callable[[str], object], path: str, _exc: object) -> None:
    """Let a refused delete through: open up the path and its folder, then try again."""
    for place in (pathlib.Path(path).parent, pathlib.Path(path)):
        _open_up(place)
    func(path)


def remove(folder: pathlib.Path) -> None:
    """Delete a run's folder, even where a test took away the rights to read or delete it."""
    if not folder.exists():
        return
    # A folder a test shut (mode 0) cannot even be listed, so open every folder first.
    for place, folders, _ in os.walk(folder):
        for name in folders:
            _open_up(pathlib.Path(place) / name)
    shutil.rmtree(folder, onexc=_writable_again)


def private_base(base: pathlib.Path) -> None:
    """Stop unless `base` is a real folder of this user's that nobody else may use.

    The base has a fixed name in the shared temporary folder, so anyone could make it
    first, or put a link there. Opened without following a link, then checked as opened.
    """
    # RULE: the base folder must be a private folder of ours
    try:
        handle = os.open(base, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    except OSError:
        found = None
    else:
        try:
            found = os.fstat(handle)
        finally:
            os.close(handle)
    if not (
        found is not None
        and stat.S_ISDIR(found.st_mode)
        and found.st_uid == os.getuid()
        and found.st_mode & 0o077 == 0
    ):
        msg = (
            f"{base} is not a private folder of yours: it is a link, a file, someone else's, "
            f"or open to other users, so nothing was run in it. Remove it with `rm -r {base}` "
            "and run this again."
        )
        raise SystemExit(msg)


def start_run(base: pathlib.Path) -> tuple[pathlib.Path, int]:
    """A new run's folder under `base`, and the lock this run now holds on it."""
    with contextlib.suppress(FileExistsError):
        base.mkdir(mode=0o700, parents=True)
    private_base(base)
    starting = pathlib.Path(tempfile.mkdtemp(prefix="starting-", dir=base))
    # RULE: a run s lock is made new
    lock = os.open(starting / LOCK, OPEN_NEW_LOCK, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX)
    while True:
        folder = base / f"run-{secrets.randbelow(10**12):012d}"
        try:
            folder.mkdir(mode=0o700)  # claims the name, so the rename cannot replace another's
        except FileExistsError:
            continue
        starting.rename(folder)
        return folder, lock


def end_run(folder: pathlib.Path, lock: int, base: pathlib.Path) -> None:
    """Remove a run's folder and let go of its lock; then the base too, if nothing is left."""
    remove(folder)
    os.close(lock)
    with contextlib.suppress(OSError):
        base.rmdir()


def _ours_to_look_at(path: pathlib.Path) -> os.stat_result | None:
    """What `path` is, if it is a real folder of this user's named like a run's.

    None when it is not, or when another sweep removed it first.
    """
    if not (NAMED.fullmatch(path.name) or STARTING.fullmatch(path.name)):
        return None
    try:
        found = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(found.st_mode) or found.st_uid != os.getuid():
        return None
    return found


def dead(path: pathlib.Path) -> bool:
    """Whether `path` is a run's folder whose run has ended: ours to look at, and unlocked."""
    found = _ours_to_look_at(path)
    if found is None:
        return False
    try:
        # RULE: a sweep never makes a lock in a folder that has none
        lock = os.open(path / LOCK, OPEN_THEIR_LOCK)
    except FileNotFoundError:
        # No lock yet: a new run's claimed name, or a run killed before it locked. The
        # first look's age is used: another sweep may have removed the folder since.
        # RULE: a folder with no lock is dead only after the grace period
        return time.time() - found.st_mtime >= STARTING_SECONDS
    except OSError:
        return False
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False  # a run still going holds it
    finally:
        os.close(lock)
    return True


def dead_runs(base: pathlib.Path) -> list[pathlib.Path]:
    """The run folders under `base` that runs which died left; never one a run holds."""
    if not os.path.lexists(base):
        return []
    private_base(base)
    return [path for path in sorted(base.iterdir()) if dead(path)]


def forget(base: pathlib.Path) -> None:
    """Remove the base once nothing is left in it."""
    with contextlib.suppress(OSError):
        base.rmdir()
