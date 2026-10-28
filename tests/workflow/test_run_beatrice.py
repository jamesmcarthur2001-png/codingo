import json
from concurrent.futures import Future
from collections.abc import Callable
from pathlib import Path

import pytest

import run_beatrice
from conftest import FakeCommands, failed, ok
from feature_state import FeatureState
from run_beatrice import Finding, merge_findings, parse_findings

RUN_A_OUTPUT = """# Review of BTRC-1234

Pipeline: lint, typecheck and tests plausibly pass.

## Findings
- `services/evermore/app/export.py:40` PY-23: `if not rows:` checks truthiness of a list.
- frontend/src/views/EntityList.vue:12 rule: no-hardcoded-color, uses #fff.
  Use a Vuetify token instead.
- The spec's edge case "export with no entities" has no test.
"""
RUN_B_OUTPUT = """## Findings
1. services/evermore/app/export.py:40 [PY-23] truthy check on a list
2. services/evermore/app/export.py:55 PY-24 call should be multiline
"""


@pytest.fixture
def beatrice_feature(tmp_path: Path, make_feature_state: Callable[..., Path], monkeypatch: pytest.MonkeyPatch) -> Path:
    feature_directory = make_feature_state(tmp_path, phase="GATE-B")
    monkeypatch.chdir(tmp_path)
    return feature_directory


class SequentialExecutor:
    """
    Runs submitted work at once, in order, so a test knows which run gets which scripted answer.
    """

    def __init__(self, max_workers: int):
        self.max_workers = max_workers

    def __enter__(self) -> "SequentialExecutor":
        return self

    def __exit__(self, *exception_details: object):
        return

    def submit(self, function: Callable[..., object], *arguments: object) -> Future[object]:
        future: Future[object] = Future()
        future.set_result(function(*arguments))
        return future


def state_of(feature_directory: Path) -> FeatureState:
    return FeatureState.load(feature_directory / "state.md")


def claude_calls(commands: FakeCommands) -> list[tuple[str, Path | None, dict[str, str] | None]]:
    return [
        call
        for call in commands.calls
        if call[0].startswith("claude ")
    ]


def test_parse_findings_reads_bullets_numbers_and_continuations():
    findings = parse_findings(RUN_A_OUTPUT)

    assert [(finding.file, finding.line, finding.rule) for finding in findings] == [
        ("services/evermore/app/export.py", 40, "PY-23"),
        ("frontend/src/views/EntityList.vue", 12, "no-hardcoded-color"),
        ("", 0, ""),
    ]
    assert "Vuetify token" in findings[1].text


def test_merge_findings_same_file_line_rule_marks_2_of_2_and_keeps_the_rest():
    merged = merge_findings(parse_findings(RUN_A_OUTPUT), parse_findings(RUN_B_OUTPUT))

    assert [(item.marks, item.finding.file, item.finding.line) for item in merged] == [
        ("2/2", "services/evermore/app/export.py", 40),
        ("1/2", "frontend/src/views/EntityList.vue", 12),
        ("1/2", "", 0),
        ("1/2", "services/evermore/app/export.py", 55),
    ]


def test_merge_findings_same_line_different_rules_stay_separate():
    first = [Finding("a", "app/x.py", 3, "PY-23")]
    second = [Finding("b", "app/x.py", 3, "PY-24")]

    merged = merge_findings(first, second)

    assert [item.marks for item in merged] == ["1/2", "1/2"]


def test_build_prompt_slash_mode_runs_command_with_base(beatrice_feature: Path):
    prompt = run_beatrice.build_prompt(state_of(beatrice_feature))

    assert prompt == "/beatrice-code-review master"


def test_build_prompt_file_mode_passes_command_text(beatrice_feature: Path, tmp_path: Path):
    command_path = tmp_path / "beatrice-code-review.md"
    command_path.write_text("---\ndescription: review\n---\nReview the diff against $ARGUMENTS.\n", encoding="utf-8")
    state = state_of(beatrice_feature)
    state.set_field("Beatrice command", str(command_path))
    state.set_field("Beatrice mode", "file")

    prompt = run_beatrice.build_prompt(state)

    assert prompt == "Review the diff against master.\n"


