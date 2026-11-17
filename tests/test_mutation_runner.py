"""The mutation runner's own rules, each switched off by its own row since mutate.py joined the check."""

import importlib.util
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).parent.parent


def _mutate(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("mutate_runner", ROOT / "scripts/mutate.py")
    mutate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mutate)
    monkeypatch.setattr(mutate, "MUTATE_TMP", tmp_path / "mutate-tmp")
    return mutate


def _suite_said(mutate, monkeypatch, stdout):
    """Run the suite with pytest's output replaced by `stdout`; give back what it was asked with."""
    asked = {}

    def ran(command, **kwargs):
        asked.update(kwargs, command=command)
        return subprocess.CompletedProcess(command, 1, stdout, "")

    monkeypatch.setattr(mutate.subprocess, "run", ran)
    return mutate.run_suite(), asked


def test_a_coloured_failure_line_is_still_attributed(tmp_path, monkeypatch):
    """A test forcing colour must not hide which test went red."""
    mutate = _mutate(tmp_path, monkeypatch)
    said = "\x1b[31mFAILED\x1b[0m tests/test_x.py::test_a_rule[one] - boom\n\x1b[31m1 failed\x1b[0m in 0.1s\n"
    (count, failed), _ = _suite_said(mutate, monkeypatch, said)
    assert (count, failed) == (1, ["test_a_rule"])


def test_two_mutations_never_share_a_bytecode_cache(tmp_path, monkeypatch):
    """Two same-size mutations in one second would otherwise run the last one's bytecode."""
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)  # a mutation run sets it
    mutate = _mutate(tmp_path, monkeypatch)
    _, asked = _suite_said(mutate, monkeypatch, "1 passed in 0.1s\n")
    assert asked["env"]["PYTHONDONTWRITEBYTECODE"] == "1"


def test_a_file_changed_during_the_run_is_never_restored_over(tmp_path, monkeypatch):
    """Restoring over an edit made while the suite ran would lose somebody's work."""
    mutate = _mutate(tmp_path, monkeypatch)
    edited = tmp_path / "rule.py"
    edited.write_text("x = 3  # edited by hand meanwhile\n")
    assert mutate.restore(edited, "x = 1\n", "x = 2\n") is False
    assert edited.read_text() == "x = 3  # edited by hand meanwhile\n"


def test_a_real_mutation_run_is_never_capped(tmp_path, monkeypatch):
    """Roy's rule: no time limit on a mutation run. Only a test's scratch suite passes a bound."""
    mutate = _mutate(tmp_path, monkeypatch)
    _, asked = _suite_said(mutate, monkeypatch, "1 passed in 0.1s\n")
    assert asked["timeout"] is None
    asked.clear()
    monkeypatch.setattr(
        mutate.subprocess,
        "run",
        lambda command, **kw: asked.update(kw) or subprocess.CompletedProcess(command, 0, "", ""),
    )
    mutate.run_suite(timeout=300)
    assert asked["timeout"] == 300
