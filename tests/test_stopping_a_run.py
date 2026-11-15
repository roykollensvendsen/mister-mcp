"""Stopping a mutation or quality run always cleans up: points 5, 6, 8 and 9 of the checklist.

The cleanup checklist (new-plugin-v8.md) is shared by every plugin. A cancelled CI
job sends SIGINT and then SIGTERM; a closed terminal sends SIGHUP. Each must end a
run the way Ctrl-C does, and a second one must not cut the cleanup short. One run
per checkout, and each run measures the package from its own checkout.
"""

import contextlib
import fcntl
import importlib.util
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_stopping", ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _project(tmp_path):
    """A scratch checkout with one rule, `x = 1`, which its row switches to `x = 2`."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "rule.py").write_text("x = 1\n")
    rows = tmp_path / "mutations" / "rule.py"
    rows.mkdir(parents=True)
    (rows / "x-is-one.toml").write_text(
        "[[rule]]\nname = \"x is one\"\nfile = \"rule.py\"\nfind = '^x = 1$'\nreplace = 'x = 2'\n"
    )
    return project


def _whole_run(tmp_path, monkeypatch):
    mutate = _load("mutate")
    monkeypatch.setattr(mutate, "ROOT", _project(tmp_path))
    monkeypatch.setattr(mutate, "ROWS", tmp_path / "mutations")
    monkeypatch.setattr(mutate, "RECOVERY", tmp_path / "recovery.json")
    monkeypatch.setattr(mutate, "MUTATE_TMP", tmp_path / "mutate-tmp")
    monkeypatch.setattr(mutate, "from_this_checkout", lambda: None)
    monkeypatch.setattr(sys, "argv", ["mutate.py"])
    return mutate


STOPPED_RUN = """
import importlib.util, pathlib, sys, time
root, tmp = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("mutate_stopped", root / "scripts/mutate.py")
mutate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mutate)
mutate.ROOT, mutate.ROWS = tmp / "project", tmp / "mutations"
mutate.RECOVERY, mutate.MUTATE_TMP = tmp / "recovery.json", tmp / "mutate-tmp"
mutate.from_this_checkout = lambda: None
sys.argv = ["mutate.py"]

def held():
    (tmp / "ready").write_text("")
    time.sleep(60)

mutate.run_suite = held
"""

SLOW_CLEANUP = """
restore = mutate.restore

def slow_restore(*args):
    (tmp / "cleaning").write_text("")
    time.sleep(2)
    return restore(*args)

mutate.restore = slow_restore
"""


def _start(script, tmp_path):
    child = subprocess.Popen(
        [sys.executable, "-c", script + "sys.exit(mutate.main())\n", str(ROOT), str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    _wait_for(tmp_path / "ready", child)
    return child


def _wait_for(path, child):
    deadline = time.monotonic() + 30
    while not path.exists() and child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert path.exists(), child.communicate()[0] if child.poll() is not None else f"no {path.name}"


@pytest.mark.parametrize("stop", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP], ids=["INT", "TERM", "HUP"])
def test_a_stopped_run_cleans_up_as_an_interrupted_one_does(tmp_path, stop):
    """Point 5: Ctrl-C, a cancelled CI job and a closed terminal all put the rule back."""
    _project(tmp_path)
    child = _start(STOPPED_RUN, tmp_path)
    assert (tmp_path / "project/rule.py").read_text() == "x = 2\n", "the rule was switched off"
    child.send_signal(stop)
    out, _ = child.communicate(timeout=30)
    assert child.returncode == (-signal.SIGINT if stop == signal.SIGINT else 128 + stop), out
    assert (tmp_path / "project/rule.py").read_text() == "x = 1\n"
    assert not (tmp_path / "recovery.json").exists()


def test_a_second_stop_does_not_cut_the_cleanup_short(tmp_path):
    """Point 5: GitHub cancels with SIGINT, then SIGTERM, while the first one is still cleaning up."""
    _project(tmp_path)
    child = _start(STOPPED_RUN + SLOW_CLEANUP, tmp_path)
    child.send_signal(signal.SIGINT)
    _wait_for(tmp_path / "cleaning", child)
    child.send_signal(signal.SIGTERM)
    out, _ = child.communicate(timeout=30)
    assert (tmp_path / "project/rule.py").read_text() == "x = 1\n", out
    assert not (tmp_path / "recovery.json").exists()


def test_one_mutation_run_per_checkout(tmp_path, monkeypatch, capsys):
    """Point 6: a second run would switch off a rule the first one is measuring."""
    mutate = _whole_run(tmp_path, monkeypatch)
    monkeypatch.setattr(mutate, "run_suite", lambda: pytest.fail("a second run measured"))
    other = os.open(mutate.ROOT, os.O_RDONLY)
    try:
        fcntl.flock(other, fcntl.LOCK_EX)
        assert mutate.main() == 1
    finally:
        os.close(other)
    assert "already running" in capsys.readouterr().out
    assert (mutate.ROOT / "rule.py").read_text() == "x = 1\n"


def test_repair_only_puts_back_what_a_killed_run_left_and_does_nothing_else(tmp_path, monkeypatch):
    """Point 6: after a kill -9, put the source back without starting a run."""
    mutate = _whole_run(tmp_path, monkeypatch)
    monkeypatch.setattr(mutate, "run_suite", lambda: pytest.fail("repair-only ran the suite"))
    monkeypatch.setattr(mutate, "sweep", lambda: pytest.fail("repair-only swept"))
    (mutate.ROOT / "rule.py").write_text("x = 2\n")
    mutate.RECOVERY.write_text(json.dumps({"file": "rule.py", "original": "x = 1\n", "mutated": "x = 2\n"}))
    monkeypatch.setattr(sys, "argv", ["mutate.py", "--repair-only"])
    assert mutate.main() == 0
    assert (mutate.ROOT / "rule.py").read_text() == "x = 1\n"
    assert not mutate.RECOVERY.exists()


STEP = """
import os, pathlib, signal, sys, time
tmp = pathlib.Path(sys.argv[1])

