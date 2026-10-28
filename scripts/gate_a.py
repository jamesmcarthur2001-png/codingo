#!/usr/bin/env python3
"""
Gate A: checks everything Beatrice would reject before she reads a line, and keeps the list of dismissed findings.

Usage: python3 gate_a.py BTRC-1234              run the gate
       python3 gate_a.py BTRC-1234 --dismissed  print the dismissed findings
Exit codes: 0 passed, 1 failed, 2 setup error (no feature, no commands, a coverage command without
--include-untracked, git failed, or another long step of the feature is running).

:author: midnight-workflow
:date: 28/10/2026
"""
# ----- Imports ----- #

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import command_runner
from check_slice import BranchReport, check_branch
from feature_state import FeatureNotFoundError, FeatureState, StepAlreadyRunningError, load_feature_state, refresh_running_marker, running_marker
from git_changes import GitError
from line_checks import FRONTEND_SUFFIXES, PYTHON_SUFFIXES
from scope_check import allowed_for_branch

# ----- Consts ----- #

FAILED_EXIT_CODE = 1
SETUP_ERROR_EXIT_CODE = 2
COMMAND_TIMEOUT_SECONDS = 45 * 60
OUTPUT_TAIL_LINES = 40
MAX_BEATRICE_ROUNDS = 5
COMMAND_LINE_PATTERN = re.compile(
    r"^\s*[-*]\s+(?P<name>[\w-]+)\s*:\s*(?P<command>.+)$",
)
COVERAGE_COMMAND_PREFIX = "coverage"
INCLUDE_UNTRACKED_FLAG = "--include-untracked"
NO_COVERAGE_LINES_MARKER = "No lines with coverage information in this diff"
MISSING_LINES_PATTERN = re.compile(
    r"^(?P<path>\S.*?) \((?P<percent>[\d.]+)%\): Missing lines (?P<lines>[\d, -]+)$",
)
EXEMPTION_PATTERN = re.compile(
    r"^\s*[-*]\s+`?(?P<path>[^`:\s]+)`?:(?P<lines>[\d,-]+)(?:(?:\s*:\s*|\s+-\s+)(?P<reason>.*))?\s*$",
)
TRIAGE_ROUND_PATTERN = re.compile(r"^##\s+Round\s+(?P<number>\d+)", re.IGNORECASE)
LOCATION_PATTERN = re.compile(r"(?P<path>[\w./-]+\.\w+):(?P<line>\d+)")
TEST_PATH_PATTERN = re.compile(
    r"(?:^|/)(?:tests?|__tests__)/|(?:^|/)test_[^/]*$|\.(?:spec|test)\.\w+$",
)
TRIAGE_MIN_CELLS = 7
TRIAGE_ID_CELL = 0
SOURCED_TRIAGE_CELLS = 8
TRIAGE_CELLS_BY_LAYOUT = {
    "sourced": {"source": 1, "location": 3, "rule": 4, "decision": 6, "reason": 7},
    "plain": {"source": -1, "location": 2, "rule": 3, "decision": 5, "reason": 6},
}
BEATRICE_SOURCE = "beatrice"
REVIEW_SOURCES = ("beatrice", "conventions", "playwright")
SOURCE_BY_ID_PREFIX = {"R": "beatrice", "C": "conventions", "P": "playwright"}
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

    def matches(self, file: str, rule: str, line_text: str, source: str = BEATRICE_SOURCE) -> bool:
        """
        Tell whether a new finding is the same as this dismissed one.

        :param file: The new finding's file.
        :param rule: The new finding's rule (may be empty).
        :param line_text: The text of the flagged line.
        :param source: Who reported the new finding (beatrice, conventions, playwright); memories are per source.
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
    Read the findings stored for a round by run_beatrice.py and review_round.py, with the flagged line text captured then.

    :param feature_directory: The feature's directory.
    :param round_number: The review round.
    :return: Finding id (e.g. `R2-3`, `C2-1`, `P2-4`) to its record; empty when the round has no record files.
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
    :return: beatrice, conventions or playwright.
    """
    if source_cell >= 0:
        named_source = cells[source_cell].strip("`").lower()
        if named_source in REVIEW_SOURCES:
            return named_source
    return SOURCE_BY_ID_PREFIX.get(finding_id[:1].upper(), BEATRICE_SOURCE)


