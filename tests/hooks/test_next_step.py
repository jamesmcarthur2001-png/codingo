import json
import time
from collections.abc import Callable
from pathlib import Path

import pytest


FEATURE_COMMAND = Path(__file__).resolve().parents[2] / "commands" / "feature.md"
PHASES_LINE_PREFIX = "Phases after approval:"


def stop_payload(repository: Path, session_id: str = "session-1") -> dict[str, object]:
    return {"hook_event_name": "Stop", "cwd": str(repository), "stop_hook_active": False, "session_id": session_id}


def decision(completed: object) -> dict[str, object]:
    stdout = getattr(completed, "stdout")
    if stdout.strip() == "":
        return {}
    return json.loads(stdout)


def set_status(feature_directory: Path, status: str):
    state_path = feature_directory / "state.md"
    state_text = state_path.read_text(encoding="utf-8").replace("Status: RUNNING", f"Status: {status}")
    state_path.write_text(state_text, encoding="utf-8")


def test_next_step_no_active_feature_allows(tmp_path: Path, run_hook: Callable[..., object]):
    completed = run_hook("next_step.py", stop_payload(tmp_path))

    assert decision(completed) == {}


def test_next_step_before_approval_allows(tmp_path: Path, make_feature_state: Callable[..., Path], run_hook: Callable[..., object]):
    make_feature_state(tmp_path, phase="GRILL", approved="no")

    completed = run_hook("next_step.py", stop_payload(tmp_path))

    assert decision(completed) == {}


@pytest.mark.parametrize("status", ["DONE", "BLOCKED: tests keep failing"])
def test_next_step_finished_feature_allows(
    tmp_path: Path,
    make_feature_state: Callable[..., Path],
    run_hook: Callable[..., object],
    status: str,
):
    set_status(make_feature_state(tmp_path), status)

    completed = run_hook("next_step.py", stop_payload(tmp_path))

    assert decision(completed) == {}


@pytest.mark.parametrize(
    ("phase", "expected_text"),
    [
        ("BUILD", 'check_slice.py" BTRC-1234 1'),
        ("TESTS", "test-plan.md"),
        ("GATE-A", 'gate_a.py" BTRC-1234'),
        ("GATE-B", 'run_beatrice.py" BTRC-1234 1'),
        ("FINISH", 'finish_branch.py" BTRC-1234'),
        ("SUMMARY", "summary.md"),
        ("NONSENSE", "has no next step"),
    ],
)
def test_next_step_approved_running_feature_blocks_with_next_step(
    tmp_path: Path,
    make_feature_state: Callable[..., Path],
    run_hook: Callable[..., object],
    phase: str,
    expected_text: str,
):
    make_feature_state(tmp_path, phase=phase)

    completed = run_hook("next_step.py", stop_payload(tmp_path))

    assert decision(completed)["decision"] == "block"
    assert expected_text in str(decision(completed)["reason"])


def test_next_step_ninth_stop_without_progress_blocks_feature(
    tmp_path: Path,
    make_feature_state: Callable[..., Path],
    run_hook: Callable[..., object],
):
    feature_directory = make_feature_state(tmp_path)
    decisions = [decision(run_hook("next_step.py", stop_payload(tmp_path))) for _ in range(8)]

    completed = run_hook("next_step.py", stop_payload(tmp_path))

    assert all(earlier["decision"] == "block" for earlier in decisions)
    assert decision(completed) == {}
    assert "Status: BLOCKED: no progress" in (feature_directory / "state.md").read_text(encoding="utf-8")


def test_next_step_state_change_resets_the_block_count(
    tmp_path: Path,
    make_feature_state: Callable[..., Path],
    run_hook: Callable[..., object],
):
    state_path = make_feature_state(tmp_path) / "state.md"
    for attempt in range(8):
        run_hook("next_step.py", stop_payload(tmp_path))
        state_path.write_text(state_path.read_text(encoding="utf-8") + f"- progress {attempt}\n", encoding="utf-8")

    completed = run_hook("next_step.py", stop_payload(tmp_path))

    assert decision(completed)["decision"] == "block"


def test_next_step_long_step_running_allows(tmp_path: Path, make_feature_state: Callable[..., Path], run_hook: Callable[..., object]):
    feature_directory = make_feature_state(tmp_path, phase="GATE-B")
    marker = {"step": "beatrice round 1", "started": time.time()}
    (feature_directory / ".running.json").write_text(json.dumps(marker), encoding="utf-8")

    completed = run_hook("next_step.py", stop_payload(tmp_path))

    assert decision(completed) == {}


