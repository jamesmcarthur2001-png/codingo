import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

import check_slice
import gate_a
from conftest import FakeCommands, failed, git, ok
from feature_state import FeatureState

HEADER = '"""\nEntities.\n\n:author: midnight-workflow\n:date: 16/10/2026\n"""\n# ----- Imports ----- #\n\nimport os\n\n# ----- Functions ----- #\n\n\n'
LEGACY_SOURCE = HEADER + "def save_entity(entity) -> None:\n    print(os.sep, entity)\n"
CLEAN_ADDITION = '\n\ndef count_entities(entities: list[str]) -> int:\n    """\n    Count the entities.\n    """\n    return len(entities)\n'
PLAN = "# Plan\n\n## Slice 1: backend\nFiles:\n- `app/entities.py`\n\n## Slice 2: tests\nFiles:\n- `tests/test_entities.py`\n"
DIFF_COVER_OUTPUT = "Diff Coverage\nDiff: origin/master...HEAD\n-------------\napp/entities.py (50.0%): Missing lines 20-21,25\n-------------\n"
TRIAGE = """# Triage

## Round 1
| # | Marks | File:line | Rule | Finding | Decision | Reason |
|---|---|---|---|---|---|---|
| R1-1 | 2/2 | app/entities.py:15 | PY-23 | truthy check | dismiss | line 14 already checks None |
| R1-2 | 1/2 | app/entities.py:16 | PY-24 | multiline call | fix | |
"""


@pytest.fixture
def branch_feature(git_repository: Path, make_feature_state: Callable[..., Path], monkeypatch: pytest.MonkeyPatch) -> Path:
    (git_repository / ".git" / "info" / "exclude").write_text("docs/features/\n", encoding="utf-8")
    (git_repository / "app").mkdir()
    (git_repository / "app" / "entities.py").write_text(LEGACY_SOURCE, encoding="utf-8")
    git(git_repository, "add", "-A")
    git(git_repository, "commit", "--quiet", "-m", "legacy entities")
    git(git_repository, "checkout", "--quiet", "-b", "BTRC-1234-csv-export")
    feature_directory = make_feature_state(git_repository)
    (feature_directory / "plan.md").write_text(PLAN, encoding="utf-8")
    monkeypatch.chdir(git_repository)
    return feature_directory


def run_script(module: object, monkeypatch: pytest.MonkeyPatch, *arguments: str) -> int:
    monkeypatch.setattr(sys, "argv", ["script", *arguments])
    return getattr(module, "main")()


def state_of(feature_directory: Path) -> FeatureState:
    return FeatureState.load(feature_directory / "state.md")


