"""
Runs external commands (git, glab, docker, claude, project tools) for the workflow scripts.

Every script calls `command_runner.run_command`, so tests replace that one function to mock the outside world.

:author: midnight-workflow
:date: 28/10/2026
"""
# ----- Imports ----- #

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# ----- Consts ----- #

DEFAULT_TIMEOUT_SECONDS = 600
FAILED_TO_START_EXIT_CODE = -1

# ----- Classes ----- #


@dataclass(frozen=True)
class CommandResult:
    """
    What a finished (or timed out) command returned.
    """
    returncode: int
    output: str
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and not self.timed_out

# ----- Functions ----- #


def find_executable(name: str) -> str:
    """
    Resolve a program name to its full path, so Windows finds `.cmd` and `.exe` wrappers.

    :param name: The program name, e.g. `glab`.
    :return: The full path when the program is on PATH, else the bare name.
    """
    executable = shutil.which(name)
    if executable is None:
        return name
    return executable


def run_command(
    command: list[str] | str,
    cwd: Path | None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    extra_environment: dict[str, str] | None = None,
) -> CommandResult:
    """
    Run one command and collect its combined stdout and stderr.

    :param command: An argument list, or a string that runs through the shell.
    :param cwd: The directory to run in.
    :param timeout: Seconds before the command is stopped.
    :param extra_environment: Variables added to the current environment.
    :return: The exit code and output; a command that could not start has exit code -1.
    """
    environment = dict(os.environ)
    if extra_environment is not None:
        environment.update(extra_environment)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            shell=isinstance(command, str),
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as timeout_error:
        partial_output = timeout_error.stdout if isinstance(timeout_error.stdout, str) else ""
        return CommandResult(
            FAILED_TO_START_EXIT_CODE,
            partial_output,
            timed_out=True,
        )
    except OSError as start_error:
        return CommandResult(
            FAILED_TO_START_EXIT_CODE,
            f"Could not run {command}: {start_error}",
        )
    return CommandResult(
        completed.returncode,
        completed.stdout + completed.stderr,
    )
