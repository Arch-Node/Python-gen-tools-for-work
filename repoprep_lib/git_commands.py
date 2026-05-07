#!/usr/bin/env python3
"""Git and file-permission commands for the elevated repo-prep workflow.

All functions here are designed to run as the already-elevated (sudo) user.
They are imported by exe_elevated_cmd, but can also be called independently
by any script running under the correct account.
"""

import os
from typing import Optional

from repoprep_lib.common import (
    RepoprepError,
    log_message,
    now_stamp,
    run_command,
    run_required_command,
    trace_message,
)

# Backward-compatible alias: exe_elevated_cmd imports this name from here.
RepoprepElevatedError = RepoprepError


# ---------------------------------------------------------------------------
# Git step functions
# ---------------------------------------------------------------------------

def git_checkout_dot(repo_path: str, trace_log: Optional[str]) -> None:
    """Remove all tracked-file modifications (git checkout .)."""
    log_message(">>> Removing untracked changes", trace_log)
    run_required_command(
        ["git", "checkout", "."],
        step_name="git-checkout-dot",
        cwd=repo_path,
        trace_log=trace_log,
        failure_message=">>> Untracked change removal (git checkout .) failed",
        exit_code=510,
    )
    log_message(">>> Untracked changes removed", trace_log)


def git_clean(repo_path: str, trace_log: Optional[str]) -> None:
    """Remove untracked files from the working tree (git clean -f)."""
    log_message(">>> Removing untracked files", trace_log)
    run_required_command(
        ["git", "clean", "-f"],
        step_name="git-clean",
        cwd=repo_path,
        trace_log=trace_log,
        failure_message=">>> Untracked file removal (git clean -f) failed",
        exit_code=511,
    )
    log_message(">>> Untracked files removed", trace_log)


def git_set_auth_url(repo_path: str, auth_url: str, trace_log: Optional[str]) -> None:
    """Set the remote origin URL to the authenticated (token-bearing) URL."""
    log_message(">>> Setting url with authentication", trace_log)
    run_required_command(
        ["git", "remote", "set-url", "origin", auth_url],
        step_name="git-set-auth-url",
        cwd=repo_path,
        trace_log=trace_log,
        failure_message=">>> Set url with authentication failed",
        exit_code=501,
        redacted_command="git remote set-url origin <redacted>",
    )
    log_message(">>> Set url with authentication succeeded", trace_log)


def git_checkout_branch(
    repo_path: str, branch: str, public_url: str, trace_log: Optional[str]
) -> None:
    """Check out the named branch; resets the remote URL on failure."""
    log_message(f">>> Checking out branch {branch}", trace_log)
    checkout_code = run_command(
        ["git", "checkout", branch],
        step_name="git-checkout-branch",
        cwd=repo_path,
        trace_log=trace_log,
    )
    if checkout_code != 0:
        _safe_reset_remote_url(repo_path, public_url, trace_log)
        raise RepoprepElevatedError(f">>> Branch checkout for {branch} failed", 502)
    log_message(f">>> Checked out branch {branch}", trace_log)


def git_pull(
    repo_path: str, branch: str, public_url: str, trace_log: Optional[str]
) -> None:
    """Pull the named branch from origin; resets the remote URL on failure."""
    log_message(f">>> Pulling branch {branch}", trace_log)
    pull_code = run_command(
        ["git", "pull", "origin", branch],
        step_name="git-pull",
        cwd=repo_path,
        trace_log=trace_log,
    )
    if pull_code != 0:
        _safe_reset_remote_url(repo_path, public_url, trace_log)
        raise RepoprepElevatedError(f">>> Git pull on {branch} failed", 504)
    log_message(f">>> Git pull succeeded on branch {branch}", trace_log)


def git_set_public_url(repo_path: str, public_url: str, trace_log: Optional[str]) -> None:
    """Restore the remote origin URL to the public (no-token) URL."""
    log_message(">>> Setting URL without authentication", trace_log)
    run_required_command(
        ["git", "remote", "set-url", "origin", public_url],
        step_name="git-set-public-url",
        cwd=repo_path,
        trace_log=trace_log,
        failure_message=">>> Set URL without authentication failed",
        exit_code=505,
    )
    log_message(">>> Set URL without authentication succeeded", trace_log)


def git_config_filemode(repo_path: str, trace_log: Optional[str]) -> None:
    """Set core.filemode to false so chmod changes are not tracked by git."""
    log_message(">>> Setting git filemode false", trace_log)
    run_required_command(
        ["git", "config", "core.filemode", "false"],
        step_name="git-config-filemode",
        cwd=repo_path,
        trace_log=trace_log,
        failure_message=">>> Ignore file permissions failed",
        exit_code=506,
    )
    log_message(">>> Ignore file permissions succeeded", trace_log)


def chmod_repo_files(repo_path: str, trace_log: Optional[str]) -> None:
    """Set 775 permissions on all files under repo_path."""
    log_message(">>> Changing file permissions for shell execution", trace_log)
    run_required_command(
        ["find", repo_path, "-type", "f", "-exec", "chmod", "775", "{}", "+"],
        step_name="chmod-repo-files",
        cwd=repo_path,
        trace_log=trace_log,
        failure_message=">>> Change file permissions failed",
        exit_code=507,
    )
    log_message(">>> Change file permissions succeeded", trace_log)


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _safe_reset_remote_url(repo_path: str, public_url: str, trace_log: Optional[str]) -> None:
    """Best-effort restore of the public remote URL; swallows errors."""
    try:
        run_command(
            ["git", "remote", "set-url", "origin", public_url],
            step_name="git-reset-url",
            cwd=repo_path,
            trace_log=trace_log,
        )
    except RepoprepElevatedError:
        pass
