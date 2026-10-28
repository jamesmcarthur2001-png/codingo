import json
import time
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path

import pytest

import run_beatrice
from conftest import FakeCommands, failed, ok
from feature_state import FeatureState
from run_beatrice import Finding, merge_findings, parse_findings

RUN_A_OUTPUT = """# Review of BTRC-1234

## Summary
- Reviewed 4 files, pipeline plausibly green.

## Findings
- `services/evermore/app/export.py:40` PY-23: `if not rows:` checks truthiness of a list.
  - Sub-point: use `len(rows) == 0`.
- frontend/src/views/EntityList.vue:12 rule: no-hardcoded-color, uses #fff.
  Use a Vuetify token instead.
- The spec's edge case "export with no entities" has no test.

```diff
- old line
+ new line
```
"""
RUN_B_OUTPUT = """## Findings
1. services/evermore/app/export.py:40 [PY-23] truthy check on a list
2. services/evermore/app/export.py:55 PY-24 call should be multiline, returns HTTP-404 and UTF-8 text
"""
BLOCK_OUTPUT = """Review text the command prints.

```beatrice-findings
{"file": "services/evermore/app/export.py", "line": 40, "rule": "PY-23", "finding": "truthy check on a list"}
{"file": "/work/repo/.claude/worktrees/BTRC-1234-csv-export/services/evermore/app/export.py", "line": 61, "rule": "", "finding": "missing test"}
```
"""
TABLE_OUTPUT = """## Findings
| File | Line | Rule | Finding |
|---|---|---|---|
| `services/evermore/app/export.py` | 40 | PY-23 | truthy check |
"""
HEADING_OUTPUT = """## Findings
### 1. services/evermore/app/export.py:40
The check `if not rows:` is a truthy check (PY-23).
"""


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


def claude_json(answer: str, denials: list[dict[str, object]] | None = None, is_error: bool = False):
    result = {
        "type": "result",
        "is_error": is_error,
        "result": answer,
        "permission_denials": [] if denials is None else denials,
    }
    return ok(json.dumps(result))


@pytest.fixture
def beatrice_feature(tmp_path: Path, make_feature_state: Callable[..., Path], monkeypatch: pytest.MonkeyPatch) -> Path:
    feature_directory = make_feature_state(tmp_path, phase="GATE-B")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_beatrice, "ThreadPoolExecutor", SequentialExecutor)
    return feature_directory


def state_of(feature_directory: Path) -> FeatureState:
    return FeatureState.load(feature_directory / "state.md")


def run_main(monkeypatch: pytest.MonkeyPatch, round_number: int) -> int:
    monkeypatch.setattr("sys.argv", ["run_beatrice.py", "BTRC-1234", str(round_number)])
    return run_beatrice.main()


def claude_calls(commands: FakeCommands) -> list[tuple[str, Path | None, dict[str, str] | None]]:
    return [
        call
        for call in commands.calls
        if call[0].startswith("claude ")
    ]


def test_parse_findings_skips_summaries_fences_and_sub_bullets():
    findings = parse_findings(RUN_A_OUTPUT, Path("/work/repo"))

    assert [(finding.file, finding.line, finding.rule) for finding in findings] == [
        ("services/evermore/app/export.py", 40, "PY-23"),
        ("frontend/src/views/EntityList.vue", 12, "no-hardcoded-color"),
        ("", 0, ""),
    ]
    assert "Sub-point" in findings[0].text
    assert "Vuetify token" in findings[1].text


def test_parse_findings_reads_only_known_rule_prefixes():
    findings = parse_findings(RUN_B_OUTPUT, Path("/work/repo"))

    assert [finding.rule for finding in findings] == ["PY-23", "PY-24"]


def test_parse_findings_prefers_the_findings_block_and_strips_the_worktree():
    findings = parse_findings(BLOCK_OUTPUT, Path("/work/repo/.claude/worktrees/BTRC-1234-csv-export"))

    assert [(finding.file, finding.line, finding.rule) for finding in findings] == [
        ("services/evermore/app/export.py", 40, "PY-23"),
        ("services/evermore/app/export.py", 61, ""),
    ]


def test_parse_findings_maps_table_columns_by_header():
    findings = parse_findings(TABLE_OUTPUT, Path("/work/repo"))

    assert [(finding.file, finding.line, finding.rule) for finding in findings] == [
        ("services/evermore/app/export.py", 40, "PY-23"),
    ]


def test_parse_findings_reads_numbered_headings_with_their_paragraph():
    findings = parse_findings(HEADING_OUTPUT, Path("/work/repo"))

    assert [(finding.file, finding.line, finding.rule) for finding in findings] == [
        ("services/evermore/app/export.py", 40, "PY-23"),
    ]


def test_merge_findings_same_file_line_rule_marks_2_of_2_and_keeps_the_rest():
    root = Path("/work/repo")
    merged = merge_findings(parse_findings(RUN_A_OUTPUT, root), parse_findings(RUN_B_OUTPUT, root))

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
    prompt = run_beatrice.build_prompt(state_of(beatrice_feature), "slash")

    assert prompt == "/beatrice-code-review master"


def test_build_prompt_file_mode_passes_command_text(beatrice_feature: Path, tmp_path: Path):
    command_path = tmp_path / "beatrice-code-review.md"
    command_path.write_text("---\ndescription: review\n---\nReview the diff against $ARGUMENTS.\n", encoding="utf-8")
    state = state_of(beatrice_feature)
    state.set_field("Beatrice command", str(command_path))

    prompt = run_beatrice.build_prompt(state, "file")

    assert prompt == "Review the diff against master.\n"