def test_run_round_two_runs_merge_into_round_file_as_reviewer(
    beatrice_feature: Path,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = fake_commands(False)
    commands.respond("claude -p", ok(RUN_A_OUTPUT), ok(RUN_B_OUTPUT))

    exit_code = run_beatrice.run_round(state_of(beatrice_feature), 1)

    merged_text = (beatrice_feature / "review" / "beatrice-1.md").read_text(encoding="utf-8")
    calls = claude_calls(commands)
    assert exit_code == 0
    assert len(calls) == 2
    assert all(extra_environment == {"MIDNIGHT_ROLE": "reviewer"} for _, _, extra_environment in calls)
    assert all("--allowedTools" in command_text for command_text, _, _ in calls)
    assert "| 2/2 | services/evermore/app/export.py:40 | PY-23" in merged_text
    assert (beatrice_feature / "review" / "beatrice-1-a.md").is_file()
    assert (beatrice_feature / "beatrice-log.md").is_file()
    assert not (beatrice_feature / ".running.json").exists()


def test_run_round_failed_run_is_retried_once(beatrice_feature: Path, fake_commands: Callable[[bool], FakeCommands]):
    commands = fake_commands(False)
    commands.respond("claude -p", failed("connection closed mid-response"), ok(RUN_A_OUTPUT), ok(RUN_B_OUTPUT))

    exit_code = run_beatrice.run_round(state_of(beatrice_feature), 2)

    assert exit_code == 0
    assert len(claude_calls(commands)) == 3
    assert "after a retry" in state_of(beatrice_feature).path.read_text(encoding="utf-8")
    assert not (beatrice_feature / "beatrice-log.md").exists()


def test_run_round_one_run_failing_twice_continues_with_the_other(
    beatrice_feature: Path,
    fake_commands: Callable[[bool], FakeCommands],
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(run_beatrice, "ThreadPoolExecutor", SequentialExecutor)
    commands = fake_commands(False)
    commands.respond("claude -p", failed(), failed(), ok(RUN_B_OUTPUT))

    exit_code = run_beatrice.run_round(state_of(beatrice_feature), 2)

    merged_text = (beatrice_feature / "review" / "beatrice-2.md").read_text(encoding="utf-8")
    assert exit_code == 0
    assert "Run a: failed twice" in merged_text
    assert "Run b: ok" in merged_text
    assert "services/evermore/app/export.py:55" in merged_text


def test_run_round_both_runs_failing_twice_fails_and_counts_a_try(
    beatrice_feature: Path,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = fake_commands(False)
    commands.respond("claude -p", failed())

    exit_code = run_beatrice.run_round(state_of(beatrice_feature), 3)

    assert exit_code == 1
    assert len(claude_calls(commands)) == 4
    assert state_of(beatrice_feature).field("Tries") == "BEATRICE-3 1"


def test_run_round_finding_dismissed_earlier_is_annotated(
    beatrice_feature: Path,
    tmp_path: Path,
    fake_commands: Callable[[bool], FakeCommands],
):
    source_path = tmp_path / "services" / "evermore" / "app" / "export.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("\n" * 39 + "    if not rows:\n", encoding="utf-8")
    review_directory = beatrice_feature / "review"
    review_directory.mkdir()
    dismissal = {
        "file": "services/evermore/app/export.py",
        "rule": "PY-23",
        "line_text": "if not rows:",
        "round": 1,
        "reason": "rows is a bool flag",
    }
    (review_directory / "dismissed.json").write_text(json.dumps([dismissal]), encoding="utf-8")
    commands = fake_commands(False)
    commands.respond("claude -p", ok(RUN_A_OUTPUT), ok(RUN_B_OUTPUT))

    run_beatrice.run_round(state_of(beatrice_feature), 2)

    merged_text = (review_directory / "beatrice-2.md").read_text(encoding="utf-8")
    assert "Dismissed in round 1, because rows is a bool flag" in merged_text