def test_check_slice_clean_change_with_legacy_violations_passes_and_advances(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    entities_path = branch_feature.parent.parent.parent / "app" / "entities.py"
    entities_path.write_text(LEGACY_SOURCE + CLEAN_ADDITION, encoding="utf-8")

    exit_code = run_script(check_slice, monkeypatch, "BTRC-1234", "1")

    assert exit_code == 0, capsys.readouterr().out
    assert state_of(branch_feature).field("Slice") == "2"


def test_check_slice_last_slice_passing_moves_to_tests(branch_feature: Path, monkeypatch: pytest.MonkeyPatch):
    exit_code = run_script(check_slice, monkeypatch, "BTRC-1234", "2")

    assert exit_code == 0
    assert state_of(branch_feature).field("Phase") == "TESTS"


def test_check_slice_file_outside_slice_fails_and_counts_a_try(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    (branch_feature.parent.parent.parent / "app" / "unplanned.py").write_text(HEADER, encoding="utf-8")

    exit_code = run_script(check_slice, monkeypatch, "BTRC-1234", "1")

    assert exit_code == 1
    assert "app/unplanned.py" in capsys.readouterr().out
    assert state_of(branch_feature).field("Tries") == "SLICE-1 1"


def test_check_slice_violation_on_changed_line_fails(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    entities_path = branch_feature.parent.parent.parent / "app" / "entities.py"
    entities_path.write_text(LEGACY_SOURCE + "\n\ndef get_entities(entities):\n    return entities  # type: ignore\n", encoding="utf-8")

    exit_code = run_script(check_slice, monkeypatch, "BTRC-1234", "1")

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "PY-62" in output
    assert "SUPPRESSION" in output
    assert "PY-02" not in output


def test_check_slice_changed_existing_line_is_listed_but_passes(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    entities_path = branch_feature.parent.parent.parent / "app" / "entities.py"
    entities_path.write_text(LEGACY_SOURCE.replace("print(os.sep, entity)", "print(os.linesep, entity)"), encoding="utf-8")

    exit_code = run_script(check_slice, monkeypatch, "BTRC-1234", "1")

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Existing lines you changed" in output
    assert "app/entities.py:15 (replaces 1 existing line(s))" in output


def test_check_slice_unknown_slice_returns_setup_error(branch_feature: Path, monkeypatch: pytest.MonkeyPatch):
    exit_code = run_script(check_slice, monkeypatch, "BTRC-1234", "7")

    assert exit_code == 2


def add_commands(feature_directory: Path, *command_lines: str):
    state = state_of(feature_directory)
    for command_line in command_lines:
        state.append_to_section("Commands", command_line)
    state.save()


def test_gate_a_without_commands_returns_setup_error(branch_feature: Path, monkeypatch: pytest.MonkeyPatch):
    exit_code = run_script(gate_a, monkeypatch, "BTRC-1234")

    assert exit_code == 2


def test_gate_a_all_commands_pass_moves_to_gate_b(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = fake_commands(True)
    add_commands(branch_feature, "- lint: npx nx lint evermore", "- test: npx nx test evermore")

    exit_code = run_script(gate_a, monkeypatch, "BTRC-1234")

    assert exit_code == 0
    assert "npx nx lint evermore" in commands.commands()
    assert state_of(branch_feature).field("Phase") == "GATE-B"


def test_gate_a_failing_command_fails_with_output_tail(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
    capsys: pytest.CaptureFixture[str],
):
    commands = fake_commands(True)
    commands.respond("npx nx typecheck", failed("error TS2322: Type 'string' is not assignable"))
    add_commands(branch_feature, "- typecheck: npx nx typecheck frontend")

    exit_code = run_script(gate_a, monkeypatch, "BTRC-1234")

    assert exit_code == 1
    assert "TS2322" in capsys.readouterr().out
    assert state_of(branch_feature).field("Tries") == "GATE-A-1 1"


def test_gate_a_uncovered_lines_without_exemption_fail(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
    capsys: pytest.CaptureFixture[str],
):
    commands = fake_commands(True)
    commands.respond("diff-cover", failed(DIFF_COVER_OUTPUT))
    add_commands(branch_feature, "- coverage-backend: diff-cover coverage.xml --compare-branch=origin/master --include-untracked --fail-under=100")

    exit_code = run_script(gate_a, monkeypatch, "BTRC-1234")

    assert exit_code == 1
    assert "app/entities.py: 20, 21, 25" in capsys.readouterr().out


def test_gate_a_uncovered_lines_all_exempt_pass(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = fake_commands(True)
    commands.respond("diff-cover", failed(DIFF_COVER_OUTPUT))
    add_commands(branch_feature, "- coverage-backend: diff-cover coverage.xml --include-untracked --fail-under=100")
    state = state_of(branch_feature)
    state.append_to_section("Coverage exemptions", "- `app/entities.py`:20-21: pass-through route, no logic")
    state.append_to_section("Coverage exemptions", "- app/entities.py:25 - defensive branch the database can't reach")
    state.save()

    exit_code = run_script(gate_a, monkeypatch, "BTRC-1234")

    assert exit_code == 0


def test_gate_a_exemption_without_reason_fails(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
    capsys: pytest.CaptureFixture[str],
):
    fake_commands(True)
    add_commands(branch_feature, "- lint: npx nx lint evermore")
    state = state_of(branch_feature)
    state.append_to_section("Coverage exemptions", "- app/entities.py:20")
    state.save()

    exit_code = run_script(gate_a, monkeypatch, "BTRC-1234")

    assert exit_code == 1
    assert "without a reason" in capsys.readouterr().out


def test_gate_a_dismissed_findings_are_remembered_by_line_text(branch_feature: Path):
    code_root = branch_feature.parent.parent.parent
    entities_path = code_root / "app" / "entities.py"
    entities_path.write_text("\n" * 14 + "if not entity:\n" + "call(a, b, c)\n", encoding="utf-8")
    review_directory = branch_feature / "review"
    review_directory.mkdir()
    (review_directory / "triage.md").write_text(TRIAGE, encoding="utf-8")

    dismissed = gate_a.sync_dismissed(state_of(branch_feature))
    same_finding = gate_a.find_dismissal(dismissed, "app/entities.py", "PY-23", "if not entity:")
    other_line = gate_a.find_dismissal(dismissed, "app/entities.py", "PY-23", "if not other:")

    assert len(dismissed) == 1
    assert same_finding is not None
    assert same_finding.round == 1
    assert same_finding.reason == "line 14 already checks None"
    assert other_line is None
    assert (review_directory / "dismissed.json").is_file()


def write_round_record(feature_directory: Path, round_number: int, records: list[dict[str, object]]):
    review_directory = feature_directory / "review"
    review_directory.mkdir(exist_ok=True)
    (review_directory / f"beatrice-{round_number}.json").write_text(json.dumps(records), encoding="utf-8")


def test_gate_a_dismissal_uses_line_text_captured_by_beatrice_not_the_shifted_line(branch_feature: Path):
    code_root = branch_feature.parent.parent.parent
    (code_root / "app" / "entities.py").write_text("\n" * 14 + "new line pushed in by a fix\n" + "if not entity:\n", encoding="utf-8")
    record = {"id": "R1-1", "file": "app/entities.py", "line": 15, "rule": "PY-23", "line_text": "if not entity:"}
    write_round_record(branch_feature, 1, [record])
    (branch_feature / "review" / "triage.md").write_text(TRIAGE, encoding="utf-8")

    dismissed = gate_a.sync_dismissed(state_of(branch_feature))

    assert [dismissal.line_text for dismissal in dismissed] == ["if not entity:"]
    assert dismissed[0].finding_id == "R1-1"


def test_gate_a_stored_dismissal_is_not_read_again(branch_feature: Path):
    record = {"id": "R1-1", "file": "app/entities.py", "line": 15, "rule": "PY-23", "line_text": "if not entity:"}
    write_round_record(branch_feature, 1, [record])
    (branch_feature / "review" / "triage.md").write_text(TRIAGE, encoding="utf-8")
    gate_a.sync_dismissed(state_of(branch_feature))
    write_round_record(branch_feature, 1, [{**record, "line_text": "something else"}])

    dismissed = gate_a.sync_dismissed(state_of(branch_feature))

    assert [dismissal.line_text for dismissal in dismissed] == ["if not entity:"]


def test_gate_a_coverage_command_without_include_untracked_is_a_setup_error(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
    capsys: pytest.CaptureFixture[str],
):
    fake_commands(True)
    add_commands(branch_feature, "- coverage-backend: diff-cover coverage.xml --fail-under=100")

    exit_code = run_script(gate_a, monkeypatch, "BTRC-1234")

    assert exit_code == 2
    assert "--include-untracked" in capsys.readouterr().out


def test_gate_a_exemption_matches_the_full_path_only(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
    capsys: pytest.CaptureFixture[str],
):
    commands = fake_commands(True)
    commands.respond("diff-cover", failed("app/tax.py (50.0%): Missing lines 3\n"))
    add_commands(branch_feature, "- coverage-backend: diff-cover coverage.xml --include-untracked --fail-under=100")
    state = state_of(branch_feature)
    state.append_to_section("Coverage exemptions", "- x.py:3: unrelated file with a common suffix")
    state.save()

    exit_code = run_script(gate_a, monkeypatch, "BTRC-1234")

    assert exit_code == 1
    assert "app/tax.py: 3" in capsys.readouterr().out


def test_gate_a_no_coverage_lines_while_code_changed_fails(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
    capsys: pytest.CaptureFixture[str],
):
    commands = fake_commands(True)
    commands.respond("diff-cover", ok("No lines with coverage information in this diff.\n"))
    add_commands(branch_feature, "- coverage-backend: diff-cover coverage.xml --include-untracked --fail-under=100")
    entities_path = branch_feature.parent.parent.parent / "app" / "entities.py"
    entities_path.write_text(LEGACY_SOURCE + CLEAN_ADDITION, encoding="utf-8")

    exit_code = run_script(gate_a, monkeypatch, "BTRC-1234")

    assert exit_code == 1
    assert "saw no changed lines" in capsys.readouterr().out


def test_gate_a_after_round_five_triage_moves_to_finish(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    fake_commands(True)
    add_commands(branch_feature, "- lint: npx nx lint evermore")
    state = state_of(branch_feature)
    state.set_field("Round", "5")
    state.save()
    (branch_feature / "review").mkdir()
    (branch_feature / "review" / "triage.md").write_text("## Round 5\n| R5-1 | 1/2 | app/x.py:1 | PY-1 | a | fix | |\n", encoding="utf-8")

    exit_code = run_script(gate_a, monkeypatch, "BTRC-1234")

    assert exit_code == 0
    assert state_of(branch_feature).field("Phase") == "FINISH"


def test_gate_a_round_five_before_review_moves_to_gate_b(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    fake_commands(True)
    add_commands(branch_feature, "- lint: npx nx lint evermore")
    state = state_of(branch_feature)
    state.set_field("Round", "5")
    state.save()

    exit_code = run_script(gate_a, monkeypatch, "BTRC-1234")

    assert exit_code == 0
    assert state_of(branch_feature).field("Phase") == "GATE-B"


def test_gate_a_while_another_step_runs_is_a_setup_error(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    fake_commands(True)
    add_commands(branch_feature, "- lint: npx nx lint evermore")
    marker = {"step": "finish", "started": time.time()}
    (branch_feature / ".running.json").write_text(json.dumps(marker), encoding="utf-8")

    exit_code = run_script(gate_a, monkeypatch, "BTRC-1234")

    assert exit_code == 2


def test_check_slice_unknown_base_is_a_setup_error(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    state = state_of(branch_feature)
    state.set_field("Base", "no-such-branch")
    state.save()

    exit_code = run_script(check_slice, monkeypatch, "BTRC-1234", "1")

    assert exit_code == 2
    assert "no-such-branch" in capsys.readouterr().out


def test_check_slice_git_warnings_are_not_changed_files(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    code_root = branch_feature.parent.parent.parent
    git(code_root, "config", "core.autocrlf", "true")
    (code_root / "app" / "entities.py").write_text(LEGACY_SOURCE + CLEAN_ADDITION, encoding="utf-8")

    exit_code = run_script(check_slice, monkeypatch, "BTRC-1234", "1")

    output = capsys.readouterr().out
    assert exit_code == 0, output
    assert "warning" not in output


def test_check_slice_renamed_file_lists_the_old_path_as_out_of_scope(
    branch_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    code_root = branch_feature.parent.parent.parent
    (code_root / "app" / "legacy.py").write_text(LEGACY_SOURCE, encoding="utf-8")
    git(code_root, "add", "-A")
    git(code_root, "commit", "--quiet", "-m", "legacy module")
    git(code_root, "branch", "--force", "master")
    git(code_root, "mv", "app/legacy.py", "app/entities_old.py")
    plan = PLAN.replace("- `app/entities.py`", "- `app/entities.py`\n- `app/entities_old.py`")
    (branch_feature / "plan.md").write_text(plan, encoding="utf-8")

    exit_code = run_script(check_slice, monkeypatch, "BTRC-1234", "1")

    assert exit_code == 1
    assert "- app/legacy.py" in capsys.readouterr().out