def test_next_step_stale_running_marker_blocks(tmp_path: Path, make_feature_state: Callable[..., Path], run_hook: Callable[..., object]):
    feature_directory = make_feature_state(tmp_path, phase="GATE-B")
    marker = {"step": "beatrice round 1", "started": time.time() - 2 * 60 * 60}
    (feature_directory / ".running.json").write_text(json.dumps(marker), encoding="utf-8")

    completed = run_hook("next_step.py", stop_payload(tmp_path))

    assert decision(completed)["decision"] == "block"


def test_next_step_reviewer_role_allows(tmp_path: Path, make_feature_state: Callable[..., Path], run_hook: Callable[..., object]):
    make_feature_state(tmp_path)

    completed = run_hook("next_step.py", stop_payload(tmp_path), {"MIDNIGHT_ROLE": "reviewer"})

    assert decision(completed) == {}


def test_next_step_first_stop_records_session_and_other_sessions_are_ignored(
    tmp_path: Path,
    make_feature_state: Callable[..., Path],
    run_hook: Callable[..., object],
):
    feature_directory = make_feature_state(tmp_path)

    first = run_hook("next_step.py", stop_payload(tmp_path, "orchestrator"))
    other = run_hook("next_step.py", stop_payload(tmp_path, "someone-else"))

    assert decision(first)["decision"] == "block"
    assert decision(other) == {}
    assert "Session: orchestrator" in (feature_directory / "state.md").read_text(encoding="utf-8")
    assert "BLOCKED" not in (feature_directory / "state.md").read_text(encoding="utf-8")


def test_next_step_other_session_never_trips_the_breaker(
    tmp_path: Path,
    make_feature_state: Callable[..., Path],
    run_hook: Callable[..., object],
):
    feature_directory = make_feature_state(tmp_path)
    run_hook("next_step.py", stop_payload(tmp_path, "orchestrator"))

    for _ in range(12):
        run_hook("next_step.py", stop_payload(tmp_path, "someone-else"))

    assert "Status: RUNNING" in (feature_directory / "state.md").read_text(encoding="utf-8")


def test_next_step_approved_with_date_blocks(tmp_path: Path, make_feature_state: Callable[..., Path], run_hook: Callable[..., object]):
    make_feature_state(tmp_path, approved="yes (28/10/2026)")

    completed = run_hook("next_step.py", stop_payload(tmp_path))

    assert decision(completed)["decision"] == "block"


def test_next_step_corrupt_counter_counts_as_missing(tmp_path: Path, make_feature_state: Callable[..., Path], run_hook: Callable[..., object]):
    feature_directory = make_feature_state(tmp_path)
    (feature_directory / ".stop-hook.json").write_text("{not json", encoding="utf-8")

    completed = run_hook("next_step.py", stop_payload(tmp_path))

    assert decision(completed)["decision"] == "block"
    assert json.loads((feature_directory / ".stop-hook.json").read_text(encoding="utf-8"))["blocks"] == 1


def test_next_step_corrupt_running_marker_counts_as_missing(tmp_path: Path, make_feature_state: Callable[..., Path], run_hook: Callable[..., object]):
    feature_directory = make_feature_state(tmp_path, phase="GATE-B")
    (feature_directory / ".running.json").write_text("garbage", encoding="utf-8")

    completed = run_hook("next_step.py", stop_payload(tmp_path))

    assert decision(completed)["decision"] == "block"


def test_next_step_allowed_stop_resets_the_counter(tmp_path: Path, make_feature_state: Callable[..., Path], run_hook: Callable[..., object]):
    feature_directory = make_feature_state(tmp_path, phase="GATE-B")
    run_hook("next_step.py", stop_payload(tmp_path))
    marker = {"step": "beatrice round 1", "started": time.time()}
    (feature_directory / ".running.json").write_text(json.dumps(marker), encoding="utf-8")

    run_hook("next_step.py", stop_payload(tmp_path))

    assert not (feature_directory / ".stop-hook.json").exists()


def test_next_step_phases_match_feature_command():
    from next_step import STEP_TEMPLATES

    phases_line = next(
        line
        for line in FEATURE_COMMAND.read_text(encoding="utf-8").splitlines()
        if line.startswith(PHASES_LINE_PREFIX)
    )
    command_phases = [phase.strip() for phase in phases_line.removeprefix(PHASES_LINE_PREFIX).split(",")]

    assert command_phases == list(STEP_TEMPLATES)


