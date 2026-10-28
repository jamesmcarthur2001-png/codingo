from collections.abc import Callable
from pathlib import Path

from conftest import git

COMPLIANT_SOURCE = '"""\nEntities.\n\n:author: midnight-workflow\n:date: 16/10/2026\n"""\n# ----- Imports ----- #\n\nimport os\n'
VIOLATING_SOURCE = COMPLIANT_SOURCE + "\n# ----- Functions ----- #\n\n\ndef save_entity(entity) -> None:\n    print(os.sep, entity)\n"


def test_post_edit_checks_compliant_python_file_allows(write_python_file: Callable[..., Path], run_hook: Callable[..., object]):
    path = write_python_file(COMPLIANT_SOURCE)

    completed = run_hook("post_edit_checks.py", {"tool_name": "Write", "tool_input": {"file_path": str(path)}})

    assert completed.returncode == 0


def test_post_edit_checks_violating_python_file_blocks_with_rule_ids(
    write_python_file: Callable[..., Path],
    run_hook: Callable[..., object],
):
    path = write_python_file(VIOLATING_SOURCE)

    completed = run_hook("post_edit_checks.py", {"tool_name": "Edit", "tool_input": {"file_path": str(path)}})

    assert completed.returncode == 2
    assert "PY-01" in completed.stderr
    assert "PY-02" in completed.stderr


def test_post_edit_checks_non_code_file_allows(tmp_path: Path, run_hook: Callable[..., object]):
    path = tmp_path / "notes.md"
    path.write_text("# Notes\n", encoding="utf-8")

    completed = run_hook("post_edit_checks.py", {"tool_name": "Write", "tool_input": {"file_path": str(path)}})

    assert completed.returncode == 0


def test_post_edit_checks_missing_file_path_allows(run_hook: Callable[..., object]):
    completed = run_hook("post_edit_checks.py", {"tool_name": "Write", "tool_input": {}})

    assert completed.returncode == 0


LEGACY_SOURCE = COMPLIANT_SOURCE + "\n# ----- Functions ----- #\n\n\ndef save_entity(entity) -> None:\n    print(os.sep, entity)\n"


def commit_file(repository: Path, relative_path: str, source: str) -> Path:
    path = repository / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    git(repository, "add", "-A")
    git(repository, "commit", "--quiet", "-m", f"add {relative_path}")
    return path


def test_post_edit_checks_legacy_violations_on_unchanged_lines_allows(git_repository: Path, run_hook: Callable[..., object]):
    path = commit_file(git_repository, "app/entities.py", LEGACY_SOURCE)
    path.write_text(LEGACY_SOURCE + "\n\ndef count_entities(entities: list[str]) -> int:\n    return len(entities)\n", encoding="utf-8")

    completed = run_hook("post_edit_checks.py", {"tool_name": "Edit", "cwd": str(git_repository), "tool_input": {"file_path": str(path)}})

    assert completed.returncode == 0


def test_post_edit_checks_violation_on_changed_line_blocks_with_only_that_line(git_repository: Path, run_hook: Callable[..., object]):
    path = commit_file(git_repository, "app/entities.py", LEGACY_SOURCE)
    path.write_text(LEGACY_SOURCE + "\n\ndef get_entity_names(entities):\n    return entities\n", encoding="utf-8")

    completed = run_hook("post_edit_checks.py", {"tool_name": "Edit", "cwd": str(git_repository), "tool_input": {"file_path": str(path)}})

    assert completed.returncode == 2
    assert "PY-62" in completed.stderr
    assert "PY-01" in completed.stderr
    assert "PY-02" not in completed.stderr


def test_post_edit_checks_untracked_file_checks_whole_file(git_repository: Path, run_hook: Callable[..., object]):
    path = git_repository / "app" / "new_module.py"
    path.parent.mkdir(parents=True)
    path.write_text(LEGACY_SOURCE, encoding="utf-8")

    completed = run_hook("post_edit_checks.py", {"tool_name": "Write", "cwd": str(git_repository), "tool_input": {"file_path": str(path)}})

    assert completed.returncode == 2
    assert "PY-02" in completed.stderr


def test_post_edit_checks_suppression_on_changed_line_blocks(git_repository: Path, run_hook: Callable[..., object]):
    path = commit_file(git_repository, "app/entities.py", COMPLIANT_SOURCE)
    path.write_text(COMPLIANT_SOURCE + "import sys  # noqa: F401\n", encoding="utf-8")

    completed = run_hook("post_edit_checks.py", {"tool_name": "Edit", "cwd": str(git_repository), "tool_input": {"file_path": str(path)}})

    assert completed.returncode == 2
    assert "SUPPRESSION" in completed.stderr


def test_post_edit_checks_reviewer_role_allows(write_python_file: Callable[..., Path], run_hook: Callable[..., object]):
    path = write_python_file(VIOLATING_SOURCE)

    completed = run_hook(
        "post_edit_checks.py",
        {"tool_name": "Edit", "tool_input": {"file_path": str(path)}},
        {"MIDNIGHT_ROLE": "reviewer"},
    )

    assert completed.returncode == 0
