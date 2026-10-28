#!/usr/bin/env python3
"""
Finds what a branch changed compared to its base: files, added lines, and changed existing lines.

:author: midnight-workflow
:date: 28/10/2026
"""
# ----- Imports ----- #

import re
from dataclasses import dataclass, field
from pathlib import Path

import command_runner

# ----- Consts ----- #

GIT_TIMEOUT_SECONDS = 60
GIT_CONFIG_ARGUMENTS = ("-c", "core.quotePath=false")
GIT_ENVIRONMENT = {"GIT_TERMINAL_PROMPT": "0"}
DIFF_ARGUMENTS = ("-U0", "--no-color", "--no-ext-diff", "--no-renames", "--src-prefix=a/", "--dst-prefix=b/")
HUNK_PATTERN = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@",
)
NEW_FILE_PREFIX = "+++ "
OLD_FILE_PREFIX = "--- "
DEV_NULL_MARKER = "/dev/null"
FALLBACK_BASES = ("master", "main")
C_ESCAPES = {
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
    '"': '"',
}

# ----- Classes ----- #


class GitError(Exception):
    """
    Raised when a git command the checks depend on fails.
    """
    pass


@dataclass(frozen=True)
class Hunk:
    """
    One `@@` block of a zero-context diff.
    """
    path: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    added_texts: tuple[str, ...]

    @property
    def added_lines(self) -> range:
        return range(self.new_start, self.new_start + self.new_count)


@dataclass(frozen=True)
class LineFilter:
    """
    The lines of one file that count as changed. A whole-file filter covers new and untracked files.
    """
    whole_file: bool
    lines: frozenset[int] = field(default_factory=frozenset)

    def covers(self, line: int) -> bool:
        if self.whole_file:
            return True
        return line in self.lines

    def covers_any(self, first_line: int, last_line: int) -> bool:
        return any(
            self.covers(line)
            for line in range(first_line, last_line + 1)
        )

# ----- Functions ----- #


def run_git(arguments: list[str], cwd: Path, timeout: int = GIT_TIMEOUT_SECONDS) -> command_runner.CommandResult:
    return command_runner.run_command(
        ["git", *GIT_CONFIG_ARGUMENTS, *arguments],
        cwd,
        timeout,
        GIT_ENVIRONMENT,
    )


def require_git(arguments: list[str], cwd: Path) -> str:
    """
    Run a git command whose output the checks need.

    :param arguments: The git arguments.
    :param cwd: The directory to run in.
    :return: The command's stdout.
    :raises GitError: When git fails, so its warnings are never read as data.
    """
    result = run_git(arguments, cwd)
    if not result.succeeded:
        raise GitError(
            f"git {' '.join(arguments)} failed in {cwd}: {result.stderr.strip()}",
        )
    return result.stdout


def repository_root(cwd: Path) -> Path | None:
    result = run_git(["rev-parse", "--show-toplevel"], cwd)
    if not result.succeeded:
        return None
    return Path(result.stdout.strip())


def default_base(cwd: Path) -> str:
    """
    Guess the base branch when no feature names one.

    :param cwd: A directory inside the repository.
    :return: The branch origin/HEAD points to, else master or main, else HEAD.
    """
    origin_head = run_git(
        ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        cwd,
    )
    if origin_head.succeeded:
        return origin_head.stdout.strip().removeprefix("origin/")

    for candidate in FALLBACK_BASES:
        if run_git(
            ["rev-parse", "--verify", "--quiet", candidate],
            cwd,
        ).succeeded:
            return candidate

    return "HEAD"


def is_ancestor(ancestor: str, descendant: str, cwd: Path) -> bool:
    return run_git(
        ["merge-base", "--is-ancestor", ancestor, descendant],
        cwd,
    ).succeeded