@pytest.mark.parametrize(
    "fragment",
    [
        'python3 "$HOME/.claude/midnight-workflow/scripts/check_slice.py" <Ticket> <Slice>',
        'python3 "$HOME/.claude/midnight-workflow/scripts/gate_a.py" <Ticket>',
        'python3 "$HOME/.claude/midnight-workflow/scripts/run_beatrice.py" <Ticket> <Round>',
        'python3 "$HOME/.claude/midnight-workflow/scripts/finish_branch.py" <Ticket>',
        "keep `Round: 5`, set `Phase: GATE-A`. Gate A then sets `Phase: VIDEO` or `Phase: FINISH`",
        "If `review/triage.md` already has `## Round <Round>`",
        'python3 "$HOME/.claude/midnight-workflow/scripts/review_round.py" capture <Ticket> <Round>',
        'python3 "$HOME/.claude/midnight-workflow/scripts/review_round.py" playwright-needed <Ticket> <Round>',
        'python3 "$HOME/.claude/midnight-workflow/scripts/worktree.py" create <Ticket>',
        "The `conventions-reviewer` agent",
        "The `playwright-reviewer` agent",
        "| # | Source | Marks | File:line | Rule | Finding | Decision | Reason |",
        "docs/features/<Ticket>/video/<Ticket>.webm",
    ],
)
def test_next_step_feature_command_holds_the_steps_the_hook_names(fragment: str):
    assert fragment in FEATURE_COMMAND.read_text(encoding="utf-8")


def test_next_step_gate_b_text_matches_the_round_five_rule(tmp_path: Path, make_feature_state: Callable[..., Path], run_hook: Callable[..., object]):
    feature_directory = make_feature_state(tmp_path, phase="GATE-B")
    state_path = feature_directory / "state.md"
    state_path.write_text(state_path.read_text(encoding="utf-8").replace("Round: 1", "Round: 5"), encoding="utf-8")

    reason = str(decision(run_hook("next_step.py", stop_payload(tmp_path)))["reason"])

    assert "keep `Round: 5`, `Phase: GATE-A`" in reason
    assert "already has `## Round 5`" in reason
    assert 'python3 "$HOME/.claude/midnight-workflow/scripts/run_beatrice.py" BTRC-1234 5' in reason


def set_frontend(feature_directory: Path, *option_lines: str):
    state_path = feature_directory / "state.md"
    frontend_section = "## Frontend\n" + "\n".join(option_lines) + "\n\n## Log"
    state_text = state_path.read_text(encoding="utf-8").replace("## Log", frontend_section)
    state_path.write_text(state_text, encoding="utf-8")


def test_next_step_phases_match_feature_state():
    from feature_state import AFTER_APPROVAL_PHASES
    from next_step import STEP_TEMPLATES

    assert tuple(STEP_TEMPLATES) == AFTER_APPROVAL_PHASES


def test_next_step_gate_b_names_the_parallel_reviewers(tmp_path: Path, make_feature_state: Callable[..., Path], run_hook: Callable[..., object]):
    make_feature_state(tmp_path, phase="GATE-B")

    reason = str(decision(run_hook("next_step.py", stop_payload(tmp_path)))["reason"])

    assert "run_beatrice.py\" BTRC-1234 1` in the background" in reason
    assert "`conventions-reviewer` agent" in reason
    assert "review_round.py\" capture BTRC-1234 1" in reason
    assert "playwright-reviewer" not in reason
    assert "no `fix` rows → `Phase: FINISH`" in reason


def test_next_step_gate_b_with_playwright_and_video_names_them(tmp_path: Path, make_feature_state: Callable[..., Path], run_hook: Callable[..., object]):
    feature_directory = make_feature_state(tmp_path, phase="GATE-B")
    set_frontend(feature_directory, "- Playwright reviewer: yes", "- Video: yes")

    reason = str(decision(run_hook("next_step.py", stop_payload(tmp_path)))["reason"])

    assert "`playwright-reviewer` agent" in reason
    assert "review_round.py\" playwright-needed BTRC-1234 1` prints yes" in reason
    assert "no `fix` rows → `Phase: VIDEO`" in reason


def test_next_step_video_phase_never_blocks_on_failure(tmp_path: Path, make_feature_state: Callable[..., Path], run_hook: Callable[..., object]):
    make_feature_state(tmp_path, phase="VIDEO")

    reason = str(decision(run_hook("next_step.py", stop_payload(tmp_path)))["reason"])

    assert "docs/features/BTRC-1234/video/BTRC-1234.webm" in reason
    assert "never write BLOCKED for this" in reason
    assert "`Phase: FINISH`" in reason
