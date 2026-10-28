"""
Gate A: checks everything Beatrice would reject before she reads a line, and keeps the list of dismissed findings.

Usage: python gate_a.py BTRC-1234            run the gate
       python gate_a.py BTRC-1234 --dismissed  print the dismissed findings
Exit codes: 0 passed, 1 failed, 2 the feature can't be found or has no commands.

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
from feature_state import FeatureNotFoundError, FeatureState, load_feature_state, running_marker
from scope_check import allowed_for_branch

# ----- Consts ----- #

FAILED_EXIT_CODE = 1
SETUP_ERROR_EXIT_CODE = 2
COMMAND_TIMEOUT_SECONDS = 45 * 60
OUTPUT_TAIL_LINES = 40
COMMAND_LINE_PATTERN = re.compile(
    r"^\s*[-*]\s+(?P<name>[\w-]+)\s*:\s*(?P<command>.+)$",
)
COVERAGE_COMMAND_PREFIX = "coverage"
MISSING_LINES_PATTERN = re.compile(
    r"^(?P<path>\S.*?) \((?P<percent>[\d.]+)%\): Missing lines (?P<lines>[\d, -]+)$",
)
EXEMPTION_PATTERN = re.compile(
    r"^\s*[-*]\s+`?(?P<path>[^`:\s]+)`?:(?P<lines>[\d,-]+)(?:(?:\s*:\s*|\s+-\s+)(?P<reason>.*))?\s*$",
)
TRIAGE_ROUND_PATTERN = re.compile(r"^##\s+Round\s+(?P<number>\d+)", re.IGNORECASE)
LOCATION_PATTERN = re.compile(r"(?P<path>[\w./\\-]+\.\w+):(?P<line>\d+)")
TRIAGE_MIN_CELLS = 7
TRIAGE_LOCATION_CELL = 2
TRIAGE_RULE_CELL = 3
TRIAGE_DECISION_CELL = 5
TRIAGE_REASON_CELL = 6
DISMISS_DECISION = "dismiss"
DISMISSED_FILE_NAME = "dismissed.json"
TRIAGE_FILE_NAME = "triage.md"
REVIEW_DIRECTORY_NAME = "review"

# ----- Classes ----- #


@dataclass(frozen=True)
class Dismissal:
    """
    A Beatrice finding the orchestrator dismissed, keyed by file, rule and the flagged line's text.
    """
    file: str
    rule: str
    line_text: str
    round: int
    reason: str

    def matches(self, file: str, rule: str, line_text: str) -> bool:
        """
        Tell whether a new finding is the same as this dismissed one.

        :param file: The new finding's file.
        :param rule: The new finding's rule (may be empty).
        :param line_text: The current text of the flagged line.
        :return: Whether file and line text match, and the rules match when both have one.
        """
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


def parse_triage(triage_text: str, code_root: Path) -> list[Dismissal]:
    """
    Read the dismissed findings from review/triage.md.

    :param triage_text: The triage file. Rows: `| # | Marks | File:line | Rule | Finding | Decision | Reason |`, under `## Round <n>`.
    :param code_root: Where the flagged files live, to read the flagged lines.
    :return: One dismissal per `dismiss` row that names a file and line.
    """
    dismissals: list[Dismissal] = []
    round_number = 0
    for triage_line in triage_text.splitlines():
        round_match = TRIAGE_ROUND_PATTERN.match(triage_line)
        if round_match is not None:
            round_number = int(round_match.group("number"))
            continue

        cells = [cell.strip() for cell in triage_line.strip().strip("|").split("|")]
        if not triage_line.strip().startswith("|") or len(cells) < TRIAGE_MIN_CELLS:
            continue

        if not cells[TRIAGE_DECISION_CELL].lower().startswith(DISMISS_DECISION):
            continue

        location = LOCATION_PATTERN.search(cells[TRIAGE_LOCATION_CELL])
        if location is None:
            continue

        reason = cells[TRIAGE_REASON_CELL]
        decision_reason = cells[TRIAGE_DECISION_CELL].partition(":")[2].strip()
        if reason == "" and decision_reason != "":
            reason = decision_reason
        dismissals.append(
            Dismissal(
                normalize_path(location.group("path")),
                cells[TRIAGE_RULE_CELL].strip("`"),
                read_line_text(
                    code_root,
                    location.group("path"),
                    int(location.group("line")),
                ),
                round_number,
                reason,
            ),
        )

    return dismissals


def dismissed_path(feature_directory: Path) -> Path:
    return feature_directory / REVIEW_DIRECTORY_NAME / DISMISSED_FILE_NAME


def load_dismissed(feature_directory: Path) -> list[Dismissal]:
    path = dismissed_path(feature_directory)
    if not path.is_file():
        return []
    return [Dismissal(**entry) for entry in json.loads(path.read_text(encoding="utf-8"))]


def sync_dismissed(state: FeatureState) -> list[Dismissal]:
    """
    Add the dismissals in review/triage.md to review/dismissed.json, keeping earlier ones.

    :param state: The feature's state.
    :return: Every dismissal known so far.
    """
    dismissed = load_dismissed(state.feature_directory)
    triage_path = state.feature_directory / REVIEW_DIRECTORY_NAME / TRIAGE_FILE_NAME
    if not triage_path.is_file():
        return dismissed
    for dismissal in parse_triage(
        triage_path.read_text(encoding="utf-8"),
        state.code_root(),
    ):
        is_known = any(
            known.file == dismissal.file and known.rule == dismissal.rule and known.line_text == dismissal.line_text
            for known in dismissed
        )
        if not is_known:
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


def find_dismissal(dismissed: list[Dismissal], file: str, rule: str, line_text: str) -> Dismissal | None:
    for dismissal in dismissed:
        if dismissal.matches(
            file,
            rule,
            line_text,
        ):
            return dismissal

    return None


def parse_commands(state: FeatureState) -> list[tuple[str, str]]:
    commands: list[tuple[str, str]] = []
    for command_line in state.section("Commands"):
        command_match = COMMAND_LINE_PATTERN.match(command_line)
        if command_match is not None:
            commands.append(
                (command_match.group("name"), command_match.group("command").strip().strip("`")),
            )

    return commands


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
    :return: The exempt lines per file, and the exemptions that give no reason.
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
    :param exemptions: The exempt lines per file.
    :return: `file: lines` entries still uncovered.
    """
    entries: list[str] = []
    for output_line in output.splitlines():
        missing_match = MISSING_LINES_PATTERN.match(output_line.strip())
        if missing_match is None:
            continue

        path = normalize_path(missing_match.group("path"))
        missing = expand_line_ranges(missing_match.group("lines"))
        exempt: set[int] = set()
        for exempt_path, exempt_lines in exemptions.items():
            if path.endswith(exempt_path) or exempt_path.endswith(path):
                exempt.update(exempt_lines)

        remaining = sorted(missing - exempt)
        if len(remaining) > 0:
            entries.append(
                f"{path}: {', '.join(str(line) for line in remaining)}",
            )

    return entries


