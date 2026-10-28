from pathlib import Path

from conftest import git
from git_changes import changed_existing_lines, changed_files, changed_line_filter, diff_base_commit, parse_hunks
from scope_check import out_of_scope_files, parse_plan_slices, parse_test_plan_files

DIFF_OUTPUT = """diff --git a/app/entities.py b/app/entities.py
--- a/app/entities.py
+++ b/app/entities.py
@@ -3,0 +4,2 @@ def a():
+    first = 1
+    second = 2
@@ -10 +12 @@ def b():
-    old = 1
+    new = 1
diff --git a/app/gone.py b/app/gone.py
--- a/app/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-x = 1
-y = 2
"""

PLAN = """# Plan: CSV export

## Slice 1: backend export
Goal: build the export.
Files:
- `services/evermore/app/entities/export.py` (new)
- services/evermore/app/entities/router.py
Verify: pytest

## Slice 2: frontend
Files:
- `frontend/src/views/entities/*.vue`
- frontend/src/requests/

## Risks
- `not/a/file.py`
"""

TEST_PLAN = """| Test name | What it checks | Expected result | File |
|---|---|---|---|
| `test_export_entities_returns_csv` | Export of two entities | CSV with a header and two rows | `services/evermore/tests/entities/test_export.py` |
| `test_export_entities_empty_returns_header` | Export with no entities | Only the header row | `services/evermore/tests/entities/test_export.py` |
"""


def test_parse_hunks_reads_added_lines_and_deleted_files():
    hunks = parse_hunks(DIFF_OUTPUT)

    assert [(hunk.path, list(hunk.added_lines)) for hunk in hunks] == [
        ("app/entities.py", [4, 5]),
        ("app/entities.py", [12]),
        ("app/gone.py", []),
    ]
    assert hunks[0].added_texts == ("    first = 1", "    second = 2")


def test_parse_plan_slices_reads_files_of_each_slice():
    slices = parse_plan_slices(PLAN)

    assert slices == {
        1: [
            "services/evermore/app/entities/export.py",
            "services/evermore/app/entities/router.py",
        ],
        2: [
            "frontend/src/views/entities/*.vue",
            "frontend/src/requests/",
        ],
    }


def test_parse_test_plan_files_reads_file_column_once():
    files = parse_test_plan_files(TEST_PLAN)

    assert files == ["services/evermore/tests/entities/test_export.py"]


def test_out_of_scope_files_allows_paths_globs_and_folders():
    changed = [
        "services/evermore/app/entities/export.py",
        "frontend/src/views/entities/EntityList.vue",
        "frontend/src/requests/entities.ts",
        "services/evermore/app/main.py",
    ]

    out_of_scope = out_of_scope_files(changed, parse_plan_slices(PLAN)[1] + parse_plan_slices(PLAN)[2])

    assert out_of_scope == ["services/evermore/app/main.py"]


def test_changed_line_filter_tracked_file_returns_only_added_lines(git_repository: Path):
    path = git_repository / "module.py"
    path.write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    git(git_repository, "add", "-A")
    git(git_repository, "commit", "--quiet", "-m", "module")
    base_commit = diff_base_commit("master", git_repository)
    path.write_text("a = 1\nb = 20\nc = 3\nd = 4\n", encoding="utf-8")

    line_filter = changed_line_filter(path, base_commit)

    assert not line_filter.whole_file
    assert sorted(line_filter.lines) == [2, 4]


def test_changed_line_filter_untracked_file_returns_whole_file(git_repository: Path):
    path = git_repository / "new.py"
    path.write_text("a = 1\n", encoding="utf-8")

    line_filter = changed_line_filter(path, "HEAD")

    assert line_filter.whole_file


def test_changed_files_and_existing_lines_on_a_branch(git_repository: Path):
    (git_repository / "module.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
    git(git_repository, "add", "-A")
    git(git_repository, "commit", "--quiet", "-m", "module")
    git(git_repository, "checkout", "--quiet", "-b", "BTRC-1-feature")
    (git_repository / "module.py").write_text("a = 10\nb = 2\nc = 3\n", encoding="utf-8")
    (git_repository / "new.py").write_text("x = 1\n", encoding="utf-8")
    base_commit = diff_base_commit("master", git_repository)

    files = changed_files(base_commit, git_repository)
    existing = changed_existing_lines(base_commit, git_repository)

    assert files == ["module.py", "new.py"]
    assert existing == ["module.py:1 (replaces 1 existing line(s))"]
