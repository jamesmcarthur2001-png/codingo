#!/usr/bin/env python3
"""
PostToolUse hook: runs the convention checker and linters on the file Claude just edited, and reports only problems on changed lines.

It acts only while an approved, unfinished feature is active for the repository (or when MIDNIGHT_CHECKS=1 is set).

:author: midnight-workflow
:date: 16/10/2026
"""
# ----- Imports ----- #

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feature_state import FeatureState, checks_forced, find_running_feature, is_reviewer_session
from git_changes import GitError, LineFilter, changed_line_filter, default_base, diff_base_commit, file_at_commit, repository_root
from line_checks import Problem, changed_line_problems

# ----- Consts ----- #

BLOCKING_EXIT_CODE = 2

# ----- Functions ----- #


def read_hook_payload() -> dict[str, object]:
    raw_payload = sys.stdin.buffer.read().decode("utf-8")
    if raw_payload.strip() == "":
        return {}
    payload = json.loads(raw_payload)
    return payload if isinstance(payload, dict) else {}


def get_edited_path(payload: dict[str, object]) -> Path | None:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or file_path.strip() == "":
        return None
    return Path(file_path)


def is_inside(path: Path, directory: Path) -> bool:
    return path.resolve().is_relative_to(directory.resolve())


def edited_file_problems(edited_path: Path, state: FeatureState | None) -> list[Problem]:
    """
    Check the edited file on the lines that differ from the base.

    :param edited_path: The file Claude just wrote.
    :param state: The running feature, or None when MIDNIGHT_CHECKS=1 forced the check.
    :return: The problems on changed lines.
    :raises GitError: When git can't tell which lines changed.
    """
    directory = edited_path.resolve().parent
    root = repository_root(directory)
    if root is None:
        return changed_line_problems(edited_path, LineFilter(whole_file=True))
    base = default_base(directory) if state is None else state.field("Base")
    base_commit = diff_base_commit(base, directory)
    line_filter = changed_line_filter(edited_path, base_commit)
    base_source: str | None = None
    if line_filter != LineFilter(whole_file=True):
        relative_path = edited_path.resolve().relative_to(root.resolve()).as_posix()
        base_source = file_at_commit(
            base_commit,
            relative_path,
            directory,
        )
    return changed_line_problems(
        edited_path,
        line_filter,
        base_source,
    )


def report_problems(path: Path, problems: list[Problem]) -> int:
    message = (
        f"Convention check failed on lines you changed in {path}. Fix these items (only these; leave unchanged lines as they are):\n"
        + "\n".join(problem.text for problem in problems)
        + "\n"
    )
    sys.stderr.buffer.write(message.encode("utf-8"))
    sys.stderr.flush()
    return BLOCKING_EXIT_CODE


def main() -> int:
    if is_reviewer_session():
        return 0
    payload = read_hook_payload()
    edited_path = get_edited_path(payload)
    if edited_path is None or not edited_path.is_file():
        return 0
    state = find_running_feature(
        Path(str(payload.get("cwd", "."))),
        str(payload.get("session_id", "")),
    )
    if state is None and not checks_forced():
        return 0
    if state is not None and not checks_forced() and not is_inside(edited_path, state.code_root()):
        return 0
    try:
        problems = edited_file_problems(edited_path, state)
    except GitError as git_error:
        setup_problem = Problem(
            0,
            f"Could not tell which lines changed: {git_error}",
        )
        problems = [setup_problem]
    if len(problems) == 0:
        return 0
    return report_problems(edited_path, problems)


if __name__ == "__main__":
    sys.exit(main())
