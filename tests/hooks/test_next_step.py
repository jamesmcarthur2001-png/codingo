import json
import time
from collections.abc import Callable
from pathlib import Path

import pytest


def stop_payload(repository: Path) -> dict[str, object]:
    return {"hook_event_name": "Stop", "cwd": str(repository), "stop_hook_active": False}


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