def output_tail(output: str) -> str:
    return "\n".join(output.strip().splitlines()[-OUTPUT_TAIL_LINES:])


def run_project_commands(state: FeatureState) -> list[str]:
    """
    Run the lint, typecheck, test and coverage commands from state.md.

    :param state: The feature's state, with `- name: command` lines under `## Commands`.
    :return: One failure description per failing command.
    """
    exemptions, without_reason = parse_exemptions(state)
    failures = [f"Coverage exemption without a reason: {exemption}" for exemption in without_reason]
    for name, command in parse_commands(state):
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

        uncovered = uncovered_lines(result.output, exemptions)
        if len(uncovered) > 0:
            failures.append(
                f"{name}: changed lines without coverage (add tests, or a `- path:lines: reason` exemption in state.md):\n"
                + "\n".join(f"  {entry}" for entry in uncovered),
            )
            continue

        has_missing_lines = any(
            MISSING_LINES_PATTERN.match(output_line.strip()) is not None
            for output_line in result.output.splitlines()
        )
        if not result.succeeded and not has_missing_lines:
            failures.append(
                f"{name} failed (`{command}`):\n{output_tail(result.output)}",
            )

    return failures


def run_gate(state: FeatureState) -> tuple[BranchReport, list[str]]:
    with running_marker(state.feature_directory, "gate A"):
        report = check_branch(
            state,
            allowed_for_branch(state.feature_directory),
        )
        failures = run_project_commands(state)

    return report, failures


def record_gate_result(state: FeatureState, passed: bool) -> str:
    round_number = max(state.number_field("Round"), 1)
    if not passed:
        failed_runs = state.record_failure(f"GATE-A-{round_number}")
        state.save()
        if state.is_finished():
            return f"Gate A failed {failed_runs} times: state.md is now BLOCKED. Stop."
        return f"Gate A failed (try {failed_runs}). Fix the items above and run this again."
    state.reset_tries()
    state.set_field("Round", str(round_number))
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
    if len(parse_commands(state)) == 0:
        print(
            "state.md has no `## Commands` (`- lint: ...`, `- typecheck: ...`, `- test: ...`, `- coverage: ...`). Add them first.",
        )
        return SETUP_ERROR_EXIT_CODE
    report, failures = run_gate(state)
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
