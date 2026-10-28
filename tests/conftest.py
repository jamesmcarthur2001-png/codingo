import importlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

SCRIPTS_DIRECTORY = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIRECTORY))
sys.path.insert(0, str(SCRIPTS_DIRECTORY / "hooks"))

command_runner = importlib.import_module("command_runner")

WORKFLOW_VARIABLES = ("MIDNIGHT_ROLE", "CLAUDE_PROJECT_DIR", "MIDNIGHT_CHECKS")
STATE_TEMPLATE = """# {ticket}: add CSV export to entities

Ticket: {ticket}
Title: add CSV export to entities
Branch: {ticket}-csv-export
Base: master
Worktree: {worktree}
Compose project: btrc-1234
Compose files:
Approved: {approved}
Session:
Pushed:
Phase: {phase}
Slice: 1
Slices: 2
Round: 1
Tries: 0
Status: RUNNING

## Commands

## Coverage exemptions

## Finish

## Log
"""


@pytest.fixture(autouse=True)
def clean_workflow_environment(monkeypatch: pytest.MonkeyPatch):
    for variable in WORKFLOW_VARIABLES:
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def write_python_file(tmp_path: Path) -> Callable[[str, str], Path]:
    def _write(source: str, file_name: str = "module.py") -> Path:
        path = tmp_path / "app" / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    return _write


@pytest.fixture
def run_hook() -> Callable[..., subprocess.CompletedProcess[str]]:
    def _run(
        hook_name: str,
        payload: dict[str, object],
        extra_environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = {
            name: value
            for name, value in os.environ.items()
            if name not in WORKFLOW_VARIABLES
        }
        if extra_environment is not None:
            environment.update(extra_environment)
        return subprocess.run(
            [sys.executable, str(SCRIPTS_DIRECTORY / "hooks" / hook_name)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            check=False,
            timeout=60,
        )

    return _run


def git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return completed.stdout


@pytest.fixture
def git_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    repository.mkdir()
    git(repository, "init", "--quiet", "--initial-branch=master")
    git(repository, "config", "user.email", "test@example.com")
    git(repository, "config", "user.name", "Test")
    git(repository, "config", "core.autocrlf", "false")
    (repository / "README.md").write_text("# repo\n", encoding="utf-8")
    git(repository, "add", "-A")
    git(repository, "commit", "--quiet", "-m", "initial")
    return repository


@pytest.fixture
def make_feature_state() -> Callable[..., Path]:
    def _make(
        repository: Path,
        ticket: str = "BTRC-1234",
        phase: str = "BUILD",
        approved: str = "yes",
        worktree: str = "",
        active: bool = True,
    ) -> Path:
        feature_directory = repository / "docs" / "features" / ticket
        feature_directory.mkdir(parents=True, exist_ok=True)
        state_text = STATE_TEMPLATE.format(
            ticket=ticket,
            worktree=worktree,
            approved=approved,
            phase=phase,
        )
        (feature_directory / "state.md").write_text(state_text, encoding="utf-8")
        if active:
            (repository / "docs" / "features" / ".active").write_text(ticket + "\n", encoding="utf-8")
        return feature_directory

    return _make


def command_words(command: list[str]) -> list[str]:
    """
    Turn an argument list into the words tests match on: the program's name, and git without its `-c` options.
    """
    words = [Path(command[0]).stem, *command[1:]]
    if words[0] != "git":
        return words
    remaining = words[1:]
    while len(remaining) >= 2 and remaining[0] == "-c":
        remaining = remaining[2:]
    return ["git", *remaining]


class FakeCommands:
    """
    Replaces command_runner.run_command: answers scripted commands and passes git through when asked.
    """

    def __init__(self, real_run_command: Callable[..., command_runner.CommandResult], pass_git_through: bool):
        self.real_run_command = real_run_command
        self.pass_git_through = pass_git_through
        self.responses: list[tuple[str, list[command_runner.CommandResult]]] = []
        self.calls: list[tuple[str, Path | None, dict[str, str] | None]] = []

    def respond(self, command_start: str, *results: command_runner.CommandResult):
        self.responses.append((command_start, list(results)))

    def __call__(
        self,
        command: list[str] | str,
        cwd: Path | None,
        timeout: int = 600,
        extra_environment: dict[str, str] | None = None,
    ) -> command_runner.CommandResult:
        command_text = command if isinstance(command, str) else " ".join(command_words(command))
        self.calls.append((command_text, cwd, extra_environment))
        for command_start, results in self.responses:
            if not command_text.startswith(command_start):
                continue
            if len(results) > 1:
                return results.pop(0)
            return results[0]
        if self.pass_git_through and command_text.startswith("git "):
            return self.real_run_command(command, cwd, timeout, extra_environment)
        return command_runner.CommandResult(0, "")

    def commands(self) -> list[str]:
        return [command_text for command_text, _, _ in self.calls]


@pytest.fixture
def fake_commands(monkeypatch: pytest.MonkeyPatch) -> Callable[[bool], FakeCommands]:
    def _install(pass_git_through: bool = False) -> FakeCommands:
        fake = FakeCommands(command_runner.run_command, pass_git_through)
        monkeypatch.setattr(command_runner, "run_command", fake)
        return fake

    return _install


def ok(output: str = "") -> command_runner.CommandResult:
    return command_runner.CommandResult(0, output)


def failed(output: str = "", returncode: int = 1) -> command_runner.CommandResult:
    return command_runner.CommandResult(returncode, output)
