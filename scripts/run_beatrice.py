#!/usr/bin/env python3
"""
Gate B: runs the team leader's Beatrice review skill, unchanged, in two parallel read-only `claude -p` sessions and merges their findings.

The prompt only asks her to review the branch with the skill and write down her comments: no feature description, no format
instructions. Each session is a full Claude Code session, so the skill starts as many subagents as it wants; nothing limits them.

Usage: python3 run_beatrice.py BTRC-1234 <round>
Writes review/beatrice-<round>-a.md, -b.md (raw), review/beatrice-<round>.md (merged, marked 2/2 or 1/2)
and review/beatrice-<round>.json (the same findings, with each flagged line's text as it was during the review).
Exit codes: 0 at least one run finished, 1 both runs failed twice, 2 setup error (no feature, or another long step is running).

:author: midnight-workflow
:date: 29/10/2026
"""
# ----- Imports ----- #

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import command_runner
from feature_state import FeatureNotFoundError, FeatureState, REVIEWER_ROLE, ROLE_VARIABLE, StepAlreadyRunningError, load_feature_state, running_marker
from gate_a import Dismissal, find_dismissal, normalize_path, read_line_text, sync_dismissed

# ----- Consts ----- #

FAILED_EXIT_CODE = 1
SETUP_ERROR_EXIT_CODE = 2
RUN_TIMEOUT_SECONDS = 30 * 60
RUN_ATTEMPTS = 2
RUN_LABELS = ("a", "b")
DEFAULT_SKILL_NAME = "beatrice-code-review"
SKILL_FILE_NAME = "SKILL.md"
SKILLS_DIRECTORY = Path(".claude") / "skills"
REVIEW_PROMPT = "Use the `{skill}` skill to review the branch {branch} against {base}. Write down your comments."
OUTSIDE_SKILL_PROMPT = "Follow the review skill in {skill_file} to review the branch {branch} against {base}. Write down your comments."
DEFAULT_ALLOWED_TOOLS = (
    "Read,Grep,Glob,Agent,Skill,"
    "Bash(git diff:*),Bash(git log:*),Bash(git show:*),"
    "Bash(glab mr view:*),Bash(glab mr diff:*),"
    "Bash(npx nx lint:*),Bash(npx nx typecheck:*),Bash(npx nx test:*)"
)
DISALLOWED_TOOLS = "Edit,Write,MultiEdit,NotebookEdit"
FINDINGS_BLOCK_NAME = "beatrice-findings"
FINDINGS_BLOCK_PATTERN = re.compile(
    rf"^```{FINDINGS_BLOCK_NAME}[ \t]*\n(?P<body>.*?)^```",
    re.DOTALL | re.MULTILINE,
)
FENCE_PREFIX = "```"
ITEM_START_PATTERN = re.compile(r"^ ?(?:[-*+]\s+|\d+[.)]\s+)")
HEADING_PATTERN = re.compile(r"^#{1,6}\s+(?P<title>.+)$")
NUMBERED_HEADING_PATTERN = re.compile(r"^\d+[.)]\s")
CONTINUATION_PATTERN = re.compile(r"^\s{2,}\S")
TABLE_SEPARATOR_PATTERN = re.compile(r"^\|?\s*:?-{3,}")
LOCATION_PATTERN = re.compile(
    r"`?(?P<path>[\w./-]+\.[A-Za-z]\w*)`?(?::| line |#L)(?P<line>\d+)",
)
EXPLICIT_RULE_PATTERN = re.compile(
    r"\brule\s*[:=]\s*`?(?P<rule>[\w./@-]+)`?",
    re.IGNORECASE,
)
RULE_ID_PATTERN = re.compile(r"\b(?P<rule>(?:PY|VU|TS|VT|BR|SQL)-\d+)\b")
NON_FINDING_HEADING_WORDS = ("summary", "overview", "scope", "pipeline", "context", "verdict")
TABLE_FILE_HEADERS = ("file", "location", "path", "where")
TABLE_LINE_HEADERS = ("line", "lines")
TABLE_RULE_HEADERS = ("rule", "rule id", "convention")
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


@dataclass(frozen=True)
class RunResult:
    """
    The outcome of one Beatrice session (after its retry, if any).
    """
    succeeded: bool
    attempts: int
    notes: tuple[str, ...] = field(default_factory=tuple)

