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
    """A kill skips every finally: the copy stays behind until the next start sweeps it.

    The sweep removes only the run's own folder. It never prunes git's worktree records,
    which would erase other sessions' records of their own worktrees too.
    """
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    ratchet = _load("ratchet", tmpdir, monkeypatch)
    repository = _repository(tmp_path / "repository")
    monkeypatch.setattr(ratchet, "ROOT", repository)
    other = tmp_path / "another-session-s-worktree"
    _git("worktree", "add", "-q", "--detach", str(other), "HEAD", cwd=repository)
    _git("worktree", "lock", str(other), cwd=repository)
    left, lock = ratchet.run_folders.start_run(ratchet.RATCHET_TMP)
    os.close(lock)  # a killed run's lock goes with its process
    ratchet.copy_of("HEAD", left / "base")
    ratchet.sweep()
    assert list(tmpdir.iterdir()) == []
    assert str(other) in _git("worktree", "list", cwd=repository)


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


def _base(name, tmpdir, monkeypatch, tmp_path):
    """A script, and the folder its runs live in."""
    module = _load(name, tmpdir, monkeypatch)
    if name == "ratchet":
        monkeypatch.setattr(module, "ROOT", _repository(tmp_path / "repository"))
        return module, module.RATCHET_TMP
    return module, module.MUTATE_TMP


@pytest.mark.parametrize("name", ["ratchet", "mutate"])
def test_a_sweep_never_removes_a_folder_a_live_run_holds(name, tmp_path, monkeypatch):
    """Two runs in one checkout: the second one's sweep must leave the first one's folder alone."""
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    module, base = _base(name, tmpdir, monkeypatch, tmp_path)
    live, lock = module.run_folders.start_run(base)
    try:
        (live / "work.txt").write_text("in use")
        module.sweep()
        assert (live / "work.txt").read_text() == "in use"
    finally:
        os.close(lock)


@pytest.mark.parametrize("name", ["ratchet", "mutate"])
def test_a_sweep_leaves_anything_not_named_like_a_run_alone(name, tmp_path, monkeypatch):
    """Only a real folder of this user's, named like a run's, is ever looked at; a link is never followed."""
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    module, base = _base(name, tmpdir, monkeypatch, tmp_path)
    base.mkdir(mode=0o700, parents=True)
    (base / "notes").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "kept.txt").write_text("x")
    (base / "run-000000000001").symlink_to(outside)
    module.sweep()
    assert (base / "notes").is_dir()
    assert (outside / "kept.txt").exists()


def test_pytest_s_folder_sits_beside_the_run_s_lock_never_around_it(tmp_path, monkeypatch):
    """Point 1: pytest empties its basetemp first, which would take the lock with it."""
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    mutate = _load("mutate", tmpdir, monkeypatch)
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "tests" / "test_lock.py").write_text(
        "def test_the_lock_is_still_there(tmp_path):\n"
        "    assert (tmp_path.parent.parent / '.lock').exists()\n"
    )
    monkeypatch.setattr(mutate, "ROOT", project)
    failed, _ = mutate.run_suite()
    assert failed == 0
