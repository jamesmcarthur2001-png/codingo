#!/usr/bin/env python3
"""
Checks Vue single-file components against the house conventions eslint and vue-tsc can't see.

Usage: python3 check_vue_conventions.py <file.vue> [...]
Reports, with the rule ID: values in `<script lang="ts">` (VU-05), a string constant used once (VU-22), colors that
don't come from the theme (VU-16), `w-[100%]` / `h-[100%]` and font sizes in px (VU-54), px sizes (VU-18), Vuetify
`d-*` display classes (VU-43), and component state in a `let` (VU-36). Comments are checked by line_checks.py (VU-40).
Exit codes: 0 no violations, 1 violations found.

:author: claude-workflow
:date: 03/11/2026
"""
# ----- Imports ----- #

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# ----- Consts ----- #

SCRIPT_BLOCK_PATTERN = re.compile(r"^<script(?P<attributes>[^>]*)>\s*$")
SCRIPT_END = "</script>"
TEMPLATE_START_PATTERN = re.compile(r"^<template(?:\s[^>]*)?>\s*$")
TEMPLATE_END = "</template>"
STYLE_START_PATTERN = re.compile(r"^<style(?:\s[^>]*)?>\s*$")
STYLE_END = "</style>"
TYPE_DECLARATION_PATTERN = re.compile(
    r"^(?:interface\s|type\s|enum\s|const\s+enum\s|import\s+type\s|declare\s)",
)
STRING_CONSTANT_PATTERN = re.compile(
    r"^const\s+(?P<name>[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|[A-Z]{2,})\s*(?::\s*string\s*)?=\s*(?P<quote>['\"`])",
)
CRITICAL_KEY_WORDS = ("KEY", "HEADER", "EVENT", "PERMISSION", "ROLE", "STORAGE", "CACHE", "QUEUE", "ROUTE")
COLOR_NAMES = (
    "slate|gray|grey|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet"
    "|purple|fuchsia|pink|rose|black|white|brown|deep-purple|light-blue|light-green|deep-orange|blue-grey"
)
TAILWIND_COLOR_PATTERN = re.compile(
    rf"(?<![\w-])(?:text|bg|border|ring|fill|stroke|from|via|to|divide|outline|placeholder|shadow|decoration|accent|caret)"
    rf"-(?:{COLOR_NAMES})(?:-\d{{2,3}})?(?![\w-])",
)
VUETIFY_PALETTE_PATTERN = re.compile(
    rf"(?<![\w-])(?:bg|text)-(?:{COLOR_NAMES})(?:-(?:lighten|darken|accent)-\d)?(?![\w-])"
    rf"|\bcolor=\"(?:{COLOR_NAMES})(?:-(?:lighten|darken|accent)-\d)?\"",
)
HEX_COLOR_PATTERN = re.compile(
    r"(?:['\"`(,]|:\s*)#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![0-9a-zA-Z_-])",
)
LITERAL_COLOR_FUNCTION_PATTERN = re.compile(r"\b(?:rgba?|hsla?)\(\s*\d")
FULL_SIZE_PATTERN = re.compile(r"(?<![\w-])[wh]-\[100%\]")
PX_SIZE_CLASS_PATTERN = re.compile(r"(?<![\w-])[\w-]+-\[\d+(?:\.\d+)?px\]")
FONT_SIZE_PX_PATTERN = re.compile(r"font-size\s*:\s*\d+(?:\.\d+)?px")
CSS_PX_PATTERN = re.compile(
    r"(?<![\w-])(?:width|height|min-width|min-height|max-width|max-height)\s*:\s*\d+(?:\.\d+)?px",
)
VUETIFY_DISPLAY_PATTERN = re.compile(
    r"(?<![\w-])d-(?:flex|inline-flex|block|inline-block|inline|none|grid)(?![\w-])",
)
LET_PATTERN = re.compile(r"^let\s")

# ----- Classes ----- #


