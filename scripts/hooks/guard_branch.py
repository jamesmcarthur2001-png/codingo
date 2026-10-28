"""
PreToolUse hook on Bash: blocks creating or renaming a branch when another branch with the same BTRC-<n> already exists.

:author: midnight-workflow
:date: 28/10/2026
"""
# ----- Imports ----- #

import json
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feature_state import is_reviewer_session
from git_changes import run_git

# ----- Consts ----- #

BLOCKING_EXIT_CODE = 2
SEGMENT_SEPARATOR_PATTERN = re.compile(r"&&|\|\||;|\||\n")
TICKET_PATTERN = re.compile(r"BTRC-(?P<number>\d+)(?!\d)", re.IGNORECASE)
GIT_OPTIONS_WITH_VALUE = ("-C", "-c", "--git-dir", "--work-tree", "--namespace")
CHECKOUT_CREATE_FLAGS = ("-b", "-B")
SWITCH_CREATE_FLAGS = ("-c", "-C", "--create", "--force-create")
BRANCH_MOVE_FLAGS = ("-m", "-M", "--move", "-c", "-C", "--copy")
BRANCH_NON_CREATING_FLAGS = (
    "-d",
    "-D",
    "--delete",
    "-l",
    "--list",
    "-a",
    "--all",
    "-r",
    "--remotes",
    "-v",
    "-vv",
    "--show-current",
    "--contains",
    "--merged",
    "--no-merged",
    "-u",
    "--set-upstream-to",
    "--unset-upstream",
    "--edit-description",
)
REMOTE_REFS_PREFIX = "refs/remotes/"
LOCAL_REFS_PREFIX = "refs/heads/"

# ----- Classes ----- #


@dataclass(frozen=True)
class BranchChange:
    """
    A branch a git command is about to create, and the local branch it renames (if any).
    """
    new_name: str
    git_directory: str
    renamed_from: str = ""

# ----- Functions ----- #


def read_hook_payload() -> dict[str, object]:
    raw_payload = sys.stdin.buffer.read().decode("utf-8")
    if raw_payload.strip() == "":
        return {}
    payload = json.loads(raw_payload)
    return payload if isinstance(payload, dict) else {}


