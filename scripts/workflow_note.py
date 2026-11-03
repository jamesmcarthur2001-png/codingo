#!/usr/bin/env python3
"""
Appends a note about the workflow itself (a rule, skill, script, hook or agent that got in the way) to the branch's feedback file.

Usage: python3 workflow_note.py --author <who> --kind <kind> --source <file or name> --what "<what happened>" --suggestion "<what to change>"
       python3 workflow_note.py --author <who> --show
Notes go to ~/.claude/workflow-feedback/<branch>/<author>.md (WORKFLOW_FEEDBACK_DIR overrides the folder): one folder per
branch, so the notes outlive the worktree, and one file per writer (orchestrator, each reviewer, each verifier), so agents
running at the same time never write to the same file. `--show` prints only the writer's own file.
Each note records the time, the ticket and phase when a feature is active, and the four fields.
The user reads these to improve the workflow; Claude only adds notes and never edits the workflow files for them.
Exit codes: 0 written (or shown), 2 setup error (not in a git repository).

:author: claude-workflow
:date: 03/11/2026
"""
# ----- Imports ----- #

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from feature_state import STATE_FILE_NAME, FeatureState, find_active_feature
from git_changes import repository_root, run_git

# ----- Consts ----- #

SETUP_ERROR_EXIT_CODE = 2
FEEDBACK_DIRECTORY_VARIABLE = "WORKFLOW_FEEDBACK_DIR"
DEFAULT_FEEDBACK_DIRECTORY = Path.home() / ".claude" / "workflow-feedback"
NO_BRANCH_NAME = "no-branch"
UNSAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
KINDS = ("rule", "skill", "script", "hook", "agent", "command", "missing-rule", "other")
TIME_FORMAT = "%d/%m/%Y %H:%M"
DEFAULT_AUTHOR = "orchestrator"

# ----- Functions ----- #


def feedback_directory() -> Path:
    configured = os.environ.get(FEEDBACK_DIRECTORY_VARIABLE, "")
    if configured != "":
        return Path(configured)
    return DEFAULT_FEEDBACK_DIRECTORY


def current_branch(code_root: Path) -> str:
    branch = run_git(
        ["branch", "--show-current"],
        code_root,
    ).stdout.strip()
    if branch == "":
        return NO_BRANCH_NAME
    return branch


def safe_name(name: str) -> str:
    return UNSAFE_NAME_PATTERN.sub("-", name).strip("-")


def feedback_path(branch: str, author: str) -> Path:
    return feedback_directory() / safe_name(branch) / f"{safe_name(author)}.md"


def feature_context(code_root: Path) -> str:
    """
    Describe the active feature, if any.

    :param code_root: The checkout.
    :return: `BTRC-1234 · Phase: GATE-B · Round: 2`, or an empty string outside a feature.
    """
    feature_directory = find_active_feature(code_root)
    if feature_directory is None or not (feature_directory / STATE_FILE_NAME).is_file():
        return ""
    state = FeatureState.load(feature_directory / STATE_FILE_NAME)
    return f"{state.field('Ticket')} · Phase: {state.field('Phase')} · Round: {state.field('Round')}"


def render_note(context: str, kind: str, source: str, what: str, suggestion: str) -> str:
    """
    Format one note.

    :param context: The active feature, or an empty string.
    :param kind: What kind of workflow part it's about.
    :param source: The file or name it's about.
    :param what: What happened.
    :param suggestion: What to change.
    :return: The note as markdown.
    """
    title = f"## {datetime.now().strftime(TIME_FORMAT)} · {kind} · {source}"
    lines = [title]
    if context != "":
        lines.append(f"- Feature: {context}")
    lines.append(f"- What happened: {what.strip()}")
    lines.append(f"- Suggestion: {suggestion.strip()}")
    return "\n".join(lines) + "\n\n"


def append_note(branch: str, author: str, note: str) -> Path:
    path = feedback_path(branch, author)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text(
            f"# Workflow feedback: {branch} ({author})\n\n",
            encoding="utf-8",
        )
    with path.open("a", encoding="utf-8") as feedback_file:
        feedback_file.write(note)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Note something about the workflow for the user to review.",
    )
    parser.add_argument(
        "--author",
        default=DEFAULT_AUTHOR,
        help="Who writes: orchestrator, or the agent's name, e.g. correctness-reviewer or finding-verifier-tests.",
    )
    parser.add_argument(
        "--kind",
        choices=KINDS,
        default="other",
    )
    parser.add_argument(
        "--source",
        default="",
        help="The file or name it's about, e.g. skills/python-conventions/SKILL.md or review_round.py.",
    )
    parser.add_argument(
        "--what",
        default="",
        help="What happened.",
    )
    parser.add_argument(
        "--suggestion",
        default="",
        help="What to change.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Print this branch's notes instead of adding one.",
    )
    arguments = parser.parse_args()
    code_root = repository_root(Path.cwd())
    if code_root is None:
        print("Setup error: not inside a git repository.")
        return SETUP_ERROR_EXIT_CODE
    branch = current_branch(code_root)
    if arguments.show:
        path = feedback_path(branch, arguments.author)
        print(
            path.read_text(encoding="utf-8") if path.is_file() else f"No notes for {branch} yet.",
        )
        return 0
    if arguments.what.strip() == "" or arguments.suggestion.strip() == "":
        print("Setup error: give both --what and --suggestion.")
        return SETUP_ERROR_EXIT_CODE
    note = render_note(
        feature_context(code_root),
        arguments.kind,
        arguments.source if arguments.source != "" else "unknown",
        arguments.what,
        arguments.suggestion,
    )
    path = append_note(
        branch,
        arguments.author,
        note,
    )
    print(f"Noted in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
