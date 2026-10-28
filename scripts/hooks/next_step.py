"""
Stop hook: keeps the orchestrator working after the spec is approved, and tells it the next step from state.md.

:author: midnight-workflow
:date: 28/10/2026
"""
# ----- Imports ----- #

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feature_state import FeatureState, STATE_FILE_NAME, find_active_feature, is_reviewer_session, running_step

# ----- Consts ----- #

BLOCK_COUNTER_NAME = ".stop-hook.json"
MAX_BLOCKS_WITHOUT_PROGRESS = 8
APPROVED_VALUE = "yes"
MAX_BEATRICE_ROUNDS = 5
STEP_TEMPLATES = {
    "BUILD": (
        "Implement slice {slice} of plan.md (only its Files). Then run "
        "`python \"{scripts}/check_slice.py\" {ticket} {slice}` and fix what it lists (it advances state.md when it passes)."
    ),
    "TESTS": (
        "Write test-plan.md (four columns: test name, what it checks, expected result, file), then the tests. "
        "Run them and the changed-line coverage, fix failures, then set `Phase: GATE-A` in state.md."
    ),
    "GATE-A": (
        "Run `python \"{scripts}/gate_a.py\" {ticket}` and fix what it lists (it sets `Phase: GATE-B` when it passes)."
    ),
    "GATE-B": (
        "Round {round} of {max_rounds}: run `python \"{scripts}/run_beatrice.py\" {ticket} {round}` in the background "
        "and wait for it. Then triage review/beatrice-{round}.md into review/triage.md (`fix` or `dismiss: <reason>` per finding), "
        "fix, and set `Round: {next_round}` and `Phase: GATE-A`. If nothing needs fixing, or this was round {max_rounds}, "
        "set `Phase: FINISH`."
    ),
    "FINISH": (
        "Run `python \"{scripts}/finish_branch.py\" {ticket}` and act on its exit code: "
        "10 resolve the conflict, run the tests, run it again; 20 fix the pipeline, run it again; 30 you are blocked."
    ),
    "SUMMARY": (
        "Write summary.md (what was built, every Beatrice finding and what happened to it, what's left for the user), "
        "set `Status: DONE` in state.md and delete docs/features/.active."
    ),
}
UNKNOWN_PHASE_TEMPLATE = (
    "state.md has `Phase: {phase}`, which has no next step. Set Phase to one of: {phases}, or write `Status: BLOCKED: <reason>`."
)

# ----- Functions ----- #


def read_hook_payload() -> dict[str, object]:
    raw_payload = sys.stdin.buffer.read().decode("utf-8")
    if raw_payload.strip() == "":
        return {}
    payload = json.loads(raw_payload)
    return payload if isinstance(payload, dict) else {}


def next_step(state: FeatureState) -> str:
    """
    Describe the next step for the phase state.md is in.

    :param state: The feature's state.
    :return: The instruction for the orchestrator.
    """
    phase = state.field("Phase")
    template = STEP_TEMPLATES.get(phase)
    if template is None:
        return UNKNOWN_PHASE_TEMPLATE.format(phase=phase, phases=", ".join(STEP_TEMPLATES))
    round_number = max(state.number_field("Round"), 1)
    slice_number = max(state.number_field("Slice"), 1)
    instruction = template.format(
        scripts=Path(__file__).resolve().parent.parent.as_posix(),
        ticket=state.field("Ticket"),
        slice=slice_number,
        round=round_number,
        next_round=round_number + 1,
        max_rounds=MAX_BEATRICE_ROUNDS,
    )
    return f"Phase: {phase}. {instruction}"


def count_block(feature_directory: Path, state_text: str) -> int:
    """
    Count this block, starting again from 1 whenever state.md changed since the last block.

    :param feature_directory: The feature's directory.
    :param state_text: The current text of state.md.
    :return: How many blocks in a row happened without state.md changing.
    """
    counter_path = feature_directory / BLOCK_COUNTER_NAME
    state_hash = hashlib.sha256(state_text.encode("utf-8")).hexdigest()
    blocks = 0
    if counter_path.is_file():
        counter = json.loads(counter_path.read_text(encoding="utf-8"))
        if isinstance(counter, dict) and counter.get("state_hash") == state_hash:
            blocks = int(counter.get("blocks", 0))

    blocks += 1
    counter_path.write_text(
        json.dumps({"state_hash": state_hash, "blocks": blocks}),
        encoding="utf-8",
    )
    return blocks


def main() -> int:
    if is_reviewer_session():
        return 0
    payload = read_hook_payload()
    feature_directory = find_active_feature(Path(str(payload.get("cwd", "."))))
    if feature_directory is None or not (feature_directory / STATE_FILE_NAME).is_file():
        return 0
    state = FeatureState.load(feature_directory / STATE_FILE_NAME)
    if state.is_finished() or state.field("Approved").lower() != APPROVED_VALUE:
        return 0
    if running_step(feature_directory) is not None:
        return 0
    blocks = count_block(
        feature_directory,
        state.path.read_text(encoding="utf-8"),
    )
    if blocks > MAX_BLOCKS_WITHOUT_PROGRESS:
        state.block("no progress")
        state.save()
        (feature_directory / BLOCK_COUNTER_NAME).unlink(missing_ok=True)
        return 0
    decision = {
        "decision": "block",
        "reason": f"The feature isn't DONE or BLOCKED yet. {next_step(state)} "
        "If you can't go on, write `Status: BLOCKED: <reason>` in state.md.",
    }
    sys.stdout.write(json.dumps(decision))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