def diff_base_commit(base: str, cwd: Path) -> str:
    """
    Find the commit the branch started from, so changes others made on the base don't count.

    :param base: The base branch name, e.g. `master`.
    :param cwd: A directory inside the repository.
    :return: The newer of the merge-bases with the local base and with origin/base.
    :raises GitError: When neither the base nor origin/base exists.
    """
    merge_bases: list[str] = []
    for candidate in (base, f"origin/{base}"):
        merge_base = run_git(["merge-base", "HEAD", candidate], cwd)
        if merge_base.succeeded:
            merge_bases.append(merge_base.stdout.strip())

    if len(merge_bases) == 0:
        raise GitError(
            f"Base branch '{base}' (or origin/{base}) not found in {cwd}.",
        )
    newest = merge_bases[0]
    for merge_base in merge_bases[1:]:
        if is_ancestor(
            newest,
            merge_base,
            cwd,
        ):
            newest = merge_base

    return newest


def unquote_git_path(raw_path: str) -> str:
    """
    Undo git's C-style quoting of a path (used for quotes, backslashes and control characters).

    :param raw_path: The path as git printed it, maybe in double quotes.
    :return: The real path.
    """
    if not (raw_path.startswith('"') and raw_path.endswith('"') and len(raw_path) >= 2):
        return raw_path
    quoted = raw_path[1:-1]
    octal_bytes = bytearray()
    index = 0
    while index < len(quoted):
        character = quoted[index]
        if character != "\\" or index + 1 >= len(quoted):
            octal_bytes.extend(character.encode("utf-8"))
            index += 1
            continue

        escape = quoted[index + 1]
        if escape.isdigit():
            octal_bytes.append(int(quoted[index + 1:index + 4], 8))
            index += 4
            continue

        octal_bytes.extend(C_ESCAPES.get(escape, escape).encode("utf-8"))
        index += 2

    return octal_bytes.decode("utf-8", errors="replace")


def diff_header_path(diff_line: str, prefix: str) -> str:
    """
    Read the path of a `--- a/x` or `+++ b/x` line.

    :param diff_line: The header line.
    :param prefix: `--- ` or `+++ `.
    :return: The path without its a/ or b/ prefix and without the tab git adds after names with spaces.
    """
    raw_path = unquote_git_path(diff_line.removeprefix(prefix).removesuffix("\t"))
    if raw_path == DEV_NULL_MARKER:
        return ""
    return raw_path[2:]


def parse_hunks(diff_output: str) -> list[Hunk]:
    """
    Split `git diff -U0` output into hunks.

    :param diff_output: The diff text, made with `--src-prefix=a/ --dst-prefix=b/`.
    :return: Every hunk with its file (repository-relative), line ranges and added line texts.
    """
    hunks: list[Hunk] = []
    current_path = ""
    old_path = ""
    current_header: re.Match[str] | None = None
    added_texts: list[str] = []
    for diff_line in [*diff_output.splitlines(), "@@END"]:
        is_hunk_end = diff_line.startswith("@@") or diff_line.startswith("diff --git")
        if is_hunk_end and current_header is not None:
            hunks.append(
                Hunk(
                    current_path,
                    int(current_header.group("old_start")),
                    count_or_one(current_header.group("old_count")),
                    int(current_header.group("new_start")),
                    count_or_one(current_header.group("new_count")),
                    tuple(added_texts),
                ),
            )
            current_header = None
            added_texts = []

        if current_header is None and diff_line.startswith(OLD_FILE_PREFIX):
            old_path = diff_header_path(diff_line, OLD_FILE_PREFIX)
        elif current_header is None and diff_line.startswith(NEW_FILE_PREFIX):
            current_path = diff_header_path(diff_line, NEW_FILE_PREFIX)
            if current_path == "":
                current_path = old_path
        elif diff_line.startswith("@@"):
            current_header = HUNK_PATTERN.match(diff_line)
        elif current_header is not None and diff_line.startswith("+"):
            added_texts.append(diff_line[1:])

    return hunks


def count_or_one(raw_count: str | None) -> int:
    if raw_count is None:
        return 1
    return int(raw_count)


def is_tracked(path: Path, cwd: Path) -> bool:
    return run_git(
        ["ls-files", "--error-unmatch", "--", str(path)],
        cwd,
    ).succeeded


