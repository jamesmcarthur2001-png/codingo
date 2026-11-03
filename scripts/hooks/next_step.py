#!/usr/bin/env python3
"""
Stop hook: keeps the orchestrator working after the spec is approved, and tells it the next step from state.md.

It acts only for the session that runs the feature: the first stop after approval records the payload's
session_id as `Session:` in state.md, and later stops from other sessions are let through.
Circuit breaker: after 8 blocks in a row without state.md changing, it writes `BLOCKED: no progress` and lets the stop happen.
The payload's `stop_hook_active` flag isn't used; the breaker is what ends a loop of blocks.

:author: claude-workflow
:date: 28/10/2026
"""
# ----- Imports ----- #

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feature_state import AFTER_APPROVAL_PHASES, FeatureState, PLAYWRIGHT_REVIEWER_OPTION, STATE_FILE_NAME, find_active_feature, is_reviewer_session, read_json_file, running_step, write_atomically

# ----- Consts ----- #

BLOCK_COUNTER_NAME = ".stop-hook.json"
MAX_BLOCKS_WITHOUT_PROGRESS = 8
MAX_REVIEW_ROUNDS = 3
SCRIPTS_PATH = "$HOME/.claude/scripts"
STEP_TEMPLATES = {
    "BUILD": (
        "Implement slice {slice} of plan.md (only its Files). Then run "
        "`python3 \"{scripts}/check_slice.py\" {ticket} {slice}` and fix what it lists (it advances state.md when it passes)."
    ),
    "TESTS": (
        "Write test-plan.md (four columns: test name, what it checks, expected result, file), then the tests. "
        "Run them and every coverage* command, fix failures, then set `Tries: 0` and `Phase: GATE-A` in state.md."
    ),
    "GATE-A": (
        "Run `python3 \"{scripts}/gate_a.py\" {ticket}` and fix what it lists. When it passes it sets `Phase: GATE-B`, "
        "or `Phase: {after_review}` once round {max_rounds} is triaged."
    ),
    "GATE-B": (
        "Round {round} of {max_rounds}. If `python3 \"{scripts}/review_round.py\" triage-check {ticket} {round}` passes, go straight to the decision below. "
        "Else, in one message, start every reviewer whose review/<source>-{round}.md is missing or has no `Done:` line: "
        "`correctness-reviewer`, `conventions-reviewer`, `tests-reviewer`, `spec-reviewer`{playwright}. "
        "As each one finishes, run `python3 \"{scripts}/review_round.py\" capture {ticket} {round} --source <source>` "
        "(exit 1: run that reviewer again), then start a `finding-verifier` for that source and run `verify-check` the same way when it finishes. "
        "Then write a row for every finding into review/triage.md under `## Round {round}` "
        "(| # | Source | Verdict | File:line | Rule | Finding | Decision | Reason |): sure → fix, invalid → dismiss with the verifier's reason, "
        "unsure → open the code and decide (a dismiss needs a reason). Run triage-check until it passes, and only then fix every `fix` row. "
        "Decision: no `fix` rows → `Phase: {after_review}`; `fix` rows and round < {max_rounds} → fix, then `Round: {next_round}` and `Phase: GATE-A`; "
        "`fix` rows in round {max_rounds} → fix, keep `Round: {max_rounds}`, `Phase: GATE-A`."
    ),
    "VIDEO": (
        "Record one Playwright run with `recordVideo` that walks the new behaviour step by step, with short pauses, "
        "and save it as docs/features/{ticket}/video/{ticket}.webm. If recording fails, note why in `## Log` and summary.md "
        "and continue; never write BLOCKED for this. Then set `Phase: FINISH`."
    ),
    "FINISH": (
        "Finished means all four: rebased on the latest base, the pipeline of the pushed commit passed, every container of the branch closed, "
        "and the worktree closed. Do the finish yourself in the code root, recording each done step under `## Finish` in state.md: "
        "write `Commit title:` (`<type>(<service>): <what was done>`, no ticket, no body) and `MR title:` (the commit title + ` ({ticket})`); "
        "check you're on the feature branch; run `python3 \"{scripts}/check_changes.py\" --base <Base>` and fix what it lists (before every commit); "
        "`git add -A` and `git commit -m \"<Commit title>\"`; `git pull --rebase origin <Base>` "
        "(resolve conflicts, run the tests, `rebase --continue`; then `- rebase: done`); `git push --force-with-lease origin HEAD:refs/heads/<Branch>` "
        "(rejected: someone else pushed, write BLOCKED); poll `glab ci status --branch <Branch>` until it passes "
        "(failed: fix, test, commit, rebase, push again; the pipeline must pass; then `- pipeline: passed (<commit>)`); "
        "`docker compose -p <Compose project> down --remove-orphans` until `docker ps` shows none of its containers (then `- containers: closed`); "
        "then set `Phase: SUMMARY`."
    ),
    "SUMMARY": (
        "Write docs/features/{ticket}/summary.md in the code root (what was built, every review finding of every source and what happened to it, "
        "the video, the MR title, what's left for the user) and show it to the user. Then close the worktree: call `ExitWorktree` (action keep) "
        "and run `python3 \"{scripts}/worktree.py\" remove {ticket} --done`: it refuses (exit 1) until the branch is rebased, the pipeline passed "
        "and the branch's containers are closed; then it copies the feature folder to the main checkout, removes the worktree and sets `Status: DONE`."
    ),
}
PLAYWRIGHT_STEP = ", `playwright-reviewer`"
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
        return UNKNOWN_PHASE_TEMPLATE.format(
            phase=phase,
            phases=", ".join(AFTER_APPROVAL_PHASES),
        )
    round_number = max(state.number_field("Round"), 1)
    slice_number = max(state.number_field("Slice"), 1)
    playwright_step = ""
    if state.is_frontend_option_on(PLAYWRIGHT_REVIEWER_OPTION):
        playwright_step = PLAYWRIGHT_STEP
    instruction = template.format(
        scripts=SCRIPTS_PATH,
        ticket=state.field("Ticket"),
        slice=slice_number,
        round=round_number,
        next_round=round_number + 1,
        max_rounds=MAX_REVIEW_ROUNDS,
        after_review=state.phase_after_review(),
        playwright=playwright_step,
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
    counter = read_json_file(counter_path)
    if counter is not None and counter.get("state_hash") == state_hash:
        stored_blocks = counter.get("blocks")
        if isinstance(stored_blocks, int):
            blocks = stored_blocks

    blocks += 1
    write_atomically(
        counter_path,
        json.dumps({"state_hash": state_hash, "blocks": blocks}),
    )
    return blocks


def reset_block_count(feature_directory: Path):
    (feature_directory / BLOCK_COUNTER_NAME).unlink(missing_ok=True)


def is_other_session(state: FeatureState, session_id: str) -> bool:
    """
    Tell whether this stop comes from a session other than the feature's orchestrator, recording the orchestrator first.

    :param state: The approved feature's state.
    :param session_id: The payload's session_id (may be empty).
    :return: True when state.md names another session.
    """
    recorded_session = state.field("Session")
    if recorded_session == "" and session_id != "":
        state.set_field("Session", session_id)
        state.save()
        return False
    return recorded_session != "" and session_id != recorded_session


def main() -> int:
    if is_reviewer_session():
        return 0
    payload = read_hook_payload()
    feature_directory = find_active_feature(
        Path(str(payload.get("cwd", "."))),
        str(payload.get("session_id", "")),
    )
    if feature_directory is None or not (feature_directory / STATE_FILE_NAME).is_file():
        return 0
    state = FeatureState.load(feature_directory / STATE_FILE_NAME)
    if not state.is_running_after_approval():
        reset_block_count(feature_directory)
        return 0
    if is_other_session(state, str(payload.get("session_id", ""))):
        return 0
    if running_step(feature_directory) is not None:
        reset_block_count(feature_directory)
        return 0
    blocks = count_block(
        feature_directory,
        state.path.read_text(encoding="utf-8"),
    )
    if blocks > MAX_BLOCKS_WITHOUT_PROGRESS:
        state.block("no progress")
        state.save()
        reset_block_count(feature_directory)
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
