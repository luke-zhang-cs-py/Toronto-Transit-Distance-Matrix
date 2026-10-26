"""The figure refresher (tools/refresh_figures.py), against a page of a few
rows.

tests/test_published_figures.py checks that docs/index.html quotes the real
numbers; this tool is what rewrites them. It runs the whole suite under
coverage to do it, which is the one thing a test of it must not do -- so
`subprocess.run` is replaced by a stand-in that answers the way pytest
would, and the page, the README and the tests/ it counts all live in
tmp_path. The real docs/index.html is never opened for writing.
"""

import io
import json
import os
import sys

import pytest

from tools import refresh_figures as rf

VERSION = "%d.%d" % sys.version_info[:2]

PAGE = """<script>
var MODULES = [
  { name: 'app.py', lines: 9, stmts: 9, missed: 9, does: 'the HTTP surface' },
  { name: 'gone.py', lines: 1, stmts: 1, missed: 0, does: 'deleted last week' }
];

var OMITTED = [
  { name: 'tools/slow.py', lines: 99, why: 'too slow' }
];

var TESTS = [
  { file: 'test_app.py', n: 1, of: 'the endpoints' },
  { file: 'test_gone.py', n: 4, of: 'deleted too' }
];

var TEST_LINES = 1;

var MEASURED_WITH = 'Python 2.7';
</script>
"""


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repository of three files, with the tool pointed at it."""
    (tmp_path / "app.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "slow.py").write_text("x = 1\n" * 4, encoding="utf-8")
    tests = tmp_path / "tests"
    (tests / "__pycache__").mkdir(parents=True)
    (tests / "test_app.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    (tests / "notes.txt").write_text("not a test\n" * 50, encoding="utf-8")
    (tests / "__pycache__" / "stale.py").write_text("x\n" * 50, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "index.html").write_text(PAGE, encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "## Tests\n\n9 tests, 50% of 9 statements -- checked.\n", encoding="utf-8")
    monkeypatch.setattr(rf, "ROOT", str(tmp_path))
    monkeypatch.setattr(rf, "PAGE", str(tmp_path / "docs" / "index.html"))
    monkeypatch.setattr(rf, "README", str(tmp_path / "README.md"))
    return tmp_path


def read(path):
    with io.open(str(path), encoding="utf-8") as handle:
        return handle.read()


MEASURED = {"app.py": {"lines": 3, "stmts": 3, "missed": 1}}
COUNTS = {"test_app.py": 2}


# ------------------------------------------------------------ measuring

def test_measure_reads_the_json_report_of_a_coverage_run(repo, monkeypatch):
    seen = {}

    def run(command, **kwargs):
        seen["command"], seen["cwd"] = command, kwargs["cwd"]
        report = [arg for arg in command if arg.startswith("--cov-report=json:")][0]
        seen["report"] = report.split(":", 1)[1]
        with open(seen["report"], "w", encoding="utf-8") as handle:
            json.dump({"files": {"app.py": {"summary": {
                "num_statements": 3, "missing_lines": 1}}}}, handle)

    monkeypatch.setattr(rf.subprocess, "run", run)
    assert rf.measure() == {"app.py": {"lines": 3, "stmts": 3, "missed": 1}}
    assert seen["command"][1:4] == ["-m", "pytest", "-q"] and "--cov" in seen["command"]
    assert seen["cwd"] == str(repo)
    assert not os.path.exists(seen["report"]), "the temporary report is removed"


def test_collect_counts_tests_per_file(monkeypatch):
    class Done:
        stdout = ("tests/test_a.py::test_one\n"
                  "tests/test_a.py::test_two[x]\n"
                  "tests/test_b.py::test_three\n"
                  "\n3 tests collected in 0.1s\n")

    monkeypatch.setattr(rf.subprocess, "run", lambda *a, **k: Done())
    assert rf.collect() == {"test_a.py": 2, "test_b.py": 1}


def test_a_collection_that_finds_nothing_stops_rather_than_writing_zeros(monkeypatch):
    class Done:
        stdout = "ERROR: file or directory not found\n"

    monkeypatch.setattr(rf.subprocess, "run", lambda *a, **k: Done())
    with pytest.raises(SystemExit, match="collection produced nothing"):
        rf.collect()


# ------------------------------------------------------------ the blocks

def test_module_rows_are_rewritten_and_a_vanished_one_is_reported():
    changes = []
    page = rf.fix_modules(PAGE, MEASURED, changes)
    assert ("  { name: 'app.py', lines:   3, stmts:   3, missed:  1, "
            "does: 'the HTTP surface' }\n];") in page
    assert "gone.py" not in page.split("var OMITTED")[0]
    assert changes[0].startswith("gone.py is on the page but coverage no longer")
    assert changes[1].split() == ["app.py", "(9,", "9,", "9)", "->", "(3,", "3,", "1)"]
    # A row that is already right is not reported.
    again = []
    rf.fix_modules(page, MEASURED, again)
    assert again == []


def test_a_module_with_no_description_needs_a_person():
    with pytest.raises(SystemExit, match="no description on the page for new.py"):
        rf.fix_modules(PAGE, dict(MEASURED, **{"new.py": MEASURED["app.py"]}), [])


def test_test_rows_are_rewritten_and_an_empty_file_is_reported():
    changes = []
    page = rf.fix_tests(PAGE, COUNTS, changes)
    assert "  { file: 'test_app.py', n:  2, of: 'the endpoints' }\n];" in page
    assert changes[0] == "test_gone.py is on the page but collects nothing"
    assert changes[1].split() == ["test_app.py", "1", "->", "2"]
    again = []
    rf.fix_tests(page, COUNTS, again)
    assert again == []


def test_a_test_file_with_no_description_needs_a_person():
    with pytest.raises(SystemExit, match="no description on the page for test_new.py"):
        rf.fix_tests(PAGE, {"test_new.py": 1}, [])


def test_the_interpreter_that_measured_is_recorded():
    changes = []
    page = rf.fix_measured_with(PAGE, changes)
    assert "var MEASURED_WITH = 'Python %s';" % VERSION in page
    assert changes == ["MEASURED_WITH Python 2.7 -> %s" % VERSION]
    again = []
    assert rf.fix_measured_with(page, again) == page and again == []
    with pytest.raises(SystemExit, match="no MEASURED_WITH line"):
        rf.fix_measured_with("<script></script>", [])


def test_test_lines_count_python_files_outside_the_cache(repo):
    changes = []
    page = rf.fix_test_lines(PAGE, changes)
    assert "var TEST_LINES = 2;" in page and changes == ["TEST_LINES 1 -> 2"]
    again = []
    rf.fix_test_lines(page, again)
    assert again == []
    # A page with no TEST_LINES is left alone rather than given one.
    assert rf.fix_test_lines("<p>none</p>", []) == "<p>none</p>"


def test_omitted_rows_get_their_real_line_counts(repo):
    changes = []
    page = rf.fix_omitted(PAGE, changes)
    assert "{ name: 'tools/slow.py', lines: 4, why: 'too slow' }" in page
    assert changes[0].split() == ["tools/slow.py", "99", "->", "4", "lines"]
    again = []
    rf.fix_omitted(page, again)
    assert again == []


def test_an_omitted_file_that_is_not_there_stops_the_refresh(repo):
    os.remove(str(repo / "tools" / "slow.py"))
    with pytest.raises(SystemExit, match="lists tools/slow.py as omitted"):
        rf.fix_omitted(PAGE, [])


def test_a_page_with_no_omissions_is_unchanged(repo):
    page = PAGE.replace("var OMITTED", "var NOTHING")
    assert rf.fix_omitted(page, []) == page


def test_the_readme_sentence_is_rewritten_only_when_wrong(repo):
    changes = []
    rf.fix_readme(MEASURED, COUNTS, changes)
    assert "2 tests, 67% of 3 statements -- checked." in read(repo / "README.md")
    assert changes == ["README  9 tests, 50% of 9 statements -> 2 tests, 67% of 3 statements"]
    again = []
    rf.fix_readme(MEASURED, COUNTS, again)
    assert again == []


def test_a_readme_that_states_no_figures_is_left_alone(repo):
    (repo / "README.md").write_text("No numbers here.\n", encoding="utf-8")
    rf.fix_readme(MEASURED, COUNTS, [])
    assert read(repo / "README.md") == "No numbers here.\n"
    os.remove(str(repo / "README.md"))
    rf.fix_readme(MEASURED, COUNTS, [])
    assert not (repo / "README.md").exists()


# ------------------------------------------------------------ the command

def test_the_command_rewrites_the_page_and_says_what_changed(repo, monkeypatch, capsys):
    monkeypatch.setattr(rf, "measure", lambda: MEASURED)
    monkeypatch.setattr(rf, "collect", lambda: COUNTS)
    rf.main()
    page = read(repo / "docs" / "index.html")
    assert "lines:   3, stmts:   3, missed:  1" in page
    assert "n:  2," in page and "var TEST_LINES = 2;" in page
    assert "Python %s" % VERSION in page
    out = capsys.readouterr().out
    assert "TEST_LINES 1 -> 2" in out and "README" in out
    assert out.rstrip().endswith("2 tests, 3 statements, 67% covered")

    # Run again: the page is right now, so only the totals are printed and
    # nothing is written.
    before = os.path.getmtime(str(repo / "docs" / "index.html"))
    rf.main()
    assert capsys.readouterr().out == "  2 tests, 3 statements, 67% covered\n"
    assert os.path.getmtime(str(repo / "docs" / "index.html")) == before


def test_a_rewrite_that_is_not_stable_is_never_written(repo, monkeypatch):
    passes = []

    def rewrite(page, measured, counts, changes):
        passes.append(1)
        return page + "x" * len(passes)

    monkeypatch.setattr(rf, "measure", lambda: MEASURED)
    monkeypatch.setattr(rf, "collect", lambda: COUNTS)
    monkeypatch.setattr(rf, "rewrite", rewrite)
    with pytest.raises(SystemExit, match="not idempotent"):
        rf.main()
    assert read(repo / "docs" / "index.html") == PAGE
