#!/usr/bin/env python3
"""
Runs mypy --strict and drops only the missing-return-annotation errors of functions that return nothing.

:author: midnight-workflow
:date: 16/10/2026
"""
# ----- Imports ----- #

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

from check_python_conventions import FUNCTION_NODE_TYPES, function_returns_value

# ----- Consts ----- #

MISSING_RETURN_MESSAGE = "Function is missing a return type annotation"
MYPY_LINE_PATTERN = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):(?:\d+:)? (?P<severity>error|note): ",
)
MYPY_UNAVAILABLE_EXIT_CODE = 2
MYPY_UNAVAILABLE_MESSAGE = "mypy could not run (is it installed in this project?)\n"
SUCCESS_MESSAGE = "Success: no issues found (functions without '-> None' are allowed)."
MYPY_ARGUMENTS = ["--strict", "--show-error-codes", "--no-error-summary", "--no-color-output"]

# ----- Functions ----- #


def build_mypy_command(mypy_arguments: list[str]) -> list[str]:
    if shutil.which("uv") is not None:
        return ["uv", "run", "mypy", *MYPY_ARGUMENTS, *mypy_arguments]
    if shutil.which("mypy") is not None:
        return ["mypy", *MYPY_ARGUMENTS, *mypy_arguments]
    return [sys.executable, "-m", "mypy", *MYPY_ARGUMENTS, *mypy_arguments]


def find_none_returning_function_lines(path: Path) -> set[int]:
    """
    Finds the lines mypy may report for functions that never return a value.

    :param path: The Python file to inspect.
    :return: The `def` and decorator line numbers of every function that returns nothing.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (OSError, SyntaxError):
        return set()
    function_lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, FUNCTION_NODE_TYPES) or function_returns_value(node):
            continue
        function_lines.add(node.lineno)
        function_lines.update(decorator.lineno for decorator in node.decorator_list)
    return function_lines


def filter_mypy_output(output_lines: list[str], base_directory: Path | None = None) -> list[str]:
    """
    Removes missing-return-annotation errors (and their notes) on functions that return nothing.

    :param output_lines: Raw mypy output lines.
    :param base_directory: The directory mypy ran in, to resolve its relative paths; the current directory when None.
    :return: The output lines that still matter.
    """
    function_lines_by_path: dict[str, set[int]] = {}
    suppressed_locations: set[tuple[str, str]] = set()
    kept_lines: list[str] = []
    for output_line in output_lines:
        line_match = MYPY_LINE_PATTERN.match(output_line)
        if line_match is None:
            kept_lines.append(output_line)
            continue
        location = (line_match.group("path"), line_match.group("line"))
        if line_match.group("severity") == "note" and location in suppressed_locations:
            continue
        if MISSING_RETURN_MESSAGE not in output_line:
            kept_lines.append(output_line)
            continue
        if location[0] not in function_lines_by_path:
            reported_path = Path(location[0])
            if base_directory is not None and not reported_path.is_absolute():
                reported_path = base_directory / reported_path
            function_lines_by_path[location[0]] = find_none_returning_function_lines(reported_path)
        if int(location[1]) in function_lines_by_path[location[0]]:
            suppressed_locations.add(location)
            continue
        kept_lines.append(output_line)
    return kept_lines


def main() -> int:
    mypy_arguments = sys.argv[1:] if len(sys.argv) > 1 else ["."]
    completed = subprocess.run(
        build_mypy_command(mypy_arguments),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output_lines = completed.stdout.splitlines()
    has_mypy_findings = any(MYPY_LINE_PATTERN.match(output_line) is not None for output_line in output_lines)
    if completed.returncode not in (0, 1) or (completed.returncode == 1 and not has_mypy_findings):
        sys.stderr.write(MYPY_UNAVAILABLE_MESSAGE)
        sys.stderr.write(completed.stdout + completed.stderr)
        return MYPY_UNAVAILABLE_EXIT_CODE
    kept_lines = filter_mypy_output(output_lines)
    error_count = sum(1 for kept_line in kept_lines if ": error: " in kept_line)
    for kept_line in kept_lines:
        print(kept_line)
    if error_count == 0:
        print(SUCCESS_MESSAGE)
        return 0
    print(f"Found {error_count} error(s).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
