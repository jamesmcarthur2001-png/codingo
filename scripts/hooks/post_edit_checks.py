"""
PostToolUse hook: runs the convention checker and linters on the file Claude just edited, and reports only problems on changed lines.

:author: midnight-workflow
:date: 16/10/2026
"""
# ----- Imports ----- #

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feature_state import FeatureNotFoundError, FeatureState, STATE_FILE_NAME, find_active_feature, is_reviewer_session
from git_changes import changed_line_filter, default_base, diff_base_commit
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


def feature_base(payload: dict[str, object]) -> str:
    """
    Read the base branch of the active feature.

    :param payload: The hook payload, whose `cwd` is searched for docs/features.
    :return: The `Base:` field of the active feature's state.md, or an empty string.
    """
    feature_directory = find_active_feature(Path(str(payload.get("cwd", "."))))
    if feature_directory is None:
        return ""
    try:
        state = FeatureState.load(feature_directory / STATE_FILE_NAME)
    except FeatureNotFoundError:
        return ""
    return state.field("Base")


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
    base = feature_base(payload)
    if base == "":
        base = default_base(edited_path.resolve().parent)
    line_filter = changed_line_filter(
        edited_path,
        diff_base_commit(base, edited_path.resolve().parent),
    )
    problems = changed_line_problems(edited_path, line_filter)
    if len(problems) == 0:
        return 0
    return report_problems(edited_path, problems)


if __name__ == "__main__":
    sys.exit(main())
