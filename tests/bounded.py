"""Waits on another program that end in a failure of the waiting test, never in a hang.

A mutation run has no time limit of its own, by the owner's rule, so a test that waits for ever
holds the whole run for ever. Every wait on a child here carries a bound the test sets
itself, and running out of it fails that one test. That is how a mutant that hangs counts
as caught. The bound is generous, so it only ever fires on a real hang.
"""

import os
import queue
import signal
import subprocess
import threading

import pytest

#: The one bound for every wait on a child, in seconds, the same in every plugin.
WITHIN = 300


def run_bounded(command, within=WITHIN, *, check=False, **kwargs):
    """Run `command` to its end like `subprocess.run`, capturing what it writes; a failure if it overruns.

    The child starts in a group of its own, so on overrunning the whole group is killed,
    with anything it started that still holds its output, such as a grandchild under a
    shell or `uv run`. `subprocess.run`'s own `timeout=` kills only the child and leaves
    those running into the next tests. SIGKILL, because nothing can catch it: a gentler
    signal to a group under `uv run` reaches Python twice, once directly and once from uv.
    """
    kwargs.pop("capture_output", None)  # always captured: the output goes in the failure
    with subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, **kwargs
    ) as child:
        try:
            out, err = child.communicate(timeout=within)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            out, err = child.communicate()
            pytest.fail(
                f"{command} was still running after {within} s, so it and its group were killed.\n"
                f"It wrote:\n{out}\nand to stderr:\n{err}"
            )
    done = subprocess.CompletedProcess(command, child.returncode, out, err)
    if check:
        done.check_returncode()
    return done


def line_within(stream, seconds=WITHIN):
    """The next line from `stream`; a failure, not a hang, if none comes within `seconds`.

    The read runs on a thread of its own, since a pipe's readline cannot be given a limit.
    Asking the operating system whether the pipe has data, with `select`, is no substitute:
    the stream's own buffer may already hold the line, and then the pipe looks empty.
    A thread left reading is a daemon, and ends when the test's cleanup kills the child.
    """
    got = queue.Queue()
    threading.Thread(target=lambda: got.put(stream.readline()), daemon=True).start()
    try:
        return got.get(timeout=seconds)
    except queue.Empty:
        pytest.fail(f"no line within {seconds} s")
