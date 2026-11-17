"""Each test starts with the stop handlers the run started with: point 7 of the checklist.

`scripts/mutate.py` and `scripts/ratchet.py` install their own handlers for SIGINT,
SIGTERM and SIGHUP, and a test that runs them in-process leaves those behind. A later
test would then stop differently, and a rule could be reported killed by another test.
`tests/conftest.py` puts the handlers back after each test; this proves it on a
scratch project. The way is garage-door's, after tv-mcp #84.
"""

import pathlib
import sys

from bounded import run_bounded

ROOT = pathlib.Path(__file__).parent.parent

TESTS = """
import signal

STOPS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
FIRST = {each: signal.getsignal(each) for each in STOPS}


def test_1_changes_them():
    for each in STOPS:
        signal.signal(each, signal.SIG_IGN)


def test_2_finds_them_as_the_run_began():
    assert {each: signal.getsignal(each) for each in STOPS} == FIRST
"""


def test_a_test_finds_the_stop_handlers_the_run_began_with(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/conftest.py").write_text((ROOT / "tests/conftest.py").read_text(encoding="utf-8"))
    (tmp_path / "tests/test_scratch.py").write_text(TESTS)
    done = run_bounded(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(tmp_path), "tests"],
        cwd=tmp_path,
        text=True,
    )
    assert done.returncode == 0, done.stdout
