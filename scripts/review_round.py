#!/usr/bin/env python3
"""
Helps the parallel review round: stores the conventions and Playwright reviewers' findings, and tells whether the Playwright reviewer must run.

Usage: python3 review_round.py capture BTRC-1234 <round>
       python3 review_round.py playwright-needed BTRC-1234 <round>
`capture` reads review/conventions-<round>.md and review/playwright-<round>.md (findings as `## <id> | <file:line> | <rule>`),
writes review/<source>-<round>.json with each flagged line's text as it is now (run it before fixing anything),
notes findings dismissed in earlier rounds, and records which frontend files the Playwright reviewer saw.
`playwright-needed` prints `yes` or `no`: yes in round 1, later only when frontend files changed since its last run.
Exit codes: 0 done, 2 setup error (no feature, git failed).

:author: midnight-workflow
:date: 28/10/2026
"""
# ----- Imports ----- #

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from feature_state import FRONTEND_SECTION, FeatureNotFoundError, FeatureState, PLAYWRIGHT_REVIEWER_OPTION, load_feature_state
from gate_a import Dismissal, find_dismissal, normalize_path, read_line_text, review_directory, sync_dismissed
from git_changes import GitError, changed_files, diff_base_commit

# ----- Consts ----- #

SETUP_ERROR_EXIT_CODE = 2
CAPTURED_SOURCES = ("conventions", "playwright")
PLAYWRIGHT_SOURCE = "playwright"
FINDING_HEADER_PATTERN = re.compile(
    r"^##\s+(?P<id>[CP]\d+-\d+)\s*\|\s*(?P<location>[^|]+?)\s*\|\s*(?P<rule>[^|]+?)\s*$",
)
LOCATION_PATTERN = re.compile(r"^`?(?P<path>[^`:\s]+\.\w+)`?:(?P<line>\d+)")
NO_VALUE_MARKERS = ("no file", "no rule", "-", "")
FRONTEND_FILE_SUFFIXES = (".vue", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".css", ".scss", ".html")
FINGERPRINT_OPTION = "Playwright checked"
EARLIER_DISMISSALS_HEADER = "## Dismissed in earlier rounds"
FIRST_ROUND = 1
FINGERPRINT_LENGTH = 16

# ----- Classes ----- #


@dataclass(frozen=True)
class ReviewerFinding:
    """
    One finding of the conventions or Playwright reviewer.
    """
    finding_id: str
    file: str
    line: int
    rule: str
    text: str

# ----- Functions ----- #


def parse_reviewer_findings(review_text: str) -> list[ReviewerFinding]:
    """
    Read the findings of a reviewer's file.

    :param review_text: review/<source>-<round>.md, findings as `## C2-1 | path:line | RULE` headers followed by their text.
    :return: The findings in file order; `no file` / `no rule` become empty values.
    """
    findings: list[ReviewerFinding] = []
    current_header: re.Match[str] | None = None
    text_lines: list[str] = []
    for review_line in [*review_text.splitlines(), "## END"]:
        if not review_line.startswith("## "):
            if current_header is not None:
                text_lines.append(review_line)
            continue

        if current_header is not None:
            location = current_header.group("location").strip()
            location_match = LOCATION_PATTERN.match(location)
            rule = current_header.group("rule").strip().strip("`")
            findings.append(
                ReviewerFinding(
                    current_header.group("id"),
                    "" if location_match is None else normalize_path(location_match.group("path")),
                    0 if location_match is None else int(location_match.group("line")),
                    "" if rule.lower() in NO_VALUE_MARKERS else rule,
                    "\n".join(text_lines).strip(),
                ),
            )

        current_header = FINDING_HEADER_PATTERN.match(review_line)
        text_lines = []

    return findings


