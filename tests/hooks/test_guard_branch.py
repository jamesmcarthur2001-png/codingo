from collections.abc import Callable
from pathlib import Path

import pytest

from conftest import git
from guard_branch import find_branch_changes


@pytest.mark.parametrize(
    ("command", "expected_name"),
    [
        ("git checkout -b BTRC-12-new", "BTRC-12-new"),
        ("git checkout -B BTRC-12-new origin/master", "BTRC-12-new"),
        ("git switch -c BTRC-12-new", "BTRC-12-new"),
        ("git switch --create BTRC-12-new", "BTRC-12-new"),
        ("git branch BTRC-12-new", "BTRC-12-new"),
        ("git branch -m BTRC-12-new", "BTRC-12-new"),
        ("git branch -m BTRC-12-old BTRC-12-new", "BTRC-12-new"),
        ("git worktree add ../wt -b BTRC-12-new master", "BTRC-12-new"),
        ("git push origin HEAD:BTRC-12-new", "BTRC-12-new"),
        ("git push origin HEAD:refs/heads/BTRC-12-new", "BTRC-12-new"),
        ("cd repo && git -C sub checkout -b BTRC-12-new", "BTRC-12-new"),
    ],
)
def test_find_branch_changes_branch_creating_commands_return_new_name(command: str, expected_name: str):
    changes = find_branch_changes(command)

    assert [change.new_name for change in changes] == [expected_name]


@pytest.mark.parametrize(
    "command",
    [
        "git checkout master",
        "git branch -d BTRC-12-old",
        "git branch --list",
        "git branch -a",
        "git push origin BTRC-12-old",
        "git switch BTRC-12-old",
        "echo git checkout -b BTRC-12-new",
    ],
)
def test_find_branch_changes_non_creating_commands_return_nothing(command: str):
    changes = find_branch_changes(command)

    assert len(changes) == 0


def bash_payload(repository: Path, command: str) -> dict[str, object]:
    return {"tool_name": "Bash", "cwd": str(repository), "tool_input": {"command": command}}


def test_guard_branch_same_btrc_under_other_name_blocks(git_repository: Path, run_hook: Callable[..., object]):
    git(git_repository, "branch", "BTRC-12-first-try")

    completed = run_hook("guard_branch.py", bash_payload(git_repository, "git checkout -b BTRC-12-second-try"))

    assert completed.returncode == 2
    assert "refs/heads/BTRC-12-first-try" in completed.stderr


def test_guard_branch_other_btrc_number_allows(git_repository: Path, run_hook: Callable[..., object]):
    git(git_repository, "branch", "BTRC-123-other")

    completed = run_hook("guard_branch.py", bash_payload(git_repository, "git checkout -b BTRC-12-new"))

    assert completed.returncode == 0


def test_guard_branch_remote_branch_with_same_btrc_blocks(git_repository: Path, run_hook: Callable[..., object]):
    head = git(git_repository, "rev-parse", "HEAD").strip()
    git(git_repository, "update-ref", "refs/remotes/origin/BTRC-12-pushed", head)

    completed = run_hook("guard_branch.py", bash_payload(git_repository, "git switch -c BTRC-12-local"))

    assert completed.returncode == 2
    assert "refs/remotes/origin/BTRC-12-pushed" in completed.stderr


def test_guard_branch_renaming_the_only_btrc_branch_allows(git_repository: Path, run_hook: Callable[..., object]):
    git(git_repository, "checkout", "--quiet", "-b", "BTRC-12-old-name")

    completed = run_hook("guard_branch.py", bash_payload(git_repository, "git branch -m BTRC-12-new-name"))

    assert completed.returncode == 0


def test_guard_branch_name_without_btrc_allows(git_repository: Path, run_hook: Callable[..., object]):
    git(git_repository, "branch", "BTRC-12-first-try")

    completed = run_hook("guard_branch.py", bash_payload(git_repository, "git checkout -b experiment"))

    assert completed.returncode == 0


def test_guard_branch_reviewer_role_allows(git_repository: Path, run_hook: Callable[..., object]):
    git(git_repository, "branch", "BTRC-12-first-try")

    completed = run_hook(
        "guard_branch.py",
        bash_payload(git_repository, "git checkout -b BTRC-12-second-try"),
        {"MIDNIGHT_ROLE": "reviewer"},
    )

    assert completed.returncode == 0
