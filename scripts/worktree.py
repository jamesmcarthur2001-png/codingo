#!/usr/bin/env python3
"""
Creates or removes a feature's native git worktree under `.claude/worktrees/<branch>`, or, with --no-worktree, switches the main checkout to the branch.

Usage: python3 worktree.py create BTRC-1234 [--no-worktree]
       python3 worktree.py remove BTRC-1234
`create` reuses the branch when it exists (locally or on origin), never creates a second branch for the same BTRC-<n>,
keeps `.claude/worktrees/` and `docs/features/` in `.git/info/exclude`, and records `Worktree:` and `Worktree mode:` in state.md.
Running it again when the worktree exists only records it.
Exit codes: 0 done, 1 git failed, 2 setup error (no feature, missing fields, another branch for the ticket).

:author: midnight-workflow
:date: 28/10/2026
"""
# ----- Imports ----- #

import argparse
import sys
from pathlib import Path

from feature_state import FeatureNotFoundError, FeatureState, NO_WORKTREE_MODE, load_feature_state
from git_changes import run_git
from hooks.guard_branch import BranchChange, conflicting_branches

# ----- Consts ----- #

FAILED_EXIT_CODE = 1
SETUP_ERROR_EXIT_CODE = 2
REMOTE = "origin"
WORKTREES_DIRECTORY = Path(".claude") / "worktrees"
EXCLUDED_PATTERNS = (".claude/worktrees/", "docs/features/")
WORKTREE_MODE = "worktree"
LOCAL_REFS_PREFIX = "refs/heads/"

# ----- Classes ----- #


class WorktreeError(Exception):
    """
    Raised when a worktree step can't be done; carries the exit code.
    """
    def __init__(self, exit_code: int, message: str):
        super().__init__(message)
        self.exit_code = exit_code

# ----- Functions ----- #


def relative_worktree_path(branch: str) -> str:
    return (WORKTREES_DIRECTORY / branch).as_posix()


def require_git(arguments: list[str], cwd: Path, message: str) -> str:
    result = run_git(arguments, cwd)
    if not result.succeeded:
        raise WorktreeError(
            FAILED_EXIT_CODE,
            f"{message}\n{result.output.strip()}",
        )
    return result.stdout


def exclude_workflow_folders(repository_root: Path):
    """
    Keep the worktrees and feature folders out of git without touching tracked files.

    :param repository_root: The main checkout.
    """
    common_directory = Path(
        require_git(
            ["rev-parse", "--git-common-dir"],
            repository_root,
            "git rev-parse failed.",
        ).strip(),
    )
    if not common_directory.is_absolute():
        common_directory = repository_root / common_directory
    exclude_path = common_directory / "info" / "exclude"
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude_path.read_text(encoding="utf-8").splitlines() if exclude_path.is_file() else []
    missing = [
        pattern
        for pattern in EXCLUDED_PATTERNS
        if pattern not in existing
    ]
    if len(missing) == 0:
        return
    prefix = "" if len(existing) == 0 or existing[-1] == "" else "\n"
    with exclude_path.open("a", encoding="utf-8") as exclude_file:
        exclude_file.write(prefix + "\n".join(missing) + "\n")


def registered_worktrees(repository_root: Path) -> list[Path]:
    output = require_git(
        ["worktree", "list", "--porcelain"],
        repository_root,
        "git worktree list failed.",
    )
    return [
        Path(line.removeprefix("worktree ")).resolve()
        for line in output.splitlines()
        if line.startswith("worktree ")
    ]


def branch_exists(branch: str, repository_root: Path) -> bool:
    """
    Tell whether the feature branch already exists, locally or on origin.

    :param branch: The feature branch.
    :param repository_root: The main checkout.
    :return: Whether git can check it out without creating it from the base.
    """
    for reference in (f"{LOCAL_REFS_PREFIX}{branch}", f"refs/remotes/{REMOTE}/{branch}"):
        if run_git(
            ["rev-parse", "--verify", "--quiet", reference],
            repository_root,
        ).succeeded:
            return True

    return False


def require_single_ticket_branch(branch: str, repository_root: Path):
    conflicts, _ = conflicting_branches(BranchChange(branch, ""), repository_root)
    if len(conflicts) == 0:
        return
    raise WorktreeError(
        SETUP_ERROR_EXIT_CODE,
        f"Another branch for this ticket already exists: {', '.join(conflicts)}. "
        "Use it as `Branch:` in state.md, or ask the user; never create a second one.",
    )


def read_branch_and_base(state: FeatureState) -> tuple[str, str]:
    branch = state.field("Branch")
    base = state.field("Base")
    if branch == "" or base == "":
        raise WorktreeError(
            SETUP_ERROR_EXIT_CODE,
            "state.md needs `Branch:` and `Base:`.",
        )
    if branch == base:
        raise WorktreeError(
            SETUP_ERROR_EXIT_CODE,
            f"`Branch:` and `Base:` are both '{branch}'.",
        )
    return branch, base