# ----- Functions ----- #


class SkillNotFoundError(Exception):
    """
    Raised when Beatrice's skill can't be found; the message lists where it was looked for.
    """
    pass


def skill_candidates(state: FeatureState) -> list[Path]:
    """
    List where Beatrice's SKILL.md may be: the `Beatrice skill:` field, else the repo's and the user's skills folders.

    :param state: The feature's state.
    :return: The SKILL.md paths to try, in order.
    """
    configured = state.field("Beatrice skill")
    if configured != "":
        configured_path = Path(configured).expanduser()
        return [configured_path if configured_path.name == SKILL_FILE_NAME else configured_path / SKILL_FILE_NAME]
    relative_skill = SKILLS_DIRECTORY / DEFAULT_SKILL_NAME / SKILL_FILE_NAME
    return [
        state.code_root() / relative_skill,
        state.repository_root / relative_skill,
        Path.home() / relative_skill,
    ]


def find_skill(state: FeatureState) -> Path:
    candidates = skill_candidates(state)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise SkillNotFoundError(
        "Beatrice's skill wasn't found. Looked for: " + ", ".join(str(candidate) for candidate in candidates)
        + ". Set `Beatrice skill: <path to its SKILL.md or folder>` in state.md.",
    )


def is_discovered_skill(skill_file: Path, code_root: Path) -> bool:
    """
    Tell whether `claude -p` in the code root loads this skill by itself (project or user skills folder).

    :param skill_file: Beatrice's SKILL.md.
    :param code_root: Where the review session runs.
    :return: Whether the skill sits in `<code root>/.claude/skills/` or `~/.claude/skills/`.
    """
    skill_folder = skill_file.parent.parent
    discovered_folders = (
        (code_root / SKILLS_DIRECTORY).resolve(),
        (Path.home() / SKILLS_DIRECTORY).resolve(),
    )
    return skill_folder in discovered_folders


def build_prompt(state: FeatureState, skill_file: Path) -> str:
    """
    Build the bare review request: review the branch with the skill and write down the comments.

    :param state: The feature's state, with `Branch:` and `Base:`.
    :param skill_file: Beatrice's SKILL.md.
    :return: The prompt; it names the skill, or its file when `claude -p` wouldn't load it by itself.
    """
    if is_discovered_skill(skill_file, state.code_root()):
        return REVIEW_PROMPT.format(
            skill=skill_file.parent.name,
            branch=state.field("Branch"),
            base=state.field("Base"),
        )
    return OUTSIDE_SKILL_PROMPT.format(
        skill_file=skill_file,
        branch=state.field("Branch"),
        base=state.field("Base"),
    )


def allowed_tools(state: FeatureState) -> str:
    tools = state.field("Beatrice tools")
    if tools == "":
        return DEFAULT_ALLOWED_TOOLS
    return tools


def build_review_command(prompt: str, tools: str, skill_file: Path, code_root: Path) -> list[str]:
    """
    Build the read-only `claude -p` command of one Beatrice session.

    :param prompt: The bare review request.
    :param tools: The allowed tools.
    :param skill_file: Beatrice's SKILL.md; its folder is added when the session wouldn't see it otherwise.
    :param code_root: Where the session runs.
    :return: The command.
    """
    command = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "json",
        "--permission-mode",
        "default",
        "--allowedTools",
        tools,
        "--disallowedTools",
        DISALLOWED_TOOLS,
    ]
    if not is_discovered_skill(skill_file, code_root):
        command.extend(["--add-dir", str(skill_file.parent)])
    return command


def read_review_result(stdout: str) -> tuple[str, list[str]] | None:
    """
    Read `claude -p --output-format json` output.

    :param stdout: What claude printed.
    :return: The answer text and the denied tool names; None when it isn't a successful result.
    """
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(result, dict) or result.get("is_error") is True:
        return None
    answer = result.get("result")
    if not isinstance(answer, str) or answer.strip() == "":
        return None
    denials = result.get("permission_denials")
    denied_tools: list[str] = []
    if isinstance(denials, list):
        for denial in denials:
            tool_name = denial.get("tool_name") if isinstance(denial, dict) else denial
            denied_tools.append(str(tool_name))

    return answer, denied_tools


