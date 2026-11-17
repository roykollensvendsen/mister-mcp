"""A test that waits on another program fails when it waits too long, and leaves nothing running.

A mutant that makes a test wait for ever would hold a whole mutation run for ever, since the
run has no time limit of its own. Each wait on a child is bounded by the test itself.
"""

import pathlib
import subprocess
import sys
import time

import pytest
from bounded import line_within, run_bounded


def _running(pid):
    """Whether `pid` is a live process: not gone, and not a zombie waiting to be reaped."""
    try:
        status = pathlib.Path(f"/proc/{pid}/status").read_text()
    except FileNotFoundError:
        return False
    return "State:\tZ" not in status


def test_a_child_that_overruns_is_killed_with_everything_it_started(tmp_path):
    """A grandchild holding the output, as under a shell or `uv run`, is not left running.

    The grandchild's own pid is checked, not the shell's or the group's: the shell dies
    either way, and a check on the group alone would pass a grandchild that left it.
    """
    grandchild = tmp_path / "grandchild"
    script = f"sleep 60 & echo $! > {grandchild}; wait"
    began = time.monotonic()
    with pytest.raises(pytest.fail.Exception, match="still running after 1 s"):
        run_bounded(["sh", "-c", script], within=1)
    assert time.monotonic() - began < 30
    pid = int(grandchild.read_text())
    deadline = time.monotonic() + 10  # a killed grandchild may take a moment to be reaped
    while _running(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _running(pid), f"the grandchild {pid} is still running"


def test_a_child_that_ends_in_time_is_answered_as_subprocess_run_would():
    done = run_bounded([sys.executable, "-c", "print('hi')"], text=True)
    assert (done.returncode, done.stdout) == (0, "hi\n")


def test_a_child_that_never_writes_a_line_fails_within_the_bound():
    with subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], stdout=subprocess.PIPE, text=True
    ) as child:
        try:
            began = time.monotonic()
            with pytest.raises(pytest.fail.Exception, match="no line within 1 s"):
                line_within(child.stdout, 1)
            assert time.monotonic() - began < 30
        finally:
            child.kill()


def test_two_lines_written_at_once_are_both_read():
    """The second line already sits in the stream's buffer, where `select` would not see it."""
    with subprocess.Popen(
        [sys.executable, "-c", "print('one\\ntwo', flush=True); import time; time.sleep(60)"],
        stdout=subprocess.PIPE,
        text=True,
    ) as child:
        try:
            assert (line_within(child.stdout, 10), line_within(child.stdout, 10)) == ("one\n", "two\n")
        finally:
            child.kill()
