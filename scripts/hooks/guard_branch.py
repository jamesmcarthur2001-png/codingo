#!/usr/bin/env python3
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
PUNCTUATION_CHARACTERS = "();<>|&\n"
SHELL_WHITESPACE = " \t\r"
SEGMENT_SEPARATORS = frozenset(
    {";", "&", "&&", "|", "||", "|&", "\n", "(", ")", ";;"},
)
ASSIGNMENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
COMMAND_PREFIXES = frozenset(
    {"sudo", "command", "exec", "env", "nice", "nohup", "time", "builtin"},
)
SHELL_NAMES = frozenset({"bash", "sh", "zsh", "dash"})
TICKET_PATTERN = re.compile(r"BTRC-(?P<number>\d+)(?!\d)", re.IGNORECASE)
GIT_OPTIONS_WITH_VALUE = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path")
CHECKOUT_CREATE_FLAGS = ("-b", "-B", "--orphan")
SWITCH_CREATE_FLAGS = ("-c", "-C", "--create", "--force-create", "--orphan")
WORKTREE_CREATE_FLAGS = ("-b", "-B", "--orphan")
WORKTREE_NO_BRANCH_FLAGS = ("-d", "--detach")
WORKTREE_OPTIONS_WITH_VALUE = ("--reason",)
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
    "--no-contains",
    "--merged",
    "--no-merged",
    "--points-at",
    "-u",
    "--set-upstream-to",
    "--unset-upstream",
    "--edit-description",
)
PUSH_DELETE_FLAGS = ("-d", "--delete")
PUSH_OPTIONS_WITH_VALUE = ("-o", "--push-option", "--repo", "--receive-pack", "--exec")
REMOTE_REFS_PREFIX = "refs/remotes/"
LOCAL_REFS_PREFIX = "refs/heads/"
FETCH_TIMEOUT_SECONDS = 15
FETCH_ARGUMENTS = [
    "-c",
    "core.sshCommand=ssh -oBatchMode=yes -oConnectTimeout=5",
    "fetch",
    "--prune",
    "--quiet",
]

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


def tokenize(command: str) -> list[str]:
    """
    Split a shell command into words and operators, keeping quoted text together.

    :param command: The Bash command.
    :return: The tokens; operators such as `&&`, `;`, `(` and newlines are tokens of their own.
    """
    lexer = shlex.shlex(
        command,
        posix=True,
        punctuation_chars=PUNCTUATION_CHARACTERS,
    )
    lexer.whitespace_split = True
    lexer.whitespace = SHELL_WHITESPACE
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return command.split()


def split_segments(tokens: list[str]) -> list[list[str]]:
    """
    Split tokens into simple commands, dropping `#` comments.

    :param tokens: The command's tokens.
    :return: One word list per simple command.
    """
    segments: list[list[str]] = [[]]
    is_in_comment = False
    for token in tokens:
        if token in SEGMENT_SEPARATORS:
            if token == "\n":
                is_in_comment = False
            segments.append([])
            continue

        if is_in_comment:
            continue

        if token.startswith("#"):
            is_in_comment = True
            continue

        segments[-1].append(token)

    return [
        segment
        for segment in segments
        if len(segment) > 0
    ]


def strip_command_prefixes(words: list[str]) -> list[str]:
    """
    Remove `VAR=value`, `sudo`, `env` and similar words in front of the real program.

    :param words: One simple command.
    :return: The words starting at the real program.
    """
    index = 0
    while index < len(words):
        word = words[index]
        if ASSIGNMENT_PATTERN.match(word) is not None or word in COMMAND_PREFIXES:
            index += 1
            continue

        if index > 0 and words[index - 1] in COMMAND_PREFIXES and word.startswith("-"):
            index += 1
            continue

        break

    return words[index:]


def shell_script_argument(words: list[str]) -> str | None:
    """
    Find the script of `bash -c "<script>"`.

    :param words: A command starting with a shell name.
    :return: The script, or None when the shell isn't given one with -c.
    """
    for index, word in enumerate(words[1:], start=1):
        is_c_flag = word.startswith("-") and not word.startswith("--") and "c" in word
        if is_c_flag and index + 1 < len(words):
            return words[index + 1]

    return None


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


def flag_value(words: list[str], flags: tuple[str, ...]) -> str:
    """
    Read the value of a flag in any of its forms: `-b X`, `-bX`, `--create X`, `--create=X`.

    :param words: The subcommand's arguments.
    :param flags: The flag spellings that take the branch name.
    :return: The value, or an empty string when none of the flags is present.
    """
    for index, word in enumerate(words):
        for flag in flags:
            if word == flag and index + 1 < len(words):
                return words[index + 1]
            if flag.startswith("--") and word.startswith(f"{flag}="):
                return word.removeprefix(f"{flag}=")
            is_attached_short = not flag.startswith("--") and len(word) > len(flag) and word.startswith(flag) and not word.startswith("--")
            if is_attached_short:
                return word[len(flag):]

    return ""


def positional_words(words: list[str], options_with_value: tuple[str, ...] = ()) -> list[str]:
    positional: list[str] = []
    skip_next = False
    for word in words:
        if skip_next:
            skip_next = False
            continue

        if word in options_with_value:
            skip_next = True
            continue

        if not word.startswith("-"):
            positional.append(word)

    return positional


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

    has_non_creating_flag = any(
        argument in BRANCH_NON_CREATING_FLAGS or argument.split("=", 1)[0] in BRANCH_NON_CREATING_FLAGS or argument.startswith("--format")
        for argument in arguments
    )
    if has_non_creating_flag:
        return None
    names = positional_words(arguments)
    if len(names) == 0:
        return None
    return BranchChange(names[0], git_directory)


