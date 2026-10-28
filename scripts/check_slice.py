#!/usr/bin/env python3
"""
Checks one built slice: lint, types, suppressions and scope, on the lines the branch changed only.

Usage: python3 check_slice.py BTRC-1234 <slice>
Exit codes: 0 passed, 1 problems found, 2 setup error (no feature, no such slice, or git failed).

:author: midnight-workflow
:date: 28/10/2026
"""
# ----- Imports ----- #

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from feature_state import FeatureNotFoundError, FeatureState, load_feature_state
from git_changes import GitError, LineFilter, branch_line_filters, changed_existing_lines, changed_files, diff_base_commit, file_at_commit
from line_checks import PYTHON_SUFFIXES, changed_line_problems, mypy_problems
from scope_check import allowed_for_slice, out_of_scope_files, parse_plan_slices

# ----- Consts ----- #

FAILED_EXIT_CODE = 1
SETUP_ERROR_EXIT_CODE = 2
FEATURES_PREFIX = "docs/features/"

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
    def passed(self) -> bool:
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


def check_branch(state: FeatureState, allowed_patterns: list[str]) -> BranchReport:
    """
    Run the changed-line checks and the scope check on everything the branch changed.

    :param state: The feature's state, naming its base and worktree.
    :param allowed_patterns: The files the plan allows so far.
    :return: The problems, out-of-scope files and changed existing lines.
    """
    code_root = state.code_root()
    base_commit = diff_base_commit(state.field("Base"), code_root)
    changed = [
        path
        for path in changed_files(base_commit, code_root)
        if not path.startswith(FEATURES_PREFIX)
    ]
    line_filters = branch_line_filters(base_commit, code_root)
    report = BranchReport(
        changed=changed,
        out_of_scope=out_of_scope_files(changed, allowed_patterns),
        existing_line_changes=changed_existing_lines(base_commit, code_root),
    )
    absolute_filters: dict[Path, LineFilter] = {}
    for relative_path in changed:
        path = code_root / relative_path
        line_filter = line_filters.get(relative_path)
        if not path.is_file() or line_filter is None:
            continue

        absolute_filters[path.resolve()] = line_filter
        base_source = file_at_commit(
            base_commit,
            relative_path,
            code_root,
        )
        report.problems.extend(
            problem.text
            for problem in changed_line_problems(
                path,
                line_filter,
                base_source,
            )
        )

    python_paths = [
        path
        for path in absolute_filters
        if path.suffix in PYTHON_SUFFIXES
    ]
    if len(python_paths) > 0:
        report.problems.extend(problem.text for problem in mypy_problems(python_paths, absolute_filters))

    return report


def record_slice_result(state: FeatureState, slice_number: int, report: BranchReport) -> str:
    """
    Advance state.md after a passing slice, or count the failed try.

    :param state: The feature's state.
    :param slice_number: The checked slice.
    :param report: The check's result.
    :return: A line telling the orchestrator what happens next.
    """
    if not report.passed:
        failed_runs = state.record_failure(f"SLICE-{slice_number}")
        state.save()
        if state.is_finished():
            return f"Slice {slice_number} failed {failed_runs} times: state.md is now BLOCKED. Stop."
        return f"Slice {slice_number} failed (try {failed_runs}). Fix the items above and run this again."

    state.reset_tries()
    state.log(f"check_slice {slice_number} passed")
    slice_count = state.number_field("Slices")
    if slice_number >= slice_count:
        state.set_field("Phase", "TESTS")
        state.save()
        return f"Slice {slice_number} passed. It was the last slice: Phase is now TESTS."
    state.set_field("Slice", str(slice_number + 1))
    state.save()
    return f"Slice {slice_number} passed. Next: slice {slice_number + 1}."


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check one slice of a feature on its changed lines.",
    )
    parser.add_argument("ticket", help="The ticket, e.g. BTRC-1234.")
    parser.add_argument(
        "slice",
        type=int,
        help="The slice number from plan.md.",
    )
    arguments = parser.parse_args()
    try:
        state = load_feature_state(arguments.ticket, Path.cwd())
    except FeatureNotFoundError as missing_error:
        print(missing_error)
        return SETUP_ERROR_EXIT_CODE
    plan_path = state.feature_directory / "plan.md"
    slices = parse_plan_slices(plan_path.read_text(encoding="utf-8")) if plan_path.is_file() else {}
    if arguments.slice not in slices:
        print(
            f"{plan_path} has no '## Slice {arguments.slice}' with a 'Files:' list.",
        )
        return SETUP_ERROR_EXIT_CODE
    if state.number_field("Slices") == 0:
        state.set_field("Slices", str(max(slices)))
    try:
        report = check_branch(
            state,
            allowed_for_slice(state.feature_directory, arguments.slice),
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
            arguments.slice,
            report,
        ),
    )
    if report.passed:
        return 0
    return FAILED_EXIT_CODE


if __name__ == "__main__":
    sys.exit(main())