def test_run_round_two_read_only_runs_merge_into_round_file(
    beatrice_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = fake_commands(False)
    commands.respond("claude -p", claude_json(RUN_A_OUTPUT + BLOCK_OUTPUT), claude_json(RUN_B_OUTPUT + BLOCK_OUTPUT))

    exit_code = run_main(monkeypatch, 1)

    merged_text = (beatrice_feature / "review" / "beatrice-1.md").read_text(encoding="utf-8")
    calls = claude_calls(commands)
    assert exit_code == 0
    assert len(calls) == 2
    assert all(extra_environment == {"MIDNIGHT_ROLE": "reviewer"} for _, _, extra_environment in calls)
    assert all("--disallowedTools Edit,Write,MultiEdit,NotebookEdit" in command_text for command_text, _, _ in calls)
    assert all("--permission-mode default" in command_text for command_text, _, _ in calls)
    assert all("Bash(glab mr:*)" not in command_text and "Bash(glab mr view:*)" in command_text for command_text, _, _ in calls)
    assert "| 2/2 | services/evermore/app/export.py:40 | PY-23" in merged_text
    assert (beatrice_feature / "review" / "beatrice-1.json").is_file()
    assert (beatrice_feature / "beatrice-log.md").is_file()
    assert not (beatrice_feature / ".running.json").exists()


def test_run_round_error_result_is_retried_once(
    beatrice_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = fake_commands(False)
    commands.respond(
        "claude -p",
        claude_json("connection closed", is_error=True),
        claude_json(BLOCK_OUTPUT),
        claude_json(BLOCK_OUTPUT),
    )

    exit_code = run_main(monkeypatch, 2)

    assert exit_code == 0
    assert len(claude_calls(commands)) == 3
    assert "after a retry" in state_of(beatrice_feature).path.read_text(encoding="utf-8")


def test_run_round_unknown_slash_command_retries_with_the_command_file(
    beatrice_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
    tmp_path: Path,
):
    command_path = tmp_path / "beatrice-code-review.md"
    command_path.write_text("Review the diff against $ARGUMENTS.\n", encoding="utf-8")
    state = state_of(beatrice_feature)
    state.set_field("Beatrice command", str(command_path))
    state.save()
    commands = fake_commands(False)
    commands.respond(
        "claude -p",
        claude_json("Unknown command: /beatrice-code-review"),
        claude_json(BLOCK_OUTPUT),
        claude_json(BLOCK_OUTPUT),
    )

    exit_code = run_main(monkeypatch, 2)

    prompts = [command_text for command_text, _, _ in claude_calls(commands)]
    assert exit_code == 0
    assert prompts[0].startswith("claude -p /beatrice-code-review master")
    assert prompts[1].startswith("claude -p Review the diff against master.")
    assert "retried with the command file" in (beatrice_feature / "review" / "beatrice-2.md").read_text(encoding="utf-8")


def test_run_round_permission_denials_are_noted(
    beatrice_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = fake_commands(False)
    commands.respond("claude -p", claude_json(BLOCK_OUTPUT, [{"tool_name": "Bash"}]))

    run_main(monkeypatch, 2)

    assert "permission denied for: Bash" in (beatrice_feature / "review" / "beatrice-2.md").read_text(encoding="utf-8")


def test_run_round_one_run_failing_twice_continues_with_the_other(
    beatrice_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = fake_commands(False)
    commands.respond("claude -p", failed(), failed(), claude_json(RUN_B_OUTPUT + BLOCK_OUTPUT))

    exit_code = run_main(monkeypatch, 2)

    merged_text = (beatrice_feature / "review" / "beatrice-2.md").read_text(encoding="utf-8")
    assert exit_code == 0
    assert "Run a: failed twice" in merged_text
    assert "Run b: ok" in merged_text


def test_run_round_both_runs_failing_twice_fails_and_counts_a_try(
    beatrice_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = fake_commands(False)
    commands.respond("claude -p", failed())

    exit_code = run_main(monkeypatch, 3)

    assert exit_code == 1
    assert len(claude_calls(commands)) == 4
    assert state_of(beatrice_feature).field("Tries") == "BEATRICE-3 1"


def test_run_round_while_another_step_runs_is_a_setup_error(
    beatrice_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = fake_commands(False)
    marker = {"step": "finish", "started": time.time()}
    (beatrice_feature / ".running.json").write_text(json.dumps(marker), encoding="utf-8")

    exit_code = run_main(monkeypatch, 1)

    assert exit_code == 2
    assert len(claude_calls(commands)) == 0


def test_run_round_finding_dismissed_earlier_is_annotated_and_line_text_is_captured(
    beatrice_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    commands.respond("claude -p", claude_json(BLOCK_OUTPUT))

    run_main(monkeypatch, 2)

    merged_text = (review_directory / "beatrice-2.md").read_text(encoding="utf-8")
    records = json.loads((review_directory / "beatrice-2.json").read_text(encoding="utf-8"))
    assert "Dismissed in round 1, because rows is a bool flag" in merged_text
    assert records[0]["id"] == "R2-1"
    assert records[0]["line_text"] == "if not rows:"


def test_run_round_rerun_of_round_one_logs_once(
    beatrice_feature: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_commands: Callable[[bool], FakeCommands],
):
    commands = fake_commands(False)
    commands.respond("claude -p", claude_json(BLOCK_OUTPUT))

    run_main(monkeypatch, 1)
    run_main(monkeypatch, 1)

    log_text = (beatrice_feature / "beatrice-log.md").read_text(encoding="utf-8")
    assert log_text.count("## BTRC-1234 round 1 ") == 1
