from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import shutil

import pytest

import worktree
from conftest import git
from feature_state import FeatureState, find_active_feature, find_running_feature, load_feature_state
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
        return load_feature_state("BTRC-1234", self.root)


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


def test_create_moves_the_feature_folder_into_the_worktree_and_leaves_nothing_in_main(repository: Repository, monkeypatch: pytest.MonkeyPatch):
    run_main(monkeypatch, "create", "BTRC-1234")

    moved = repository.root / WORKTREE / "docs" / "features" / "BTRC-1234"
    assert (moved / "state.md").is_file()
    assert not (repository.root / "docs" / "features").exists()
    assert (repository.root / WORKTREE / "docs" / "features" / ".active").read_text(encoding="utf-8") == "BTRC-1234\n"
    assert repository.state().field("Repository") == repository.root.resolve().as_posix()
    assert repository.state().code_root().resolve() == (repository.root / WORKTREE).resolve()


def test_active_feature_is_found_from_the_worktree_and_from_the_main_checkout(repository: Repository, monkeypatch: pytest.MonkeyPatch):
    run_main(monkeypatch, "create", "BTRC-1234")
    moved = (repository.root / WORKTREE / "docs" / "features" / "BTRC-1234").resolve()
    subfolder = repository.root / WORKTREE / "services"
    subfolder.mkdir()

    from_worktree = find_active_feature(subfolder)
    from_main = find_active_feature(repository.root)

    assert from_worktree is not None and from_worktree.resolve() == moved
    assert from_main is not None and from_main.resolve() == moved


def test_active_feature_is_found_through_the_main_checkout_when_the_worktree_has_no_docs(repository: Repository, monkeypatch: pytest.MonkeyPatch):
    state = repository.state()
    state.set_field("Approved", "yes")
    state.save()
    run_main(monkeypatch, "create", "BTRC-1234", "--no-worktree")
    other_worktree = repository.root / ".claude" / "worktrees" / "scratch"
    git(repository.root, "worktree", "add", "--quiet", "--detach", str(other_worktree), "master")

    running = find_running_feature(other_worktree)

    assert running is not None
    assert running.field("Ticket") == "BTRC-1234"


def test_create_copies_the_files_worktreeinclude_lists(repository: Repository, monkeypatch: pytest.MonkeyPatch):
    (repository.root / ".gitignore").write_text(".env\nlocal.cfg\n", encoding="utf-8")
    git(repository.root, "add", ".gitignore")
    git(repository.root, "commit", "--quiet", "-m", "ignore env")
    git(repository.root, "push", "--quiet", "origin", "master")
    (repository.root / ".worktreeinclude").write_text(".env\n", encoding="utf-8")
    (repository.root / ".env").write_text("DATABASE_URL=postgres://localhost/test\n", encoding="utf-8")
    (repository.root / "local.cfg").write_text("not listed\n", encoding="utf-8")

    exit_code = run_main(monkeypatch, "create", "BTRC-1234")

    assert exit_code == 0
    assert (repository.root / WORKTREE / ".env").read_text(encoding="utf-8") == "DATABASE_URL=postgres://localhost/test\n"
    assert not (repository.root / WORKTREE / "local.cfg").exists()


def remove_main_feature(repository: Repository):
    shutil.rmtree(repository.root / "docs")


def test_create_new_feature_writes_state_only_in_the_worktree(repository: Repository, monkeypatch: pytest.MonkeyPatch):
    remove_main_feature(repository)

    exit_code = run_main(monkeypatch, "create", "BTRC-1234", "--branch", BRANCH, "--base", "master", "--title", "CSV export")

    state = repository.state()
    assert exit_code == 0
    assert state.feature_directory == repository.root / WORKTREE / "docs" / "features" / "BTRC-1234"
    assert state.field("Title") == "CSV export"
    assert state.field("Worktree") == WORKTREE
    assert state.field("Repository") == repository.root.resolve().as_posix()
    assert not (repository.root / "docs").exists()


def test_create_new_feature_without_branch_is_a_setup_error(repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    remove_main_feature(repository)

    exit_code = run_main(monkeypatch, "create", "BTRC-1234")

    assert exit_code == 2
    assert "--branch and --base" in capsys.readouterr().out
    assert not (repository.root / WORKTREE).exists()


def test_create_new_feature_without_worktree_writes_in_the_main_checkout(repository: Repository, monkeypatch: pytest.MonkeyPatch):
    remove_main_feature(repository)

    exit_code = run_main(monkeypatch, "create", "BTRC-1234", "--branch", BRANCH, "--base", "master", "--no-worktree")

    assert exit_code == 0
    assert (repository.root / "docs" / "features" / "BTRC-1234" / "state.md").is_file()
    assert git(repository.root, "branch", "--show-current").strip() == BRANCH


def test_two_worktree_features_each_find_their_own_folder(repository: Repository, monkeypatch: pytest.MonkeyPatch):
    remove_main_feature(repository)
    other_branch = "BTRC-77-other"
    run_main(monkeypatch, "create", "BTRC-1234", "--branch", BRANCH, "--base", "master")
    run_main(monkeypatch, "create", "BTRC-77", "--branch", other_branch, "--base", "master")
    other = load_feature_state("BTRC-77", repository.root)
    other.set_field("Session", "session-77")
    other.save()

    from_first = find_active_feature(repository.root / WORKTREE)
    from_second = find_active_feature(repository.root / ".claude" / "worktrees" / other_branch)
    from_main_for_second = find_active_feature(repository.root, "session-77")
    from_main_unknown = find_active_feature(repository.root)

    assert from_first == repository.root / WORKTREE / "docs" / "features" / "BTRC-1234"
    assert from_second == repository.root / ".claude" / "worktrees" / other_branch / "docs" / "features" / "BTRC-77"
    assert from_main_for_second == from_second
    assert from_main_unknown is None
    assert not (repository.root / "docs").exists()
