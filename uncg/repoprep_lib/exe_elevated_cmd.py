#!/usr/bin/env python3
"""Run the elevated repo-prep workflow after the shell shim has done sudo.

This script is intended to be executed as the target account already.
It orchestrates the git and permission steps by calling repoprep_lib.git_commands.
"""

import argparse
import os
import sys

from uncg.repoprep_lib.git_commands import (
    RepoprepElevatedError,
    chmod_repo_files,
    git_checkout_branch,
    git_checkout_dot,
    git_clean,
    git_config_filemode,
    git_pull,
    git_set_auth_url,
    git_set_public_url,
    log_message,
    now_stamp,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run repo prep after shell-based sudo elevation.")
    parser.add_argument("--repo-path", required=True, help="Path to the uncg repository checkout")
    parser.add_argument("--branch", required=True, help="Git branch to check out and pull")
    parser.add_argument("--public-url", required=True, help="Git remote URL without credentials")
    parser.add_argument("--auth-url", required=True, help="Git remote URL with authentication token")
    parser.add_argument("--gh-user", default="", help="GitHub user label for logging context")
    parser.add_argument("--trace-log", default="", help="Optional trace log path")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    trace_log = args.trace_log or None

    try:
        repo_path = os.path.abspath(args.repo_path)

        if not os.path.isdir(repo_path):
            raise RepoprepElevatedError(f"Repo path does not exist: {repo_path}", 500)

        log_message(f">>> Starting elevated repoprep in {repo_path}", trace_log)
        log_message(f">>> Github User is: {args.gh_user}", trace_log)
        log_message(f">>> Branch is: {args.branch}", trace_log)

        git_checkout_dot(repo_path, trace_log)
        git_clean(repo_path, trace_log)
        git_set_auth_url(repo_path, args.auth_url, trace_log)
        git_checkout_branch(repo_path, args.branch, args.public_url, trace_log)
        git_pull(repo_path, args.branch, args.public_url, trace_log)
        git_set_public_url(repo_path, args.public_url, trace_log)
        git_config_filemode(repo_path, trace_log)
        chmod_repo_files(repo_path, trace_log)

        log_message(f"END: elevated repoprep exit code 0 at {now_stamp()}", trace_log)
        return 0

    except RepoprepElevatedError as error:
        log_message(f"ERROR: {error}", trace_log)
        log_message(f"END: elevated repoprep exit code {error.exit_code} at {now_stamp()}", trace_log)
        return error.exit_code

    except Exception as error:
        log_message(f"ERROR: Unexpected failure: {error}", trace_log)
        log_message(f"END: elevated repoprep exit code 599 at {now_stamp()}", trace_log)
        return 599


if __name__ == "__main__":
    sys.exit(main())

