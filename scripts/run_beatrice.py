"""
Gate B: runs the team leader's Beatrice review command, unchanged, in two parallel `claude -p` sessions and merges their findings.

Usage: python run_beatrice.py BTRC-1234 <round>
Writes review/beatrice-<round>-a.md, -b.md (raw) and review/beatrice-<round>.md (merged, marked 2/2 or 1/2).
Exit codes: 0 at least one run finished, 1 both runs failed twice, 2 the feature can't be found.

:author: midnight-workflow
:date: 28/10/2026
"""
# ----- Imports ----- #

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import command_runner
from feature_state import FeatureNotFoundError, FeatureState, REVIEWER_ROLE, ROLE_VARIABLE, load_feature_state, running_marker
from gate_a import Dismissal, find_dismissal, normalize_path, read_line_text, sync_dismissed

# ----- Consts ----- #

FAILED_EXIT_CODE = 1
SETUP_ERROR_EXIT_CODE = 2
RUN_TIMEOUT_SECONDS = 30 * 60
RUN_ATTEMPTS = 2
RUN_LABELS = ("a", "b")
DEFAULT_COMMAND_NAME = "beatrice-code-review"
DEFAULT_ALLOWED_TOOLS = "Read,Grep,Glob,Agent,Bash(git diff:*),Bash(git log:*),Bash(git show:*),Bash(glab mr:*),Bash(npx nx:*)"
SLASH_MODE = "slash"
FILE_MODE = "file"
FRONTMATTER_PATTERN = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
ITEM_START_PATTERN = re.compile(
    r"^\s{0,3}(?:[-*+]\s+|\d+[.)]\s+|\|(?!\s*:?-{3,}))",
)
CONTINUATION_PATTERN = re.compile(r"^\s{2,}\S")
LOCATION_PATTERN = re.compile(
    r"`?(?P<path>[\w./\\-]+\.[A-Za-z]\w*)`?(?::| line |#L)(?P<line>\d+)",
)
EXPLICIT_RULE_PATTERN = re.compile(
    r"\brule\s*[:=]\s*`?(?P<rule>[\w./@-]+)`?",
    re.IGNORECASE,
)
RULE_ID_PATTERN = re.compile(r"\b(?!BTRC-)(?P<rule>[A-Z]{2,6}-\d+)\b")
TABLE_HEADER_WORDS = ("file", "finding", "severity", "rule", "location")
WORD_PATTERN = re.compile(r"[a-z0-9]+")
BEATRICE_LOG_NAME = "beatrice-log.md"
LOG_TIME_FORMAT = "%d/%m/%Y"

# ----- Classes ----- #


@dataclass(frozen=True)
class Finding:
    """
    One item of a Beatrice run's output.
    """
    text: str
    file: str = ""
    line: int = 0
    rule: str = ""

    @property
    def normalized_text(self) -> str:
        return " ".join(WORD_PATTERN.findall(self.text.lower()))

    def is_same_as(self, other: "Finding") -> bool:
        """
        Tell whether two runs reported the same finding: same file, line and rule (when both name a rule).

        :param other: A finding from the other run.
        :return: Whether they are the same finding.
        """
        if self.file == "" or other.file == "":
            return self.file == other.file and self.normalized_text == other.normalized_text
        if normalize_path(self.file) != normalize_path(other.file) or self.line != other.line:
            return False
        if self.rule != "" and other.rule != "":
            return self.rule.lower() == other.rule.lower()
        return True


@dataclass(frozen=True)
class MergedFinding:
    """
    A finding after merging both runs, with how many runs reported it.
    """
    finding: Finding
    marks: str
    other_text: str = ""

# ----- Functions ----- #


def build_prompt(state: FeatureState) -> str:
    """
    Build the prompt that starts Beatrice's command, unchanged, on the feature's base branch.

    :param state: The feature's state, with `Base:`, `Beatrice command:` and `Beatrice mode:`.
    :return: `/<command> <base>` in slash mode; the command file's text with $ARGUMENTS filled in file mode.
    """
    base = state.field("Base")
    command_path = state.field("Beatrice command")
    command_name = DEFAULT_COMMAND_NAME if command_path == "" else Path(command_path).stem
    if state.field("Beatrice mode").lower() != FILE_MODE:
        return f"/{command_name} {base}"
    command_text = Path(command_path).expanduser().read_text(encoding="utf-8")
    command_text = FRONTMATTER_PATTERN.sub(
        "",
        command_text.replace("\r\n", "\n"),
        count=1,
    )
    return command_text.replace("$ARGUMENTS", base)


def allowed_tools(state: FeatureState) -> str:
    tools = state.field("Beatrice tools")
    if tools == "":
        return DEFAULT_ALLOWED_TOOLS
    return tools


