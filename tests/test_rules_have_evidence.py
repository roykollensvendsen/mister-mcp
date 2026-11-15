"""Every rule this project enforces has evidence, and the evidence names it.

A rule here is one line of source marked ``# RULE: what it says``. Three things
have to be true of each, and none of them is true by writing the rule:

* it has a row in ``scripts/mutations/``, so something switches it off;
* a test carries the rule's own words as its name;
* switching it off turns *that* test red, which ``scripts/mutate.py`` checks.

The second is what makes the third readable. A mutation breaks whatever it
breaks, and a kill only means something when the test that went red is the one
that names the rule — otherwise a documented example that happened to change can
leave a rule looking guarded while nothing guards it.
"""

import importlib.util
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).parent.parent


def _mutate():
    """The mutation runner, loaded by path: scripts/ is not a package."""
    spec = importlib.util.spec_from_file_location("mutate", ROOT / "scripts/mutate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def marked_rules() -> set[str]:
    """Every rule the source marks, by the words the marker gives it."""
    found = set()
    # The checks this project added count too; the scripts the start-repo
    # skill ships carry rules that skill proves.
    scripts = [
        ROOT / "scripts" / n
        for n in ("no_session_links.py", "private_data_scan.py", "ratchet.py", "run_folders.py", "mutate.py")
    ]
    sources = [*(ROOT / "src").rglob("*.py"), *scripts]
    for source in sorted(sources):
        for line in source.read_text(encoding="utf-8").splitlines():
            match = _mutate().MARKER.search(line)
            if match:
                found.add(match.group(1))
    return found


def rowed_rules() -> set[str]:
    """Every rule the mutation rows claim to switch off."""
    return {str(rule["name"]) for rule in _mutate().all_rows()}


def defined_test_names() -> set[str]:
    """Every test function this suite defines.

    Not called ``test_names``: pytest collects anything starting with ``test_``,
    and a helper that returns a set would be reported as a test that forgot to
    assert.
    """
    found = set()
    for module in sorted((ROOT / "tests").rglob("test_*.py")):
        found.update(re.findall(r"^(?:async )?def (test_\w+)", module.read_text(), re.MULTILINE))
    return found


def test_every_rule_in_the_source_has_a_row_in_the_mutation_table():
    """Without this the evidence falls behind the code and nobody sees it happen."""
    marked, rowed = marked_rules(), rowed_rules()
    assert marked - rowed == set(), f"marked in the source and never switched off: {marked - rowed}"
    assert rowed - marked == set(), f"a row for a rule no longer in the source: {rowed - marked}"


def test_every_rule_has_a_test_named_after_it():
    """A kill is only evidence about a rule when the test that went red names it."""
    name_for = _mutate().test_name_for
    named = defined_test_names()
    missing = sorted(rule for rule in marked_rules() if name_for(rule) not in named)
    wanted = ", ".join(f"{name_for(rule)}()" for rule in missing)
    assert not missing, f"rules with no test named after them — write {wanted}"


def _row(name, file="src/mister_mcp/service.py"):
    return f"[[rule]]\nname = \"{name}\"\nfile = \"{file}\"\nfind = 'x'\nreplace = 'y'\n"


def _put(folder, source, file_name, text):
    place = folder / source
    place.mkdir(parents=True, exist_ok=True)
    (place / file_name).write_text(text, encoding="utf-8")


def test_every_row_is_read_from_a_file_of_its_own(tmp_path):
    """Two pull requests that each add a row at the end of one table collide; one file each cannot."""
    folder = tmp_path / "mutations"
    _put(folder, "src/mister_mcp/service.py", "one.toml", _row("one"))
    _put(folder, "src/mister_mcp/zaparoo.py", "two.toml", _row("two", "src/mister_mcp/zaparoo.py"))
    assert [rule["name"] for rule in _mutate().all_rows(folder)] == ["one", "two"]


def test_the_same_rule_in_two_row_files_is_refused_naming_both(tmp_path):
    """Moving a row and forgetting the old one would switch the rule off twice and count it twice."""
    folder = tmp_path / "mutations"
    _put(folder, "src/mister_mcp/service.py", "twice.toml", _row("twice"))
    _put(folder, "src/mister_mcp/zaparoo.py", "twice.toml", _row("twice"))
    with pytest.raises(SystemExit) as refused:
        _mutate().all_rows(folder)
    said = str(refused.value)
    assert "src/mister_mcp/service.py/twice.toml" in said
    assert "src/mister_mcp/zaparoo.py/twice.toml" in said
    assert "delete one" in said


def test_a_row_file_sits_in_its_source_s_folder_under_its_own_name(tmp_path):
    """Where a row lives is never a choice, so two pull requests only meet over the same rule."""
    folder = tmp_path / "mutations"
    there = "src/mister_mcp/service.py"
    _put(folder, there, "in-place.toml", _row("in place"))
    _put(folder, "src/mister_mcp/zaparoo.py", "wrong-folder.toml", _row("wrong folder"))
    _put(folder, there, "a-wrong-name.toml", _row("named otherwise"))
    _put(folder, there, "two-rows.toml", _row("two rows") + _row("in one file"))
    found = " ".join(_mutate().misfiled(folder))
    assert f"src/mister_mcp/zaparoo.py/wrong-folder.toml should be {there}/wrong-folder.toml" in found
    assert f"{there}/a-wrong-name.toml should be {there}/named-otherwise.toml" in found
    assert f"{there}/two-rows.toml holds 2 rows" in found
    assert "in-place" not in found


def test_every_row_file_in_the_repository_is_where_its_rule_says():
    misfiled = _mutate().misfiled()
    assert not misfiled, "row files out of place: " + "; ".join(misfiled)


def test_the_old_shared_table_is_gone():
    """One place for rows: a table left beside the folder would be read by nothing."""
    assert not (ROOT / "scripts/mutations.toml").exists()


def test_a_rule_whose_words_give_no_file_name_is_refused():
    """A name with no letter or digit would be filed as ".toml", and the next one on top of it."""
    with pytest.raises(SystemExit, match=r"'\?!' has no letter or digit"):
        _mutate().row_path({"name": "?!", "file": "src/mister_mcp/service.py"})


def test_a_row_s_folder_is_the_whole_path_of_the_file_it_switches_off():
    """The same layout as the other repositories: the whole path, extension included."""
    row_path = _mutate().row_path
    assert str(row_path({"name": "A press, needs a yes!", "file": "src/mister_mcp/server.py"})) == (
        "src/mister_mcp/server.py/a-press-needs-a-yes.toml"
    )
    assert row_path({"name": "x", "file": "scripts/ratchet.py"}) != row_path(
        {"name": "x", "file": "src/ratchet.py"}
    )


def test_the_rows_folder_is_read_when_called_not_when_loaded(tmp_path, monkeypatch):
    """A default bound at load time keeps reading the real folder after a test points ROWS elsewhere."""
    mutate = _mutate()
    folder = tmp_path / "mutations"
    _put(folder, "src/mister_mcp/service.py", "elsewhere.toml", _row("elsewhere"))
    monkeypatch.setattr(mutate, "ROWS", folder)
    assert [rule["name"] for rule in mutate.all_rows()] == ["elsewhere"]
    assert mutate.misfiled() == []


def _bare(tmp_path, monkeypatch, *, marked):
    """A checkout with no row files, whose source does or does not mark a rule."""
    mutate = _mutate()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "thing.py").write_text("# RULE: a thing is kept\n" if marked else "x = 1\n")
    monkeypatch.setattr(mutate, "ROOT", tmp_path)
    monkeypatch.setattr(mutate, "ROWS", tmp_path / "scripts/mutations")
    monkeypatch.setattr(mutate, "RECOVERY", tmp_path / "recovery.json")
    monkeypatch.setattr(mutate, "MUTATE_TMP", tmp_path / "mutate-tmp")
    monkeypatch.setattr(sys, "argv", ["mutate.py"])
    return mutate


def test_rules_marked_with_no_rows_fail_the_run_and_say_how_to_get_them_back(tmp_path, monkeypatch, capsys):
    """A lost or unchecked-out folder would otherwise pass with nothing switched off."""
    assert _bare(tmp_path, monkeypatch, marked=True).main() == 1
    said = capsys.readouterr().out
    assert "git checkout origin/main -- scripts/mutations" in said
    assert "1 rule" in said


def test_a_new_repository_with_no_rules_and_no_rows_is_not_a_failure(tmp_path, monkeypatch, capsys):
    assert _bare(tmp_path, monkeypatch, marked=False).main() == 0
    assert "no rules" in capsys.readouterr().out