def run_review(state: FeatureState, skill_file: Path, output_path: Path) -> RunResult:
    """
    Run one Beatrice session, retrying once when it fails.

    :param state: The feature's state (branch, base, tools, worktree).
    :param skill_file: Beatrice's SKILL.md.
    :param output_path: Where the run's answer (or error output) goes.
    :return: Whether a run succeeded, how many attempts it took, and notes for the merged file.
    """
    notes: list[str] = []
    for attempt in range(1, RUN_ATTEMPTS + 1):
        result = command_runner.run_command(
            build_review_command(
                build_prompt(state, skill_file),
                allowed_tools(state),
                skill_file,
                state.code_root(),
            ),
            state.code_root(),
            RUN_TIMEOUT_SECONDS,
            {ROLE_VARIABLE: REVIEWER_ROLE},
        )
        review = read_review_result(result.stdout) if result.succeeded else None
        if review is None:
            output_path.write_text(result.output, encoding="utf-8")
            continue

        answer, denied_tools = review
        output_path.write_text(answer, encoding="utf-8")
        if len(denied_tools) > 0:
            denied_text = ", ".join(sorted(set(denied_tools)))
            notes.append(f"permission denied for: {denied_text}")
        return RunResult(
            True,
            attempt,
            tuple(notes),
        )

    return RunResult(
        False,
        RUN_ATTEMPTS,
        tuple(notes),
    )


def relative_to_code_root(path: str, code_root: Path) -> str:
    normalized = normalize_path(path)
    for root in (code_root, code_root.resolve()):
        root_prefix = root.as_posix().rstrip("/") + "/"
        if normalized.startswith(root_prefix):
            return normalized.removeprefix(root_prefix)

    return normalized


def parse_findings_block(answer: str, code_root: Path) -> list[Finding] | None:
    """
    Read the machine-readable findings block the reviewers were asked to add.

    :param answer: One run's answer.
    :param code_root: The worktree, to turn absolute paths into repo-relative ones.
    :return: The findings, or None when the answer has no such block.
    """
    block_match = FINDINGS_BLOCK_PATTERN.search(answer)
    if block_match is None:
        return None
    findings: list[Finding] = []
    for block_line in block_match.group("body").splitlines():
        if block_line.strip() == "":
            continue

        try:
            record = json.loads(block_line)
        except json.JSONDecodeError:
            findings.append(Finding(block_line.strip()))
            continue

        if not isinstance(record, dict):
            continue

        raw_line = record.get("line", 0)
        findings.append(
            Finding(
                str(record.get("finding", "")).strip(),
                relative_to_code_root(str(record.get("file", "")), code_root),
                int(raw_line) if isinstance(raw_line, int) or str(raw_line).isdigit() else 0,
                str(record.get("rule", "")).strip(),
            ),
        )

    return findings


def build_finding(text: str, code_root: Path) -> Finding:
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
        relative_to_code_root(location.group("path"), code_root),
        int(location.group("line")),
        rule,
    )


def table_cells(table_line: str) -> list[str]:
    return [cell.strip() for cell in table_line.strip().strip("|").split("|")]


