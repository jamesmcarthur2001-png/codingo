#!/usr/bin/env python3
"""
Runs the changed-line checks (conventions, comments, Vue rules, ruff, eslint, mypy, suppressions) on a branch, inside or outside /feature.

Usage: python3 check_changes.py [--base <base>]
Run it from the branch's checkout before every commit to a feature branch: a pipeline fix, a quick fix, anything.
The base is `--base`, else the `Base:` of the feature this checkout belongs to, else the branch origin/HEAD points to.
Exit codes: 0 passed, 1 problems found, 2 setup error (not a git repository, or git failed).

:author: claude-workflow
:date: 03/11/2026
"""
# ----- Imports ----- #

import argparse
import sys
from pathlib import Path

from check_slice import changed_line_report
from feature_state import STATE_FILE_NAME, FeatureState, find_active_feature
from git_changes import GitError, default_base, repository_root

# ----- Consts ----- #

FAILED_EXIT_CODE = 1
SETUP_ERROR_EXIT_CODE = 2

# ----- Functions ----- #


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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check the lines a branch changed before committing.",
    )
    parser.add_argument(
        "--base",
        default="",
        help="The base branch to compare against.",
    )
    arguments = parser.parse_args()
    code_root = repository_root(Path.cwd())
    if code_root is None:
        print("Setup error: not inside a git repository.")
        return SETUP_ERROR_EXIT_CODE
    base = resolve_base(
        arguments.base,
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


if __name__ == "__main__":
    sys.exit(main())
