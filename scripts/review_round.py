#!/usr/bin/env python3
"""
Plumbing for the review round: checks that every reviewer and verifier wrote a complete file, stores the findings, and checks triage.md.

Usage: python3 review_round.py expected BTRC-1234 <round>
       python3 review_round.py capture BTRC-1234 <round> --source <source>
       python3 review_round.py verify-check BTRC-1234 <round> --source <source>
       python3 review_round.py triage-check BTRC-1234 <round>
`expected` prints the reviewers this round needs: correctness, conventions, tests, spec, and playwright when the grill chose it.
`capture` reads review/<source>-<round>.md (findings as `## <where> | <rule>` followed by the problem, ending with
`Done: <k> finding(s)`; reviewers write no ids), fails when the file is missing, has no `Done:` line, k doesn't match, or a
`## ` line isn't a finding, and otherwise numbers the findings (`## K1-1 | <where> | <rule>`, written back into the file) and
writes review/<source>-<round>.json with each flagged line's text as it is now (run it before fixing anything).
`verify-check` reads review/verify-<source>-<round>.md (`## <id> | sure|unsure|invalid` per finding) and fails unless every
finding of the source has exactly one verdict.
`triage-check` fails unless every expected source is captured and verified, and every finding has a row under `## Round <round>`
in review/triage.md whose Verdict matches the verifier and whose Decision follows it: sure → fix, invalid → dismiss,
unsure → fix, or dismiss with a reason.
Exit codes: 0 done, 1 something is missing or wrong (the message says what), 2 setup error (no feature, git failed).
A source failing `capture` or `verify-check` 3 times in a row blocks the feature.

:author: claude-workflow
:date: 02/11/2026
"""
# ----- Imports ----- #

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from feature_state import FeatureNotFoundError, FeatureState, PLAYWRIGHT_REVIEWER_OPTION, load_feature_state
from gate_a import SOURCE_BY_ID_PREFIX, TRIAGE_FILE_NAME, TRIAGE_ROUND_PATTERN, Dismissal, find_dismissal, normalize_path, read_line_text, review_directory, sync_dismissed
from git_changes import GitError

# ----- Consts ----- #

