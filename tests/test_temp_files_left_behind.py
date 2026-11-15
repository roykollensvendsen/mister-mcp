"""A run of the scripts leaves nothing behind in the machine's temporary folder.

Hundreds of folders under /tmp, 3.1 GB, were left over a few days by test,
mutation and ratchet runs across the projects. Here the leaks were two: a
ratchet stopped mid-run kept its copy of main and a git worktree pointing at
it, and every mutation run kept the folder its runs lived in. Each script now
cleans up when it ends, when it is stopped, and sweeps what a killed run left.
"""

import importlib.util
import os
import pathlib
import signal
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).parent.parent


def _load(name, tmpdir, monkeypatch):
    """A script loaded by path, with the temporary folder set to `tmpdir` before it loads."""
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    monkeypatch.setattr("tempfile.tempdir", None)
    spec = importlib.util.spec_from_file_location(f"{name}_left", ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def _repository(place):
    place.mkdir()
    _git("init", "-q", cwd=place)
    (place / "a.txt").write_text("a")
    _git(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.org",
        "commit",
        "-qam",
        "a",
        "--allow-empty",
        cwd=place,
    )
    _git("add", "a.txt", cwd=place)
    _git("-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-qm", "a", cwd=place)
    return place


def test_a_mutation_run_leaves_nothing_in_the_temporary_folder(tmp_path, monkeypatch):
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    mutate = _load("mutate", tmpdir, monkeypatch)
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "tests" / "test_one.py").write_text(
        "def test_one(tmp_path):\n    (tmp_path / 'x').write_text('x')\n"
    )
    monkeypatch.setattr(mutate, "ROOT", project)
    failed, _ = mutate.run_suite()
    assert failed == 0
    assert list(tmpdir.iterdir()) == []


def test_a_killed_ratchet_s_copy_of_main_is_swept_at_the_next_start(tmp_path, monkeypatch):
    """A kill skips every finally: the copy and the worktree git keeps for it stay behind."""
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    ratchet = _load("ratchet", tmpdir, monkeypatch)
    repository = _repository(tmp_path / "repository")
    monkeypatch.setattr(ratchet, "ROOT", repository)
    left = ratchet.RATCHET_TMP / "base-left-by-a-killed-run"
    left.mkdir(parents=True)
    _git("worktree", "add", "-q", "--detach", str(left / "base"), "HEAD", cwd=repository)
    ratchet.sweep()
    assert list(tmpdir.iterdir()) == []
    assert str(left) not in _git("worktree", "list", cwd=repository)


@pytest.mark.skipif(sys.platform == "win32", reason="no SIGTERM to send on Windows")
@pytest.mark.parametrize("name", ["ratchet", "mutate"])
def test_a_stopped_run_still_removes_its_temporary_files(name, tmp_path):
    """Stopping a run sends SIGTERM, which ends Python without running a finally unless handled."""
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    script = (
        "import importlib.util, sys, tempfile, time\n"
        f"spec = importlib.util.spec_from_file_location('s', {str(ROOT / f'scripts/{name}.py')!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "module.stop_cleanly()\n"
        "with tempfile.TemporaryDirectory():\n"
        "    print('ready', flush=True)\n"
        "    time.sleep(30)\n"
    )
    env = {**os.environ, "TMPDIR": str(tmpdir)}
    run = subprocess.Popen([sys.executable, "-c", script], env=env, stdout=subprocess.PIPE, text=True)
    assert run.stdout.readline().strip() == "ready"
    run.send_signal(signal.SIGTERM)
    run.wait(timeout=10)
    deadline = time.monotonic() + 5
    while list(tmpdir.iterdir()) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert list(tmpdir.iterdir()) == []