def parse_triage(triage_text: str, feature_directory: Path, code_root: Path) -> list[Dismissal]:
    """
    Read the dismissed findings from review/triage.md.

    :param triage_text: The triage file. Rows: `| # | Source | Marks | File:line | Rule | Finding | Decision | Reason |` under `## Round <n>`
        (rows without the Source column are read as Beatrice's).
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
        if dismissal.matches(
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


def parse_commands(state: FeatureState) -> list[tuple[str, str]]:
    commands: list[tuple[str, str]] = []
    for command_line in state.section("Commands"):
        command_match = COMMAND_LINE_PATTERN.match(command_line)
        if command_match is not None:
            commands.append(
                (command_match.group("name"), command_match.group("command").strip().strip("`")),
            )

    return commands


def coverage_commands_without_untracked(commands: list[tuple[str, str]]) -> list[str]:
    return [
        name
        for name, command in commands
        if name.startswith(COVERAGE_COMMAND_PREFIX) and INCLUDE_UNTRACKED_FLAG not in command
    ]


def expand_line_ranges(raw_ranges: str) -> set[int]:
    """
    Turn `3,5-7` into {3, 5, 6, 7}.

    :param raw_ranges: Comma-separated lines and ranges.
    :return: Every line number in them.
    """
    lines: set[int] = set()
    for part in raw_ranges.split(","):
        start, _, end = part.strip().partition("-")
        if not start.strip().isdigit():
            continue

        last = end.strip() if end.strip().isdigit() else start.strip()
        lines.update(range(int(start), int(last) + 1))

    return lines


def parse_exemptions(state: FeatureState) -> tuple[dict[str, set[int]], list[str]]:
    """
    Read the coverage exemptions of state.md.

    :param state: The feature's state, with `- path:lines: reason` lines under `## Coverage exemptions`.
    :return: The exempt lines per repo-relative file, and the exemptions that give no reason.
    """
    exemptions: dict[str, set[int]] = {}
    without_reason: list[str] = []
    for exemption_line in state.section("Coverage exemptions"):
        exemption_match = EXEMPTION_PATTERN.match(exemption_line)
        if exemption_match is None:
            continue

        reason = exemption_match.group("reason")
        if reason is None or reason.strip() == "":
            without_reason.append(exemption_line.strip())
            continue

        path = normalize_path(exemption_match.group("path"))
        exemptions.setdefault(path, set()).update(
            expand_line_ranges(exemption_match.group("lines")),
        )

    return exemptions, without_reason


def uncovered_lines(output: str, exemptions: dict[str, set[int]]) -> list[str]:
    """
    Read diff-cover's missing lines and drop the exempt ones.

    :param output: diff-cover's console output.
    :param exemptions: The exempt lines per repo-relative file (matched by the full path only).
    :return: `file: lines` entries still uncovered.
    """
    entries: list[str] = []
    for output_line in output.splitlines():
        missing_match = MISSING_LINES_PATTERN.match(output_line.strip())
        if missing_match is None:
            continue

        path = normalize_path(missing_match.group("path"))
        missing = expand_line_ranges(missing_match.group("lines"))
        remaining = sorted(missing - exemptions.get(path, set()))
        if len(remaining) > 0:
            entries.append(
                f"{path}: {', '.join(str(line) for line in remaining)}",
            )

    return entries


def has_changed_code(changed: list[str]) -> bool:
    return any(
        Path(path).suffix in PYTHON_SUFFIXES + FRONTEND_SUFFIXES and TEST_PATH_PATTERN.search(path) is None
        for path in changed
    )


def output_tail(output: str) -> str:
    return "\n".join(output.strip().splitlines()[-OUTPUT_TAIL_LINES:])


def coverage_failure(
    name: str,
    command: str,
    result: command_runner.CommandResult,
    exemptions: dict[str, set[int]],
    changed_code: bool,
) -> str | None:
    """
    Judge one diff-cover run.

    :param name: The command's name in state.md.
    :param command: The command.
    :param result: What it returned.
    :param exemptions: The exempt lines per file.
    :param changed_code: Whether the branch changed non-test code.
    :return: The failure description, or None when coverage is complete.
    """
    uncovered = uncovered_lines(result.output, exemptions)
    if len(uncovered) > 0:
        return (
            f"{name}: changed lines without coverage (add tests, or a `- path:lines: reason` exemption in state.md):\n"
            + "\n".join(f"  {entry}" for entry in uncovered)
        )
    if NO_COVERAGE_LINES_MARKER in result.output and changed_code:
        return f"{name}: diff-cover saw no changed lines, but the branch changed code. Check the report path and {INCLUDE_UNTRACKED_FLAG}."
    has_missing_lines = any(
        MISSING_LINES_PATTERN.match(output_line.strip()) is not None
        for output_line in result.output.splitlines()
    )
    if not result.succeeded and not has_missing_lines:
        return f"{name} failed (`{command}`):\n{output_tail(result.output)}"
    return None


def run_project_commands(state: FeatureState, changed: list[str]) -> list[str]:
    """
    Run the lint, typecheck, test and coverage commands from state.md.

    :param state: The feature's state, with `- name: command` lines under `## Commands`.
    :param changed: The files the branch changed.
    :return: One failure description per failing command.
    """
    exemptions, without_reason = parse_exemptions(state)
    failures = [f"Coverage exemption without a reason: {exemption}" for exemption in without_reason]
    for name, command in parse_commands(state):
        refresh_running_marker(state.feature_directory, f"gate A: {name}")
        result = command_runner.run_command(
            command,
            state.code_root(),
            COMMAND_TIMEOUT_SECONDS,
        )
        if not name.startswith(COVERAGE_COMMAND_PREFIX):
            if not result.succeeded:
                failures.append(
                    f"{name} failed (`{command}`):\n{output_tail(result.output)}",
                )
            continue

        failure = coverage_failure(
            name,
            command,
            result,
            exemptions,
            has_changed_code(changed),
        )
        if failure is not None:
            failures.append(failure)

    return failures


def run_gate(state: FeatureState) -> tuple[BranchReport, list[str]]:
    with running_marker(state.feature_directory, "gate A"):
        report = check_branch(
            state,
            allowed_for_branch(state.feature_directory),
        )
        failures = run_project_commands(state, report.changed)

    return report, failures


def record_gate_result(state: FeatureState, passed: bool) -> str:
    """
    Advance state.md after the gate, or count the failed try.

    :param state: The feature's state.
    :param passed: Whether the gate passed.
    :return: A line telling the orchestrator what happens next.
    """
    state.reload()
    round_number = max(state.number_field("Round"), 1)
    if not passed:
        failed_runs = state.record_failure(f"GATE-A-{round_number}")
        state.save()
        if state.is_finished():
            return f"Gate A failed {failed_runs} times: state.md is now BLOCKED. Stop."
        return f"Gate A failed (try {failed_runs}). Fix the items above and run this again."
    state.reset_tries()
    state.set_field("Round", str(round_number))
    is_last_round_done = round_number >= MAX_BEATRICE_ROUNDS and is_round_triaged(state.feature_directory, round_number)
    if is_last_round_done:
        next_phase = state.phase_after_review()
        state.set_field("Phase", next_phase)
        state.log(
            f"Gate A passed after the fixes of Beatrice round {round_number}, the last one",
        )
        state.save()
        return f"Gate A passed. Round {round_number} was the last review round: Phase is now {next_phase}."
    state.set_field("Phase", "GATE-B")
    state.log(
        f"Gate A passed before Beatrice round {round_number}",
    )
    state.save()
    return f"Gate A passed. Phase is now GATE-B, round {round_number}."


def print_dismissed(dismissed: list[Dismissal]):
    if len(dismissed) == 0:
        print("No dismissed findings.")
        return
    for dismissal in dismissed:
        print(
            f"- {dismissal.file} [{dismissal.rule}] `{dismissal.line_text}`: dismissed in round {dismissal.round}, because {dismissal.reason}",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Gate A for a feature.")
    parser.add_argument("ticket", help="The ticket, e.g. BTRC-1234.")
    parser.add_argument(
        "--dismissed",
        action="store_true",
        help="Only print the dismissed findings.",
    )
    arguments = parser.parse_args()
    try:
        state = load_feature_state(arguments.ticket, Path.cwd())
    except FeatureNotFoundError as missing_error:
        print(missing_error)
        return SETUP_ERROR_EXIT_CODE
    dismissed = sync_dismissed(state)
    if arguments.dismissed:
        print_dismissed(dismissed)
        return 0
    commands = parse_commands(state)
    if len(commands) == 0:
        print(
            "state.md has no `## Commands` (`- lint: ...`, `- typecheck: ...`, `- test: ...`, `- coverage: ...`). Add them first.",
        )
        return SETUP_ERROR_EXIT_CODE
    missing_untracked = coverage_commands_without_untracked(commands)
    if len(missing_untracked) > 0:
        print(
            f"Coverage commands without {INCLUDE_UNTRACKED_FLAG} (new files are untracked until finish): {', '.join(missing_untracked)}.",
        )
        return SETUP_ERROR_EXIT_CODE
    try:
        report, failures = run_gate(state)
    except (GitError, StepAlreadyRunningError) as setup_error:
        print(f"Setup error: {setup_error}")
        return SETUP_ERROR_EXIT_CODE
    rendered_report = report.render()
    if rendered_report != "":
        print(rendered_report + "\n")
    for failure in failures:
        print(failure + "\n")
    passed = report.passed and len(failures) == 0
    print(record_gate_result(state, passed))
    if passed:
        return 0
    return FAILED_EXIT_CODE


if __name__ == "__main__":
    sys.exit(main())