def first_column_value(values: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        if name in values:
            return values[name].strip("`")

    return ""


def table_row_text(header: list[str], cells: list[str]) -> str:
    """
    Turn a table row into finding text with its location and rule in a form the parser reads.

    :param header: The table's lowercased header cells.
    :param cells: The row's cells.
    :return: e.g. "app/x.py:40 rule: PY-23 | truthy check".
    """
    values = dict(zip(header, cells))
    file_value = first_column_value(values, TABLE_FILE_HEADERS)
    line_value = first_column_value(values, TABLE_LINE_HEADERS)
    rule_value = first_column_value(values, TABLE_RULE_HEADERS)
    location = file_value
    if file_value != "" and line_value.isdigit() and LOCATION_PATTERN.search(file_value) is None:
        location = f"{file_value}:{line_value}"
    rule_text = f" rule: {rule_value}" if rule_value != "" else ""
    return f"{location}{rule_text} | {' | '.join(cells)}".strip()


def parse_free_form(answer: str, code_root: Path) -> list[Finding]:
    """
    Split a free-form answer into findings: top-level bullets, numbered items, table rows and numbered or located headings.

    Fenced code blocks are skipped, indented bullets continue the item above, and items under summary-like headings are left out.

    :param answer: One run's answer.
    :param code_root: The worktree, to turn absolute paths into repo-relative ones.
    :return: The findings in output order.
    """
    items: list[list[str]] = []
    is_in_item = False
    is_in_fence = False
    is_finding_section = True
    is_heading_item = False
    table_header: list[str] = []
    for answer_line in answer.splitlines():
        if answer_line.strip().startswith(FENCE_PREFIX):
            is_in_fence = not is_in_fence
            continue

        if is_in_fence:
            continue

        heading_match = HEADING_PATTERN.match(answer_line)
        if heading_match is not None:
            title = heading_match.group("title")
            is_located = NUMBERED_HEADING_PATTERN.match(title) is not None or LOCATION_PATTERN.search(title) is not None
            if is_located:
                items.append([title.strip()])
                is_in_item = True
                is_heading_item = True
                continue

            is_heading_item = False
            is_finding_section = not any(word in title.lower() for word in NON_FINDING_HEADING_WORDS)
            is_in_item = False
            table_header = []
            continue

        if not is_finding_section:
            continue

        if answer_line.strip().startswith("|"):
            if TABLE_SEPARATOR_PATTERN.match(answer_line.strip()) is not None:
                continue

            if len(table_header) == 0:
                table_header = [cell.lower() for cell in table_cells(answer_line)]
                continue

            items.append(
                [table_row_text(table_header, table_cells(answer_line))],
            )
            is_in_item = False
            continue

        table_header = []
        if ITEM_START_PATTERN.match(answer_line) is not None and not (is_heading_item and is_in_item):
            items.append([answer_line.strip()])
            is_in_item = True
            continue

        if answer_line.strip() == "":
            continue

        is_continuation = CONTINUATION_PATTERN.match(answer_line) is not None or is_heading_item
        if is_in_item and is_continuation:
            items[-1].append(answer_line.strip())
            continue

        is_in_item = False

    return [
        build_finding("\n".join(item), code_root)
        for item in items
        if "".join(item).strip("|-*+ ") != ""
    ]


def parse_findings(answer: str, code_root: Path) -> list[Finding]:
    """
    Read one run's findings: the machine-readable block when present, else the free-form text.

    :param answer: One run's answer.
    :param code_root: The worktree, to turn absolute paths into repo-relative ones.
    :return: The findings.
    """
    block_findings = parse_findings_block(answer, code_root)
    if block_findings is not None:
        return block_findings
    return parse_free_form(answer, code_root)


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
        shared.append(
            MergedFinding(
                finding,
                "2/2",
                other_text,
            ),
        )

    only_second = [
        MergedFinding(finding, "1/2")
        for finding in unmatched_second
    ]
    return [*shared, *only_first, *only_second]


def finding_records(state: FeatureState, round_number: int, merged: list[MergedFinding]) -> list[dict[str, object]]:
    """
    Build the stored record of every merged finding, capturing the flagged line's text now.

    :param state: The feature's state.
    :param round_number: The Beatrice round.
    :param merged: The merged findings.
    :return: One record per finding, in the order of beatrice-<round>.md.
    """
    records: list[dict[str, object]] = []
    for index, merged_finding in enumerate(merged, start=1):
        finding = merged_finding.finding
        line_text = ""
        if finding.file != "":
            line_text = read_line_text(
                state.code_root(),
                finding.file,
                finding.line,
            )
        records.append(
            {
                "id": f"R{round_number}-{index}",
                "marks": merged_finding.marks,
                "file": finding.file,
                "line": finding.line,
                "rule": finding.rule,
                "text": finding.text,
                "line_text": line_text,
            },
        )

    return records


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
    :param run_notes: One line per run (ok, retried, failed, denials).
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
        "Triage every finding in review/triage.md as `fix` or `dismiss` with a reason pointing to a line or a rule, "
        "using the finding's id in the `#` column. 1/2 findings count as much as 2/2.",
        "",
    ]
    if len(merged) == 0:
        lines.append(
            "No findings could be read from the outputs. Read the raw outputs above.",
        )
    records = finding_records(
        state,
        round_number,
        merged,
    )
    for merged_finding, record in zip(merged, records):
        finding = merged_finding.finding
        location = f"{finding.file}:{finding.line}" if finding.file != "" else "no file"
        rule = finding.rule if finding.rule != "" else "no rule"
        lines.extend(
            [f"## {record['id']} | {merged_finding.marks} | {location} | {rule}", "", finding.text],
        )
        if merged_finding.other_text != "":
            lines.extend(["", f"Other run: {merged_finding.other_text}"])

        dismissal = find_dismissal(
            dismissed,
            finding.file,
            finding.rule,
            str(record["line_text"]),
        )
        if dismissal is not None:
            lines.extend(
                ["", f"**Dismissed in round {dismissal.round}, because {dismissal.reason}**"],
            )

        lines.append("")

    return "\n".join(lines) + "\n"