def put_back(signum, frame):
    time.sleep(0.3)  # putting a line back takes a moment; the ratchet must wait for it
    (tmp / "put-back").write_text("")
    sys.exit(1)

signal.signal(signal.SIGINT, put_back)
(tmp / "step.pid").write_text(str(os.getpid()))
(tmp / "ready").write_text("")
time.sleep(20)  # never told: give up, and leave no put-back behind
"""

SLOW_STEP = STEP.replace("time.sleep(0.3)", "(tmp / 'cleaning').write_text(''); time.sleep(2)")

RATCHET = """
import importlib.util, pathlib, sys
path = pathlib.Path(sys.argv[1]) / "scripts/ratchet.py"
spec = importlib.util.spec_from_file_location("ratchet_stopped", path)
ratchet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ratchet)
ratchet.stop_cleanly()
ratchet._run(sys.executable, "-c", sys.argv[3], sys.argv[2])
"""

COUNTED_STEP = """
import os, pathlib, signal, sys, time
tmp = pathlib.Path(sys.argv[1])

def count(signum, frame):
    with (tmp / "got-int").open("a") as got:
        got.write("INT\\n")

signal.signal(signal.SIGINT, count)
(tmp / "step.pid").write_text(str(os.getpid()))
(tmp / "ready").write_text("")
deadline = time.monotonic() + 20
while not (tmp / "got-int").exists() and time.monotonic() < deadline:
    time.sleep(0.05)
time.sleep(0.5)  # any second Ctrl-C arrives while the line is being put back
(tmp / "put-back").write_text("")
"""


#: The same stand-in, starting its step through uv, as the ratchet starts its own.
RATCHET_THROUGH_UV = RATCHET.replace(
    "ratchet._run(sys.executable,", 'ratchet._run("uv", "run", "--no-project", "python",'
)


@contextlib.contextmanager
def _ratchet(tmp_path, step, stand_in=RATCHET, **popen):
    ratchet = subprocess.Popen(
        [sys.executable, "-c", stand_in, str(ROOT), str(tmp_path), step],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        **popen,
    )
    try:
        _wait_for(tmp_path / "ready", ratchet)
        yield ratchet
    finally:
        if ratchet.poll() is None:
            ratchet.kill()
        if (tmp_path / "step.pid").exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int((tmp_path / "step.pid").read_text()), signal.SIGKILL)


@pytest.mark.parametrize("stop", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP], ids=["INT", "TERM", "HUP"])
def test_a_stopped_measurement_lets_its_step_put_back_what_it_changed(tmp_path, stop):
    """Point 8: the ratchet passes a stop to its child as Ctrl-C, and waits for it."""
    with _ratchet(tmp_path, STEP) as ratchet:
        ratchet.send_signal(stop)  # to the ratchet alone, as when its job is cancelled
        out, _ = ratchet.communicate(timeout=60)
        assert (tmp_path / "put-back").exists(), out


def test_a_second_stop_does_not_cut_the_ratchet_s_wait_short(tmp_path):
    """Point 5 for the ratchet: SIGINT, then SIGTERM while its child is still putting back."""
    with _ratchet(tmp_path, SLOW_STEP) as ratchet:
        ratchet.send_signal(signal.SIGINT)
        _wait_for(tmp_path / "cleaning", ratchet)
        ratchet.send_signal(signal.SIGTERM)
        out, _ = ratchet.communicate(timeout=60)
        assert (tmp_path / "put-back").exists(), out


def test_a_ctrl_c_in_the_terminal_reaches_the_step_once(tmp_path):
    """Point 8: a terminal sends Ctrl-C to the whole group; with the forwarded one, a step got two."""
    with _ratchet(tmp_path, COUNTED_STEP, start_new_session=True) as ratchet:
        os.killpg(ratchet.pid, signal.SIGINT)
        out, _ = ratchet.communicate(timeout=60)
        assert (tmp_path / "put-back").exists(), out
        assert (tmp_path / "got-int").read_text() == "INT\n"


@pytest.mark.parametrize("stop", [signal.SIGTERM, signal.SIGINT], ids=["kill", "ctrl-c"])
def test_a_stopped_ratchet_tells_the_python_under_uv_once(tmp_path, stop):
    """Point 8: uv passes a Ctrl-C on to its own child, so one sent to uv's group came twice."""
    with _ratchet(tmp_path, COUNTED_STEP, RATCHET_THROUGH_UV, start_new_session=True) as ratchet:
        if stop == signal.SIGINT:
            os.killpg(ratchet.pid, stop)  # a terminal's Ctrl-C, to the ratchet's whole group
        else:
            ratchet.send_signal(stop)  # to the ratchet alone, as when its job is cancelled
        out, _ = ratchet.communicate(timeout=60)
        assert (tmp_path / "put-back").exists(), out
        assert (tmp_path / "got-int").read_text() == "INT\n"  # once, not twice


