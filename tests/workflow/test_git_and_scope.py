from pathlib import Path

import pytest

from conftest import git
from git_changes import GitError, branch_line_filters, changed_existing_lines, changed_files, changed_line_filter, diff_base_commit, parse_hunks
from scope_check import matches_allowed, out_of_scope_files, parse_plan_slices, parse_test_plan_files

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


def test_parse_hunks_path_with_space_drops_the_trailing_tab():
    diff_output = "diff --git a/app/my file.py b/app/my file.py\n--- a/app/my file.py\t\n+++ b/app/my file.py\t\n@@ -1,0 +2 @@\n+x = 1\n"

    hunks = parse_hunks(diff_output)

    assert [hunk.path for hunk in hunks] == ["app/my file.py"]


def test_parse_hunks_quoted_path_is_unquoted():
    diff_output = 'diff --git "a/app/caf\\303\\251.py" "b/app/caf\\303\\251.py"\n--- "a/app/caf\\303\\251.py"\n+++ "b/app/caf\\303\\251.py"\n@@ -1,0 +2 @@\n+x = 1\n'

    hunks = parse_hunks(diff_output)

    assert [hunk.path for hunk in hunks] == ["app/café.py"]


def test_parse_hunks_removed_line_that_looks_like_a_header_is_ignored():
    diff_output = "diff --git a/notes.md b/notes.md\n--- a/notes.md\n+++ b/notes.md\n@@ -3 +3 @@\n--- old rule\n++++ new rule\n"

    hunks = parse_hunks(diff_output)

    assert [hunk.path for hunk in hunks] == ["notes.md"]
    assert hunks[0].added_texts == ("+++ new rule",)


def test_changed_files_ignore_diff_prefix_settings_and_list_deletions(git_repository: Path):
    (git_repository / "old.py").write_text("a = 1\n", encoding="utf-8")
    git(git_repository, "add", "-A")
    git(git_repository, "commit", "--quiet", "-m", "old")
    base_commit = diff_base_commit("master", git_repository)
    git(git_repository, "config", "diff.noprefix", "true")
    git(git_repository, "config", "diff.mnemonicPrefix", "true")
    (git_repository / "old.py").unlink()
    (git_repository / "README.md").write_text("# changed\n", encoding="utf-8")

    files = changed_files(base_commit, git_repository)
    filters = branch_line_filters(base_commit, git_repository)

    assert files == ["README.md", "old.py"]
    assert sorted(filters["README.md"].lines) == [1]


def test_diff_base_commit_uses_the_newer_of_local_and_origin_base(git_repository: Path):
    old_master = git(git_repository, "rev-parse", "HEAD").strip()
    (git_repository / "later.py").write_text("a = 1\n", encoding="utf-8")
    git(git_repository, "add", "-A")
    git(git_repository, "commit", "--quiet", "-m", "later on master")
    newer = git(git_repository, "rev-parse", "HEAD").strip()
    git(git_repository, "update-ref", "refs/remotes/origin/master", newer)
    git(git_repository, "checkout", "--quiet", "-b", "BTRC-1-feature")
    git(git_repository, "branch", "--force", "master", old_master)

    base_commit = diff_base_commit("master", git_repository)

    assert base_commit == newer


def test_diff_base_commit_unknown_base_raises_git_error(git_repository: Path):
    with pytest.raises(GitError, match="no-such-branch"):
        diff_base_commit("no-such-branch", git_repository)


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("frontend/src/views/EntityList.vue", "frontend/src/views/*.vue", True),
        ("frontend/src/views/entities/EntityList.vue", "frontend/src/views/*.vue", False),
        ("frontend/src/views/entities/EntityList.vue", "frontend/src/views/**/*.vue", True),
        ("frontend/src/views/EntityList.vue", "frontend/src/views/**/*.vue", True),
        ("frontend/src/requests/a/b.ts", "frontend/src/requests/", True),
        ("services/evermore/app/x.py", "services/evermore/app/x.py", True),
    ],
)
def test_matches_allowed_star_stays_in_one_folder(path: str, pattern: str, expected: bool):
    assert matches_allowed(path, [pattern]) is expected
