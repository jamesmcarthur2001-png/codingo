import sys
import time
from pathlib import Path

import pytest

import command_runner
from git_changes import LineFilter
from line_checks import Problem, collect_suppression_problems, keep_changed, parse_eslint_output
from mypy_strict import filter_mypy_output

IS_WINDOWS = sys.platform == "win32"


def python_command(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_run_command_keeps_stdout_and_stderr_apart(tmp_path: Path):
    result = command_runner.run_command(
        python_command("import sys; print('data'); print('warning: noise', file=sys.stderr)"),
        tmp_path,
    )

    assert result.succeeded
    assert result.stdout.strip() == "data"
    assert result.stderr.strip() == "warning: noise"
    assert "data" in result.output and "noise" in result.output


def test_run_command_gives_no_stdin(tmp_path: Path):
    result = command_runner.run_command(
        python_command("import sys; print(repr(sys.stdin.read()))"),
        tmp_path,
    )

    assert result.stdout.strip() == "''"


def test_run_command_timeout_keeps_partial_output(tmp_path: Path):
    result = command_runner.run_command(
        python_command("import sys, time; print('started', flush=True); time.sleep(30)"),
        tmp_path,
        timeout=2,
    )

    assert result.timed_out
    assert not result.succeeded
    assert "started" in result.stdout


@pytest.mark.skipif(IS_WINDOWS, reason="process groups are a POSIX feature")
def test_run_command_timeout_kills_the_children_too(tmp_path: Path):
    marker = tmp_path / "child-survived"
    child_code = f"import time, pathlib; time.sleep(3); pathlib.Path({str(marker)!r}).write_text('x')"
    parent_code = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child_code!r}]); time.sleep(30)"

    command_runner.run_command(python_command(parent_code), tmp_path, timeout=1)
    time.sleep(4)

    assert not marker.exists()


@pytest.mark.skipif(IS_WINDOWS, reason="string commands run through bash -lc on Ubuntu")
def test_run_command_string_runs_through_bash(tmp_path: Path):
    result = command_runner.run_command("echo ${BASH_VERSION:+bash}", tmp_path)

    assert result.stdout.strip() == "bash"


def test_run_command_missing_program_fails_without_raising(tmp_path: Path):
    result = command_runner.run_command(["no-such-program-xyz"], tmp_path)

    assert result.returncode == command_runner.FAILED_TO_START_EXIT_CODE
    assert "no-such-program-xyz" in result.stderr


def test_parse_eslint_output_reads_json_from_stdout_only():
    output = '[{"filePath": "a.vue", "messages": [{"line": 4, "endLine": 6, "ruleId": "no-console", "message": "Unexpected console"}]}]'

    problems = parse_eslint_output(Path("a.vue"), output)

    assert problems == [Problem(4, "a.vue:4: no-console Unexpected console", 6)]


def test_keep_changed_keeps_a_problem_whose_span_touches_a_changed_line():
    problems = [Problem(10, "call", 13), Problem(20, "other", 20)]

    kept = keep_changed(problems, LineFilter(whole_file=False, lines=frozenset({12})))

    assert kept == [Problem(10, "call", 13)]


@pytest.mark.parametrize(
    ("file_name", "line"),
    [
        ("view.vue", "// eslint-disable-next-line no-console"),
        ("view.ts", "// @ts-expect-error wrong type"),
        ("view.jsx", "/* eslint no-console: off */"),
        ("types.pyi", "x: int  # type: ignore"),
        (".eslintrc.json", '"no-console": "off",'),
        ("mypy.ini", "ignore_errors = True"),
    ],
)
def test_collect_suppression_problems_finds_new_suppressions(tmp_path: Path, file_name: str, line: str):
    path = tmp_path / file_name
    path.write_text(line + "\n", encoding="utf-8")

    problems = collect_suppression_problems(path, LineFilter(whole_file=True))

    assert len(problems) == 1


def test_filter_mypy_output_resolves_relative_paths_against_the_project(tmp_path: Path):
    project = tmp_path / "service"
    (project / "app").mkdir(parents=True)
    (project / "app" / "save.py").write_text("def save(value: int):\n    print(value)\n", encoding="utf-8")
    output_lines = ["app/save.py:1: error: Function is missing a return type annotation  [no-untyped-def]"]

    kept = filter_mypy_output(output_lines, project)

    assert kept == []
