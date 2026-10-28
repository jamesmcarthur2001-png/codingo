import time
from collections.abc import Callable
from pathlib import Path

import pytest

import finish_branch
from conftest import FakeCommands, failed, ok
from feature_state import FeatureState
from finish_branch import parse_pipeline_state

HEAD = "abc1234def5678"
PIPELINE_PASSED = f"(success) build\nSHA: {HEAD}\nPipeline state: success\n"
PIPELINE_RUNNING = f"(running) build\nSHA: {HEAD}\nPipeline state: running\n"
PIPELINE_FAILED = f"(failed) • 01m 02s test unit-tests\nSHA: {HEAD}\nPipeline state: failed\n"


@pytest.fixture
def finish_feature(tmp_path: Path, make_feature_state: Callable[..., Path], monkeypatch: pytest.MonkeyPatch) -> Path:
    worktree = tmp_path / "worktrees" / "BTRC-1234-csv-export"
    worktree.mkdir(parents=True)
    feature_directory = make_feature_state(tmp_path, phase="FINISH", worktree=worktree.as_posix())
    (feature_directory / "spec.md").write_text("# Spec: CSV export for entities\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    return feature_directory


def install_happy_git(fake_commands: Callable[[bool], FakeCommands]) -> FakeCommands:
    commands = fake_commands(False)
    commands.respond("git status --porcelain", ok(" M services/evermore/app/export.py\n"), ok(""))
    commands.respond("git rev-parse HEAD", ok(HEAD + "\n"))
    commands.respond("git rev-parse --git-path", ok(""))
    commands.respond("git merge-base --is-ancestor", failed())
    commands.respond("git rev-parse --verify --quiet origin/", failed())
    commands.respond("glab ci status", ok(PIPELINE_RUNNING), ok(PIPELINE_PASSED))
    return commands


def run_finish(monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr("sys.argv", ["finish_branch.py", "BTRC-1234"])
    return finish_branch.main()


def state_of(feature_directory: Path) -> FeatureState:
    return FeatureState.load(feature_directory / "state.md")


def test_finish_branch_happy_path_runs_every_step_in_order(
    finish_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = install_happy_git(fake_commands)

    exit_code = run_finish(monkeypatch)

    worktree = state_of(finish_feature).field("Worktree")
    expected_order = [
        "git add -A",
        "git commit -m BTRC-1234: CSV export for entities",
        "git fetch origin",
        "git pull --rebase origin master",
        "git push --force-with-lease origin BTRC-1234-csv-export",
        "glab ci status --branch BTRC-1234-csv-export",
        "docker compose -p btrc-1234 down",
        f"git worktree remove {worktree}",
    ]
    issued = commands.commands()
    positions = [issued.index(command) for command in expected_order]
    assert exit_code == 0
    assert positions == sorted(positions)
    assert state_of(finish_feature).field("Phase") == "SUMMARY"


def test_finish_branch_rebase_conflict_exits_10_with_files(
    finish_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
    capsys: pytest.CaptureFixture[str],
):
    commands = install_happy_git(fake_commands)
    commands.responses.insert(0, ("git pull --rebase", [failed("CONFLICT (content): Merge conflict in app/x.py")]))
    commands.responses.insert(0, ("git diff --name-only --diff-filter=U", [ok("app/x.py\n")]))

    exit_code = run_finish(monkeypatch)

    assert exit_code == 10
    assert "- app/x.py" in capsys.readouterr().out
    assert "git push --force-with-lease origin BTRC-1234-csv-export" not in commands.commands()
    assert state_of(finish_feature).field("Tries") == "FINISH-10 1"


def test_finish_branch_pipeline_failed_exits_20_with_job_log(
    finish_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
    capsys: pytest.CaptureFixture[str],
):
    commands = install_happy_git(fake_commands)
    commands.responses.insert(0, ("glab ci status", [ok(PIPELINE_FAILED)]))
    commands.respond("glab ci trace unit-tests", ok("collected 40 items\nFAILED test_export.py::test_export_entities_returns_csv\n"))

    exit_code = run_finish(monkeypatch)

    output = capsys.readouterr().out
    assert exit_code == 20
    assert "Failing job: unit-tests" in output
    assert "FAILED test_export.py" in output
    assert "docker compose -p btrc-1234 down" not in commands.commands()


def test_finish_branch_push_rejected_exits_30_and_blocks(
    finish_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = install_happy_git(fake_commands)
    commands.responses.insert(0, ("git push", [failed(" ! [rejected] BTRC-1234-csv-export (stale info)")]))

    exit_code = run_finish(monkeypatch)

    assert exit_code == 30
    assert state_of(finish_feature).status().startswith("BLOCKED")


def test_finish_branch_third_failure_with_same_code_blocks(
    finish_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = install_happy_git(fake_commands)
    commands.responses.insert(0, ("glab ci status", [ok(PIPELINE_FAILED)]))

    exit_codes = [run_finish(monkeypatch) for _ in range(3)]

    assert exit_codes == [20, 20, 20]
    assert state_of(finish_feature).status().startswith("BLOCKED")


def test_finish_branch_rerun_skips_finished_steps(
    finish_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = fake_commands(False)
    commands.respond("git status --porcelain", ok(""))
    commands.respond("git rev-parse HEAD", ok(HEAD + "\n"))
    commands.respond("git rev-parse --git-path", ok(""))
    commands.respond("git rev-parse --verify --quiet origin/", ok(HEAD + "\n"))
    state = state_of(finish_feature)
    state.append_to_section("Finish", f"- pipeline: done ({HEAD[:10]})")
    state.append_to_section("Finish", "- containers: done (btrc-1234)")
    state.save()

    exit_code = run_finish(monkeypatch)

    issued = commands.commands()
    assert exit_code == 0
    assert not any(command.startswith(("git commit", "git pull", "git push", "glab", "docker")) for command in issued)
    assert any(command.startswith("git worktree remove") for command in issued)


def test_finish_branch_conflict_resolved_continues_the_rebase(
    finish_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
    tmp_path: Path,
):
    rebase_directory = tmp_path / "rebase-merge"
    rebase_directory.mkdir()
    commands = install_happy_git(fake_commands)
    commands.responses.insert(0, ("git rev-parse --git-path rebase-merge", [ok(str(rebase_directory) + "\n")]))
    commands.responses.insert(0, ("git merge-base --is-ancestor", [ok()]))

    exit_code = run_finish(monkeypatch)

    assert exit_code == 0
    assert "git -c core.editor=true rebase --continue" in commands.commands()


@pytest.mark.parametrize(
    ("output", "expected_state"),
    [
        (PIPELINE_PASSED, "success"),
        (PIPELINE_FAILED, "failed"),
        (PIPELINE_RUNNING, "running"),
        ("SHA: 9999999\nPipeline state: success\n", "running"),
        ("no pipeline found", "running"),
    ],
)
def test_parse_pipeline_state_reads_state_of_this_commit(output: str, expected_state: str):
    pipeline_state = parse_pipeline_state(output, HEAD)

    assert pipeline_state == expected_state
