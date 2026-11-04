#!/usr/bin/env python3
"""
The review round's memory: reads the findings stored per round and the dismissed findings from review/triage.md.

Usage: python3 review_memory.py BTRC-1234   print the dismissed findings
A dismissal is keyed by its reviewer, file, rule and the flagged line's text as it was when it was flagged, so a later
round that flags the same unchanged line keeps the earlier decision.
Exit codes: 0 printed, 2 setup error (no feature).

:author: claude-workflow
:date: 04/11/2026
"""
# ----- Imports ----- #

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from feature_state import FeatureNotFoundError, FeatureState, load_feature_state

# ----- Consts ----- #

SETUP_ERROR_EXIT_CODE = 2
MAX_REVIEW_ROUNDS = 3
TRIAGE_ROUND_PATTERN = re.compile(r"^##\s+Round\s+(?P<number>\d+)", re.IGNORECASE)
LOCATION_PATTERN = re.compile(r"(?P<path>[\w./-]+\.\w+):(?P<line>\d+)")
TRIAGE_MIN_CELLS = 7
TRIAGE_ID_CELL = 0
SOURCED_TRIAGE_CELLS = 8
TRIAGE_CELLS_BY_LAYOUT = {
    "sourced": {"source": 1, "location": 3, "rule": 4, "decision": 6, "reason": 7},
    "plain": {"source": -1, "location": 2, "rule": 3, "decision": 5, "reason": 6},
}
BEATRICE_SOURCE = "beatrice"
SOURCE_BY_ID_PREFIX = {
    "K": "correctness",
    "C": "conventions",
    "T": "tests",
    "S": "spec",
    "P": "playwright",
    "R": BEATRICE_SOURCE,
}
REVIEW_SOURCES = tuple(SOURCE_BY_ID_PREFIX.values())
DISMISS_DECISION = "dismiss"
DISMISSED_FILE_NAME = "dismissed.json"
TRIAGE_FILE_NAME = "triage.md"
REVIEW_DIRECTORY_NAME = "review"

# ----- Classes ----- #


@dataclass(frozen=True)
class Dismissal:
    """
    A review finding the orchestrator dismissed, keyed by its source, file, rule and the flagged line's text as it was when it was flagged.
    """
    file: str
    rule: str
    line_text: str
    round: int
    reason: str
    finding_id: str = ""
    source: str = BEATRICE_SOURCE

    def is_same_finding(self, file: str, rule: str, line_text: str, source: str = BEATRICE_SOURCE) -> bool:
        """
        Tell whether a new finding is the same as this dismissed one.

        :param file: The new finding's file.
        :param rule: The new finding's rule (may be empty).
        :param line_text: The text of the flagged line.
        :param source: Who reported the new finding; memories are per source.
        :return: Whether source, file and line text match, and the rules match when both have one.
        """
        if self.source != source:
            return False
        if self.line_text == "" or normalize_path(file) != normalize_path(self.file):
            return False
        if line_text.strip() != self.line_text:
            return False
        if self.rule != "" and rule != "":
            return self.rule.lower() == rule.lower()
        return True

# ----- Functions ----- #


def normalize_path(path: str) -> str:
    return path.strip().replace("\\", "/").removeprefix("./")


def read_line_text(code_root: Path, file: str, line: int) -> str:
    path = code_root / normalize_path(file)
    if not path.is_file():
        return ""
    source_lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    if line < 1 or line > len(source_lines):
        return ""
    return source_lines[line - 1].strip()


def review_directory(feature_directory: Path) -> Path:
    return feature_directory / REVIEW_DIRECTORY_NAME


def load_round_findings(feature_directory: Path, round_number: int) -> dict[str, dict[str, object]]:
    """
    Read the findings stored for a round by review_round.py (and, for older features, run_beatrice.py), with the flagged line text captured then.

    :param feature_directory: The feature's directory.
    :param round_number: The review round.
    :return: Finding id (e.g. `K2-3`, `C2-1`, `P2-4`) to its record; empty when the round has no record files.
    """
    findings: dict[str, dict[str, object]] = {}
    for review_source in REVIEW_SOURCES:
        path = review_directory(feature_directory) / f"{review_source}-{round_number}.json"
        if not path.is_file():
            continue

        for record in json.loads(path.read_text(encoding="utf-8")):
            if isinstance(record, dict) and "id" in record:
                findings[str(record["id"])] = record

    return findings


def triage_source(cells: list[str], source_cell: int, finding_id: str) -> str:
    """
    Read which reviewer a triage row is about.

    :param cells: The row's cells.
    :param source_cell: The Source column, or -1 for the old layout without one.
    :param finding_id: The row's finding id, whose prefix also names the source.
    :return: The reviewer's source name (correctness, conventions, tests, spec, playwright; beatrice for older features).
    """
    if source_cell >= 0:
        named_source = cells[source_cell].strip("`").lower()
        if named_source in REVIEW_SOURCES:
            return named_source
    return SOURCE_BY_ID_PREFIX.get(finding_id[:1].upper(), BEATRICE_SOURCE)