def run_review(prompt: str, tools: str, cwd: Path, output_path: Path) -> tuple[bool, int]:
    """
    Run one Beatrice session, retrying once when it fails, times out or prints nothing.

    :param prompt: The review prompt.
    :param tools: The --allowedTools value.
    :param cwd: The worktree to review.
    :param output_path: Where the run's output goes.
    :return: Whether a run succeeded, and how many attempts it took.
    """
    for attempt in range(1, RUN_ATTEMPTS + 1):
        result = command_runner.run_command(
            [command_runner.find_executable("claude"), "-p", prompt, "--allowedTools", tools],
            cwd,
            RUN_TIMEOUT_SECONDS,
            {ROLE_VARIABLE: REVIEWER_ROLE},
        )
        output_path.write_text(result.output, encoding="utf-8")
        if result.succeeded and result.output.strip() != "":
            return True, attempt

    return False, RUN_ATTEMPTS


def is_table_header_or_separator(line: str) -> bool:
    cells = [cell.strip().lower() for cell in line.strip().strip("|").split("|")]
    return any(cell in TABLE_HEADER_WORDS for cell in cells)


def build_finding(text: str) -> Finding:
    location = LOCATION_PATTERN.search(text)
    explicit_rule = EXPLICIT_RULE_PATTERN.search(text)
    rule_id = RULE_ID_PATTERN.search(text)
    rule = ""
    if explicit_rule is not None:
        rule = explicit_rule.group("rule")
    elif rule_id is not None:
        rule = rule_id.group("rule")

    if location is None:
        return Finding(text, rule=rule)
    return Finding(
        text,
        normalize_path(location.group("path")),
        int(location.group("line")),
        rule,
    )


def parse_findings(output: str) -> list[Finding]:
    """
    Split a run's output into findings: every bullet, numbered item or table row, with its indented continuation lines.

    The real output format of Beatrice's command isn't known on this machine, so this stays tolerant; the raw outputs are kept too.

    :param output: What one run printed.
    :return: The findings in output order.
    """
    items: list[list[str]] = []
    is_in_item = False
    for output_line in output.splitlines():
        if ITEM_START_PATTERN.match(output_line) is not None:
            if output_line.strip().startswith("|") and is_table_header_or_separator(output_line):
                is_in_item = False
                continue

            items.append([output_line.strip()])
            is_in_item = True
            continue

        if is_in_item and CONTINUATION_PATTERN.match(output_line) is not None:
            items[-1].append(output_line.strip())
            continue

        is_in_item = False

    return [
        build_finding("\n".join(item))
        for item in items
        if "".join(item).strip("|-*+ ") != ""
    ]


def merge_findings(first: list[Finding], second: list[Finding]) -> list[MergedFinding]:
    """
    Merge both runs' findings: the same finding becomes one marked 2/2, the rest are marked 1/2.

    :param first: Findings of run a.
    :param second: Findings of run b.
    :return: 2/2 findings first, then run a's, then run b's.
    """
    unmatched_second = list(second)
    shared: list[MergedFinding] = []
    only_first: list[MergedFinding] = []
    for finding in first:
        match = next(
            (
                candidate
                for candidate in unmatched_second
                if finding.is_same_as(candidate)
            ),
            None,
        )
        if match is None:
            only_first.append(MergedFinding(finding, "1/2"))
            continue

        unmatched_second.remove(match)
        other_text = "" if match.normalized_text == finding.normalized_text else match.text
        shared.append(MergedFinding(finding, "2/2", other_text))

    only_second = [
        MergedFinding(finding, "1/2")
        for finding in unmatched_second
    ]
    return [*shared, *only_first, *only_second]


def render_merged(
    state: FeatureState,
    round_number: int,
    merged: list[MergedFinding],
    run_notes: list[str],
    dismissed: list[Dismissal],
) -> str:
    """
    Write the merged review in the format the orchestrator triages.

    :param state: The feature's state.
    :param round_number: The Beatrice round.
    :param merged: The merged findings.
    :param run_notes: One line per run (ok, retried, failed).
    :param dismissed: The findings dismissed in earlier rounds.
    :return: The markdown text of review/beatrice-<round>.md.
    """
    lines = [
        f"# Beatrice round {round_number} ({state.field('Ticket')})",
        "",
        f"Base: {state.field('Base')}",
        *[f"- {note}" for note in run_notes],
        f"- Raw outputs: review/beatrice-{round_number}-a.md, review/beatrice-{round_number}-b.md",
        "",
        "Triage every finding in review/triage.md as `fix` or `dismiss: <reason pointing to a line or a rule>`. "
        "1/2 findings count as much as 2/2.",
        "",
    ]
    if len(merged) == 0:
        lines.append(
            "No findings could be read from the outputs. Read the raw outputs above.",
        )
    for index, merged_finding in enumerate(merged, start=1):
        finding = merged_finding.finding
        location = f"{finding.file}:{finding.line}" if finding.file != "" else "no file"
        rule = finding.rule if finding.rule != "" else "no rule"
        lines.extend(
            [f"## R{round_number}-{index} | {merged_finding.marks} | {location} | {rule}", "", finding.text],
        )
        if merged_finding.other_text != "":
            lines.extend(["", f"Other run: {merged_finding.other_text}"])

        if finding.file != "":
            line_text = read_line_text(
                state.code_root(),
                finding.file,
                finding.line,
            )
            dismissal = find_dismissal(
                dismissed,
                finding.file,
                finding.rule,
                line_text,
            )
            if dismissal is not None:
                lines.extend(
                    ["", f"**Dismissed in round {dismissal.round}, because {dismissal.reason}**"],
                )

        lines.append("")

    return "\n".join(lines) + "\n"


