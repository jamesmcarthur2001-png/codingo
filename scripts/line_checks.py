#!/usr/bin/env python3
"""
Runs the convention checker, ruff, eslint, mypy and the suppression check, keeping only problems on changed lines.

:author: midnight-workflow
:date: 28/10/2026
"""
# ----- Imports ----- #

import json
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import command_runner
from check_python_conventions import check_python_file
from git_changes import LineFilter
from mypy_strict import build_mypy_command, filter_mypy_output

# ----- Consts ----- #

LINTER_TIMEOUT_SECONDS = 45
MYPY_TIMEOUT_SECONDS = 600
PYTHON_SUFFIXES = (".py", ".pyi")
FRONTEND_SUFFIXES = (".vue", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
PYTHON_PROJECT_MARKER = "pyproject.toml"
RUFF_VENV_CANDIDATE = ".venv/bin/ruff"
ESLINT_BIN_CANDIDATE = "node_modules/.bin/eslint"
RUFF_LINE_PATTERN = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):(?P<column>\d+): (?P<message>.+)$",
)
MYPY_ERROR_PATTERN = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):(?:\d+:)? (?:error|note): ",
)
SUPPRESSION_PATTERN = re.compile(
    r"#\s*noqa\b"
    r"|#\s*(?:ruff|flake8)\s*:\s*noqa"
    r"|#\s*type:\s*ignore"
    r"|#\s*mypy:\s*ignore-errors"
    r"|#\s*pylint:\s*disable"
    r"|#\s*pyright:\s*ignore"
    r"|#\s*pragma:\s*no\s*cover"
    r"|eslint-disable"
    r"|/\*\s*eslint\s+[\w@/-]+\s*:\s*['\"]?(?:off|0)\b"
    r"|@ts-ignore|@ts-nocheck|@ts-expect-error",
    re.IGNORECASE,
)
PYTHON_CONFIG_NAMES = ("pyproject.toml", "setup.cfg", "ruff.toml", ".ruff.toml", "mypy.ini", ".flake8", "tox.ini", ".pylintrc")
PYTHON_CONFIG_SUPPRESSION_PATTERN = re.compile(
    r"per-file-ignores|extend-ignore|^\s*ignore\s*=|ignore_errors\s*=\s*true|disable_error_code|^\s*disable\s*=",
    re.IGNORECASE,
)
ESLINT_CONFIG_PATTERN = re.compile(
    r"^(?:\.eslintrc(?:\.\w+)?|eslint\.config\.\w+)$",
)
ESLINT_CONFIG_SUPPRESSION_PATTERN = re.compile(
    r"""['"]?[\w@/-]+['"]?\s*:\s*(?:\[\s*)?['"]?(?:off|0)['"]?\b""",
)
NOT_LINE_BOUND = 0

# ----- Classes ----- #


@dataclass(frozen=True)
class Problem:
    """
    One reported problem, spanning `line` to `end_line`. Line 0 means a tool error that isn't tied to a line, which is always reported.
    """
    line: int
    text: str
    end_line: int = 0

    @property
    def last_line(self) -> int:
        return max(self.line, self.end_line)

# ----- Functions ----- #


def find_project_root(path: Path, marker: str) -> Path | None:
    for directory in path.resolve().parents:
        if (directory / marker).is_file():
            return directory

    return None


def find_ruff(project_root: Path | None) -> str | None:
    if project_root is not None and (project_root / RUFF_VENV_CANDIDATE).is_file():
        return str(project_root / RUFF_VENV_CANDIDATE)
    return shutil.which("ruff")


def find_eslint(path: Path) -> tuple[str, Path] | None:
    """
    Find the nearest project-local eslint binary above the edited file.

    :param path: The edited frontend file.
    :return: The eslint executable and the directory to run it from, when one is installed.
    """
    for directory in path.resolve().parents:
        if (directory / ESLINT_BIN_CANDIDATE).is_file():
            return str(directory / ESLINT_BIN_CANDIDATE), directory

    return None


def parse_ruff_output(output: str) -> list[Problem]:
    """
    Turn ruff's concise output into problems.

    :param output: What ruff printed on stdout.
    :return: One problem per diagnostic; the whole output as one line-less problem when nothing parses.
    """
    problems = [
        Problem(
            int(line_match.group("line")),
            line_match.group(0),
        )
        for line_match in (RUFF_LINE_PATTERN.match(line) for line in output.splitlines())
        if line_match is not None
    ]
    if len(problems) == 0 and output.strip() != "":
        return [Problem(NOT_LINE_BOUND, f"ruff: {output.strip()}")]
    return problems


def parse_eslint_output(path: Path, output: str) -> list[Problem]:
    """
    Turn eslint's JSON output into problems.

    :param path: The checked file, used in the messages.
    :param output: What `eslint --format json` printed on stdout.
    :return: One problem per message; the whole output as one line-less problem when it isn't JSON.
    """
    try:
        results = json.loads(output)
    except json.JSONDecodeError:
        return [Problem(NOT_LINE_BOUND, f"eslint: {output.strip()}")]
    problems: list[Problem] = []
    for result in results:
        for message in result.get("messages", []):
            line = int(message.get("line", NOT_LINE_BOUND))
            end_line = int(message.get("endLine", line))
            rule_id = message.get("ruleId")
            rule_text = "eslint" if rule_id is None else str(rule_id)
            problems.append(
                Problem(
                    line,
                    f"{path}:{line}: {rule_text} {message.get('message', '')}",
                    end_line,
                ),
            )

    return problems


