import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

import finish_branch
from conftest import FakeCommands, failed, git, ok
from feature_state import FeatureState, load_feature_state
from finish_branch import failed_job_name, parse_pipeline_state
from worktree import bring_feature_home, create_worktree

HEAD = "abc1234def5678"
PIPELINE_PASSED = "(success) build\nPipeline state: success\n"
PIPELINE_RUNNING = "(running) build\nPipeline state: running\n"
PIPELINE_FAILED = "(failed) • 01m 02s\ttest\tunit tests\nPipeline state: failed\n"
BRANCH = "BTRC-1234-csv-export"
TWO_FILE_BASE = {"a.py": "a = 1\n", "b.py": "b = 1\n"}


@dataclass(frozen=True)
class FinishSetup:
    """
    A bare remote, the main checkout, the feature's worktree inside it, and its state.
    """
    remote: Path
    repository: Path
    worktree: Path
    feature_directory: Path


def commit_files(repository: Path, files: dict[str, str], message: str):
    for relative_path, content in files.items():
        (repository / relative_path).write_text(content, encoding="utf-8")
    git(repository, "add", "-A")
    git(repository, "commit", "--quiet", "-m", message)


def colleague_clone(setup: FinishSetup, name: str) -> Path:
    clone = setup.remote.parent / name
    git(setup.remote.parent, "clone", "--quiet", str(setup.remote), name)
    return clone


@pytest.fixture
def finish_setup(tmp_path: Path, make_feature_state: Callable[..., Path], monkeypatch: pytest.MonkeyPatch) -> FinishSetup:
    for variable in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(variable, "Test")
    for variable in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(variable, "test@example.com")
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=master", str(remote))
    repository = tmp_path / "repo"
    repository.mkdir()
    git(repository, "init", "--quiet", "--initial-branch=master")
    git(repository, "config", "core.autocrlf", "false")
    commit_files(repository, {"README.md": "# repo\n", **TWO_FILE_BASE}, "initial")
    git(repository, "remote", "add", "origin", str(remote))
    git(repository, "push", "--quiet", "origin", "master")
    feature_directory = make_feature_state(repository, phase="FINISH")
    state = FeatureState.load(feature_directory / "state.md")
    state.set_field("Compose files", "docker-compose.yml")
    state.save()
    create_worktree(state)
    worktree = repository / ".claude" / "worktrees" / BRANCH
    feature_directory = worktree / "docs" / "features" / "BTRC-1234"
    (feature_directory / "spec.md").write_text("# Spec: CSV export for entities\n", encoding="utf-8")
    (worktree / "export.py").write_text("rows = []\n", encoding="utf-8")
    monkeypatch.chdir(worktree)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    return FinishSetup(remote, repository, worktree, feature_directory)


def install_tools(fake_commands: Callable[[bool], FakeCommands], *pipeline_outputs: str) -> FakeCommands:
    commands = fake_commands(True)
    outputs = pipeline_outputs if len(pipeline_outputs) > 0 else (PIPELINE_PASSED,)
    commands.respond("glab ci status", *[ok(output) for output in outputs])
    return commands


def run_finish(monkeypatch: pytest.MonkeyPatch, *extra_arguments: str) -> int:
    monkeypatch.setattr("sys.argv", ["finish_branch.py", "BTRC-1234", *extra_arguments])
    return finish_branch.main()


def run_cleanup(monkeypatch: pytest.MonkeyPatch, setup: FinishSetup) -> int:
    monkeypatch.chdir(setup.repository)
    return run_finish(monkeypatch, "--cleanup")


def state_of(setup: FinishSetup) -> FeatureState:
    return load_feature_state("BTRC-1234", setup.repository)


def remote_log(setup: FinishSetup, reference: str) -> str:
    return git(setup.remote, "log", "--format=%s", reference)