def record_worktree(state: FeatureState, worktree: str, mode: str):
    state.reload()
    state.set_field("Worktree", worktree)
    state.set_field("Worktree mode", mode)
    state.save()


def create_worktree(state: FeatureState) -> str:
    """
    Create the feature's worktree at `.claude/worktrees/<branch>`, reusing the branch when it exists.

    :param state: The feature's state.
    :return: What was done, for the orchestrator.
    :raises WorktreeError: When git fails or another branch for the ticket exists.
    """
    branch, base = read_branch_and_base(state)
    repository_root = state.repository_root
    exclude_workflow_folders(repository_root)
    worktree = relative_worktree_path(branch)
    worktree_path = (repository_root / worktree).resolve()
    if worktree_path in registered_worktrees(repository_root):
        record_worktree(
            state,
            worktree,
            WORKTREE_MODE,
        )
        return f"Worktree {worktree} already exists; recorded it."
    require_git(
        ["fetch", REMOTE, base],
        repository_root,
        f"git fetch {REMOTE} {base} failed.",
    )
    require_single_ticket_branch(branch, repository_root)
    if branch_exists(branch, repository_root):
        require_git(
            ["worktree", "add", worktree, branch],
            repository_root,
            f"git worktree add {worktree} {branch} failed.",
        )
        record_worktree(
            state,
            worktree,
            WORKTREE_MODE,
        )
        return f"Reused branch {branch} in {worktree}."
    require_git(
        ["worktree", "add", "-b", branch, worktree, f"{REMOTE}/{base}"],
        repository_root,
        f"git worktree add -b {branch} {worktree} {REMOTE}/{base} failed.",
    )
    record_worktree(
        state,
        worktree,
        WORKTREE_MODE,
    )
    return f"Created branch {branch} from {REMOTE}/{base} in {worktree}."


def switch_main_checkout(state: FeatureState) -> str:
    """
    Work without a worktree: switch the main checkout to the feature branch, creating it from the base when needed.

    :param state: The feature's state.
    :return: What was done, for the orchestrator.
    :raises WorktreeError: When git fails (e.g. uncommitted changes) or another branch for the ticket exists.
    """
    branch, base = read_branch_and_base(state)
    repository_root = state.repository_root
    exclude_workflow_folders(repository_root)
    current = run_git(
        ["symbolic-ref", "--short", "HEAD"],
        repository_root,
    ).stdout.strip()
    if current == branch:
        record_worktree(
            state,
            "",
            NO_WORKTREE_MODE,
        )
        return f"The main checkout is already on {branch}; recorded it."
    require_git(
        ["fetch", REMOTE, base],
        repository_root,
        f"git fetch {REMOTE} {base} failed.",
    )
    require_single_ticket_branch(branch, repository_root)
    if branch_exists(branch, repository_root):
        require_git(
            ["switch", branch],
            repository_root,
            f"git switch {branch} failed.",
        )
        record_worktree(
            state,
            "",
            NO_WORKTREE_MODE,
        )
        return f"Switched the main checkout to the existing branch {branch}."
    require_git(
        ["switch", "-c", branch, f"{REMOTE}/{base}"],
        repository_root,
        f"git switch -c {branch} {REMOTE}/{base} failed.",
    )
    record_worktree(
        state,
        "",
        NO_WORKTREE_MODE,
    )
    return f"Created branch {branch} from {REMOTE}/{base} in the main checkout."


def remove_worktree(state: FeatureState) -> str:
    """
    Remove the feature's worktree; the branch itself stays.

    :param state: The feature's state.
    :return: What was done.
    :raises WorktreeError: When git can't remove it (uncommitted files, or a program has it open).
    """
    if not state.uses_worktree() or state.field("Worktree") == "":
        return "No worktree to remove (the feature works in the main checkout)."
    worktree_path = state.code_root().resolve()
    repository_root = state.repository_root
    if worktree_path not in registered_worktrees(repository_root):
        return f"Worktree {worktree_path} is already removed."
    require_git(
        ["worktree", "remove", str(worktree_path)],
        repository_root,
        f"git worktree remove {worktree_path} failed (uncommitted files, or a program still has it open).",
    )
    return f"Removed worktree {worktree_path}."


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or remove a feature's worktree.",
    )
    parser.add_argument("action", choices=["create", "remove"])
    parser.add_argument("ticket", help="The ticket, e.g. BTRC-1234.")
    parser.add_argument(
        "--no-worktree",
        action="store_true",
        help="Work in the main checkout: switch it to the branch instead of creating a worktree.",
    )
    arguments = parser.parse_args()
    try:
        state = load_feature_state(arguments.ticket, Path.cwd())
    except FeatureNotFoundError as missing_error:
        print(missing_error)
        return SETUP_ERROR_EXIT_CODE
    try:
        if arguments.action == "remove":
            print(remove_worktree(state))
        elif arguments.no_worktree:
            print(switch_main_checkout(state))
        else:
            print(create_worktree(state))
    except WorktreeError as worktree_error:
        print(worktree_error)
        return worktree_error.exit_code
    return 0


if __name__ == "__main__":
    sys.exit(main())
