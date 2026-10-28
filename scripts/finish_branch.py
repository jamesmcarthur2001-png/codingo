"""
Finishes a feature branch: commit, rebase on the base, push with --force-with-lease, wait for the pipeline, stop the branch's containers, remove the worktree.

Usage: python finish_branch.py BTRC-1234
Every step checks whether it is still needed, so running the script again resumes where it stopped.
Exit codes: 0 done, 10 rebase conflict, 20 pipeline failed, 30 push rejected, 1 another error, 2 the feature can't be found.

:author: midnight-workflow
:date: 28/10/2026
"""
# ----- Imports ----- #

import argparse
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import command_runner
from feature_state import FeatureNotFoundError, FeatureState, load_feature_state, running_marker
from git_changes import run_git

# ----- Consts ----- #

DONE_EXIT_CODE = 0
OTHER_ERROR_EXIT_CODE = 1
SETUP_ERROR_EXIT_CODE = 2
CONFLICT_EXIT_CODE = 10
PIPELINE_FAILED_EXIT_CODE = 20
PUSH_REJECTED_EXIT_CODE = 30
REMOTE = "origin"
PIPELINE_POLL_SECONDS = 30
PIPELINE_MAX_WAIT_SECONDS = 45 * 60
COMMAND_TIMEOUT_SECONDS = 300
LOG_TAIL_LINES = 60
PIPELINE_STATE_PATTERN = re.compile(
    r"pipeline\s+state\s*:\s*(?P<state>\w+)",
    re.IGNORECASE,
)
PIPELINE_SHA_PATTERN = re.compile(
    r"\bSHA\s*:\s*(?P<sha>[0-9a-f]{7,40})",
    re.IGNORECASE,
)
FAILED_JOB_PATTERN = re.compile(
    r"^\s*\(failed\).*?(?P<job>[\w:./-]+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
SUCCESS_STATES = ("success", "passed")
FAILED_STATES = ("failed", "canceled", "cancelled")
PUSH_REJECTED_MARKERS = ("rejected", "stale info")
SPEC_TITLE_PREFIXES = ("Spec:", "Spec -")

# ----- Classes ----- #


class FinishStepError(Exception):
    """
    Raised when a finish step stops the script with one of its exit codes.
    """
    def __init__(self, exit_code: int, message: str):
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class BranchContext:
    """
    The branch, base, worktree and container project the script works on, all read from state.md.
    """
    ticket: str
    branch: str
    base: str
    code_root: Path
    repository_root: Path
    worktree: str
    compose_project: str

# ----- Functions ----- #


def git(arguments: list[str], cwd: Path) -> command_runner.CommandResult:
    return run_git(arguments, cwd)


def require_success(result: command_runner.CommandResult, exit_code: int, message: str):
    if result.succeeded:
        return
    raise FinishStepError(exit_code, f"{message}\n{result.output.strip()}")


def read_context(state: FeatureState) -> BranchContext:
    """
    Read what the script needs from state.md.

    :param state: The feature's state.
    :return: The branch context.
    :raises FinishStepError: When `Branch:` or `Base:` is missing.
    """
    branch = state.field("Branch")
    base = state.field("Base")
    if branch == "" or base == "":
        raise FinishStepError(
            SETUP_ERROR_EXIT_CODE,
            "state.md needs `Branch:` and `Base:`.",
        )
    return BranchContext(
        state.field("Ticket"),
        branch,
        base,
        state.code_root(),
        state.feature_directory.parent.parent.parent,
        state.field("Worktree"),
        state.field("Compose project"),
    )


def commit_title(state: FeatureState) -> str:
    """
    Read the feature's title from the first heading of spec.md.

    :param state: The feature's state.
    :return: The heading without a `Spec:` prefix, else the `Title:` field.
    """
    spec_path = state.feature_directory / "spec.md"
    if spec_path.is_file():
        for spec_line in spec_path.read_text(encoding="utf-8").splitlines():
            if not spec_line.startswith("# "):
                continue

            title = spec_line.removeprefix("# ").strip()
            for prefix in SPEC_TITLE_PREFIXES:
                title = title.removeprefix(prefix).strip()

            return title

    return state.field("Title")


def record_step(state: FeatureState, step: str, detail: str):
    state.lines = FeatureState.load(state.path).lines
    state.append_to_section("Finish", f"- {step}: done {detail}".rstrip())
    state.save()


def head_commit(context: BranchContext) -> str:
    return git(["rev-parse", "HEAD"], context.code_root).output.strip()


def commit_changes(state: FeatureState, context: BranchContext):
    status = git(["status", "--porcelain"], context.code_root)
    require_success(
        status,
        OTHER_ERROR_EXIT_CODE,
        "git status failed.",
    )
    if status.output.strip() == "":
        return
    require_success(
        git(["add", "-A"], context.code_root),
        OTHER_ERROR_EXIT_CODE,
        "git add failed.",
    )
    commit = git(
        ["commit", "-m", f"{context.ticket}: {commit_title(state)}"],
        context.code_root,
    )
    require_success(
        commit,
        OTHER_ERROR_EXIT_CODE,
        "git commit failed.",
    )
    record_step(
        state,
        "commit",
        f"({head_commit(context)[:10]})",
    )


def conflicted_files(context: BranchContext) -> list[str]:
    result = git(
        ["diff", "--name-only", "--diff-filter=U"],
        context.code_root,
    )
    return [
        line.strip()
        for line in result.output.splitlines()
        if line.strip() != ""
    ]


def is_rebase_in_progress(context: BranchContext) -> bool:
    for state_directory in ("rebase-merge", "rebase-apply"):
        git_path = git(
            ["rev-parse", "--git-path", state_directory],
            context.code_root,
        ).output.strip()
        if git_path == "":
            continue

        path = Path(git_path)
        if not path.is_absolute():
            path = context.code_root / path
        if path.is_dir():
            return True

    return False


def raise_conflict(context: BranchContext, output: str):
    conflicts = conflicted_files(context)
    if len(conflicts) == 0:
        raise FinishStepError(
            OTHER_ERROR_EXIT_CODE,
            f"git pull --rebase failed without conflicts:\n{output.strip()}",
        )
    raise FinishStepError(
        CONFLICT_EXIT_CODE,
        "Rebase conflict in:\n"
        + "\n".join(f"- {path}" for path in conflicts)
        + "\nResolve them, `git add` them, run the tests, then run this script again (it continues the rebase).",
    )


def rebase_on_base(state: FeatureState, context: BranchContext):
    """
    Bring the branch on top of the latest base, continuing a rebase a conflict stopped.

    :param state: The feature's state.
    :param context: The branch context.
    :raises FinishStepError: With code 10 when files conflict.
    """
    if is_rebase_in_progress(context):
        if len(conflicted_files(context)) > 0:
            raise_conflict(context, "")
        continued = git(
            ["-c", "core.editor=true", "rebase", "--continue"],
            context.code_root,
        )
        if not continued.succeeded:
            raise_conflict(context, continued.output)

    base_reference = f"{REMOTE}/{context.base}"
    is_up_to_date = git(
        ["merge-base", "--is-ancestor", base_reference, "HEAD"],
        context.code_root,
    ).succeeded
    if is_up_to_date:
        return
    pulled = git(
        ["pull", "--rebase", REMOTE, context.base],
        context.code_root,
    )
    if not pulled.succeeded:
        raise_conflict(context, pulled.output)
    record_step(
        state,
        "rebase",
        f"on {base_reference}",
    )


def push_branch(state: FeatureState, context: BranchContext):
    remote_head = git(
        ["rev-parse", "--verify", "--quiet", f"{REMOTE}/{context.branch}"],
        context.code_root,
    )
    if remote_head.succeeded and remote_head.output.strip() == head_commit(context):
        return
    pushed = git(
        ["push", "--force-with-lease", REMOTE, context.branch],
        context.code_root,
    )
    if pushed.succeeded:
        record_step(
            state,
            "push",
            f"({head_commit(context)[:10]})",
        )
        return
    is_rejected = any(marker in pushed.output.lower() for marker in PUSH_REJECTED_MARKERS)
    if is_rejected:
        raise FinishStepError(
            PUSH_REJECTED_EXIT_CODE,
            f"Push rejected: someone else pushed to {context.branch} since the last fetch. The user decides.\n{pushed.output.strip()}",
        )
    raise FinishStepError(
        OTHER_ERROR_EXIT_CODE,
        f"git push failed:\n{pushed.output.strip()}",
    )


def parse_pipeline_state(output: str, head: str) -> str:
    """
    Read the pipeline's state from `glab ci status` output.

    The output format is not verified against the team's glab version; adjust the patterns here if it differs.

    :param output: What `glab ci status --branch <branch>` printed.
    :param head: The pushed commit, so an older commit's pipeline isn't taken for this one.
    :return: `success`, `failed` or `running`.
    """
    sha_match = PIPELINE_SHA_PATTERN.search(output)
    if sha_match is not None:
        pipeline_sha = sha_match.group("sha").lower()
        is_this_commit = head.startswith(pipeline_sha) or pipeline_sha.startswith(head)
        if not is_this_commit:
            return "running"

    state_match = PIPELINE_STATE_PATTERN.search(output)
    words = [state_match.group("state").lower()] if state_match is not None else output.lower().split()
    if any(word in FAILED_STATES for word in words):
        return "failed"
    if state_match is not None and words[0] in SUCCESS_STATES:
        return "success"
    return "running"


def failing_job_log(context: BranchContext, status_output: str) -> str:
    job_match = FAILED_JOB_PATTERN.search(status_output)
    if job_match is None:
        return status_output.strip()
    trace = command_runner.run_command(
        [command_runner.find_executable("glab"), "ci", "trace", job_match.group("job"), "--branch", context.branch],
        context.code_root,
        COMMAND_TIMEOUT_SECONDS,
    )
    tail = "\n".join(
        trace.output.strip().splitlines()[-LOG_TAIL_LINES:],
    )
    return f"Failing job: {job_match.group('job')}\n{tail}"


def wait_for_pipeline(state: FeatureState, context: BranchContext):
    """
    Poll the branch's pipeline every 30 seconds until it passes or fails, for at most 45 minutes.

    :param state: The feature's state.
    :param context: The branch context.
    :raises FinishStepError: With code 20 when the pipeline fails, 1 when it doesn't finish in time.
    """
    head = head_commit(context)
    finished_lines = state.section("Finish")
    if f"- pipeline: done ({head[:10]})" in finished_lines:
        return
    waited_seconds = 0
    with running_marker(state.feature_directory, "pipeline"):
        while waited_seconds <= PIPELINE_MAX_WAIT_SECONDS:
            status = command_runner.run_command(
                [command_runner.find_executable("glab"), "ci", "status", "--branch", context.branch],
                context.code_root,
                COMMAND_TIMEOUT_SECONDS,
            )
            pipeline_state = parse_pipeline_state(status.output, head)
            if pipeline_state == "success":
                record_step(
                    state,
                    "pipeline",
                    f"({head[:10]})",
                )
                return
            if pipeline_state == "failed":
                raise FinishStepError(
                    PIPELINE_FAILED_EXIT_CODE,
                    f"Pipeline failed.\n{failing_job_log(context, status.output)}",
                )
            time.sleep(PIPELINE_POLL_SECONDS)
            waited_seconds += PIPELINE_POLL_SECONDS

    raise FinishStepError(
        OTHER_ERROR_EXIT_CODE,
        f"The pipeline of {context.branch} didn't finish in 45 minutes.",
    )


def stop_containers(state: FeatureState, context: BranchContext):
    is_stopped = any(
        finish_line.startswith("- containers: done")
        for finish_line in state.section("Finish")
    )
    if is_stopped:
        return
    if context.compose_project == "":
        record_step(
            state,
            "containers",
            "(no `Compose project:` in state.md, nothing stopped)",
        )
        return
    stopped = command_runner.run_command(
        [command_runner.find_executable("docker"), "compose", "-p", context.compose_project, "down"],
        context.repository_root,
        COMMAND_TIMEOUT_SECONDS,
    )
    require_success(
        stopped,
        OTHER_ERROR_EXIT_CODE,
        f"docker compose -p {context.compose_project} down failed.",
    )
    record_step(
        state,
        "containers",
        f"({context.compose_project})",
    )


def remove_worktree(state: FeatureState, context: BranchContext):
    if context.worktree == "" or not Path(context.worktree).exists():
        return
    removed = git(
        ["worktree", "remove", context.worktree],
        context.repository_root,
    )
    require_success(
        removed,
        OTHER_ERROR_EXIT_CODE,
        f"git worktree remove {context.worktree} failed (uncommitted files, or a program still has it open).",
    )
    record_step(
        state,
        "worktree",
        f"({context.worktree})",
    )


def finish(state: FeatureState) -> int:
    """
    Run every finish step that is still needed, in order.

    :param state: The feature's state.
    :return: The exit code.
    """
    context = read_context(state)
    worktree_is_gone = context.worktree != "" and not Path(context.worktree).exists()
    if not worktree_is_gone:
        commit_changes(state, context)
        require_success(
            git(["fetch", REMOTE], context.code_root),
            OTHER_ERROR_EXIT_CODE,
            "git fetch failed.",
        )
        rebase_on_base(state, context)
        push_branch(state, context)
        wait_for_pipeline(state, context)
        stop_containers(state, context)
        remove_worktree(state, context)

    return DONE_EXIT_CODE


def record_result(state: FeatureState, exit_code: int, message: str) -> str:
    if exit_code == DONE_EXIT_CODE:
        state.reset_tries()
        state.set_field("Phase", "SUMMARY")
        state.log("finish_branch done")
        state.save()
        return "Branch finished. Phase is now SUMMARY."
    if exit_code == PUSH_REJECTED_EXIT_CODE:
        state.block(
            "push rejected, someone else pushed to the branch",
        )
        state.save()
        return f"{message}\nstate.md is now BLOCKED. Stop."
    failed_runs = state.record_failure(f"FINISH-{exit_code}")
    state.save()
    if state.is_finished():
        return f"{message}\nExit {exit_code} {failed_runs} times in a row: state.md is now BLOCKED. Stop."
    return message


def main() -> int:
    parser = argparse.ArgumentParser(description="Finish a feature branch.")
    parser.add_argument("ticket", help="The ticket, e.g. BTRC-1234.")
    arguments = parser.parse_args()
    try:
        state = load_feature_state(arguments.ticket, Path.cwd())
    except FeatureNotFoundError as missing_error:
        print(missing_error)
        return SETUP_ERROR_EXIT_CODE
    try:
        exit_code = finish(state)
        message = ""
    except FinishStepError as step_error:
        exit_code = step_error.exit_code
        message = str(step_error)
    print(record_result(state, exit_code, message))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
