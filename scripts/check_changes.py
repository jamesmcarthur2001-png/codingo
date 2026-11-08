#!/usr/bin/env python3
"""
Runs the changed-line checks (conventions, comments, Vue rules, ruff, eslint, mypy, suppressions) on a branch, and checks a built slice's file scope.

Usage: python3 check_changes.py [--base <base>]            before every commit to a feature branch
       python3 check_changes.py --slice BTRC-1234 <slice>   after building a slice of /feature
Before a commit the base is `--base`, else the `Base:` of the feature this checkout belongs to, else the branch origin/HEAD points to.
With --slice it also fails on changed files outside plan.md's slices 1..n, lists changed existing lines, and advances
`Slice`/`Phase` in state.md on a pass.
Exit codes: 0 passed, 1 problems found, 2 setup error (no feature, no such slice, not a git repository, or git failed).

:author: claude-workflow
:date: 03/11/2026
"""
# ----- Imports ----- #

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from feature_state import (
    STATE_FILE_NAME,
    FeatureNotFoundError,
    FeatureState,
    find_active_feature,
    load_feature_state,
)
from git_changes import (
    GitError,
    LineFilter,
    branch_line_filters,
    changed_existing_lines,
    changed_files,
    default_base,
    diff_base_commit,
    file_at_commit,
    repository_root,
)
from line_checks import PYTHON_SUFFIXES, changed_line_problems, mypy_problems

# ----- Consts ----- #

CHECK_WORKERS = 8
FAILED_EXIT_CODE = 1
SETUP_ERROR_EXIT_CODE = 2
FEATURES_PREFIX = "docs/features/"
SLICE_HEADER_PATTERN = re.compile(
    r"^#{2,3}\s+Slice\s+(?P<number>\d+)\b",
    re.IGNORECASE,
)
HEADER_PATTERN = re.compile(r"^#{1,6}\s")
FILES_LABEL_PATTERN = re.compile(r"^\**Files\**\s*:", re.IGNORECASE)
LABEL_PATTERN = re.compile(r"^\**[A-Z][A-Za-z ]*\**\s*:")
BULLET_PATTERN = re.compile(r"^\s*[-*]\s+(?P<entry>.+)$")
PLAN_FILE_NAME = "plan.md"

# ----- Classes ----- #


@dataclass
class BranchReport:
    """
    What the changed-line checks found on the branch.
    """
    problems: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    existing_line_changes: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)

    @property
    def has_passed(self) -> bool:
        return len(self.problems) == 0 and len(self.out_of_scope) == 0

    def render(self) -> str:
        sections: list[str] = []
        if len(self.out_of_scope) > 0:
            sections.append(
                "Files outside the allowed list (revert them, or add them to the slice's Files in plan.md with a reason):\n"
                + "\n".join(f"- {path}" for path in self.out_of_scope),
            )

        if len(self.problems) > 0:
            sections.append(
                "Problems on changed lines:\n" + "\n".join(f"- {problem}" for problem in self.problems),
            )

        if len(self.existing_line_changes) > 0:
            sections.append(
                "Existing lines you changed (not a failure: check each one was needed for the task, else restore it):\n"
                + "\n".join(f"- {entry}" for entry in self.existing_line_changes),
            )

        return "\n\n".join(sections)

# ----- Functions ----- #


def clean_path_entry(entry: str) -> str:
    """
    Turn one bullet of a Files list into a path or glob.

    :param entry: The bullet text, e.g. "`services/evermore/app/x.py` (new)".
    :return: The path with backticks, notes and backslashes removed.
    """
    backtick_match = re.search(r"`([^`]+)`", entry)
    path = backtick_match.group(1) if backtick_match is not None else entry.split()[0]
    return path.strip().replace("\\", "/").removeprefix("./")


def parse_plan_slices(plan_text: str) -> dict[int, list[str]]:
    """
    Read the allowed files of every slice in plan.md.

    :param plan_text: The plan's text. Each slice is a `## Slice <n>` header followed by a `Files:` bullet list.
    :return: Slice number to its paths and globs.
    """
    slices: dict[int, list[str]] = {}
    current_slice: int | None = None
    is_in_files = False
    for plan_line in plan_text.splitlines():
        slice_match = SLICE_HEADER_PATTERN.match(plan_line)
        if slice_match is not None:
            current_slice = int(slice_match.group("number"))
            slices[current_slice] = []
            is_in_files = False
            continue

        if HEADER_PATTERN.match(plan_line) is not None:
            current_slice = None
            continue

        if current_slice is None:
            continue

        stripped_line = plan_line.strip()
        if FILES_LABEL_PATTERN.match(stripped_line) is not None:
            is_in_files = True
            continue

        if LABEL_PATTERN.match(stripped_line) is not None:
            is_in_files = False
            continue

        bullet_match = BULLET_PATTERN.match(plan_line)
        if is_in_files and bullet_match is not None:
            slices[current_slice].append(clean_path_entry(bullet_match.group("entry")))

    return slices


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """
    Turn a plan glob into a regex where `*` and `?` stay inside one folder and `**` crosses folders.

    :param pattern: e.g. `frontend/src/**/*.vue`.
    :return: The compiled pattern, matched against the whole path.
    """
    regex_parts: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            regex_parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            regex_parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            regex_parts.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            regex_parts.append("[^/]")
            index += 1
        else:
            regex_parts.append(re.escape(pattern[index]))
            index += 1

    return re.compile("".join(regex_parts))