@dataclass(frozen=True)
class Violation:
    """
    One convention violation, with the rule it breaks.
    """
    path: Path
    line: int
    rule_id: str
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.rule_id} {self.message}"

# ----- Functions ----- #


def braces_delta(code_line: str) -> int:
    return code_line.count("{") + code_line.count("(") + code_line.count("[") - code_line.count("}") - code_line.count(")") - code_line.count("]")


def script_blocks(lines: list[str]) -> list[tuple[bool, int, int]]:
    """
    Find the `<script>` blocks of a component.

    :param lines: The file's lines.
    :return: One `(is_setup, first_line, last_line)` per block, with 1-based line numbers of the code inside the tags.
    """
    blocks: list[tuple[bool, int, int]] = []
    start_index = -1
    is_setup = False
    for index, source_line in enumerate(lines):
        script_match = SCRIPT_BLOCK_PATTERN.match(source_line.strip())
        if script_match is not None and start_index < 0:
            start_index = index + 1
            is_setup = "setup" in script_match.group("attributes")
            continue

        if source_line.strip() == SCRIPT_END and start_index >= 0:
            blocks.append(
                (is_setup, start_index + 1, index),
            )
            start_index = -1

    return blocks


def section_line_numbers(lines: list[str], start_pattern: re.Pattern[str], end_tag: str) -> list[int]:
    """
    List the line numbers inside the outermost `<template>` or `<style>` blocks.

    :param lines: The file's lines.
    :param start_pattern: The opening tag.
    :param end_tag: The closing tag.
    :return: 1-based line numbers, the tag lines included.
    """
    numbers: list[int] = []
    depth = 0
    for index, source_line in enumerate(lines):
        stripped = source_line.strip()
        is_start = start_pattern.match(stripped) is not None and (end_tag == STYLE_END or not source_line.startswith((" ", "\t")))
        if is_start:
            depth += 1
        if depth > 0:
            numbers.append(index + 1)
        if stripped == end_tag and depth > 0 and not source_line.startswith((" ", "\t")):
            depth -= 1

    return numbers


def top_level_lines(lines: list[str], first_line: int, last_line: int) -> list[tuple[int, str]]:
    """
    List the statements that start at the top level of a script block.

    :param lines: The file's lines.
    :param first_line: The block's first code line.
    :param last_line: The block's last code line.
    :return: `(line number, stripped line)` for each non-blank line that starts at depth 0.
    """
    statements: list[tuple[int, str]] = []
    depth = 0
    for line_number in range(first_line, last_line + 1):
        code_line = lines[line_number - 1].strip()
        if depth == 0 and code_line != "":
            statements.append(
                (line_number, code_line),
            )
        depth = max(depth + braces_delta(code_line), 0)

    return statements


def check_type_block(path: Path, lines: list[str], first_line: int, last_line: int) -> list[Violation]:
    return [
        Violation(
            path,
            line_number,
            "VU-05",
            "`<script lang=\"ts\">` holds only types (interface, type, enum); move this into `<script setup>`.",
        )
        for line_number, code_line in top_level_lines(
            lines,
            first_line,
            last_line,
        )
        if TYPE_DECLARATION_PATTERN.match(code_line) is None and not code_line.startswith(("}", ")", "]", "|", "&"))
    ]


