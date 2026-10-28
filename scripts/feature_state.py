#!/usr/bin/env python3
"""
Reads and updates a feature's state.md, the file every workflow step writes where it is.

:author: midnight-workflow
:date: 28/10/2026
"""
# ----- Imports ----- #

import json
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# ----- Consts ----- #

ROLE_VARIABLE = "MIDNIGHT_ROLE"
REVIEWER_ROLE = "reviewer"
PROJECT_DIRECTORY_VARIABLE = "CLAUDE_PROJECT_DIR"
FEATURES_DIRECTORY = Path("docs") / "features"
ACTIVE_MARKER_NAME = ".active"
STATE_FILE_NAME = "state.md"
RUNNING_MARKER_NAME = ".running.json"
FIELD_PATTERN = re.compile(r"^(?P<name>[A-Z][A-Za-z ]*): ?(?P<value>.*)$")
SECTION_PATTERN = re.compile(r"^## (?P<name>.+?)\s*$")
TRIES_PATTERN = re.compile(r"^(?P<step>\S+) (?P<count>\d+)$")
DONE_STATUS = "DONE"
BLOCKED_STATUS = "BLOCKED"
RUNNING_STATUS = "RUNNING"
MAX_FAILED_RUNS = 3
RUNNING_MARKER_MAX_AGE_SECONDS = 75 * 60
APPROVED_PREFIX = "yes"
CHECKS_VARIABLE = "MIDNIGHT_CHECKS"
LOG_TIME_FORMAT = "%d/%m/%Y %H:%M"

# ----- Classes ----- #


class FeatureNotFoundError(Exception):
    """
    Raised when a ticket has no feature directory or no state.md.
    """
    pass


class StepAlreadyRunningError(Exception):
    """
    Raised when a long step starts while another one of the same feature is still running.
    """
    pass