INCOMPLETE_EXIT_CODE = 1
SETUP_ERROR_EXIT_CODE = 2
ALWAYS_EXPECTED_SOURCES = ("correctness", "conventions", "tests", "spec")
PLAYWRIGHT_SOURCE = "playwright"
REVIEWER_SOURCES = (*ALWAYS_EXPECTED_SOURCES, PLAYWRIGHT_SOURCE)
PREFIX_BY_SOURCE = {
    review_source: prefix
    for prefix, review_source in SOURCE_BY_ID_PREFIX.items()
}
FINDING_HEADER_PATTERN = re.compile(
    r"^##\s+(?:(?P<id>[KCTSP]\d+-\d+)\s*\|\s*)?(?P<location>[^|]+?)\s*\|\s*(?P<rule>[^|]+?)\s*$",
)
VERDICT_HEADER_PATTERN = re.compile(
    r"^##\s+(?P<id>[KCTSP]\d+-\d+)\s*\|\s*(?P<verdict>sure|unsure|invalid)\s*$",
    re.IGNORECASE,
)
DONE_PATTERN = re.compile(
    r"^\s*Done:\s*(?P<count>\d+)\s+findings?(?:\(s\))?\s*\.?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
TRIAGE_ID_PATTERN = re.compile(r"^\|\s*(?P<id>[KCTSPR]\d+-\d+)\s*\|")
LOCATION_PATTERN = re.compile(r"^`?(?P<path>[^`:\s]+\.\w+)`?:(?P<line>\d+)")
NO_VALUE_MARKERS = ("no file", "no rule", "-", "")
EARLIER_DISMISSALS_HEADER = "## Dismissed in earlier rounds"
ALLOWED_OTHER_HEADERS = (EARLIER_DISMISSALS_HEADER,)
SURE = "sure"
UNSURE = "unsure"
INVALID = "invalid"
FIX_DECISION = "fix"
DISMISS_DECISION = "dismiss"
DECISIONS_BY_VERDICT = {
    SURE: (FIX_DECISION,),
    INVALID: (DISMISS_DECISION,),
    UNSURE: (FIX_DECISION, DISMISS_DECISION),
}
TRIAGE_VERDICT_CELL = 2
TRIAGE_DECISION_CELL = 6
TRIAGE_REASON_CELL = 7
TRIAGE_CELLS = 8

# ----- Classes ----- #


@dataclass(frozen=True)
class ReviewerFinding:
    """
    One finding of a reviewer.
    """
    finding_id: str
    file: str
    line: int
    rule: str
    text: str

# ----- Functions ----- #


def expected_sources(state: FeatureState) -> list[str]:
    """
    List the reviewers that must report in every round of this feature.

    :param state: The feature's state.
    :return: The four code reviewers, plus playwright when the grill chose it.
    """
    sources = list(ALWAYS_EXPECTED_SOURCES)
    if state.is_frontend_option_on(PLAYWRIGHT_REVIEWER_OPTION):
        sources.append(PLAYWRIGHT_SOURCE)
    return sources


def reviewer_path(state: FeatureState, review_source: str, round_number: int) -> Path:
    return review_directory(state.feature_directory) / f"{review_source}-{round_number}.md"


def verify_path(state: FeatureState, review_source: str, round_number: int) -> Path:
    return review_directory(state.feature_directory) / f"verify-{review_source}-{round_number}.md"


def parse_reviewer_findings(review_text: str) -> list[ReviewerFinding]:
    """
    Read the findings of a reviewer's file.

    :param review_text: review/<source>-<round>.md, after capture numbered it: `## K2-1 | path:line | RULE` headers followed by their text.
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
                    DONE_PATTERN.sub("", "\n".join(text_lines)).strip(),
                ),
            )

        current_header = FINDING_HEADER_PATTERN.match(review_line)
        text_lines = []

    return findings


def reviewer_file_problems(review_text: str, review_source: str, round_number: int) -> list[str]:
    """
    Check that a reviewer's file is complete: every `## ` line is a finding of this source and round, and `Done: k` matches.

    :param review_text: The reviewer's file.
    :param review_source: The reviewer.
    :param round_number: The review round.
    :return: One line per problem; empty when the file is complete.
    """
    problems: list[str] = []
    expected_prefix = f"{PREFIX_BY_SOURCE[review_source]}{round_number}-"
    header_count = 0
    for review_line in review_text.splitlines():
        if not review_line.startswith("## ") or review_line.strip() in ALLOWED_OTHER_HEADERS:
            continue

        header_match = FINDING_HEADER_PATTERN.match(review_line)
        if header_match is None:
            problems.append(
                f"not a finding header (`## <where> | <rule>`): {review_line.strip()}",
            )
            continue

        finding_id = header_match.group("id")
        if finding_id is not None and not finding_id.startswith(expected_prefix):
            problems.append(
                f"{finding_id} should start with {expected_prefix}",
            )
        header_count += 1

    done_matches = DONE_PATTERN.findall(review_text)
    if len(done_matches) == 0:
        problems.append(
            "no `Done: <k> finding(s)` line at the end (the reviewer didn't finish)",
        )
    elif int(done_matches[-1]) != header_count:
        problems.append(
            f"`Done: {done_matches[-1]}` but {header_count} finding header(s) were read",
        )
    return problems


def numbered_review(review_text: str, review_source: str, round_number: int) -> str:
    """
    Give every finding header its id, `<prefix><round>-<i>` in file order; headers that already have one keep it.

    :param review_text: The reviewer's file, already checked.
    :param review_source: The reviewer.
    :param round_number: The review round.
    :return: The file with every header as `## <id> | <where> | <rule>`.
    """
    prefix = f"{PREFIX_BY_SOURCE[review_source]}{round_number}-"
    numbered_lines: list[str] = []
    finding_number = 0
    for review_line in review_text.splitlines():
        header_match = FINDING_HEADER_PATTERN.match(review_line)
        if header_match is None or review_line.strip() in ALLOWED_OTHER_HEADERS:
            numbered_lines.append(review_line)
            continue

        finding_number += 1
        finding_id = header_match.group("id")
        if finding_id is None:
            finding_id = f"{prefix}{finding_number}"
        numbered_lines.append(
            f"## {finding_id} | {header_match.group('location')} | {header_match.group('rule')}",
        )

    return "\n".join(numbered_lines) + "\n"


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


def load_captured_ids(state: FeatureState, review_source: str, round_number: int) -> list[str] | None:
    review_path = reviewer_path(
        state,
        review_source,
        round_number,
    )
    json_path = review_path.with_suffix(".json")
    if not json_path.is_file():
        return None
    return [
        str(record["id"])
        for record in json.loads(json_path.read_text(encoding="utf-8"))
    ]


def capture_source(state: FeatureState, review_source: str, round_number: int) -> tuple[list[str], str]:
    """
    Check one reviewer's file and store its findings with their flagged lines' text.

    :param state: The feature's state.
    :param review_source: The reviewer.
    :param round_number: The review round.
    :return: The problems (empty when captured) and a one-line summary.
    """
    review_path = reviewer_path(
        state,
        review_source,
        round_number,
    )
    if not review_path.is_file():
        return [f"{review_path.name} doesn't exist: run the {review_source}-reviewer again"], ""
    review_text = review_path.read_text(encoding="utf-8")
    problems = reviewer_file_problems(
        review_text,
        review_source,
        round_number,
    )
    if len(problems) > 0:
        return problems, ""
    review_text = numbered_review(
        review_text,
        review_source,
        round_number,
    )
    review_path.write_text(review_text, encoding="utf-8")
    records = finding_records(state, parse_reviewer_findings(review_text))
    review_path.with_suffix(".json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    notes = earlier_dismissal_notes(
        records,
        sync_dismissed(state),
        review_source,
    )
    if len(notes) > 0 and EARLIER_DISMISSALS_HEADER not in review_text:
        review_path.write_text(
            review_text.rstrip("\n") + f"\n\n{EARLIER_DISMISSALS_HEADER}\n" + "\n".join(notes) + "\n",
            encoding="utf-8",
        )
    return [], f"{review_path.name}: {len(records)} finding(s), {len(notes)} dismissed earlier"


def read_verdicts(verify_text: str) -> tuple[dict[str, str], list[str]]:
    """
    Read a verifier's verdicts.

    :param verify_text: review/verify-<source>-<round>.md.
    :return: Finding id to its verdict, and the ids that got more than one verdict.
    """
    verdicts: dict[str, str] = {}
    repeated: list[str] = []
    for verify_line in verify_text.splitlines():
        verdict_match = VERDICT_HEADER_PATTERN.match(verify_line.strip())
        if verdict_match is None:
            continue

        finding_id = verdict_match.group("id")
        if finding_id in verdicts:
            repeated.append(finding_id)
        verdicts[finding_id] = verdict_match.group("verdict").lower()

    return verdicts, repeated


def verify_problems(state: FeatureState, review_source: str, round_number: int) -> list[str]:
    """
    Check that the verifier gave every finding of a source exactly one verdict.

    :param state: The feature's state.
    :param review_source: The reviewer whose findings were verified.
    :param round_number: The review round.
    :return: One line per problem; empty when complete (also when the source had no findings).
    """
    captured_ids = load_captured_ids(
        state,
        review_source,
        round_number,
    )
    if captured_ids is None:
        return [f"{review_source} isn't captured yet: run `capture` for it first"]
    if len(captured_ids) == 0:
        return []
    path = verify_path(
        state,
        review_source,
        round_number,
    )
    if not path.is_file():
        return [f"{path.name} doesn't exist: run the finding-verifier for {review_source}"]
    verdicts, repeated = read_verdicts(path.read_text(encoding="utf-8"))
    problems = [f"{finding_id} has more than one verdict" for finding_id in repeated]
    problems += [
        f"{finding_id} has no verdict (`## {finding_id} | sure|unsure|invalid`)"
        for finding_id in captured_ids
        if finding_id not in verdicts
    ]
    problems += [
        f"{finding_id} isn't a finding of {review_source}-{round_number}.md"
        for finding_id in verdicts
        if finding_id not in captured_ids
    ]
    return problems


def round_verdicts(state: FeatureState, round_number: int) -> dict[str, str]:
    verdicts: dict[str, str] = {}
    for review_source in expected_sources(state):
        path = verify_path(
            state,
            review_source,
            round_number,
        )
        if path.is_file():
            verdicts.update(
                read_verdicts(path.read_text(encoding="utf-8"))[0],
            )

    return verdicts


def triage_rows(state: FeatureState, round_number: int) -> dict[str, list[str]]:
    """
    Read the rows of the round's section of review/triage.md.

    :param state: The feature's state.
    :param round_number: The review round.
    :return: Finding id to the row's cells.
    """
    triage_path = review_directory(state.feature_directory) / TRIAGE_FILE_NAME
    if not triage_path.is_file():
        return {}
    current_round = 0
    rows: dict[str, list[str]] = {}
    for triage_line in triage_path.read_text(encoding="utf-8").splitlines():
        round_match = TRIAGE_ROUND_PATTERN.match(triage_line)
        if round_match is not None:
            current_round = int(round_match.group("number"))
            continue

        id_match = TRIAGE_ID_PATTERN.match(triage_line.strip())
        if current_round == round_number and id_match is not None:
            rows[id_match.group("id")] = [cell.strip() for cell in triage_line.strip().strip("|").split("|")]

    return rows


def row_problems(finding_id: str, cells: list[str], verdict: str) -> list[str]:
    """
    Check that a triage row carries the verifier's verdict and a decision that follows it.

    :param finding_id: The finding.
    :param cells: The row's cells.
    :param verdict: The verifier's verdict.
    :return: One line per problem.
    """
    if len(cells) < TRIAGE_CELLS:
        return [f"{finding_id}: the row needs 8 cells (# | Source | Verdict | File:line | Rule | Finding | Decision | Reason)"]
    problems: list[str] = []
    if cells[TRIAGE_VERDICT_CELL].lower() != verdict:
        problems.append(
            f"{finding_id}: Verdict is `{cells[TRIAGE_VERDICT_CELL]}`, the verifier said `{verdict}`",
        )
    decision = cells[TRIAGE_DECISION_CELL].lower().partition(":")[0].strip()
    if decision not in DECISIONS_BY_VERDICT[verdict]:
        allowed = " or ".join(DECISIONS_BY_VERDICT[verdict])
        problems.append(
            f"{finding_id}: verdict `{verdict}` needs Decision {allowed}, not `{cells[TRIAGE_DECISION_CELL]}`",
        )
    if decision == DISMISS_DECISION and cells[TRIAGE_REASON_CELL] == "":
        problems.append(f"{finding_id}: a dismiss needs a Reason")
    return problems


def triage_problems(state: FeatureState, round_number: int) -> list[str]:
    """
    List everything that keeps the round from being triaged: a source not captured or verified, a finding without a row, a wrong row.

    :param state: The feature's state.
    :param round_number: The review round.
    :return: One line per problem; empty when the round is fully triaged.
    """
    problems: list[str] = []
    finding_ids: list[str] = []
    for review_source in expected_sources(state):
        captured_ids = load_captured_ids(
            state,
            review_source,
            round_number,
        )
        if captured_ids is None:
            problems.append(
                f"{review_source}: not captured (run the reviewer, then `capture --source {review_source}`)",
            )
            continue

        problems += [f"{review_source}: {problem}" for problem in verify_problems(
            state,
            review_source,
            round_number,
        )]
        finding_ids += captured_ids

    verdicts = round_verdicts(state, round_number)
    rows = triage_rows(state, round_number)
    for finding_id in finding_ids:
        if finding_id not in verdicts:
            continue

        if finding_id not in rows:
            problems.append(
                f"{finding_id}: no row under `## Round {round_number}` in triage.md",
            )
            continue

        problems += row_problems(
            finding_id,
            rows[finding_id],
            verdicts[finding_id],
        )

    return problems


def record_source_failure(state: FeatureState, step: str) -> str:
    state.reload()
    failed_runs = state.record_failure(step)
    state.save()
    if state.is_finished():
        return f"{step} failed {failed_runs} times in a row: state.md is now BLOCKED. Stop."
    return f"Run that agent again (try {failed_runs} of 3)."


def print_problems(title: str, problems: list[str]):
    print(title)
    for problem in problems:
        print(f"- {problem}")


def run_action(state: FeatureState, action: str, round_number: int, review_source: str) -> int:
    """
    Run one action and print its result.

    :param state: The feature's state.
    :param action: expected, capture, verify-check or triage-check.
    :param round_number: The review round.
    :param review_source: The reviewer, for capture and verify-check.
    :return: The exit code.
    """
    if action == "expected":
        print(" ".join(expected_sources(state)))
        return 0
    if action == "triage-check":
        problems = triage_problems(state, round_number)
        if len(problems) == 0:
            print(
                f"Round {round_number} is fully triaged. Fix every `fix` row now.",
            )
            return 0
        print_problems(
            f"Round {round_number} isn't triaged yet:",
            problems,
        )
        return INCOMPLETE_EXIT_CODE
    if review_source not in REVIEWER_SOURCES:
        print(
            f"Setup error: --source must be one of {', '.join(REVIEWER_SOURCES)}.",
        )
        return SETUP_ERROR_EXIT_CODE
    if action == "capture":
        problems, summary = capture_source(
            state,
            review_source,
            round_number,
        )
    else:
        problems = verify_problems(
            state,
            review_source,
            round_number,
        )
        summary = f"verify-{review_source}-{round_number}: every finding has one verdict"
    if len(problems) == 0:
        print(summary)
        return 0
    step = f"{action.upper()}-{review_source}-{round_number}"
    print_problems(f"{step} is incomplete:", problems)
    print(record_source_failure(state, step))
    return INCOMPLETE_EXIT_CODE


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plumbing for a feature's review round.",
    )
    parser.add_argument(
        "action",
        choices=["expected", "capture", "verify-check", "triage-check"],
    )
    parser.add_argument("ticket", help="The ticket, e.g. BTRC-1234.")
    parser.add_argument(
        "round",
        type=int,
        help="The review round, 1 to 3.",
    )
    parser.add_argument(
        "--source",
        default="",
        help="The reviewer, for capture and verify-check: correctness, conventions, tests, spec or playwright.",
    )
    arguments = parser.parse_args()
    try:
        state = load_feature_state(arguments.ticket, Path.cwd())
        return run_action(
            state,
            arguments.action,
            arguments.round,
            arguments.source,
        )
    except (FeatureNotFoundError, GitError) as setup_error:
        print(f"Setup error: {setup_error}")
        return SETUP_ERROR_EXIT_CODE


if __name__ == "__main__":
    sys.exit(main())
