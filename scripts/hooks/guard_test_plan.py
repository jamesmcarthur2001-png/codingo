#!/usr/bin/env python3
"""
PreToolUse hook: blocks adding tests that are not listed in the running feature's test-plan.md (exact names, first column).

:author: midnight-workflow
:date: 16/10/2026
"""
# ----- Imports ----- #

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feature_state import find_running_feature, is_reviewer_session

# ----- Consts ----- #

BLOCKING_EXIT_CODE = 2
TEST_PLAN_FILE_NAME = "test-plan.md"
PYTHON_TEST_PATTERN = re.compile(
    r"^\s*(?:async\s+)?def\s+(test_\w+)\s*\(",
    re.MULTILINE,
)
FRONTEND_TEST_PATTERN = re.compile(
    r"""^\s*(?:it|test)(?:\.(?:only|skip|todo|fixme|fail|fails|slow|concurrent))?\s*\(\s*(['"`])(.+?)\1""",
    re.MULTILINE,
)
FRONTEND_TEST_SUFFIXES = (".spec.ts", ".test.ts", ".spec.tsx", ".test.tsx", ".spec.js", ".test.js", ".spec.mts", ".test.mts")
TABLE_SEPARATOR_PATTERN = re.compile(r"^\|?\s*:?-{3,}")
HEADER_FIRST_CELL = "test name"
NAME_QUOTE_CHARACTERS = "`'\" "
EDIT_TOOL_NAMES = ("Edit", "MultiEdit")

# ----- Functions ----- #


def read_hook_payload() -> dict[str, object]:
    raw_payload = sys.stdin.buffer.read().decode("utf-8")
    if raw_payload.strip() == "":
        return {}
    payload = json.loads(raw_payload)
    return payload if isinstance(payload, dict) else {}


def is_python_test_file(path: Path) -> bool:
    return path.suffix == ".py" and path.name.startswith("test_")


def is_frontend_test_file(path: Path) -> bool:
    return path.name.endswith(FRONTEND_TEST_SUFFIXES) or "__tests__" in path.parts


def extract_test_names(path: Path, source: str) -> list[str]:
    if is_python_test_file(path):
        return PYTHON_TEST_PATTERN.findall(source)
    return [test_match.group(2) for test_match in FRONTEND_TEST_PATTERN.finditer(source)]


def read_existing_source(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8-sig", errors="replace")


def collect_source_changes(tool_name: str, tool_input: dict[str, object]) -> list[tuple[str, str]]:
    """
    Lists the (before, after) text pairs a Write or Edit call would apply.

    :param tool_name: The tool being called.
    :param tool_input: The tool's input payload.
    :return: The replaced text and its replacement for every change in the call.
    """
    if tool_name not in EDIT_TOOL_NAMES:
        file_path = str(tool_input.get("file_path", ""))
        new_content = str(tool_input.get("content", ""))
        return [(read_existing_source(Path(file_path)), new_content)]
    raw_edits = tool_input.get("edits")
    edits = raw_edits if isinstance(raw_edits, list) else [tool_input]
    source_changes: list[tuple[str, str]] = []
    for edit in edits:
        if isinstance(edit, dict):
            old_source = str(edit.get("old_string", ""))
            new_source = str(edit.get("new_string", ""))
            source_changes.append((old_source, new_source))
    return source_changes


def find_added_test_names(path: Path, source_changes: list[tuple[str, str]]) -> list[str]:
    added_test_names: list[str] = []
    for old_source, new_source in source_changes:
        existing_names = set(extract_test_names(path, old_source))
        for test_name in extract_test_names(path, new_source):
            if test_name not in existing_names:
                added_test_names.append(test_name)
    return added_test_names


def planned_test_names(test_plan_text: str) -> set[str]:
    """
    Read the test names of the four-column test plan.

    :param test_plan_text: The test plan's text.
    :return: The exact names in the first column of every table row.
    """
    names: set[str] = set()
    for test_plan_line in test_plan_text.splitlines():
        stripped_line = test_plan_line.strip()
        if not stripped_line.startswith("|") or TABLE_SEPARATOR_PATTERN.match(stripped_line) is not None:
            continue

        first_cell = stripped_line.strip("|").split("|")[0].strip(NAME_QUOTE_CHARACTERS)
        if first_cell != "" and first_cell.lower() != HEADER_FIRST_CELL:
            names.add(first_cell)

    return names


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
    path = Path(str(tool_input.get("file_path", "")))
    if not is_python_test_file(path) and not is_frontend_test_file(path):
        return 0
    source_changes = collect_source_changes(str(payload.get("tool_name", "")), tool_input)
    added_test_names = find_added_test_names(path, source_changes)
    if len(added_test_names) == 0:
        return 0
    state = find_running_feature(
        Path(str(payload.get("cwd", "."))),
        str(payload.get("session_id", "")),
    )
    if state is None:
        return 0
    test_plan_path = state.feature_directory / TEST_PLAN_FILE_NAME
    if not test_plan_path.is_file():
        return block(
            f"Blocked: feature '{state.field('Ticket')}' has no {test_plan_path}. "
            "Write the test plan (test name, what it checks, expected result, file) before writing tests.",
        )
    planned_names = planned_test_names(test_plan_path.read_text(encoding="utf-8"))
    unplanned_names = [
        test_name
        for test_name in added_test_names
        if test_name not in planned_names
    ]
    if len(unplanned_names) == 0:
        return 0
    return block(
        f"Blocked: these tests are not in {test_plan_path}: {', '.join(unplanned_names)}. "
        "Add a row for each one to the test plan first, then write the test.",
    )


if __name__ == "__main__":
    sys.exit(main())
