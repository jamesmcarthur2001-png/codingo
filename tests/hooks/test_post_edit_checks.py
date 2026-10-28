from collections.abc import Callable
from pathlib import Path

import pytest

from conftest import git

COMPLIANT_SOURCE = '"""\nEntities.\n\n:author: midnight-workflow\n:date: 16/10/2026\n"""\n# ----- Imports ----- #\n\nimport os\n'
VIOLATING_SOURCE = COMPLIANT_SOURCE + "\n# ----- Functions ----- #\n\n\ndef save_entity(entity) -> None:\n    print(os.sep, entity)\n"
LEGACY_SOURCE = VIOLATING_SOURCE
LEGACY_CALL_SOURCE = COMPLIANT_SOURCE + "\n# ----- Functions ----- #\n\n\ndef build_entity(name: str) -> dict[str, str]:\n    return dict(name=name, kind='entity', owner='nobody', status='active')\n"


@pytest.fixture
def feature_repository(git_repository: Path, make_feature_state: Callable[..., Path]) -> Path:
    (git_repository / ".git" / "info" / "exclude").write_text("docs/features/\n", encoding="utf-8")
    make_feature_state(git_repository, phase="BUILD")
    return git_repository


def commit_file(repository: Path, relative_path: str, source: str) -> Path:
    path = repository / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    git(repository, "add", "-A")
    git(repository, "commit", "--quiet", "-m", f"add {relative_path}")
    return path


def edit_payload(repository: Path, path: Path) -> dict[str, object]:
    return {"tool_name": "Edit", "cwd": str(repository), "tool_input": {"file_path": str(path)}}


def test_post_edit_checks_without_running_feature_allows(write_python_file: Callable[..., Path], run_hook: Callable[..., object]):
    path = write_python_file(VIOLATING_SOURCE)

    completed = run_hook("post_edit_checks.py", {"tool_name": "Edit", "tool_input": {"file_path": str(path)}})

    assert completed.returncode == 0


def test_post_edit_checks_forced_without_feature_blocks_with_rule_ids(
    write_python_file: Callable[..., Path],
    run_hook: Callable[..., object],
):
    path = write_python_file(VIOLATING_SOURCE)

    completed = run_hook(
        "post_edit_checks.py",
        {"tool_name": "Edit", "tool_input": {"file_path": str(path)}},
        {"MIDNIGHT_CHECKS": "1"},
    )

    assert completed.returncode == 2
    assert "PY-01" in completed.stderr
    assert "PY-02" in completed.stderr


def test_post_edit_checks_forced_compliant_file_allows(write_python_file: Callable[..., Path], run_hook: Callable[..., object]):
    path = write_python_file(COMPLIANT_SOURCE)

    completed = run_hook(
        "post_edit_checks.py",
        {"tool_name": "Write", "tool_input": {"file_path": str(path)}},
        {"MIDNIGHT_CHECKS": "1"},
    )

    assert completed.returncode == 0


def test_post_edit_checks_non_code_file_allows(feature_repository: Path, run_hook: Callable[..., object]):
    path = feature_repository / "notes.md"
    path.write_text("# Notes\n", encoding="utf-8")

    completed = run_hook("post_edit_checks.py", edit_payload(feature_repository, path))

    assert completed.returncode == 0


def test_post_edit_checks_missing_file_path_allows(run_hook: Callable[..., object]):
    completed = run_hook("post_edit_checks.py", {"tool_name": "Write", "tool_input": {}})

    assert completed.returncode == 0


def test_post_edit_checks_legacy_violations_on_unchanged_lines_allows(feature_repository: Path, run_hook: Callable[..., object]):
    path = commit_file(feature_repository, "app/entities.py", LEGACY_SOURCE)
    path.write_text(LEGACY_SOURCE + "\n\ndef count_entities(entities: list[str]) -> int:\n    return len(entities)\n", encoding="utf-8")

    completed = run_hook("post_edit_checks.py", edit_payload(feature_repository, path))

    assert completed.returncode == 0


def test_post_edit_checks_violation_on_changed_line_blocks_with_only_that_line(feature_repository: Path, run_hook: Callable[..., object]):
    path = commit_file(feature_repository, "app/entities.py", LEGACY_SOURCE)
    path.write_text(LEGACY_SOURCE + "\n\ndef get_entity_names(entities):\n    return entities\n", encoding="utf-8")

    completed = run_hook("post_edit_checks.py", edit_payload(feature_repository, path))

    assert completed.returncode == 2
    assert "PY-62" in completed.stderr
    assert "PY-01" in completed.stderr
    assert "PY-02" not in completed.stderr