def split_words(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def strip_git_options(words: list[str]) -> tuple[list[str], str]:
    """
    Remove git's global options so the subcommand comes first.

    :param words: The words after `git`.
    :return: The remaining words and the `-C` directory (empty when not given).
    """
    git_directory = ""
    index = 0
    while index < len(words) and words[index].startswith("-"):
        option = words[index]
        if option == "-C" and index + 1 < len(words):
            git_directory = words[index + 1]
        if option in GIT_OPTIONS_WITH_VALUE:
            index += 2
            continue

        index += 1

    return words[index:], git_directory


def positional_words(words: list[str]) -> list[str]:
    return [
        word
        for word in words
        if not word.startswith("-")
    ]


def value_after_flag(words: list[str], flags: tuple[str, ...]) -> str:
    for index, word in enumerate(words):
        if word in flags and index + 1 < len(words):
            return words[index + 1]

    return ""


def branch_command_change(arguments: list[str], git_directory: str) -> BranchChange | None:
    """
    Read what `git branch ...` creates or renames.

    :param arguments: The words after `branch`.
    :param git_directory: The `-C` directory of the command.
    :return: The branch change, or None when the command doesn't create a branch.
    """
    if any(argument in BRANCH_MOVE_FLAGS for argument in arguments):
        names = positional_words(arguments)
        if len(names) == 0:
            return None
        if len(names) == 1:
            return BranchChange(
                names[0],
                git_directory,
                renamed_from="HEAD",
            )
        return BranchChange(
            names[1],
            git_directory,
            renamed_from=names[0],
        )

    if any(argument in BRANCH_NON_CREATING_FLAGS or argument.startswith("--format") for argument in arguments):
        return None
    names = positional_words(arguments)
    if len(names) == 0:
        return None
    return BranchChange(names[0], git_directory)


def push_command_change(arguments: list[str], git_directory: str) -> BranchChange | None:
    for refspec in positional_words(arguments)[1:]:
        if ":" not in refspec:
            continue

        target = refspec.split(":", 1)[1].removeprefix(LOCAL_REFS_PREFIX)
        if target != "":
            return BranchChange(target, git_directory)

    return None


def git_branch_change(words: list[str]) -> BranchChange | None:
    """
    Read the branch one git command creates or renames.

    :param words: The words of one shell segment, starting with `git`.
    :return: The branch change, or None when the command creates no branch.
    """
    remaining, git_directory = strip_git_options(words[1:])
    if len(remaining) == 0:
        return None
    subcommand, arguments = remaining[0], remaining[1:]
    if subcommand == "checkout":
        new_name = value_after_flag(arguments, CHECKOUT_CREATE_FLAGS)
    elif subcommand == "switch":
        new_name = value_after_flag(arguments, SWITCH_CREATE_FLAGS)
    elif subcommand == "worktree" and len(arguments) > 0 and arguments[0] == "add":
        new_name = value_after_flag(arguments, CHECKOUT_CREATE_FLAGS)
    elif subcommand == "branch":
        return branch_command_change(arguments, git_directory)
    elif subcommand == "push":
        return push_command_change(arguments, git_directory)
    else:
        return None

    if new_name == "":
        return None
    return BranchChange(new_name, git_directory)


def find_branch_changes(command: str) -> list[BranchChange]:
    changes: list[BranchChange] = []
    for segment in SEGMENT_SEPARATOR_PATTERN.split(command):
        words = split_words(segment.strip())
        if len(words) == 0 or Path(words[0]).stem != "git":
            continue

        change = git_branch_change(words)
        if change is not None:
            changes.append(change)

    return changes


def short_branch_name(reference: str) -> str:
    """
    Turn a full ref into a branch name without its remote.

    :param reference: e.g. `refs/remotes/origin/BTRC-1-x` or `refs/heads/BTRC-1-x`.
    :return: The branch name, e.g. `BTRC-1-x`.
    """
    if reference.startswith(REMOTE_REFS_PREFIX):
        return reference.removeprefix(REMOTE_REFS_PREFIX).split("/", 1)[-1]
    return reference.removeprefix(LOCAL_REFS_PREFIX)


def existing_branches(cwd: Path) -> list[tuple[str, str]]:
    """
    List local and remote branches after refreshing the remote ones.

    :param cwd: The repository directory.
    :return: (full ref, short name) pairs.
    """
    run_git(["fetch", "--prune", "--quiet"], cwd)
    references = run_git(
        ["for-each-ref", "--format=%(refname)", LOCAL_REFS_PREFIX, REMOTE_REFS_PREFIX],
        cwd,
    )
    branches: list[tuple[str, str]] = []
    for reference in references.output.splitlines():
        reference = reference.strip()
        short_name = short_branch_name(reference)
        if reference == "" or short_name == "HEAD":
            continue

        branches.append((reference, short_name))

    return branches


def current_branch(cwd: Path) -> str:
    return run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd).output.strip()


def conflicting_branches(change: BranchChange, cwd: Path) -> list[str]:
    """
    Find other branches with the same BTRC-<n> as the new branch.

    :param change: The branch about to be created or renamed.
    :param cwd: The repository directory.
    :return: The conflicting refs; empty when the new name has no BTRC-<n> or none conflicts.
    """
    ticket_match = TICKET_PATTERN.search(change.new_name)
    if ticket_match is None:
        return []
    renamed_from = change.renamed_from
    if renamed_from == "HEAD":
        renamed_from = current_branch(cwd)
    conflicts: list[str] = []
    for reference, short_name in existing_branches(cwd):
        if short_name == change.new_name:
            continue

        is_renamed_local = reference == f"{LOCAL_REFS_PREFIX}{renamed_from}"
        if is_renamed_local:
            continue

        other_match = TICKET_PATTERN.search(short_name)
        if other_match is not None and other_match.group("number") == ticket_match.group("number"):
            conflicts.append(reference)

    return conflicts


def block(message: str) -> int:
    sys.stderr.buffer.write((message + "\n").encode("utf-8"))
    sys.stderr.flush()
    return BLOCKING_EXIT_CODE


def main() -> int:
    if is_reviewer_session():
        return 0
    payload = read_hook_payload()
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    command = tool_input.get("command")
    if not isinstance(command, str):
        return 0
    payload_directory = Path(str(payload.get("cwd", ".")))
    for change in find_branch_changes(command):
        cwd = payload_directory
        if change.git_directory != "":
            cwd = payload_directory / change.git_directory
        conflicts = conflicting_branches(change, cwd)
        if len(conflicts) > 0:
            return block(
                f"Blocked: '{change.new_name}' would be a second branch for the same ticket. "
                f"Existing: {', '.join(conflicts)}. Use the existing branch. "
                "If you really need a second one, ask the user to create it.",
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
