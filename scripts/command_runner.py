#!/usr/bin/env python3
"""
Runs external commands (git, glab, docker, claude, project tools) for the workflow scripts.

Every script calls `command_runner.run_command`, so tests replace that one function to mock the outside world.

:author: midnight-workflow
:date: 28/10/2026
"""
# ----- Imports ----- #

import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

# ----- Consts ----- #

DEFAULT_TIMEOUT_SECONDS = 600
FAILED_TO_START_EXIT_CODE = -1
SHELL_PREFIX = ("bash", "-lc")
OUTPUT_ENCODING = "utf-8"

# ----- Classes ----- #


@dataclass(frozen=True)
class CommandResult:
    """
    What a finished (or timed out) command returned, with stdout and stderr kept apart.
    """
    returncode: int
    stdout: str
    stderr: str = ""
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    @property
    def output(self) -> str:
        """
        Join stdout and stderr, for messages shown to the orchestrator.

        :return: stdout, then stderr on a new line when there is any.
        """
        if self.stderr.strip() == "":
            return self.stdout
        if self.stdout.strip() == "":
            return self.stderr
        return f"{self.stdout.rstrip()}\n{self.stderr}"

# ----- Functions ----- #


def decode_output(raw_output: bytes | str | None) -> str:
    if raw_output is None:
        return ""
    if isinstance(raw_output, str):
        return raw_output
    return raw_output.decode(OUTPUT_ENCODING, errors="replace")


def stop_process_group(process: subprocess.Popen[bytes]):
    """
    Kill a timed-out command and every child it started.

    :param process: The command's process, started in its own session.
    """
    if hasattr(os, "killpg"):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        return
    process.kill()


def build_argument_list(command: list[str] | str) -> list[str]:
    if isinstance(command, str):
        return [*SHELL_PREFIX, command]
    return command


def run_command(
    command: list[str] | str,
    cwd: Path | None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    extra_environment: dict[str, str] | None = None,
) -> CommandResult:
    """
    Run one command without stdin, in its own process group.

    :param command: An argument list, or a string that runs through `bash -lc`.
    :param cwd: The directory to run in.
    :param timeout: Seconds before the command and its children are killed.
    :param extra_environment: Variables added to the current environment.
    :return: The exit code, stdout and stderr; a command that could not start has exit code -1.
    """
    environment = dict(os.environ)
    if extra_environment is not None:
        environment.update(extra_environment)
    try:
        process = subprocess.Popen(
            build_argument_list(command),
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as start_error:
        return CommandResult(
            FAILED_TO_START_EXIT_CODE,
            "",
            f"Could not run {command}: {start_error}",
        )
    try:
        raw_stdout, raw_stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        stop_process_group(process)
        raw_stdout, raw_stderr = process.communicate()
        return CommandResult(
            FAILED_TO_START_EXIT_CODE,
            decode_output(raw_stdout),
            decode_output(raw_stderr),
            timed_out=True,
        )
    return CommandResult(
        process.returncode,
        decode_output(raw_stdout),
        decode_output(raw_stderr),
    )
