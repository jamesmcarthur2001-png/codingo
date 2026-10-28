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
HUNK_PATTERN = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@",
)
NEW_FILE_PREFIX = "+++ b/"
OLD_FILE_PREFIX = "--- a/"
DEV_NULL_MARKER = "/dev/null"
FALLBACK_BASES = ("master", "main")

# ----- Classes ----- #


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

# ----- Functions ----- #


def run_git(arguments: list[str], cwd: Path) -> command_runner.CommandResult:
    return command_runner.run_command(
        ["git", *arguments],
        cwd,
        GIT_TIMEOUT_SECONDS,
    )


def repository_root(cwd: Path) -> Path | None:
    result = run_git(["rev-parse", "--show-toplevel"], cwd)
    if not result.succeeded:
        return None
    return Path(result.output.strip())


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
        return origin_head.output.strip().removeprefix("origin/")

    for candidate in FALLBACK_BASES:
        if run_git(
            ["rev-parse", "--verify", "--quiet", candidate],
            cwd,
        ).succeeded:
            return candidate

    return "HEAD"


def diff_base_commit(base: str, cwd: Path) -> str:
    """
    Find the commit the branch started from, so changes others made on the base don't count.

    :param base: The base branch name, e.g. `master`.
    :param cwd: A directory inside the repository.
    :return: The merge-base commit with the base (or origin/base), else HEAD.
    """
    for candidate in (base, f"origin/{base}"):
        merge_base = run_git(["merge-base", "HEAD", candidate], cwd)
        if merge_base.succeeded:
            return merge_base.output.strip()

    return "HEAD"


def parse_hunks(diff_output: str) -> list[Hunk]:
    """
    Split `git diff -U0` output into hunks.

    :param diff_output: The diff text.
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

        if diff_line.startswith(OLD_FILE_PREFIX):
            old_path = diff_line.removeprefix(OLD_FILE_PREFIX)
        elif diff_line.startswith(NEW_FILE_PREFIX):
            current_path = diff_line.removeprefix(NEW_FILE_PREFIX)
        elif diff_line.startswith("+++ ") and DEV_NULL_MARKER in diff_line:
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
    """
    directory = path.resolve().parent
    if repository_root(directory) is None or not is_tracked(path.resolve(), directory):
        return LineFilter(whole_file=True)
    diff = run_git(
        ["diff", "-U0", "--no-color", "--no-ext-diff", base_commit, "--", str(path.resolve())],
        directory,
    )
    added_lines = {
        line
        for hunk in parse_hunks(diff.output)
        for line in hunk.added_lines
    }
    return LineFilter(whole_file=False, lines=frozenset(added_lines))


def branch_hunks(base_commit: str, cwd: Path) -> list[Hunk]:
    diff = run_git(
        ["diff", "-U0", "--no-color", "--no-ext-diff", base_commit],
        cwd,
    )
    return parse_hunks(diff.output)


def untracked_files(cwd: Path) -> list[str]:
    result = run_git(
        ["ls-files", "--others", "--exclude-standard", "--full-name"],
        cwd,
    )
    return [
        line.strip()
        for line in result.output.splitlines()
        if line.strip() != ""
    ]


def changed_files(base_commit: str, cwd: Path) -> list[str]:
    """
    List every file the branch changed, committed or not, including new untracked files.

    :param base_commit: The commit to compare with.
    :param cwd: A directory inside the repository.
    :return: Repository-relative paths with forward slashes, sorted.
    """
    tracked = run_git(
        ["diff", "--name-only", "--no-color", base_commit],
        cwd,
    )
    names = {
        line.strip()
        for line in tracked.output.splitlines()
        if line.strip() != ""
    }
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