def _git(where, *args):
    return subprocess.run(
        ["git", *args], cwd=where, capture_output=True, text=True, check=True
    ).stdout.strip()


def _clone(tmp_path, *messages):
    here = tmp_path / "clone"
    here.mkdir()
    _git(here, "init", "-q", "-b", "main")
    for message in messages:
        _git(
            here,
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.org",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            message,
        )
    return here


def test_the_base_is_measured_where_no_other_branch_can_be_seen(tmp_path, monkeypatch):
    """A worktree shares every branch of the clone, and git keeps a record of it that a kill leaves."""
    ratchet = _load("ratchet")
    here = _clone(tmp_path, "base")
    _git(here, "branch", "under-review")
    monkeypatch.setattr(ratchet, "ROOT", here)
    copy = tmp_path / "copy"
    ratchet.copy_of("main", copy)
    assert _git(copy, "rev-parse", "HEAD") == _git(here, "rev-parse", "main")
    assert _git(copy, "for-each-ref") == ""
    assert _git(here, "worktree", "list").count("\n") == 0  # no record of the copy in the clone


def test_the_base_may_be_a_commit_no_branch_points_at(tmp_path, monkeypatch):
    """CI's base is main's commit when the pull request began, which main may have moved on from.

    git's newer protocol fetches such a commit by its id; the older one refuses it, so the test
    sets the older one, as an old git or a person's own settings would.
    """
    settings = tmp_path / "gitconfig"
    settings.write_text("[protocol]\n\tversion = 0\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(settings))
    ratchet = _load("ratchet")
    here = _clone(tmp_path, "base", "later")
    behind = _git(here, "rev-parse", "main~1")
    monkeypatch.setattr(ratchet, "ROOT", here)
    copy = tmp_path / "copy"
    ratchet.copy_of(behind, copy)
    assert _git(copy, "rev-parse", "HEAD") == behind


def test_a_run_refuses_a_package_imported_from_another_checkout(tmp_path, monkeypatch):
    """Point 9: a run here that measures another worktree's code measures nothing of this one."""
    mutate = _whole_run(tmp_path, monkeypatch)
    monkeypatch.undo()
    monkeypatch.setattr(mutate, "ROOT", tmp_path / "project")
    with pytest.raises(SystemExit, match=r"(?s)imports mister_mcp from .*not .*project.*uv sync"):
        mutate.from_this_checkout()
    real = _load("mutate")
    real.from_this_checkout()  # this checkout's own package: no refusal


def test_the_ratchet_refuses_a_package_imported_from_another_checkout(tmp_path, monkeypatch):
    """Point 9, for every copy the ratchet measures, the base's included."""
    ratchet = _load("ratchet")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(ratchet, "ROOT", elsewhere)
    with pytest.raises(SystemExit, match=r"(?s)mister_mcp.*elsewhere.*uv sync"):
        ratchet.from_this_checkout()
    monkeypatch.undo()
    ratchet.from_this_checkout()