def collect_python_problems(path: Path, base_source: str | None) -> list[Problem]:
    problems = [
        Problem(
            violation.line,
            violation.format_for_output(),
            violation.last_line,
        )
        for violation in check_python_file(path, base_source)
    ]
    project_root = find_project_root(path, PYTHON_PROJECT_MARKER)
    ruff = find_ruff(project_root)
    if ruff is None:
        return problems
    ruff_result = command_runner.run_command(
        [ruff, "check", "--no-fix", "--output-format", "concise", str(path)],
        project_root,
        LINTER_TIMEOUT_SECONDS,
    )
    if ruff_result.returncode == 1:
        problems.extend(parse_ruff_output(ruff_result.stdout))
    elif not ruff_result.succeeded:
        problems.append(
            Problem(
                NOT_LINE_BOUND,
                f"ruff could not run: {ruff_result.output.strip()}",
            ),
        )

    return problems


def collect_frontend_problems(path: Path) -> list[Problem]:
    eslint = find_eslint(path)
    if eslint is None:
        return []
    eslint_executable, working_directory = eslint
    eslint_result = command_runner.run_command(
        [eslint_executable, "--format", "json", str(path)],
        working_directory,
        LINTER_TIMEOUT_SECONDS,
    )
    if eslint_result.succeeded:
        return []
    return parse_eslint_output(path, eslint_result.stdout)


def suppression_pattern_for(path: Path) -> re.Pattern[str] | None:
    """
    Pick the pattern that finds suppressions in this kind of file.

    :param path: The file.
    :return: The pattern for code, Python tool configs or eslint configs; None for other files.
    """
    if path.suffix in PYTHON_SUFFIXES or path.suffix in FRONTEND_SUFFIXES:
        return SUPPRESSION_PATTERN
    if path.name in PYTHON_CONFIG_NAMES:
        return PYTHON_CONFIG_SUPPRESSION_PATTERN
    if ESLINT_CONFIG_PATTERN.match(path.name) is not None:
        return ESLINT_CONFIG_SUPPRESSION_PATTERN
    return None


def collect_suppression_problems(path: Path, line_filter: LineFilter) -> list[Problem]:
    """
    Find lint, type-checker and coverage suppressions on the changed lines, in code and in tool configs.

    :param path: The file to read.
    :param line_filter: The changed lines.
    :return: One problem per changed line that holds a suppression.
    """
    pattern = suppression_pattern_for(path)
    if pattern is None:
        return []
    problems: list[Problem] = []
    source_lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    for line_number, source_line in enumerate(source_lines, start=1):
        if not line_filter.covers(line_number):
            continue

        suppression = pattern.search(source_line)
        if suppression is None:
            continue

        problems.append(
            Problem(
                line_number,
                f"{path}:{line_number}: SUPPRESSION '{suppression.group(0).strip()}' is not allowed. Fix the code instead.",
            ),
        )

    return problems


def keep_changed(problems: Iterable[Problem], line_filter: LineFilter) -> list[Problem]:
    return [
        problem
        for problem in problems
        if problem.line == NOT_LINE_BOUND or line_filter.covers_any(problem.line, problem.last_line)
    ]


def changed_line_problems(path: Path, line_filter: LineFilter, base_source: str | None = None) -> list[Problem]:
    """
    Run every per-file check on one file and keep the problems that touch its changed lines.

    :param path: The file to check.
    :param line_filter: The lines that count as changed.
    :param base_source: The file's text in the base commit (None for a new file), so existing names aren't new.
    :return: The problems on changed lines, or not tied to a line.
    """
    problems: list[Problem] = []
    if path.suffix in PYTHON_SUFFIXES:
        problems = collect_python_problems(path, base_source)
    elif path.suffix in FRONTEND_SUFFIXES:
        problems = collect_frontend_problems(path)

    problems.extend(collect_suppression_problems(path, line_filter))
    return keep_changed(problems, line_filter)


def mypy_problems(python_paths: list[Path], line_filters: dict[Path, LineFilter]) -> list[Problem]:
    """
    Run mypy --strict per Python project and keep the errors on changed lines.

    :param python_paths: The changed Python files (absolute).
    :param line_filters: Each file's changed lines, keyed by its absolute path.
    :return: The mypy errors and notes on changed lines, or a line-less problem when mypy can't run.
    """
    paths_by_project: dict[Path, list[Path]] = {}
    for python_path in python_paths:
        project_root = find_project_root(python_path, PYTHON_PROJECT_MARKER)
        if project_root is None:
            continue

        paths_by_project.setdefault(project_root, []).append(python_path)

    problems: list[Problem] = []
    for project_root, project_paths in paths_by_project.items():
        mypy_result = command_runner.run_command(
            build_mypy_command(
                [str(project_path) for project_path in project_paths],
            ),
            project_root,
            MYPY_TIMEOUT_SECONDS,
        )
        output_lines = mypy_result.stdout.splitlines()
        has_findings = any(
            MYPY_ERROR_PATTERN.match(output_line) is not None
            for output_line in output_lines
        )
        if mypy_result.returncode != 0 and not has_findings:
            problems.append(
                Problem(
                    NOT_LINE_BOUND,
                    f"mypy could not run in {project_root}: {mypy_result.output.strip()}",
                ),
            )
            continue

        for kept_line in filter_mypy_output(output_lines, project_root):
            line_match = MYPY_ERROR_PATTERN.match(kept_line)
            if line_match is None:
                continue

            reported_path = Path(line_match.group("path"))
            absolute_path = reported_path if reported_path.is_absolute() else project_root / reported_path
            line_filter = line_filters.get(absolute_path.resolve())
            if line_filter is not None and line_filter.covers(int(line_match.group("line"))):
                problems.append(Problem(int(line_match.group("line")), kept_line))

    return problems
