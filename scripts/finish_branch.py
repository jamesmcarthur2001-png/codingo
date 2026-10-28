#!/usr/bin/env python3
"""
Finishes a feature branch: commit, rebase on the base, push with a lease, wait for the pipeline, stop the branch's containers, remove the worktree, update the base in the main checkout.

Usage: python3 finish_branch.py BTRC-1234
Every step checks whether it is still needed (and finished steps are recorded under `## Finish`), so running the script again resumes.
Exit codes: 0 done, 10 rebase conflict, 20 pipeline failed, 30 push rejected (someone else pushed),
1 another error, 2 setup error (state.md fields, wrong branch checked out, or another long step running).

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
from feature_state import FeatureNotFoundError, FeatureState, StepAlreadyRunningError, load_feature_state, refresh_running_marker, running_marker
from git_changes import is_ancestor, run_git

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
FAILED_JOB_LINE_PATTERN = re.compile(
    r"^\s*\(failed\)(?P<rest>.*)$",
    re.IGNORECASE | re.MULTILINE,
)
JOB_FIELD_SEPARATOR_PATTERN = re.compile(r"\t+|\s{2,}")
SUCCESS_STATES = frozenset({"success", "passed"})
FAILED_STATES = frozenset({"failed"})
NEEDS_PERSON_STATES = frozenset(
    {"manual", "blocked", "canceled", "cancelled", "skipped"},
)
SUCCESS = "success"
FAILED = "failed"
RUNNING = "running"
NEEDS_PERSON = "needs a person"
PUSH_REJECTED_MARKERS = ("rejected", "stale info")
CONFLICT_MARKER_PATTERN = re.compile(r"^(?:<<<<<<<|>>>>>>>)(?: |$)", re.MULTILINE)
SPEC_TITLE_PREFIXES = ("Spec:", "Spec -")
REBASE_STATE_DIRECTORIES = ("rebase-merge", "rebase-apply")
LOCAL_REFS_PREFIX = "refs/heads/"

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
    compose_files: tuple[str, ...]

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
    :raises FinishStepError: With code 2 when `Branch:` or `Base:` is missing, or they are the same branch.
    """
    branch = state.field("Branch")
    base = state.field("Base")
    if branch == "" or base == "":
        raise FinishStepError(
            SETUP_ERROR_EXIT_CODE,
            "state.md needs `Branch:` and `Base:`.",
        )
    if branch == base:
        raise FinishStepError(
            SETUP_ERROR_EXIT_CODE,
            f"`Branch:` and `Base:` are both '{branch}'. The script never commits to or pushes the base.",
        )
    return BranchContext(
        state.field("Ticket"),
        branch,
        base,
        state.code_root(),
        state.repository_root,
        state.field("Worktree"),
        state.field("Compose project"),
        tuple(state.field("Compose files").split()),
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
    state.reload()
    state.append_to_section("Finish", f"- {step}: done {detail}".rstrip())
    state.save()


def is_step_recorded(state: FeatureState, step: str) -> bool:
    return any(
        finish_line.startswith(f"- {step}: done")
        for finish_line in state.section("Finish")
    )


def head_commit(context: BranchContext) -> str:
    return git(["rev-parse", "HEAD"], context.code_root).stdout.strip()


def git_path(context: BranchContext, name: str) -> Path:
    raw_path = git(
        ["rev-parse", "--git-path", name],
        context.code_root,
    ).stdout.strip()
    path = Path(raw_path)
    if not path.is_absolute():
        path = context.code_root / path
    return path


def rebase_state_directory(context: BranchContext) -> Path | None:
    for name in REBASE_STATE_DIRECTORIES:
        path = git_path(context, name)
        if path.is_dir():
            return path

    return None


def checked_out_branch(context: BranchContext) -> str:
    """
    Read the branch the worktree is on, also while a rebase has HEAD detached.

    :param context: The branch context.
    :return: The branch name, or an empty string when HEAD is detached outside a rebase.
    """
    rebase_directory = rebase_state_directory(context)
    if rebase_directory is not None and (rebase_directory / "head-name").is_file():
        head_name = (rebase_directory / "head-name").read_text(encoding="utf-8").strip()
        return head_name.removeprefix(LOCAL_REFS_PREFIX)
    symbolic_ref = git(
        ["symbolic-ref", "--short", "HEAD"],
        context.code_root,
    )
    if not symbolic_ref.succeeded:
        return ""
    return symbolic_ref.stdout.strip()


def require_feature_branch(context: BranchContext):
    current = checked_out_branch(context)
    if current == context.branch:
        return
    raise FinishStepError(
        SETUP_ERROR_EXIT_CODE,
        f"The worktree {context.code_root} is on '{current}', not on '{context.branch}'. Nothing was committed or pushed.",
    )


def name_list(result: command_runner.CommandResult) -> list[str]:
    return [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() != ""
    ]


def conflicted_files(context: BranchContext) -> list[str]:
    return name_list(
        git(
            ["diff", "--name-only", "--diff-filter=U"],
            context.code_root,
        ),
    )


def files_with_conflict_markers(context: BranchContext) -> list[str]:
    """
    Find staged or modified files that still hold `<<<<<<<` or `>>>>>>>` lines.

    :param context: The branch context.
    :return: Repo-relative paths with leftover conflict markers.
    """
    candidates = set(
        name_list(
            git(
                ["diff", "--cached", "--name-only"],
                context.code_root,
            ),
        ),
    )
    candidates.update(
        name_list(git(["diff", "--name-only"], context.code_root)),
    )
    with_markers: list[str] = []
    for relative_path in sorted(candidates):
        path = context.code_root / relative_path
        if not path.is_file():
            continue

        if CONFLICT_MARKER_PATTERN.search(
            path.read_text(encoding="utf-8", errors="replace"),
        ) is not None:
            with_markers.append(relative_path)

    return with_markers


def raise_conflict(files: list[str], output: str):
    if len(files) == 0:
        raise FinishStepError(
            OTHER_ERROR_EXIT_CODE,
            f"git rebase failed without conflicts:\n{output.strip()}",
        )
    raise FinishStepError(
        CONFLICT_EXIT_CODE,
        "Rebase conflict in:\n"
        + "\n".join(f"- {path}" for path in files)
        + "\nResolve them (no <<<<<<< / >>>>>>> lines left), `git add` them, run the tests, then run this script again (it continues the rebase).",
    )


def continue_rebase(context: BranchContext):
    """
    Continue a rebase a conflict stopped, but only when every conflict is really resolved.

    :param context: The branch context.
    :raises FinishStepError: With code 10 while files are unmerged or still hold conflict markers.
    """
    unresolved = conflicted_files(context)
    if len(unresolved) > 0:
        raise_conflict(unresolved, "")
    with_markers = files_with_conflict_markers(context)
    if len(with_markers) > 0:
        raise_conflict(with_markers, "")
    require_success(
        git(["add", "-u"], context.code_root),
        OTHER_ERROR_EXIT_CODE,
        "git add -u failed.",
    )
    continued = git(
        ["-c", "core.editor=true", "rebase", "--continue"],
        context.code_root,
    )
    if not continued.succeeded:
        raise_conflict(conflicted_files(context), continued.output)


def commit_changes(state: FeatureState, context: BranchContext):
    status = git(["status", "--porcelain"], context.code_root)
    require_success(
        status,
        OTHER_ERROR_EXIT_CODE,
        "git status failed.",
    )
    if status.stdout.strip() == "":
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


def remote_branch_commit(context: BranchContext) -> str:
    result = git(
        ["rev-parse", "--verify", "--quiet", f"{REMOTE}/{context.branch}"],
        context.code_root,
    )
    if not result.succeeded:
        return ""
    return result.stdout.strip()


def expected_remote_commit(state: FeatureState, context: BranchContext) -> str:
    """
    Decide which commit the remote branch must still be on, so a colleague's push is never overwritten.

    :param state: The feature's state, with `Pushed:` (the last commit this script pushed).
    :param context: The branch context.
    :return: The commit the lease expects (empty: the branch must not exist on the remote yet).
    :raises FinishStepError: With code 30 when the remote branch moved to something this branch doesn't contain.
    """
    pushed = state.field("Pushed")
    remote_commit = remote_branch_commit(context)
    if remote_commit == "" or remote_commit == pushed:
        return remote_commit
    if is_ancestor(
        remote_commit,
        "HEAD",
        context.code_root,
    ):
        return remote_commit
    raise FinishStepError(
        PUSH_REJECTED_EXIT_CODE,
        f"{REMOTE}/{context.branch} is at {remote_commit[:10]}, which this script didn't push and the branch doesn't contain: "
        "someone else pushed. The user decides.",
    )


def rebase_on_base(state: FeatureState, context: BranchContext):
    """
    Bring the branch on top of the latest base.

    :param state: The feature's state.
    :param context: The branch context.
    :raises FinishStepError: With code 10 when files conflict.
    """
    base_reference = f"{REMOTE}/{context.base}"
    if is_ancestor(
        base_reference,
        "HEAD",
        context.code_root,
    ):
        return
    pulled = git(
        ["pull", "--rebase", REMOTE, context.base],
        context.code_root,
    )
    if not pulled.succeeded:
        raise_conflict(conflicted_files(context), pulled.output)
    record_step(
        state,
        "rebase",
        f"on {base_reference}",
    )


def push_branch(state: FeatureState, context: BranchContext, expected_commit: str):
    """
    Push HEAD to the feature branch, refusing when the remote branch isn't where this script expects it.

    :param state: The feature's state.
    :param context: The branch context.
    :param expected_commit: The commit the remote branch must be on (empty: it must not exist).
    :raises FinishStepError: With code 30 when the push is rejected.
    """
    head = head_commit(context)
    if remote_branch_commit(context) == head:
        state.reload()
        state.set_field("Pushed", head)
        state.save()
        return
    target = f"{LOCAL_REFS_PREFIX}{context.branch}"
    pushed = git(
        ["push", f"--force-with-lease={target}:{expected_commit}", REMOTE, f"HEAD:{target}"],
        context.code_root,
    )
    if pushed.succeeded:
        state.reload()
        state.set_field("Pushed", head)
        state.save()
        record_step(
            state,
            "push",
            f"({head[:10]})",
        )
        return
    is_rejected = any(marker in pushed.output.lower() for marker in PUSH_REJECTED_MARKERS)
    if is_rejected:
        raise FinishStepError(
            PUSH_REJECTED_EXIT_CODE,
            f"Push rejected: someone else pushed to {context.branch}. The user decides.\n{pushed.output.strip()}",
        )
    raise FinishStepError(
        OTHER_ERROR_EXIT_CODE,
        f"git push failed:\n{pushed.output.strip()}",
    )


def parse_pipeline_state(output: str, head: str) -> str:
    """
    Read the pipeline's state from `glab ci status` output.

    The output format is not verified against the team's glab version; adjust the patterns here if it differs.

    :param output: What `glab ci status --branch <branch>` printed on stdout.
    :param head: The pushed commit, so an older commit's pipeline isn't taken for this one.
    :return: `success`, `failed`, `needs a person` (manual, blocked, canceled, skipped) or `running`.
    """
    sha_match = PIPELINE_SHA_PATTERN.search(output)
    if sha_match is not None:
        pipeline_sha = sha_match.group("sha").lower()
        is_this_commit = head.startswith(pipeline_sha) or pipeline_sha.startswith(head)
        if not is_this_commit:
            return RUNNING

    state_match = PIPELINE_STATE_PATTERN.search(output)
    if state_match is None:
        return RUNNING
    pipeline_state = state_match.group("state").lower()
    if pipeline_state in SUCCESS_STATES:
        return SUCCESS
    if pipeline_state in FAILED_STATES:
        return FAILED
    if pipeline_state in NEEDS_PERSON_STATES:
        return NEEDS_PERSON
    return RUNNING


def failed_job_name(status_output: str) -> str:
    """
    Read the first failed job's name from a `(failed) • 01m 02s<TAB>stage<TAB>job name` line.

    :param status_output: What `glab ci status` printed.
    :return: The job name (the last field, which may contain spaces), or an empty string.
    """
    job_match = FAILED_JOB_LINE_PATTERN.search(status_output)
    if job_match is None:
        return ""
    fields = [
        job_field.strip()
        for job_field in JOB_FIELD_SEPARATOR_PATTERN.split(job_match.group("rest"))
        if job_field.strip() not in ("", "•")
    ]
    if len(fields) == 0:
        return ""
    return fields[-1]


def failing_job_log(context: BranchContext, status_output: str) -> str:
    job_name = failed_job_name(status_output)
    if job_name == "":
        return status_output.strip()
    trace = command_runner.run_command(
        ["glab", "ci", "trace", job_name, "--branch", context.branch],
        context.code_root,
        COMMAND_TIMEOUT_SECONDS,
    )
    tail = "\n".join(
        trace.output.strip().splitlines()[-LOG_TAIL_LINES:],
    )
    return f"Failing job: {job_name}\n{tail}"


def wait_for_pipeline(state: FeatureState, context: BranchContext):
    """
    Poll the branch's pipeline every 30 seconds until it passes or fails, for at most 45 minutes.

    :param state: The feature's state.
    :param context: The branch context.
    :raises FinishStepError: With code 20 when the pipeline fails, 1 when glab fails, a person is needed, or it doesn't finish in time.
    """
    head = head_commit(context)
    if f"- pipeline: done ({head[:10]})" in state.section("Finish"):
        return
    waited_seconds = 0
    while waited_seconds <= PIPELINE_MAX_WAIT_SECONDS:
        refresh_running_marker(state.feature_directory, "finish: pipeline")
        status = command_runner.run_command(
            ["glab", "ci", "status", "--branch", context.branch],
            context.code_root,
            COMMAND_TIMEOUT_SECONDS,
        )
        has_state_line = PIPELINE_STATE_PATTERN.search(status.stdout) is not None
        if not status.succeeded and not has_state_line:
            raise FinishStepError(
                OTHER_ERROR_EXIT_CODE,
                f"glab ci status failed:\n{status.output.strip()}",
            )
        pipeline_state = parse_pipeline_state(status.stdout, head)
        if pipeline_state == SUCCESS:
            record_step(
                state,
                "pipeline",
                f"({head[:10]})",
            )
            return
        if pipeline_state == FAILED:
            raise FinishStepError(
                PIPELINE_FAILED_EXIT_CODE,
                f"Pipeline failed.\n{failing_job_log(context, status.stdout)}",
            )
        if pipeline_state == NEEDS_PERSON:
            raise FinishStepError(
                OTHER_ERROR_EXIT_CODE,
                f"The pipeline of {context.branch} is waiting for a person (manual, blocked, canceled or skipped):\n{status.stdout.strip()}",
            )
        time.sleep(PIPELINE_POLL_SECONDS)
        waited_seconds += PIPELINE_POLL_SECONDS

    raise FinishStepError(
        OTHER_ERROR_EXIT_CODE,
        f"The pipeline of {context.branch} didn't finish in 45 minutes.",
    )


def stop_containers(state: FeatureState, context: BranchContext):
    """
    Stop this branch's containers with the same project name and compose files setup used. Volumes are kept.

    :param state: The feature's state.
    :param context: The branch context.
    """
    if is_step_recorded(state, "containers"):
        return
    if context.compose_project == "":
        record_step(
            state,
            "containers",
            "(no `Compose project:` in state.md, nothing stopped)",
        )
        return
    file_arguments = [
        argument
        for compose_file in context.compose_files
        for argument in ("-f", compose_file)
    ]
    working_directory = context.code_root if len(file_arguments) > 0 else state.feature_directory
    stopped = command_runner.run_command(
        ["docker", "compose", "-p", context.compose_project, *file_arguments, "down", "--remove-orphans"],
        working_directory,
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
    if context.worktree == "":
        record_step(
            state,
            "worktree",
            "(no worktree in state.md)",
        )
        return
    removed = git(
        ["worktree", "remove", str(context.code_root)],
        context.repository_root,
    )
    require_success(
        removed,
        OTHER_ERROR_EXIT_CODE,
        f"git worktree remove {context.code_root} failed (uncommitted files, or a program still has it open).",
    )
    record_step(
        state,
        "worktree",
        f"({context.code_root})",
    )


def update_base_checkout(state: FeatureState, context: BranchContext):
    """
    Pull the base branch in the main checkout, as after every merge. A failure is recorded, not fatal.

    :param state: The feature's state.
    :param context: The branch context.
    """
    if is_step_recorded(state, "base"):
        return
    main_branch = git(
        ["symbolic-ref", "--short", "HEAD"],
        context.repository_root,
    ).stdout.strip()
    if main_branch == context.base:
        updated = git(
            ["pull", "--ff-only", REMOTE, context.base],
            context.repository_root,
        )
    else:
        updated = git(
            ["fetch", REMOTE, f"{context.base}:{context.base}"],
            context.repository_root,
        )
    if updated.succeeded:
        record_step(
            state,
            "base",
            f"({context.base} updated in {context.repository_root})",
        )
        return
    state.reload()
    state.log(
        f"finish: could not update {context.base} in the main checkout: {updated.output.strip()}",
    )
    state.save()
    record_step(
        state,
        "base",
        f"(not updated: {updated.stderr.strip()[:120]})",
    )


def finish(state: FeatureState) -> int:
    """
    Run every finish step that is still needed, in order.

    :param state: The feature's state.
    :return: The exit code.
    """
    context = read_context(state)
    if not is_step_recorded(state, "worktree"):
        if not context.code_root.is_dir():
            raise FinishStepError(
                OTHER_ERROR_EXIT_CODE,
                f"The worktree {context.code_root} doesn't exist, but its removal isn't recorded in `## Finish`.",
            )
        require_feature_branch(context)
        if rebase_state_directory(context) is not None:
            continue_rebase(context)
        else:
            commit_changes(state, context)
        require_success(
            git(["fetch", REMOTE], context.code_root),
            OTHER_ERROR_EXIT_CODE,
            "git fetch failed.",
        )
        expected_commit = expected_remote_commit(state, context)
        rebase_on_base(state, context)
        push_branch(
            state,
            context,
            expected_commit,
        )
        wait_for_pipeline(state, context)
        stop_containers(state, context)
        remove_worktree(state, context)

    update_base_checkout(state, context)
    return DONE_EXIT_CODE


def record_result(state: FeatureState, exit_code: int, message: str) -> str:
    state.reload()
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
        with running_marker(state.feature_directory, "finish"):
            try:
                exit_code = finish(state)
                message = ""
            except FinishStepError as step_error:
                exit_code = step_error.exit_code
                message = str(step_error)
            print(
                record_result(
                    state,
                    exit_code,
                    message,
                ),
            )
    except StepAlreadyRunningError as running_error:
        print(f"Setup error: {running_error}")
        return SETUP_ERROR_EXIT_CODE
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