@dataclass
class FeatureState:
    """
    The parsed state.md of one feature: `Name: value` fields on top, then `## Section` blocks of lines.
    """
    path: Path
    lines: list[str]

    @classmethod
    def load(cls, path: Path) -> "FeatureState":
        if not path.is_file():
            raise FeatureNotFoundError(f"No state file at {path}.")
        return cls(
            path,
            path.read_text(encoding="utf-8").splitlines(),
        )

    @property
    def feature_directory(self) -> Path:
        return self.path.parent

    def save(self):
        write_atomically(self.path, "\n".join(self.lines) + "\n")

    def reload(self):
        self.lines = FeatureState.load(self.path).lines

    def first_section_index(self) -> int:
        for index, line in enumerate(self.lines):
            if SECTION_PATTERN.match(line) is not None:
                return index

        return len(self.lines)

    def field(self, name: str) -> str:
        """
        Read one top field.

        :param name: The field name, e.g. `Base`.
        :return: The stripped value, or an empty string when the field is missing.
        """
        for line in self.lines[:self.first_section_index()]:
            field_match = FIELD_PATTERN.match(line)
            if field_match is not None and field_match.group("name") == name:
                return field_match.group("value").strip()

        return ""

    def set_field(self, name: str, value: str):
        """
        Write one top field, adding it before the first section when it's missing.

        :param name: The field name.
        :param value: The new value.
        """
        section_index = self.first_section_index()
        for index, line in enumerate(self.lines[:section_index]):
            field_match = FIELD_PATTERN.match(line)
            if field_match is not None and field_match.group("name") == name:
                self.lines[index] = f"{name}: {value}"
                return

        insert_index = section_index
        while insert_index > 0 and self.lines[insert_index - 1].strip() == "":
            insert_index -= 1

        self.lines.insert(insert_index, f"{name}: {value}")

    def section_bounds(self, name: str) -> tuple[int, int] | None:
        start_index: int | None = None
        for index, line in enumerate(self.lines):
            section_match = SECTION_PATTERN.match(line)
            if section_match is None:
                continue

            if start_index is not None:
                return start_index, index

            if section_match.group("name") == name:
                start_index = index + 1

        if start_index is None:
            return None
        return start_index, len(self.lines)

    def section(self, name: str) -> list[str]:
        """
        Read the non-empty lines of one `## Section`.

        :param name: The section name, e.g. `Commands`.
        :return: The section's lines without blank lines; empty when the section is missing.
        """
        bounds = self.section_bounds(name)
        if bounds is None:
            return []
        start_index, end_index = bounds
        return [
            line
            for line in self.lines[start_index:end_index]
            if line.strip() != ""
        ]

    def append_to_section(self, name: str, line: str):
        bounds = self.section_bounds(name)
        if bounds is None:
            if len(self.lines) > 0 and self.lines[-1].strip() != "":
                self.lines.append("")

            self.lines.extend([f"## {name}", line])
            return

        _, end_index = bounds
        insert_index = end_index
        while insert_index > 0 and self.lines[insert_index - 1].strip() == "":
            insert_index -= 1

        self.lines.insert(insert_index, line)

    def log(self, message: str):
        self.append_to_section(
            "Log",
            f"- {datetime.now().strftime(LOG_TIME_FORMAT)} {message}",
        )

    def status(self) -> str:
        return self.field("Status")

    def is_finished(self) -> bool:
        status = self.status()
        return status.startswith(DONE_STATUS) or status.startswith(BLOCKED_STATUS)

    def is_approved(self) -> bool:
        return self.field("Approved").lower().startswith(APPROVED_PREFIX)

    def is_running_after_approval(self) -> bool:
        return self.is_approved() and not self.is_finished()

    def block(self, reason: str):
        self.set_field("Status", f"{BLOCKED_STATUS}: {reason}")
        self.log(f"BLOCKED: {reason}")

    def number_field(self, name: str) -> int:
        value = self.field(name)
        if not value.isdigit():
            return 0
        return int(value)

    def record_failure(self, step: str) -> int:
        """
        Count one failed run of a step, and block the feature when the step reaches its try limit.

        :param step: A name for the step that failed, e.g. `GATE-A-2`.
        :return: How many runs of this step have failed in a row.
        """
        tries_match = TRIES_PATTERN.match(self.field("Tries"))
        failed_runs = 1
        if tries_match is not None and tries_match.group("step") == step:
            failed_runs = int(tries_match.group("count")) + 1

        self.set_field("Tries", f"{step} {failed_runs}")
        if failed_runs >= MAX_FAILED_RUNS:
            self.block(f"{step} failed {failed_runs} times in a row")

        return failed_runs

    def reset_tries(self):
        self.set_field("Tries", "0")

    @property
    def repository_root(self) -> Path:
        return self.feature_directory.parent.parent.parent

    def code_root(self) -> Path:
        """
        Find the directory the feature's code lives in.

        :return: The `Worktree:` path (relative paths resolved against the repository) when set, else the repository holding docs/features.
        """
        worktree = self.field("Worktree")
        if worktree == "":
            return self.repository_root
        worktree_path = Path(worktree).expanduser()
        if worktree_path.is_absolute():
            return worktree_path
        return self.repository_root / worktree_path

# ----- Functions ----- #


def is_reviewer_session() -> bool:
    return os.environ.get(ROLE_VARIABLE, "") == REVIEWER_ROLE


def checks_forced() -> bool:
    return os.environ.get(CHECKS_VARIABLE, "") == "1"


def write_atomically(path: Path, text: str):
    """
    Write a file so readers see either the old or the new content, never half of it.

    :param path: The file to write.
    :param text: The new content.
    """
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary_path.write_text(text, encoding="utf-8")
    os.replace(temporary_path, path)


def read_json_file(path: Path) -> dict[str, object] | None:
    """
    Read a small JSON state file written by the hooks or scripts.

    :param path: The file.
    :return: Its object, or None when it is missing, unreadable or not a JSON object.
    """
    if not path.is_file():
        return None
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(content, dict):
        return None
    return content


