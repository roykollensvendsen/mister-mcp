"""The sweep's four points from the cleanup checklist (new-plugin-v8.md), proven on run_folders."""

import importlib.util
import os
import pathlib
import time

import pytest

ROOT = pathlib.Path(__file__).parent.parent


def _run_folders():
    spec = importlib.util.spec_from_file_location("run_folders_t", ROOT / "scripts/run_folders.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rf = _run_folders()


def _base(tmp_path):
    base = tmp_path / "base"
    base.mkdir(mode=0o700)
    return base


def _aged(path, seconds):
    then = time.time() - seconds
    os.utime(path, (then, then))


def test_a_run_s_lock_is_made_new(tmp_path, monkeypatch):
    """Point 1: a lock file someone else put in the starting folder first is never shared."""
    base = _base(tmp_path)
    planted = base / "starting-planted"
    planted.mkdir()
    (planted / ".lock").write_text("")
    monkeypatch.setattr(rf.tempfile, "mkdtemp", lambda **_: str(planted))
    with pytest.raises(FileExistsError):
        rf.start_run(base)


def test_a_run_s_lock_is_private(tmp_path):
    """Point 1: only this user may open a run's lock."""
    folder, lock = rf.start_run(_base(tmp_path))
    try:
        assert ((folder / ".lock").stat().st_mode & 0o777) == 0o600
    finally:
        os.close(lock)


def test_a_sweep_never_makes_a_lock_in_a_folder_that_has_none(tmp_path):
    """Point 2: a lock a sweep made would sit in a new run's folder before that run moves in."""
    base = _base(tmp_path)
    young = base / "run-000000000001"
    young.mkdir()
    assert rf.dead_runs(base) == []
    assert not (young / ".lock").exists()


def test_a_folder_with_no_lock_is_dead_only_after_the_grace_period(tmp_path):
    """Point 3: for run- and starting- names alike."""
    base = _base(tmp_path)
    names = ["run-000000000001", "starting-abc", "run-000000000002", "starting-def"]
    for name in names:
        (base / name).mkdir()
    for name in names[2:]:
        _aged(base / name, rf.STARTING_SECONDS + 60)
    assert [p.name for p in rf.dead_runs(base)] == ["run-000000000002", "starting-def"]


def test_a_folder_another_sweep_removed_first_is_passed_over(tmp_path, monkeypatch):
    """Point 3: the first look's age is used, so a folder gone by the second look is no error."""
    base = _base(tmp_path)
    gone = base / "run-000000000001"
    gone.mkdir()
    _aged(gone, rf.STARTING_SECONDS + 60)
    real_open = os.open

    def removed_meanwhile(path, *args, **kwargs):
        if str(path).endswith(".lock"):
            gone.rmdir()
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(rf.os, "open", removed_meanwhile)
    assert [p.name for p in rf.dead_runs(base)] == ["run-000000000001"]


@pytest.mark.parametrize("shape", ["link", "open to others", "a file"])
def test_the_base_folder_must_be_a_private_folder_of_ours(shape, tmp_path):
    """Point 4: at the start of a run as well as in the sweep; anything else stops with the fix."""
    base = tmp_path / "base"
    if shape == "link":
        (tmp_path / "elsewhere").mkdir(mode=0o700)
        base.symlink_to(tmp_path / "elsewhere")
    elif shape == "open to others":
        base.mkdir()
        base.chmod(0o755)
    else:
        base.write_text("x")
    for call in (rf.start_run, rf.dead_runs):
        with pytest.raises(SystemExit, match=f"{base}.*rm -r"):
            call(base)