def append_to_beatrice_log(state: FeatureState, merged: list[MergedFinding]):
    log_path = state.feature_directory / BEATRICE_LOG_NAME
    entries = [f"## {state.field('Ticket')} round 1 ({datetime.now().strftime(LOG_TIME_FORMAT)})"]
    entries.extend(
        f"- {merged_finding.marks} {merged_finding.finding.rule} {merged_finding.finding.text.splitlines()[0]}"
        for merged_finding in merged
    )
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write("\n".join(entries) + "\n\n")


def run_round(state: FeatureState, round_number: int) -> int:
    """
    Run both Beatrice sessions in parallel, merge their findings and record the round in state.md.

    :param state: The feature's state.
    :param round_number: The Beatrice round, 1 to 5.
    :return: The exit code.
    """
    review_directory = state.feature_directory / "review"
    review_directory.mkdir(parents=True, exist_ok=True)
    prompt = build_prompt(state)
    tools = allowed_tools(state)
    output_paths = [review_directory / f"beatrice-{round_number}-{label}.md" for label in RUN_LABELS]
    with running_marker(
        state.feature_directory,
        f"beatrice round {round_number}",
    ):
        with ThreadPoolExecutor(max_workers=len(RUN_LABELS)) as executor:
            futures = [
                executor.submit(
                    run_review,
                    prompt,
                    tools,
                    state.code_root(),
                    output_path,
                )
                for output_path in output_paths
            ]
            results = [future.result() for future in futures]

    state = FeatureState.load(state.path)
    run_notes: list[str] = []
    findings_per_run: list[list[Finding]] = []
    for label, output_path, (succeeded, attempts) in zip(
        RUN_LABELS,
        output_paths,
        results,
    ):
        if not succeeded:
            run_notes.append(
                f"Run {label}: failed twice, its findings are missing",
            )
            findings_per_run.append([])
            continue

        retry_note = "" if attempts == 1 else " (after a retry)"
        run_notes.append(f"Run {label}: ok{retry_note}")
        findings_per_run.append(
            parse_findings(output_path.read_text(encoding="utf-8")),
        )

    state.log(
        f"Beatrice round {round_number}: " + "; ".join(run_notes),
    )
    if not any(succeeded for succeeded, _ in results):
        failed_runs = state.record_failure(f"BEATRICE-{round_number}")
        state.save()
        print(
            f"Both Beatrice runs failed twice (try {failed_runs}). See {output_paths[0]} and {output_paths[1]}.",
        )
        return FAILED_EXIT_CODE
    merged = merge_findings(findings_per_run[0], findings_per_run[1])
    merged_path = review_directory / f"beatrice-{round_number}.md"
    merged_path.write_text(
        render_merged(
            state,
            round_number,
            merged,
            run_notes,
            sync_dismissed(state),
        ),
        encoding="utf-8",
    )
    if round_number == 1:
        append_to_beatrice_log(state, merged)
    state.reset_tries()
    state.save()
    shared_count = sum(1 for merged_finding in merged if merged_finding.marks == "2/2")
    print(
        f"Wrote {merged_path}: {len(merged)} finding(s), {shared_count} found by both runs. {' '.join(run_notes)}",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Beatrice twice in parallel and merge the findings.",
    )
    parser.add_argument("ticket", help="The ticket, e.g. BTRC-1234.")
    parser.add_argument(
        "round",
        type=int,
        help="The Beatrice round, 1 to 5.",
    )
    arguments = parser.parse_args()
    try:
        state = load_feature_state(arguments.ticket, Path.cwd())
    except FeatureNotFoundError as missing_error:
        print(missing_error)
        return SETUP_ERROR_EXIT_CODE
    return run_round(state, arguments.round)


if __name__ == "__main__":
    sys.exit(main())