def test_finish_branch_happy_path_pushes_cleans_up_and_updates_the_base(
    finish_setup: FinishSetup,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = install_tools(fake_commands, PIPELINE_RUNNING, PIPELINE_PASSED)
    colleague = colleague_clone(finish_setup, "colleague")
    commit_files(colleague, {"other.py": "x = 1\n"}, "colleague work on master")
    git(colleague, "push", "--quiet", "origin", "master")

    part_a_exit = run_finish(monkeypatch)
    after_part_a = state_of(finish_setup)
    worktree_kept_after_part_a = finish_setup.worktree.exists()
    cleanup_exit = run_cleanup(monkeypatch, finish_setup)

    state = state_of(finish_setup)
    assert part_a_exit == 0
    assert after_part_a.field("Phase") == "FINISH"
    assert after_part_a.field("Finish stage") == "cleanup"
    assert worktree_kept_after_part_a
    assert cleanup_exit == 0
    assert "BTRC-1234: CSV export for entities" in remote_log(finish_setup, BRANCH)
    assert "colleague work on master" in remote_log(finish_setup, BRANCH)
    assert state.field("Pushed") == git(finish_setup.remote, "rev-parse", BRANCH).strip()
    assert state.field("Phase") == "SUMMARY"
    assert state.feature_directory == finish_setup.repository / "docs" / "features" / "BTRC-1234"
    assert (state.feature_directory / "spec.md").is_file()
    assert not (state.feature_directory / ".running.json").exists()
    assert not finish_setup.worktree.exists()
    assert "docker compose -p btrc-1234 -f docker-compose.yml down --remove-orphans" in commands.commands()
    assert (finish_setup.repository / "other.py").is_file()


def test_finish_branch_cleanup_from_inside_the_worktree_is_refused(
    finish_setup: FinishSetup,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
    capsys: pytest.CaptureFixture[str],
):
    install_tools(fake_commands)
    run_finish(monkeypatch)

    exit_code = run_finish(monkeypatch, "--cleanup")

    assert exit_code == 2
    assert "Call ExitWorktree first" in capsys.readouterr().out
    assert finish_setup.worktree.exists()


def test_finish_branch_cleanup_before_part_a_is_refused(
    finish_setup: FinishSetup,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    install_tools(fake_commands)

    exit_code = run_cleanup(monkeypatch, finish_setup)

    assert exit_code == 2
    assert finish_setup.worktree.exists()


def test_finish_branch_conflict_with_one_file_left_unresolved_never_commits_markers(
    finish_setup: FinishSetup,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
    capsys: pytest.CaptureFixture[str],
):
    install_tools(fake_commands)
    commit_files(finish_setup.worktree, {"a.py": "a = 'mine'\n", "b.py": "b = 'mine'\n"}, "feature edits")
    colleague = colleague_clone(finish_setup, "colleague")
    commit_files(colleague, {"a.py": "a = 'theirs'\n", "b.py": "b = 'theirs'\n"}, "colleague edits")
    git(colleague, "push", "--quiet", "origin", "master")

    first_exit = run_finish(monkeypatch)
    first_output = capsys.readouterr().out
    (finish_setup.worktree / "a.py").write_text("a = 'merged'\n", encoding="utf-8")
    git(finish_setup.worktree, "add", "a.py", "b.py")
    second_exit = run_finish(monkeypatch)
    second_output = capsys.readouterr().out
    (finish_setup.worktree / "b.py").write_text("b = 'merged'\n", encoding="utf-8")
    third_exit = run_finish(monkeypatch)

    assert first_exit == 10
    assert "- a.py" in first_output and "- b.py" in first_output
    assert second_exit == 10
    assert "- b.py" in second_output and "- a.py" not in second_output
    assert third_exit == 0
    pushed_b = git(finish_setup.remote, "show", f"{BRANCH}:b.py")
    assert "<<<<<<<" not in pushed_b
    assert pushed_b == "b = 'merged'\n"


def test_finish_branch_colleague_push_after_ours_is_never_overwritten(
    finish_setup: FinishSetup,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = install_tools(fake_commands, "(failed) • 00m 10s\ttest\tunit tests\nPipeline state: failed\n")
    first_exit = run_finish(monkeypatch)
    colleague = colleague_clone(finish_setup, "colleague")
    git(colleague, "checkout", "--quiet", BRANCH)
    commit_files(colleague, {"colleague.py": "c = 1\n"}, "colleague commit on the feature branch")
    git(colleague, "push", "--quiet", "origin", BRANCH)
    commands.responses.insert(0, ("glab ci status", [ok(PIPELINE_PASSED)]))
    (finish_setup.worktree / "export.py").write_text("rows: list[str] = []\n", encoding="utf-8")

    second_exit = run_finish(monkeypatch)

    assert first_exit == 20
    assert second_exit == 30
    assert "colleague commit on the feature branch" in remote_log(finish_setup, BRANCH)
    assert state_of(finish_setup).status().startswith("BLOCKED")


def test_finish_branch_branch_equal_to_base_is_a_setup_error(
    finish_setup: FinishSetup,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = install_tools(fake_commands)
    state = state_of(finish_setup)
    state.set_field("Branch", "master")
    state.save()

    exit_code = run_finish(monkeypatch)

    assert exit_code == 2
    assert not any(command.startswith("git push") for command in commands.commands())


def test_finish_branch_worktree_on_another_branch_is_a_setup_error(
    finish_setup: FinishSetup,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
    capsys: pytest.CaptureFixture[str],
):
    commands = install_tools(fake_commands)
    git(finish_setup.worktree, "checkout", "--quiet", "-b", "something-else")

    exit_code = run_finish(monkeypatch)

    assert exit_code == 2
    assert "something-else" in capsys.readouterr().out
    assert not any(command.startswith(("git commit", "git push")) for command in commands.commands())


def test_finish_branch_pipeline_failed_exits_20_with_the_job_log(
    finish_setup: FinishSetup,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
    capsys: pytest.CaptureFixture[str],
):
    commands = install_tools(fake_commands, PIPELINE_FAILED)
    commands.respond("glab ci trace unit tests", ok("collected 40 items\nFAILED test_export.py::test_export_entities_returns_csv\n"))

    exit_code = run_finish(monkeypatch)

    output = capsys.readouterr().out
    assert exit_code == 20
    assert "Failing job: unit tests" in output
    assert "FAILED test_export.py" in output
    assert not any(command.startswith("docker") for command in commands.commands())


def test_finish_branch_glab_error_exits_1_without_waiting(
    finish_setup: FinishSetup,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
    capsys: pytest.CaptureFixture[str],
):
    commands = fake_commands(True)
    commands.respond("glab ci status", failed("", returncode=1))

    exit_code = run_finish(monkeypatch)

    assert exit_code == 1
    assert "glab ci status failed" in capsys.readouterr().out
    assert len([command for command in commands.commands() if command.startswith("glab ci status")]) == 1


def test_finish_branch_manual_pipeline_needs_a_person(
    finish_setup: FinishSetup,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    install_tools(fake_commands, "Pipeline state: manual\n")

    exit_code = run_finish(monkeypatch)

    assert exit_code == 1


def test_finish_branch_third_failure_with_same_code_blocks(
    finish_setup: FinishSetup,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    install_tools(fake_commands, PIPELINE_FAILED)

    exit_codes = [run_finish(monkeypatch) for _ in range(3)]

    assert exit_codes == [20, 20, 20]
    assert state_of(finish_setup).status().startswith("BLOCKED")


def test_finish_branch_rerun_after_the_worktree_was_removed_only_finishes_the_rest(
    finish_setup: FinishSetup,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    install_tools(fake_commands)
    assert run_finish(monkeypatch) == 0
    assert run_cleanup(monkeypatch, finish_setup) == 0
    commands = install_tools(fake_commands)

    exit_code = run_finish(monkeypatch)

    assert exit_code == 0
    assert not any(command.startswith(("git commit", "git push", "glab", "docker")) for command in commands.commands())


def test_finish_branch_missing_worktree_that_was_never_removed_is_an_error(
    finish_setup: FinishSetup,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    install_tools(fake_commands)
    state = state_of(finish_setup)
    state.set_field("Worktree", ".claude/worktrees/does-not-exist")
    state.save()

    exit_code = run_finish(monkeypatch)

    assert exit_code == 1


def test_finish_branch_while_another_run_is_going_is_a_setup_error(
    finish_setup: FinishSetup,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = install_tools(fake_commands)
    marker = {"step": "finish: pipeline", "started": time.time()}
    (finish_setup.feature_directory / ".running.json").write_text(json.dumps(marker), encoding="utf-8")

    exit_code = run_finish(monkeypatch)

    assert exit_code == 2
    assert all(command == "git rev-parse --git-common-dir" for command in commands.commands())


@pytest.mark.parametrize(
    ("output", "expected_state"),
    [
        (f"SHA: {HEAD}\nPipeline state: success\n", "success"),
        (f"SHA: {HEAD}\nPipeline state: failed\n", "failed"),
        (f"SHA: {HEAD}\nPipeline state: running\n", "running"),
        ("SHA: 9999999\nPipeline state: success\n", "running"),
        ("Pipeline state: manual\n", "needs a person"),
        ("Pipeline state: canceled\n", "needs a person"),
        ("Pipeline state: scheduled\n", "running"),
        ("error: failed to reach the server\n", "running"),
    ],
)
def test_parse_pipeline_state_reads_only_the_state_line(output: str, expected_state: str):
    pipeline_state = parse_pipeline_state(output, HEAD)

    assert pipeline_state == expected_state


def test_failed_job_name_keeps_spaces_inside_the_name():
    job_name = failed_job_name(PIPELINE_FAILED)

    assert job_name == "unit tests"


def switch_to_main_checkout(setup: FinishSetup, monkeypatch: pytest.MonkeyPatch) -> FeatureState:
    changed = (setup.worktree / "export.py").read_text(encoding="utf-8")
    bring_feature_home(state_of(setup))
    monkeypatch.chdir(setup.repository)
    git(setup.repository, "worktree", "remove", "--force", str(setup.worktree))
    git(setup.repository, "switch", "--quiet", BRANCH)
    (setup.repository / "export.py").write_text(changed, encoding="utf-8")
    state = state_of(setup)
    state.set_field("Worktree", "")
    state.set_field("Worktree mode", "none")
    state.save()
    return state


def test_finish_branch_without_worktree_finishes_in_the_main_checkout(
    finish_setup: FinishSetup,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    install_tools(fake_commands)
    switch_to_main_checkout(finish_setup, monkeypatch)

    exit_code = run_finish(monkeypatch)

    finish_lines = state_of(finish_setup).section("Finish")
    assert exit_code == 0
    assert "BTRC-1234: CSV export for entities" in remote_log(finish_setup, BRANCH)
    assert any("no worktree: the feature used the main checkout" in line for line in finish_lines)
    assert state_of(finish_setup).field("Phase") == "SUMMARY"


def test_finish_branch_without_worktree_on_the_wrong_branch_is_a_setup_error(
    finish_setup: FinishSetup,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
    capsys: pytest.CaptureFixture[str],
):
    commands = install_tools(fake_commands)
    switch_to_main_checkout(finish_setup, monkeypatch)
    git(finish_setup.repository, "switch", "--quiet", "master")

    exit_code = run_finish(monkeypatch)

    assert exit_code == 2
    assert "The main checkout" in capsys.readouterr().out
    assert not any(command.startswith(("git commit", "git push")) for command in commands.commands())


def test_finish_branch_worktree_mode_without_a_worktree_path_is_a_setup_error(
    finish_setup: FinishSetup,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    install_tools(fake_commands)
    state = state_of(finish_setup)
    state.set_field("Worktree", "")
    state.save()

    exit_code = run_finish(monkeypatch)

    assert exit_code == 2