def push_command_change(arguments: list[str], git_directory: str) -> BranchChange | None:
    """
    Read the remote branch `git push <remote> <src>:<dst>` creates.

    :param arguments: The words after `push`.
    :param git_directory: The `-C` directory of the command.
    :return: The created branch; None for deletes and pushes without a renaming refspec.
    """
    if any(argument in PUSH_DELETE_FLAGS for argument in arguments):
        return None
    for refspec in positional_words(arguments, PUSH_OPTIONS_WITH_VALUE)[1:]:
        if ":" not in refspec:
            continue

        source, target = refspec.removeprefix("+").split(":", 1)
        if source == "":
            continue

        target = target.removeprefix(LOCAL_REFS_PREFIX)
        if target != "":
            return BranchChange(target, git_directory)

    return None


def worktree_command_change(arguments: list[str], git_directory: str) -> BranchChange | None:
    """
    Read the branch `git worktree add` creates: the `-b` name, or the path's last folder when no branch is given.

    :param arguments: The words after `worktree`.
    :param git_directory: The `-C` directory of the command.
    :return: The created branch, or None.
    """
    if len(arguments) == 0 or arguments[0] != "add":
        return None
    add_arguments = arguments[1:]
    new_name = flag_value(add_arguments, WORKTREE_CREATE_FLAGS)
    if new_name != "":
        return BranchChange(new_name, git_directory)
    if any(argument in WORKTREE_NO_BRANCH_FLAGS for argument in add_arguments):
        return None
    positional = positional_words(add_arguments, WORKTREE_OPTIONS_WITH_VALUE)
    if len(positional) != 1:
        return None
    return BranchChange(
        Path(positional[0].rstrip("/")).name,
        git_directory,
    )


def git_branch_change(words: list[str]) -> BranchChange | None:
    """
    Read the branch one git command creates or renames.

    :param words: One simple command, starting with `git`.
    :return: The branch change, or None when the command creates no branch.
    """
    remaining, git_directory = strip_git_options(words[1:])
    if len(remaining) == 0:
        return None
    subcommand, arguments = remaining[0], remaining[1:]
    if subcommand == "branch":
        return branch_command_change(arguments, git_directory)
    if subcommand == "push":
        return push_command_change(arguments, git_directory)
    if subcommand == "worktree":
        return worktree_command_change(arguments, git_directory)
    flags_by_subcommand = {
        "checkout": CHECKOUT_CREATE_FLAGS,
        "switch": SWITCH_CREATE_FLAGS,
    }
    flags = flags_by_subcommand.get(subcommand)
    if flags is None:
        return None
    new_name = flag_value(arguments, flags)
    if new_name == "":
        return None
    return BranchChange(new_name, git_directory)


def find_branch_changes(command: str) -> list[BranchChange]:
    """
    Find every branch a Bash command would create or rename, including inside `bash -c "..."`.

    :param command: The Bash command.
    :return: The branch changes, in order.
    """
    changes: list[BranchChange] = []
    for segment in split_segments(tokenize(command)):
        words = strip_command_prefixes(segment)
        if len(words) == 0:
            continue

        program = Path(words[0]).name
        if program in SHELL_NAMES:
            script = shell_script_argument(words)
            if script is not None:
                changes.extend(find_branch_changes(script))
            continue

        if program != "git":
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


def existing_branches(cwd: Path) -> tuple[list[tuple[str, str]], bool]:
    """
    List local and remote branches after trying to refresh the remote ones.

    :param cwd: The repository directory.
    :return: (full ref, short name) pairs, and whether the fetch worked (if not, remote refs may be stale).
    """
    fetched = run_git(
        FETCH_ARGUMENTS,
        cwd,
        FETCH_TIMEOUT_SECONDS,
    ).succeeded
    references = run_git(
        ["for-each-ref", "--format=%(refname)", LOCAL_REFS_PREFIX, REMOTE_REFS_PREFIX],
        cwd,
    )
    branches: list[tuple[str, str]] = []
    for raw_reference in references.stdout.splitlines():
        reference = raw_reference.strip()
        short_name = short_branch_name(reference)
        if reference == "" or short_name == "HEAD":
            continue

        branches.append((reference, short_name))

    return branches, fetched


def current_branch(cwd: Path) -> str:
    return run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd).stdout.strip()


def conflicting_branches(change: BranchChange, cwd: Path) -> tuple[list[str], bool]:
    """
    Find other branches with the same BTRC-<n> as the new branch.

    :param change: The branch about to be created or renamed.
    :param cwd: The repository directory.
    :return: The conflicting refs (empty when the new name has no BTRC-<n>), and whether the remote refs are fresh.
    """
    ticket_match = TICKET_PATTERN.search(change.new_name)
    if ticket_match is None:
        return [], True
    renamed_from = change.renamed_from
    if renamed_from == "HEAD":
        renamed_from = current_branch(cwd)
    branches, fetched = existing_branches(cwd)
    conflicts: list[str] = []
    for reference, short_name in branches:
        if short_name == change.new_name:
            continue

        is_renamed_local = reference == f"{LOCAL_REFS_PREFIX}{renamed_from}"
        if is_renamed_local:
            continue

        other_match = TICKET_PATTERN.search(short_name)
        if other_match is not None and other_match.group("number") == ticket_match.group("number"):
            conflicts.append(reference)

    return conflicts, fetched


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
        conflicts, fetched = conflicting_branches(change, cwd)
        if len(conflicts) == 0:
            continue

        stale_note = "" if fetched else " (git fetch failed, so remote refs may be stale)"
        return block(
            f"Blocked: '{change.new_name}' would be a second branch for the same ticket. "
            f"Existing{stale_note}: {', '.join(conflicts)}. Use the existing branch. "
            "If you really need a second one, ask the user to create it.",
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
