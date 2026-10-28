#!/usr/bin/env python3
"""
Reads which files each slice of plan.md and the test plan may touch, and finds changed files outside them.

:author: midnight-workflow
:date: 28/10/2026
"""
# ----- Imports ----- #

import re
from pathlib import Path

# ----- Consts ----- #

SLICE_HEADER_PATTERN = re.compile(
    r"^#{2,3}\s+Slice\s+(?P<number>\d+)\b",
    re.IGNORECASE,
)
HEADER_PATTERN = re.compile(r"^#{1,6}\s")
FILES_LABEL_PATTERN = re.compile(r"^\**Files\**\s*:", re.IGNORECASE)
LABEL_PATTERN = re.compile(r"^\**[A-Z][A-Za-z ]*\**\s*:")
BULLET_PATTERN = re.compile(r"^\s*[-*]\s+(?P<entry>.+)$")
TABLE_SEPARATOR_PATTERN = re.compile(r"^\|?\s*:?-{3,}")
TEST_PLAN_FILE_COLUMN = 3
PLAN_FILE_NAME = "plan.md"
TEST_PLAN_FILE_NAME = "test-plan.md"
ALL_SLICES = 1_000_000

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


def parse_test_plan_files(test_plan_text: str) -> list[str]:
    """
    Read the File column of the four-column test plan.

    :param test_plan_text: The test plan's text.
    :return: Every test file the plan names, without duplicates.
    """
    files: list[str] = []
    for test_plan_line in test_plan_text.splitlines():
        if not test_plan_line.strip().startswith("|") or TABLE_SEPARATOR_PATTERN.match(test_plan_line.strip()) is not None:
            continue

        cells = [cell.strip() for cell in test_plan_line.strip().strip("|").split("|")]
        if len(cells) <= TEST_PLAN_FILE_COLUMN or cells[TEST_PLAN_FILE_COLUMN].lower() == "file":
            continue

        if cells[TEST_PLAN_FILE_COLUMN] == "":
            continue

        test_file = clean_path_entry(cells[TEST_PLAN_FILE_COLUMN])
        if test_file not in files:
            files.append(test_file)

    return files


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


def allowed_for_branch(feature_directory: Path) -> list[str]:
    allowed = allowed_for_slice(feature_directory, ALL_SLICES)
    test_plan_path = feature_directory / TEST_PLAN_FILE_NAME
    if test_plan_path.is_file():
        allowed.extend(
            parse_test_plan_files(test_plan_path.read_text(encoding="utf-8")),
        )

    return allowed