def test_post_edit_checks_existing_get_function_with_changed_def_line_allows(feature_repository: Path, run_hook: Callable[..., object]):
    source = COMPLIANT_SOURCE + "\n# ----- Functions ----- #\n\n\ndef get_entity(entity_id: int) -> int:\n    return entity_id\n"
    path = commit_file(feature_repository, "app/entities.py", source)
    path.write_text(source.replace("def get_entity(entity_id: int)", "def get_entity(entity_id: int, deleted: bool)"), encoding="utf-8")

    completed = run_hook("post_edit_checks.py", edit_payload(feature_repository, path))

    assert "PY-62" not in completed.stderr


def test_post_edit_checks_change_inside_existing_call_reports_the_call(feature_repository: Path, run_hook: Callable[..., object]):
    path = commit_file(feature_repository, "app/entities.py", LEGACY_CALL_SOURCE)
    exploded = LEGACY_CALL_SOURCE.replace(
        "dict(name=name, kind='entity', owner='nobody', status='active')",
        "dict(name=name, kind='entity',\n        owner='somebody', status='active')",
    )
    path.write_text(exploded, encoding="utf-8")

    completed = run_hook("post_edit_checks.py", edit_payload(feature_repository, path))

    assert completed.returncode == 2
    assert "PY-24" in completed.stderr


def test_post_edit_checks_untracked_file_checks_whole_file(feature_repository: Path, run_hook: Callable[..., object]):
    path = feature_repository / "app" / "new_module.py"
    path.parent.mkdir(parents=True)
    path.write_text(LEGACY_SOURCE, encoding="utf-8")

    completed = run_hook("post_edit_checks.py", edit_payload(feature_repository, path))

    assert completed.returncode == 2
    assert "PY-02" in completed.stderr


def test_post_edit_checks_path_with_space_checks_changed_lines(feature_repository: Path, run_hook: Callable[..., object]):
    path = commit_file(feature_repository, "app/my entities.py", LEGACY_SOURCE)
    path.write_text(LEGACY_SOURCE + "\n\ndef get_entity_names(entities):\n    return entities\n", encoding="utf-8")

    completed = run_hook("post_edit_checks.py", edit_payload(feature_repository, path))

    assert completed.returncode == 2
    assert "PY-62" in completed.stderr
    assert "PY-02" not in completed.stderr


@pytest.mark.parametrize(
    "suppression",
    [
        "import sys  # noqa: F401",
        "# ruff: noqa",
        "# mypy: ignore-errors",
        "value = 1  # pragma: no cover",
    ],
)
def test_post_edit_checks_suppression_on_changed_line_blocks(
    feature_repository: Path,
    run_hook: Callable[..., object],
    suppression: str,
):
    path = commit_file(feature_repository, "app/entities.py", COMPLIANT_SOURCE)
    path.write_text(COMPLIANT_SOURCE + suppression + "\n", encoding="utf-8")

    completed = run_hook("post_edit_checks.py", edit_payload(feature_repository, path))

    assert completed.returncode == 2
    assert "SUPPRESSION" in completed.stderr


def test_post_edit_checks_suppression_in_tool_config_blocks(feature_repository: Path, run_hook: Callable[..., object]):
    path = commit_file(feature_repository, "pyproject.toml", "[tool.ruff]\nline-length = 120\n")
    path.write_text("[tool.ruff]\nline-length = 120\n[tool.ruff.lint.per-file-ignores]\n\"app/x.py\" = [\"E501\"]\n", encoding="utf-8")

    completed = run_hook("post_edit_checks.py", edit_payload(feature_repository, path))

    assert completed.returncode == 2
    assert "per-file-ignores" in completed.stderr


def test_post_edit_checks_unknown_base_reports_one_setup_problem(feature_repository: Path, run_hook: Callable[..., object]):
    state_path = feature_repository / "docs" / "features" / "BTRC-1234" / "state.md"
    state_path.write_text(state_path.read_text(encoding="utf-8").replace("Base: master", "Base: no-such-branch"), encoding="utf-8")
    path = commit_file(feature_repository, "app/entities.py", COMPLIANT_SOURCE)

    completed = run_hook("post_edit_checks.py", edit_payload(feature_repository, path))

    assert completed.returncode == 2
    assert "no-such-branch" in completed.stderr


def test_post_edit_checks_reviewer_role_allows(feature_repository: Path, run_hook: Callable[..., object]):
    path = feature_repository / "app" / "new_module.py"
    path.parent.mkdir(parents=True)
    path.write_text(VIOLATING_SOURCE, encoding="utf-8")

    completed = run_hook(
        "post_edit_checks.py",
        edit_payload(feature_repository, path),
        {"MIDNIGHT_ROLE": "reviewer"},
    )

    assert completed.returncode == 0
