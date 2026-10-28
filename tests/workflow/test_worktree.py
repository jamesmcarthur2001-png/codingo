from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

import worktree
from conftest import git
from feature_state import FeatureState
from guard_branch import find_branch_changes

BRANCH = "BTRC-1234-csv-export"
WORKTREE = f".claude/worktrees/{BRANCH}"


@dataclass(frozen=True)
class Repository:
    """
    A main checkout with a bare origin, and the feature's state.
    """
    remote: Path
    root: Path
    feature_directory: Path

    def state(self) -> FeatureState:
        return FeatureState.load(self.feature_directory / "state.md")


@pytest.fixture
def repository(tmp_path: Path, make_feature_state: Callable[..., Path], monkeypatch: pytest.MonkeyPatch) -> Repository:
    for variable in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(variable, "Test")
    for variable in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(variable, "test@example.com")
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=master", str(remote))
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "--quiet", "--initial-branch=master")
    (root / "README.md").write_text("# repo\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", "initial")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "push", "--quiet", "origin", "master")
    feature_directory = make_feature_state(root, phase="SETUP", approved="no")
    monkeypatch.chdir(root)
    return Repository(remote, root, feature_directory)


def run_main(monkeypatch: pytest.MonkeyPatch, *arguments: str) -> int:
    monkeypatch.setattr("sys.argv", ["worktree.py", *arguments])
    return worktree.main()


def test_create_adds_the_worktree_from_origin_base_and_records_it(repository: Repository, monkeypatch: pytest.MonkeyPatch):
    exit_code = run_main(monkeypatch, "create", "BTRC-1234")

    state = repository.state()
    exclude_text = (repository.root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert exit_code == 0
    assert (repository.root / WORKTREE / "README.md").is_file()
    assert git(repository.root / WORKTREE, "branch", "--show-current").strip() == BRANCH
    assert state.field("Worktree") == WORKTREE
    assert state.field("Worktree mode") == "worktree"
    assert ".claude/worktrees/" in exclude_text
    assert "docs/features/" in exclude_text


def test_create_twice_only_records_the_existing_worktree(repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    run_main(monkeypatch, "create", "BTRC-1234")

    exit_code = run_main(monkeypatch, "create", "BTRC-1234")

    exclude_lines = (repository.root / ".git" / "info" / "exclude").read_text(encoding="utf-8").splitlines()
    assert exit_code == 0
    assert "already exists" in capsys.readouterr().out
    assert exclude_lines.count(".claude/worktrees/") == 1


def test_create_reuses_an_existing_local_branch(repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    git(repository.root, "branch", BRANCH)

    exit_code = run_main(monkeypatch, "create", "BTRC-1234")

    assert exit_code == 0
    assert "Reused branch" in capsys.readouterr().out
    assert git(repository.root / WORKTREE, "branch", "--show-current").strip() == BRANCH


def test_create_reuses_a_branch_that_only_exists_on_origin(repository: Repository, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    colleague = tmp_path / "colleague"
    git(tmp_path, "clone", "--quiet", str(repository.remote), "colleague")
    git(colleague, "checkout", "--quiet", "-b", BRANCH)
    (colleague / "started.py").write_text("x = 1\n", encoding="utf-8")
    git(colleague, "add", "-A")
    git(colleague, "commit", "--quiet", "-m", "started elsewhere")
    git(colleague, "push", "--quiet", "origin", BRANCH)

    exit_code = run_main(monkeypatch, "create", "BTRC-1234")

    assert exit_code == 0
    assert (repository.root / WORKTREE / "started.py").is_file()


def test_create_refuses_a_second_branch_for_the_same_ticket(repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    git(repository.root, "branch", "BTRC-1234-first-try")

    exit_code = run_main(monkeypatch, "create", "BTRC-1234")

    assert exit_code == 2
    assert "BTRC-1234-first-try" in capsys.readouterr().out
    assert not (repository.root / WORKTREE).exists()


def test_create_without_worktree_switches_the_main_checkout(repository: Repository, monkeypatch: pytest.MonkeyPatch):
    exit_code = run_main(monkeypatch, "create", "BTRC-1234", "--no-worktree")

    state = repository.state()
    assert exit_code == 0
    assert git(repository.root, "branch", "--show-current").strip() == BRANCH
    assert state.field("Worktree") == ""
    assert state.field("Worktree mode") == "none"
    assert not (repository.root / ".claude" / "worktrees").exists()


def test_create_without_worktree_reuses_the_branch(repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    git(repository.root, "branch", BRANCH)

    exit_code = run_main(monkeypatch, "create", "BTRC-1234", "--no-worktree")

    assert exit_code == 0
    assert "existing branch" in capsys.readouterr().out
    assert git(repository.root, "branch", "--show-current").strip() == BRANCH


def test_remove_deletes_the_worktree_and_keeps_the_branch(repository: Repository, monkeypatch: pytest.MonkeyPatch):
    run_main(monkeypatch, "create", "BTRC-1234")

    exit_code = run_main(monkeypatch, "remove", "BTRC-1234")

    assert exit_code == 0
    assert not (repository.root / WORKTREE).exists()
    assert git(repository.root, "branch", "--list", BRANCH).strip() != ""


def test_remove_in_no_worktree_mode_does_nothing(repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    run_main(monkeypatch, "create", "BTRC-1234", "--no-worktree")

    exit_code = run_main(monkeypatch, "remove", "BTRC-1234")

    assert exit_code == 0
    assert "No worktree to remove" in capsys.readouterr().out


def test_create_with_branch_equal_to_base_is_a_setup_error(repository: Repository, monkeypatch: pytest.MonkeyPatch):
    state = repository.state()
    state.set_field("Branch", "master")
    state.save()

    exit_code = run_main(monkeypatch, "create", "BTRC-1234")

    assert exit_code == 2


def test_guard_branch_lets_the_script_call_through():
    changes = find_branch_changes('python3 "$HOME/.claude/midnight-workflow/scripts/worktree.py" create BTRC-1234 --no-worktree')

    assert changes == []