def parse_triage(triage_text: str, feature_directory: Path, code_root: Path) -> list[Dismissal]:
    """
    Read the dismissed findings from review/triage.md.

    :param triage_text: The triage file. Rows: `| # | Source | Verdict | File:line | Rule | Finding | Decision | Reason |` under `## Round <n>`
        (older features have Marks where Verdict is; rows without the Source column are read as Beatrice's).
    :param feature_directory: The feature's directory, holding the rounds' finding records.
    :param code_root: Where the flagged files live, for rows whose id isn't in a record.
    :return: One dismissal per `dismiss` row; the line text comes from the round's record when the id is there.
    """
    dismissals: list[Dismissal] = []
    round_number = 0
    round_findings: dict[str, dict[str, object]] = {}
    for triage_line in triage_text.splitlines():
        round_match = TRIAGE_ROUND_PATTERN.match(triage_line)
        if round_match is not None:
            round_number = int(round_match.group("number"))
            round_findings = load_round_findings(feature_directory, round_number)
            continue

        cells = [cell.strip() for cell in triage_line.strip().strip("|").split("|")]
        if not triage_line.strip().startswith("|") or len(cells) < TRIAGE_MIN_CELLS:
            continue

        layout = TRIAGE_CELLS_BY_LAYOUT["sourced" if len(cells) >= SOURCED_TRIAGE_CELLS else "plain"]
        if not cells[layout["decision"]].lower().startswith(DISMISS_DECISION):
            continue

        reason = cells[layout["reason"]]
        decision_reason = cells[layout["decision"]].partition(":")[2].strip()
        if reason == "" and decision_reason != "":
            reason = decision_reason
        finding_id = cells[TRIAGE_ID_CELL].strip("`")
        review_source = triage_source(
            cells,
            layout["source"],
            finding_id,
        )
        record = round_findings.get(finding_id)
        if record is not None:
            dismissals.append(
                Dismissal(
                    normalize_path(str(record.get("file", ""))),
                    str(record.get("rule", "")),
                    str(record.get("line_text", "")),
                    round_number,
                    reason,
                    finding_id,
                    review_source,
                ),
            )
            continue

        location = LOCATION_PATTERN.search(cells[layout["location"]])
        if location is None:
            continue

        dismissals.append(
            Dismissal(
                normalize_path(location.group("path")),
                cells[layout["rule"]].strip("`"),
                read_line_text(
                    code_root,
                    location.group("path"),
                    int(location.group("line")),
                ),
                round_number,
                reason,
                finding_id,
                review_source,
            ),
        )

    return dismissals


def dismissed_path(feature_directory: Path) -> Path:
    return review_directory(feature_directory) / DISMISSED_FILE_NAME


def load_dismissed(feature_directory: Path) -> list[Dismissal]:
    path = dismissed_path(feature_directory)
    if not path.is_file():
        return []
    return [Dismissal(**entry) for entry in json.loads(path.read_text(encoding="utf-8"))]


def is_stored(dismissal: Dismissal, dismissed: list[Dismissal]) -> bool:
    for known in dismissed:
        if dismissal.finding_id != "" and (known.round, known.finding_id) == (dismissal.round, dismissal.finding_id):
            return True

        is_same_key = (known.source, known.file, known.rule, known.line_text) == (dismissal.source, dismissal.file, dismissal.rule, dismissal.line_text)
        if is_same_key:
            return True

    return False


def sync_dismissed(state: FeatureState) -> list[Dismissal]:
    """
    Add new dismissals from review/triage.md to review/dismissed.json; rows already stored are never read again.

    :param state: The feature's state.
    :return: Every dismissal known so far.
    """
    dismissed = load_dismissed(state.feature_directory)
    triage_path = review_directory(state.feature_directory) / TRIAGE_FILE_NAME
    if not triage_path.is_file():
        return dismissed
    for dismissal in parse_triage(
        triage_path.read_text(encoding="utf-8"),
        state.feature_directory,
        state.code_root(),
    ):
        if not is_stored(dismissal, dismissed):
            dismissed.append(dismissal)

    path = dismissed_path(state.feature_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [asdict(dismissal) for dismissal in dismissed],
            indent=2,
        ),
        encoding="utf-8",
    )
    return dismissed


def find_dismissal(
    dismissed: list[Dismissal],
    file: str,
    rule: str,
    line_text: str,
    source: str = BEATRICE_SOURCE,
) -> Dismissal | None:
    for dismissal in dismissed:
        if dismissal.is_same_finding(
            file,
            rule,
            line_text,
            source,
        ):
            return dismissal

    return None


def is_round_triaged(feature_directory: Path, round_number: int) -> bool:
    triage_path = review_directory(feature_directory) / TRIAGE_FILE_NAME
    if not triage_path.is_file():
        return False
    for triage_line in triage_path.read_text(encoding="utf-8").splitlines():
        round_match = TRIAGE_ROUND_PATTERN.match(triage_line)
        if round_match is not None and int(round_match.group("number")) == round_number:
            return True

    return False


def print_dismissed(dismissed: list[Dismissal]):
    if len(dismissed) == 0:
        print("No dismissed findings.")
        return
    for dismissal in dismissed:
        print(
            f"- {dismissal.file} [{dismissal.rule}] `{dismissal.line_text}`: dismissed in round {dismissal.round}, because {dismissal.reason}",
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print a feature's dismissed review findings.",
    )
    parser.add_argument("ticket", help="The ticket, e.g. BTRC-1234.")
    arguments = parser.parse_args()
    try:
        state = load_feature_state(arguments.ticket, Path.cwd())
    except FeatureNotFoundError as missing_error:
        print(missing_error)
        return SETUP_ERROR_EXIT_CODE
    print_dismissed(sync_dismissed(state))
    return 0


if __name__ == "__main__":
    sys.exit(main())