def matches_allowed(path: str, allowed_patterns: list[str]) -> bool:
    """
    Tell whether a changed file is covered by an allowed path, folder or glob.

    :param path: Repository-relative path with forward slashes.
    :param allowed_patterns: Paths, folders ending in `/`, or globs from the plan.
    :return: Whether the file is allowed.
    """
    for pattern in allowed_patterns:
        if pattern.endswith("/") and path.startswith(pattern):
            return True

        if path == pattern or glob_to_regex(pattern).fullmatch(path) is not None:
            return True

    return False


def out_of_scope_files(changed: list[str], allowed_patterns: list[str]) -> list[str]:
    return [
        path
        for path in changed
        if not matches_allowed(path, allowed_patterns)
    ]


def allowed_for_slice(feature_directory: Path, slice_number: int) -> list[str]:
    """
    Collect the files slices 1..n may touch, since earlier slices' files stay changed.

    :param feature_directory: The feature's directory, holding plan.md.
    :param slice_number: The slice that was just built.
    :return: The allowed paths and globs.
    """
    plan_path = feature_directory / PLAN_FILE_NAME
    if not plan_path.is_file():
        return []
    slices = parse_plan_slices(plan_path.read_text(encoding="utf-8"))
    return [
        pattern
        for number, patterns in sorted(slices.items())
        if number <= slice_number
        for pattern in patterns
    ]



def changed_line_report(code_root: Path, base: str) -> tuple[list[str], list[str]]:
    """
    Run the changed-line checks on everything a branch changed against its base.

    :param code_root: The checkout to check.
    :param base: The base branch.
    :return: The changed files, and one line per problem on a changed line.
    :raises GitError: When git can't find the base or the changes.
    """
    base_commit = diff_base_commit(base, code_root)
    changed = [
        path
        for path in changed_files(base_commit, code_root)
        if not path.startswith(FEATURES_PREFIX)
    ]
    line_filters = branch_line_filters(base_commit, code_root)
    absolute_filters: dict[Path, LineFilter] = {}
    base_sources: dict[Path, str | None] = {}
    for relative_path in changed:
        path = code_root / relative_path
        line_filter = line_filters.get(relative_path)
        if not path.is_file() or line_filter is None:
            continue

        absolute_filters[path.resolve()] = line_filter
        base_sources[path] = file_at_commit(
            base_commit,
            relative_path,
            code_root,
        )

    python_paths = [
        path
        for path in absolute_filters
        if path.suffix in PYTHON_SUFFIXES
    ]
    problems: list[str] = []
    with ThreadPoolExecutor(max_workers=CHECK_WORKERS) as executor:
        mypy_future = executor.submit(
            mypy_problems,
            python_paths,
            absolute_filters,
        ) if len(python_paths) > 0 else None
        file_futures = [
            executor.submit(
                changed_line_problems,
                path,
                absolute_filters[path.resolve()],
                base_source,
            )
            for path, base_source in base_sources.items()
        ]
        for file_future in file_futures:
            problems.extend(problem.text for problem in file_future.result())

        if mypy_future is not None:
            problems.extend(problem.text for problem in mypy_future.result())

    return changed, problems


def check_branch(state: FeatureState, allowed_patterns: list[str]) -> BranchReport:
    """
    Run the changed-line checks and the scope check on everything the branch changed.

    :param state: The feature's state, naming its base and worktree.
    :param allowed_patterns: The files the plan allows so far.
    :return: The problems, out-of-scope files and changed existing lines.
    """
    code_root = state.code_root()
    changed, problems = changed_line_report(
        code_root,
        state.field("Base"),
    )
    report = BranchReport(
        changed=changed,
        out_of_scope=out_of_scope_files(changed, allowed_patterns),
        existing_line_changes=changed_existing_lines(
            diff_base_commit(state.field("Base"), code_root),
            code_root,
        ),
    )
    report.problems.extend(problems)
    return report