def check_setup_block(path: Path, lines: list[str], first_line: int, last_line: int) -> list[Violation]:
    """
    Report single-use string constants and `let` state at the top level of `<script setup>`.

    :param path: The component.
    :param lines: The file's lines.
    :param first_line: The block's first code line.
    :param last_line: The block's last code line.
    :return: The violations found.
    """
    violations: list[Violation] = []
    whole_file = "\n".join(lines)
    for line_number, code_line in top_level_lines(
        lines,
        first_line,
        last_line,
    ):
        if LET_PATTERN.match(code_line) is not None:
            violations.append(
                Violation(
                    path,
                    line_number,
                    "VU-36",
                    "Component state is a typed `ref`, not a `let`.",
                ),
            )
            continue

        constant_match = STRING_CONSTANT_PATTERN.match(code_line)
        if constant_match is None:
            continue

        name = constant_match.group("name")
        is_critical_key = any(word in name.split("_") for word in CRITICAL_KEY_WORDS)
        uses = len(
            re.findall(
                rf"(?<![\w$]){re.escape(name)}(?![\w$])",
                whole_file,
            ),
        ) - 1
        if uses <= 1 and not is_critical_key:
            violations.append(
                Violation(
                    path,
                    line_number,
                    "VU-22",
                    f"'{name}' is used {uses} time(s): a string becomes a constant only when it's used in more than one place. Inline it.",
                ),
            )

    return violations


def line_violations(path: Path, line_number: int, source_line: str, is_style: bool) -> list[Violation]:
    """
    Report the color, size and display rules broken on one template or style line.

    :param path: The component.
    :param line_number: The line's number.
    :param source_line: The line.
    :param is_style: Whether the line is inside `<style>`.
    :return: The violations found on the line.
    """
    checks = [
        (TAILWIND_COLOR_PATTERN, "VU-16", "Tailwind color class: use a theme color (e.g. `text-entryText`, `bg-surface`)."),
        (VUETIFY_PALETTE_PATTERN, "VU-16", "Vuetify palette color: use a theme color that changes with light and dark."),
        (HEX_COLOR_PATTERN, "VU-16", "Hard-coded hex color: use a theme color."),
        (LITERAL_COLOR_FUNCTION_PATTERN, "VU-16", "Literal rgb()/hsl() color: use a theme color (`rgb(var(--v-theme-<name>))`)."),
        (FULL_SIZE_PATTERN, "VU-54", "Use `w-full` / `h-full`, not `w-[100%]` / `h-[100%]`."),
        (PX_SIZE_CLASS_PATTERN, "VU-18", "No px sizes in classes: use flex, or rem / vh / vw / %."),
        (VUETIFY_DISPLAY_PATTERN, "VU-43", "Vuetify display class: use Tailwind (`flex`, `block`, `hidden`)."),
    ]
    if is_style:
        checks += [
            (FONT_SIZE_PX_PATTERN, "VU-54", "Font sizes in rem, not px."),
            (CSS_PX_PATTERN, "VU-18", "No px for sizing: use flex, or rem / vh / vw / %."),
        ]
    return [
        Violation(
            path,
            line_number,
            rule_id,
            message,
        )
        for pattern, rule_id, message in checks
        if pattern.search(source_line) is not None
    ]


def check_vue_file(path: Path) -> list[Violation]:
    """
    Run every check on one component.

    :param path: The `.vue` file.
    :return: The violations, sorted by line.
    """
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    violations: list[Violation] = []
    for is_setup, first_line, last_line in script_blocks(lines):
        if is_setup:
            violations += check_setup_block(
                path,
                lines,
                first_line,
                last_line,
            )
        else:
            violations += check_type_block(
                path,
                lines,
                first_line,
                last_line,
            )

    style_lines = set(
        section_line_numbers(
            lines,
            STYLE_START_PATTERN,
            STYLE_END,
        ),
    )
    for line_number in sorted(
        style_lines | set(
            section_line_numbers(
                lines,
                TEMPLATE_START_PATTERN,
                TEMPLATE_END,
            ),
        ),
    ):
        violations += line_violations(
            path,
            line_number,
            lines[line_number - 1],
            line_number in style_lines,
        )

    return sorted(
        violations,
        key=lambda violation: (violation.line, violation.rule_id),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check Vue components against the house conventions.",
    )
    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
    )
    arguments = parser.parse_args()
    violations = [
        violation
        for path in arguments.files
        for violation in check_vue_file(path)
    ]
    for violation in violations:
        print(violation.render())
    if len(violations) == 0:
        return 0
    print(f"{len(violations)} convention violation(s).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
