#!/usr/bin/env python3
"""Shared infrastructure for the repoprep_lib package.

Contains the common exception, logging helpers, and subprocess runners used
by all modules in the library. Import from here rather than duplicating
these utilities in each module.
"""

import datetime
import os
import subprocess
from typing import List, Optional


# ---------------------------------------------------------------------------
# Common exception
# ---------------------------------------------------------------------------

class RepoprepError(Exception):
    """Raised when a controlled repoprep step fails with a known exit code."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def now_stamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def append_line(file_path: Optional[str], message: str) -> None:
    """Append a timestamped line to file_path; silently no-ops if file_path is None."""
    if not file_path:
        return
    with open(file_path, "a", encoding="utf-8") as handle:
        handle.write(message.rstrip("\n") + "\n")


def log_message(message: str, log_path: Optional[str] = None) -> None:
    """Print message to stdout and optionally append it to log_path."""
    text = message.rstrip("\n")
    print(text)
    append_line(log_path, f"[{now_stamp()}] {text}")


def trace_message(trace_log: Optional[str], message: str) -> None:
    """Append a trace entry to trace_log; no stdout output."""
    append_line(trace_log, f"[{now_stamp()}] {message}")


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def run_command(
    command: List[str],
    *,
    step_name: str,
    cwd: str,
    trace_log: Optional[str],
    redacted_command: Optional[str] = None,
) -> int:
    """Run command, stream output to stdout and trace_log, return exit code."""
    display_command = redacted_command if redacted_command is not None else " ".join(command)
    trace_message(trace_log, f"RUN [{step_name}] {display_command}")
    trace_message(trace_log, f"CWD [{step_name}] {cwd}")

    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        raise RepoprepError(f"Unable to start {step_name}: {exc}", 599) from exc

    if process.stdout is not None:
        for line in process.stdout:
            cleaned_line = line.rstrip("\n")
            log_message(cleaned_line, trace_log)
            trace_message(trace_log, f"OUT [{step_name}] {cleaned_line}")

    process.wait()
    trace_message(trace_log, f"EXIT [{step_name}] {process.returncode}")
    return process.returncode


def run_required_command(
    command: List[str],
    *,
    step_name: str,
    failure_message: str,
    exit_code: int,
    cwd: str,
    trace_log: Optional[str],
    redacted_command: Optional[str] = None,
) -> None:
    """Run command and raise RepoprepError if it exits non-zero."""
    result_code = run_command(
        command,
        step_name=step_name,
        cwd=cwd,
        trace_log=trace_log,
        redacted_command=redacted_command,
    )
    if result_code != 0:
        raise RepoprepError(failure_message, exit_code)