def record_slice_result(state: FeatureState, slice_number: int, report: BranchReport) -> str:
    """
    Advance state.md after a passing slice, or count the failed try.

    :param state: The feature's state.
    :param slice_number: The checked slice.
    :param report: The check's result.
    :return: A line telling the orchestrator what happens next.
    """
    if not report.has_passed:
        failed_runs = state.record_failure(f"SLICE-{slice_number}")
        state.save()
        if state.is_finished():
            return f"Slice {slice_number} failed {failed_runs} times: state.md is now BLOCKED. Stop."
        return f"Slice {slice_number} failed (try {failed_runs}). Fix the items above and run this again."

    state.reset_tries()
    state.log(f"slice {slice_number} passed")
    slice_count = state.number_field("Slices")
    if slice_number >= slice_count:
        state.set_field("Phase", "TESTS")
        state.save()
        return f"Slice {slice_number} passed. It was the last slice: Phase is now TESTS."
    state.set_field("Slice", str(slice_number + 1))
    state.save()
    return f"Slice {slice_number} passed. Next: slice {slice_number + 1}."


def resolve_base(requested_base: str, code_root: Path) -> str:
    """
    Pick the base to compare against.

    :param requested_base: The `--base` argument, or an empty string.
    :param code_root: The checkout.
    :return: The base branch name.
    """
    if requested_base != "":
        return requested_base
    feature_directory = find_active_feature(code_root)
    if feature_directory is not None and (feature_directory / STATE_FILE_NAME).is_file():
        feature_base = FeatureState.load(feature_directory / STATE_FILE_NAME).field("Base")
        if feature_base != "":
            return feature_base
    return default_base(code_root)


def check_slice(ticket: str, slice_number: int) -> int:
    """
    Check one built slice: the changed-line checks plus the plan's file scope, then advance state.md on a pass.

    :param ticket: The feature's ticket.
    :param slice_number: The slice number from plan.md.
    :return: The exit code.
    """
    try:
        state = load_feature_state(ticket, Path.cwd())
    except FeatureNotFoundError as missing_error:
        print(missing_error)
        return SETUP_ERROR_EXIT_CODE
    plan_path = state.feature_directory / PLAN_FILE_NAME
    slices = parse_plan_slices(plan_path.read_text(encoding="utf-8")) if plan_path.is_file() else {}
    if slice_number not in slices:
        print(
            f"{plan_path} has no '## Slice {slice_number}' with a 'Files:' list.",
        )
        return SETUP_ERROR_EXIT_CODE
    if state.number_field("Slices") == 0:
        state.set_field("Slices", str(max(slices)))
    try:
        report = check_branch(
            state,
            allowed_for_slice(state.feature_directory, slice_number),
        )
    except GitError as git_error:
        print(f"Setup error: {git_error}")
        return SETUP_ERROR_EXIT_CODE
    rendered_report = report.render()
    if rendered_report != "":
        print(rendered_report + "\n")
    print(
        record_slice_result(
            state,
            slice_number,
            report,
        ),
    )
    if report.has_passed:
        return 0
    return FAILED_EXIT_CODE


def check_before_commit(requested_base: str) -> int:
    """
    Run the changed-line checks on the whole branch before a commit.

    :param requested_base: The `--base` argument, or an empty string.
    :return: The exit code.
    """
    code_root = repository_root(Path.cwd())
    if code_root is None:
        print("Setup error: not inside a git repository.")
        return SETUP_ERROR_EXIT_CODE
    base = resolve_base(
        requested_base,
        code_root,
    )
    try:
        changed, problems = changed_line_report(
            code_root,
            base,
        )
    except GitError as git_error:
        print(f"Setup error: {git_error}")
        return SETUP_ERROR_EXIT_CODE
    for problem in problems:
        print(problem)
    if len(problems) > 0:
        print(
            f"{len(problems)} problem(s) on the lines this branch changed against {base}. Fix them before committing.",
        )
        return FAILED_EXIT_CODE
    print(
        f"No problems on the changed lines of {len(changed)} file(s) against {base}. You can commit.",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check the lines a branch changed, before a commit or after building a slice.",
    )
    parser.add_argument(
        "--base",
        default="",
        help="The base branch to compare against.",
    )
    parser.add_argument(
        "--slice",
        nargs=2,
        metavar=("TICKET", "SLICE"),
        default=None,
        help="Check one slice of a feature: also checks plan.md's file scope and advances state.md on a pass.",
    )
    arguments = parser.parse_args()
    if arguments.slice is not None:
        ticket, slice_text = arguments.slice
        if not slice_text.isdigit():
            print(
                f"Setup error: the slice must be a number, got {slice_text!r}.",
            )
            return SETUP_ERROR_EXIT_CODE
        return check_slice(ticket, int(slice_text))
    return check_before_commit(arguments.base)


if __name__ == "__main__":
    sys.exit(main())