def search_starts(start: Path) -> list[Path]:
    starts = [start.resolve()]
    project_directory = os.environ.get(PROJECT_DIRECTORY_VARIABLE, "")
    if project_directory != "":
        starts.append(Path(project_directory).resolve())

    return starts


def find_features_directory(start: Path) -> Path | None:
    """
    Find docs/features in the start directory, one of its parents, or the Claude project directory.

    :param start: The directory to search from.
    :return: The docs/features directory, when one exists.
    """
    for search_start in search_starts(start):
        for directory in (search_start, *search_start.parents):
            candidate = directory / FEATURES_DIRECTORY
            if candidate.is_dir():
                return candidate

    return None


def find_active_feature(start: Path) -> Path | None:
    """
    Find the feature currently running, named in docs/features/.active.

    :param start: The directory to search from.
    :return: The active feature's directory, when one is active.
    """
    features_directory = find_features_directory(start)
    if features_directory is None:
        return None
    marker = features_directory / ACTIVE_MARKER_NAME
    if not marker.is_file():
        return None
    ticket = marker.read_text(encoding="utf-8").strip()
    if ticket == "":
        return None
    return features_directory / ticket


def find_running_feature(start: Path) -> FeatureState | None:
    """
    Find the active feature when it is approved and not DONE or BLOCKED; the guards act only then.

    :param start: The directory to search from.
    :return: Its state, or None when no approved feature is running.
    """
    feature_directory = find_active_feature(start)
    if feature_directory is None or not (feature_directory / STATE_FILE_NAME).is_file():
        return None
    state = FeatureState.load(feature_directory / STATE_FILE_NAME)
    if not state.is_running_after_approval():
        return None
    return state


def load_feature_state(ticket: str, start: Path) -> FeatureState:
    """
    Load the state.md of a ticket.

    :param ticket: The ticket, e.g. `BTRC-1234`.
    :param start: The directory to search for docs/features from.
    :return: The feature's state.
    :raises FeatureNotFoundError: When docs/features or the ticket's state.md doesn't exist.
    """
    features_directory = find_features_directory(start)
    if features_directory is None:
        raise FeatureNotFoundError(
            f"No docs/features directory above {start}. Run this from the repository root.",
        )
    return FeatureState.load(features_directory / ticket / STATE_FILE_NAME)


def write_running_marker(feature_directory: Path, step: str):
    write_atomically(
        feature_directory / RUNNING_MARKER_NAME,
        json.dumps({"step": step, "started": time.time()}),
    )


@contextmanager
def running_marker(feature_directory: Path, step: str) -> Iterator[None]:
    """
    Mark a long step as running, so the Stop hook lets the orchestrator wait and a second run refuses to start.

    :param feature_directory: The feature's directory.
    :param step: What is running, e.g. `beatrice round 2`.
    :raises StepAlreadyRunningError: When another long step of this feature is still running.
    """
    already_running = running_step(feature_directory)
    if already_running is not None:
        raise StepAlreadyRunningError(
            f"'{already_running}' is still running for this feature. Wait for it to finish.",
        )
    write_running_marker(feature_directory, step)
    try:
        yield
    finally:
        (feature_directory / RUNNING_MARKER_NAME).unlink(missing_ok=True)


def refresh_running_marker(feature_directory: Path, step: str):
    write_running_marker(feature_directory, step)


def running_step(feature_directory: Path) -> str | None:
    """
    Tell which long step is running right now.

    :param feature_directory: The feature's directory.
    :return: The running step, or None when nothing runs, the marker is corrupt, or it is older than 75 minutes.
    """
    marker_content = read_json_file(feature_directory / RUNNING_MARKER_NAME)
    if marker_content is None:
        return None
    started = marker_content.get("started")
    if not isinstance(started, (int, float)):
        return None
    if time.time() - started > RUNNING_MARKER_MAX_AGE_SECONDS:
        return None
    return str(marker_content.get("step", "a long step"))