def finding_records(state: FeatureState, findings: list[ReviewerFinding]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for finding in findings:
        line_text = ""
        if finding.file != "":
            line_text = read_line_text(
                state.code_root(),
                finding.file,
                finding.line,
            )
        records.append(
            {
                "id": finding.finding_id,
                "file": finding.file,
                "line": finding.line,
                "rule": finding.rule,
                "text": finding.text,
                "line_text": line_text,
            },
        )

    return records


def earlier_dismissal_notes(records: list[dict[str, object]], dismissed: list[Dismissal], review_source: str) -> list[str]:
    notes: list[str] = []
    for record in records:
        dismissal = find_dismissal(
            dismissed,
            str(record["file"]),
            str(record["rule"]),
            str(record["line_text"]),
            review_source,
        )
        if dismissal is not None:
            notes.append(
                f"- {record['id']}: dismissed in round {dismissal.round}, because {dismissal.reason}",
            )

    return notes


def frontend_fingerprint(state: FeatureState) -> str:
    """
    Summarise the branch's changed frontend files, so a later round can tell whether they changed.

    :param state: The feature's state.
    :return: A short hash of the changed frontend files' paths and contents.
    :raises GitError: When git can't list the changed files.
    """
    code_root = state.code_root()
    base_commit = diff_base_commit(state.field("Base"), code_root)
    digest = hashlib.sha256()
    for relative_path in changed_files(base_commit, code_root):
        if Path(relative_path).suffix not in FRONTEND_FILE_SUFFIXES:
            continue

        path = code_root / relative_path
        digest.update(relative_path.encode("utf-8"))
        digest.update(
            path.read_bytes() if path.is_file() else b"<deleted>",
        )

    return digest.hexdigest()[:FINGERPRINT_LENGTH]


def set_frontend_option(state: FeatureState, name: str, value: str):
    state.reload()
    prefix = f"- {name}:"
    bounds = state.section_bounds(FRONTEND_SECTION)
    if bounds is not None:
        start_index, end_index = bounds
        for index in range(start_index, end_index):
            if state.lines[index].strip().startswith(prefix):
                state.lines[index] = f"{prefix} {value}"
                state.save()
                return

    state.append_to_section(FRONTEND_SECTION, f"{prefix} {value}")
    state.save()


def capture_round(state: FeatureState, round_number: int) -> list[str]:
    """
    Store the round's conventions and Playwright findings with their flagged lines' text, and note earlier dismissals.

    :param state: The feature's state.
    :param round_number: The review round.
    :return: One line per reviewer file handled.
    :raises GitError: When the Playwright fingerprint can't be computed.
    """
    messages: list[str] = []
    dismissed = sync_dismissed(state)
    for review_source in CAPTURED_SOURCES:
        review_path = review_directory(state.feature_directory) / f"{review_source}-{round_number}.md"
        if not review_path.is_file():
            continue

        review_text = review_path.read_text(encoding="utf-8")
        records = finding_records(state, parse_reviewer_findings(review_text))
        review_path.with_suffix(".json").write_text(json.dumps(records, indent=2), encoding="utf-8")
        notes = earlier_dismissal_notes(
            records,
            dismissed,
            review_source,
        )
        if len(notes) > 0 and EARLIER_DISMISSALS_HEADER not in review_text:
            review_path.write_text(
                review_text.rstrip("\n") + f"\n\n{EARLIER_DISMISSALS_HEADER}\n" + "\n".join(notes) + "\n",
                encoding="utf-8",
            )
        if review_source == PLAYWRIGHT_SOURCE:
            set_frontend_option(
                state,
                FINGERPRINT_OPTION,
                frontend_fingerprint(state),
            )
        messages.append(
            f"{review_path.name}: {len(records)} finding(s), {len(notes)} dismissed earlier",
        )

    return messages


def is_playwright_needed(state: FeatureState, round_number: int) -> bool:
    """
    Tell whether the Playwright reviewer runs this round.

    :param state: The feature's state.
    :param round_number: The review round.
    :return: True when the grill chose it and it's round 1, it never ran, or frontend files changed since it last ran.
    :raises GitError: When the changed files can't be listed.
    """
    if not state.is_frontend_option_on(PLAYWRIGHT_REVIEWER_OPTION):
        return False
    last_fingerprint = state.frontend_option(FINGERPRINT_OPTION)
    if round_number <= FIRST_ROUND or last_fingerprint == "":
        return True
    return frontend_fingerprint(state) != last_fingerprint


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Support the parallel review round of a feature.",
    )
    parser.add_argument(
        "action",
        choices=["capture", "playwright-needed"],
    )
    parser.add_argument("ticket", help="The ticket, e.g. BTRC-1234.")
    parser.add_argument(
        "round",
        type=int,
        help="The review round, 1 to 5.",
    )
    arguments = parser.parse_args()
    try:
        state = load_feature_state(arguments.ticket, Path.cwd())
        if arguments.action == "capture":
            for message in capture_round(state, arguments.round):
                print(message)
            return 0
        print(
            "yes" if is_playwright_needed(state, arguments.round) else "no",
        )
    except (FeatureNotFoundError, GitError) as setup_error:
        print(f"Setup error: {setup_error}")
        return SETUP_ERROR_EXIT_CODE
    return 0


if __name__ == "__main__":
    sys.exit(main())
