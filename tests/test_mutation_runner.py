"""The mutation runner's own rules, each switched off by its own row since mutate.py joined the check."""

import importlib.util
import pathlib
import subprocess
import sys

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
    """The owner's rule: no time limit on a mutation run. Only a test's scratch suite passes a bound."""
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


def _broken_row_run(tmp_path, monkeypatch, *argv):
    """A whole run over one rule, `x = 1`, whose row's replacement `x = (` is not valid code."""
    mutate = _mutate(tmp_path, monkeypatch)
    project = tmp_path / "project"
    project.mkdir()
    (project / "rule.py").write_text("x = 1\n")
    rows = tmp_path / "mutations" / "rule.py"
    rows.mkdir(parents=True)
    (rows / "x-is-one.toml").write_text(
        "[[rule]]\nname = \"x is one\"\nfile = \"rule.py\"\nfind = '^x = 1$'\nreplace = 'x = ('\n"
    )
    monkeypatch.setattr(mutate, "ROOT", project)
    monkeypatch.setattr(mutate, "ROWS", tmp_path / "mutations")
    monkeypatch.setattr(mutate, "RECOVERY", tmp_path / "recovery.json")
    monkeypatch.setattr(mutate, "from_this_checkout", lambda: None)
    monkeypatch.setattr(sys, "argv", ["mutate.py", *argv])
    suites = []

    def suite():
        suites.append((project / "rule.py").read_text())
        return 1, ["test_x_is_one"]  # every test errors when the module does not compile

    monkeypatch.setattr(mutate, "run_suite", suite)
    return mutate, project, suites


def test_a_row_that_breaks_the_code_is_reported_as_broken(tmp_path, monkeypatch, capsys):
    """A replacement that does not compile fails every test, which would pass for a kill."""
    mutate, project, suites = _broken_row_run(tmp_path, monkeypatch)
    assert mutate.main() == 1
    out = capsys.readouterr().out
    assert "BROKEN   x is one: the replacement is not valid code (line 1:" in out
    assert "KILLED" not in out
    assert "0/1 rules turned off the test that names them" in out
    assert "BROKEN ROW, so nothing was tested; make each a whole valid line: x is one" in out
    assert "mutations/rule.py/x-is-one.toml" in out
    assert suites == []
    assert (project / "rule.py").read_text() == "x = 1\n"


def test_a_broken_row_is_listed_in_the_report_and_the_step_summary(tmp_path, monkeypatch):
    """The evidence page and the CI job's summary say which row to fix, not only the log."""
    page, summary = tmp_path / "rule-mutations.md", tmp_path / "step-summary.md"
    summary.write_text("earlier steps\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    mutate, _, _ = _broken_row_run(tmp_path, monkeypatch, "--write", str(page))
    assert mutate.main() == 1
    assert "Broken rows, so nothing was tested: x is one." in page.read_text()
    said = summary.read_text()
    assert said.startswith("earlier steps\n")
    assert "0 of 1 rules turned off the test that names them" in said
    assert "Broken rows, so nothing was tested: x is one." in said