def changed_line_filter(path: Path, base_commit: str) -> LineFilter:
    """
    Find the lines of one file that differ from the base commit.

    :param path: The file, absolute or relative to the current directory.
    :param base_commit: The commit to compare with.
    :return: The added lines; the whole file when it's untracked or not in a repository.
    :raises GitError: When the diff itself fails.
    """
    directory = path.resolve().parent
    if repository_root(directory) is None or not is_tracked(path.resolve(), directory):
        return LineFilter(whole_file=True)
    diff = require_git(
        ["diff", *DIFF_ARGUMENTS, base_commit, "--", str(path.resolve())],
        directory,
    )
    added_lines = {
        line
        for hunk in parse_hunks(diff)
        for line in hunk.added_lines
    }
    return LineFilter(whole_file=False, lines=frozenset(added_lines))


def branch_hunks(base_commit: str, cwd: Path) -> list[Hunk]:
    return parse_hunks(
        require_git(["diff", *DIFF_ARGUMENTS, base_commit], cwd),
    )


def split_nul_list(output: str) -> list[str]:
    return [
        entry
        for entry in output.split("\0")
        if entry != ""
    ]


def untracked_files(cwd: Path) -> list[str]:
    return split_nul_list(
        require_git(
            ["ls-files", "-z", "--others", "--exclude-standard", "--full-name"],
            cwd,
        ),
    )


def changed_files(base_commit: str, cwd: Path) -> list[str]:
    """
    List every file the branch changed, committed or not: added, modified, deleted (renames count as both paths), and new untracked files.

    :param base_commit: The commit to compare with.
    :param cwd: A directory inside the repository.
    :return: Repository-relative paths, sorted.
    """
    entries = split_nul_list(
        require_git(
            ["diff", "--name-status", "-z", "--no-renames", base_commit],
            cwd,
        ),
    )
    names = set(entries[1::2])
    names.update(untracked_files(cwd))
    return sorted(names)


def branch_line_filters(base_commit: str, cwd: Path) -> dict[str, LineFilter]:
    """
    Build a changed-lines filter for every file the branch changed.

    :param base_commit: The commit to compare with.
    :param cwd: A directory inside the repository.
    :return: Repository-relative path to its filter.
    """
    added_lines_by_path: dict[str, set[int]] = {}
    for hunk in branch_hunks(base_commit, cwd):
        added_lines_by_path.setdefault(hunk.path, set()).update(hunk.added_lines)

    filters = {
        path: LineFilter(whole_file=False, lines=frozenset(lines))
        for path, lines in added_lines_by_path.items()
    }
    for path in untracked_files(cwd):
        filters[path] = LineFilter(whole_file=True)

    return filters


def changed_existing_lines(base_commit: str, cwd: Path) -> list[str]:
    """
    List the places where the branch replaced or deleted lines that already existed.

    :param base_commit: The commit to compare with.
    :param cwd: A directory inside the repository.
    :return: `file:line` entries (new line numbers), with a note for pure deletions.
    """
    entries: list[str] = []
    for hunk in branch_hunks(base_commit, cwd):
        if hunk.old_count == 0:
            continue

        if hunk.new_count == 0:
            entries.append(
                f"{hunk.path}:{hunk.new_start} ({hunk.old_count} existing line(s) deleted after this line)",
            )
            continue

        last_line = hunk.new_start + hunk.new_count - 1
        line_range = str(hunk.new_start) if last_line == hunk.new_start else f"{hunk.new_start}-{last_line}"
        entries.append(
            f"{hunk.path}:{line_range} (replaces {hunk.old_count} existing line(s))",
        )

    return entries


def file_at_commit(commit: str, relative_path: str, cwd: Path) -> str | None:
    """
    Read a file as it was in a commit.

    :param commit: The commit, e.g. the merge-base.
    :param relative_path: Repository-relative path.
    :param cwd: A directory inside the repository.
    :return: The file's text, or None when the file didn't exist there.
    """
    result = run_git(["show", f"{commit}:{relative_path}"], cwd)
    if not result.succeeded:
        return None
    return result.stdout