def append_to_beatrice_log(state: FeatureState, merged: list[MergedFinding]):
    """
    Append round 1's findings to beatrice-log.md once, so recurring ones can become rules later.

    :param state: The feature's state.
    :param merged: Round 1's merged findings.
    """
    log_path = state.feature_directory / BEATRICE_LOG_NAME
    header_start = f"## {state.field('Ticket')} round 1 "
    if log_path.is_file() and any(line.startswith(header_start) for line in log_path.read_text(encoding="utf-8").splitlines()):
        return
    entries = [f"{header_start}({datetime.now().strftime(LOG_TIME_FORMAT)})"]
    entries.extend(
        f"- {merged_finding.marks} {merged_finding.finding.rule} {merged_finding.finding.text.splitlines()[0]}"
        for merged_finding in merged
        if merged_finding.finding.text != ""
    )
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write("\n".join(entries) + "\n\n")


def run_both_reviews(state: FeatureState, skill_file: Path, output_paths: list[Path]) -> list[RunResult]:
    with ThreadPoolExecutor(max_workers=len(RUN_LABELS)) as executor:
        futures = [
            executor.submit(
                run_review,
                state,
                skill_file,
                output_path,
            )
            for output_path in output_paths
        ]
        return [future.result() for future in futures]


def run_round(state: FeatureState, round_number: int) -> int:
    """
    Run both Beatrice sessions in parallel, merge their findings and record the round in state.md.

    :param state: The feature's state.
    :param round_number: The Beatrice round, 1 to 5.
    :return: The exit code.
    """
    try:
        skill_file = find_skill(state)
    except SkillNotFoundError as missing_skill:
        print(f"Setup error: {missing_skill}")
        return SETUP_ERROR_EXIT_CODE
    review_path = state.feature_directory / "review"
    review_path.mkdir(parents=True, exist_ok=True)
    output_paths = [review_path / f"beatrice-{round_number}-{label}.md" for label in RUN_LABELS]
    results = run_both_reviews(
        state,
        skill_file,
        output_paths,
    )
    state.reload()
    run_notes: list[str] = []
    findings_per_run: list[list[Finding]] = []
    for label, output_path, result in zip(
        RUN_LABELS,
        output_paths,
        results,
    ):
        if not result.succeeded:
            run_notes.append(
                f"Run {label}: failed twice, its findings are missing",
            )
            findings_per_run.append([])
            continue

        retry_note = "" if result.attempts == 1 else " (after a retry)"
        extra_notes = "".join(f"; {note}" for note in result.notes)
        run_notes.append(f"Run {label}: ok{retry_note}{extra_notes}")
        findings_per_run.append(
            parse_findings(
                output_path.read_text(encoding="utf-8"),
                state.code_root(),
            ),
        )

    state.log(
        f"Beatrice round {round_number}: " + "; ".join(run_notes),
    )
    if not any(result.succeeded for result in results):
        failed_runs = state.record_failure(f"BEATRICE-{round_number}")
        state.save()
        print(
            f"Both Beatrice runs failed twice (try {failed_runs}). See {output_paths[0]} and {output_paths[1]}.",
        )
        return FAILED_EXIT_CODE
    merged = merge_findings(findings_per_run[0], findings_per_run[1])
    (review_path / f"beatrice-{round_number}.json").write_text(
        json.dumps(
            finding_records(
                state,
                round_number,
                merged,
            ),
            indent=2,
        ),
        encoding="utf-8",
    )
    merged_path = review_path / f"beatrice-{round_number}.md"
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
    try:
        with running_marker(
            state.feature_directory,
            f"beatrice round {arguments.round}",
        ):
            return run_round(state, arguments.round)
    except StepAlreadyRunningError as running_error:
        print(f"Setup error: {running_error}")
        return SETUP_ERROR_EXIT_CODE


if __name__ == "__main__":
    sys.exit(main())
