#!/usr/bin/env python3
"""
Native Python repo-prep runner with step-by-step logging and tracing.

This keeps the workflow in one program instead of embedding a large shell
script inside Python. External shell execution is still used where required
for existing operational commands such as git, chmod, and installer scripts.
"""

import argparse
import datetime
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional

from repoprep_lib.common import RepoprepError, append_line, now_stamp
from repoprep_lib.relink import run_relink_step


SID_CONFIG = {
    "banprd": {"branch": "master", "sudo_user": "banner"},
    "ugval3": {"branch": "uat", "sudo_user": "banner"},
    "ugdev8": {"branch": "dev", "sudo_user": "intf_git"},
}

@dataclass
class RunContext:
    gh_user: str
    inc_to_run: str
    oracle_sid: str
    banner_home: str
    banner_links: str
    branch: str
    sudo_user: str
    repo_path: str
    url: str
    auth_url: str
    main_log: str
    trace_log: str
    relink_log: str


def log_message(context: RunContext, message: str) -> None:
    text = message.rstrip("\n")
    print(text)
    append_line(context.main_log, f"[{now_stamp()}] {text}")


def trace_message(context: RunContext, message: str) -> None:
    append_line(context.trace_log, f"[{now_stamp()}] {message}")


def get_required_env_var(name: str, exit_code: int = 500) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RepoprepError(f"{name} is not set", exit_code)
    return value


def read_token() -> str:
    token_file_path = os.path.join(os.path.expanduser("~"), ".secure", "github.app")
    if not os.path.isfile(token_file_path):
        raise RepoprepError(f"Cannot read GitHub app token file: {token_file_path}", 500)

    try:
        with open(token_file_path, "r", encoding="utf-8") as token_handle:
            token_value = token_handle.read().strip()
    except OSError as exc:
        raise RepoprepError(f"Cannot read GitHub app token file: {token_file_path} ({exc})", 500) from exc

    if not token_value:
        raise RepoprepError("GitHub app token is empty", 500)
    return token_value


def choose_log_directory() -> str:
    primary_path = "/banvol/uncgoutput"
    fallback_path = "/tmp"

    try:
        os.makedirs(primary_path, exist_ok=True)
        return primary_path
    except OSError:
        os.makedirs(fallback_path, exist_ok=True)
        return fallback_path


def command_to_text(command: List[str]) -> str:
    return " ".join(command)


def build_context(args: argparse.Namespace) -> RunContext:
    oracle_sid = get_required_env_var("ORACLE_SID")
    banner_home = get_required_env_var("BANNER_HOME")
    banner_links = get_required_env_var("BANNER_LINKS")

    sid_info = SID_CONFIG.get(oracle_sid)
    if sid_info is None:
        raise RepoprepError(f"ORACLE_SID not recognized ({oracle_sid})", 500)

    token = read_token()
    log_dir = choose_log_directory()
    run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    configured_sudo_user = sid_info["sudo_user"]
    env_sudo_user = (os.environ.get("SUDOUSR") or os.environ.get("SUDOUSER") or "").strip()
    effective_sudo_user = env_sudo_user if env_sudo_user else configured_sudo_user

    return RunContext(
        gh_user=args.gh_user,
        inc_to_run=args.inc_to_run,
        oracle_sid=oracle_sid,
        banner_home=banner_home,
        banner_links=banner_links,
        branch=sid_info["branch"],
        sudo_user=effective_sudo_user,
        repo_path=os.path.join(banner_home, "uncg"),
        url="https://username:password@github.com/uncg-its/uncg.git",
        auth_url=f"https://{token}@github.com/uncg-its/uncg.git",
        main_log=os.path.join(log_dir, f"repoprep_{oracle_sid}_{run_timestamp}.log"),
        trace_log=os.path.join(log_dir, f"repoprep_{oracle_sid}_{run_timestamp}.xtrace.log"),
        relink_log=os.path.join(log_dir, f"repoprep_{oracle_sid}_{run_timestamp}.relink.log"),
    )


def run_command(
    context: RunContext,
    command: List[str],
    *,
    step_name: str,
    cwd: Optional[str] = None,
    redacted_command: Optional[str] = None,
) -> int:
    display_command = redacted_command if redacted_command is not None else command_to_text(command)
    trace_message(context, f"RUN [{step_name}] {display_command}")
    if cwd is not None:
        trace_message(context, f"CWD [{step_name}] {cwd}")

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
            log_message(context, cleaned_line)
            trace_message(context, f"OUT [{step_name}] {cleaned_line}")

    process.wait()
    trace_message(context, f"EXIT [{step_name}] {process.returncode}")
    return process.returncode


def run_required_command(
    context: RunContext,
    command: List[str],
    *,
    step_name: str,
    failure_message: str,
    exit_code: int,
    cwd: Optional[str] = None,
    redacted_command: Optional[str] = None,
) -> None:
    result_code = run_command(
        context,
        command,
        step_name=step_name,
        cwd=cwd,
        redacted_command=redacted_command,
    )
    if result_code != 0:
        raise RepoprepError(failure_message, exit_code)


def run_elevated_workflow(context: RunContext) -> None:
    """Run all elevated git/permission steps in one sudo boundary."""
    log_message(context, f">>> ORACLE_SID is {context.oracle_sid} using branch {context.branch}")
    log_message(context, f">>> Github User is: {context.gh_user}")
    log_message(context, f">>> Running elevated workflow as {context.sudo_user}")

    elevated_command = [
        "sudo",
        "-i",
        "-u",
        context.sudo_user,
        sys.executable,
        "-m",
        "repoprep_lib.exe_elevated_cmd",
        "--repo-path",
        context.repo_path,
        "--branch",
        context.branch,
        "--public-url",
        context.url,
        "--auth-url",
        context.auth_url,
        "--gh-user",
        context.gh_user,
        "--trace-log",
        context.trace_log,
    ]
    redacted_command = (
        f"sudo -i -u {context.sudo_user} {sys.executable} -m repoprep_lib.exe_elevated_cmd "
        f"--repo-path {context.repo_path} --branch {context.branch} --public-url {context.url} "
        f"--auth-url <redacted> --gh-user {context.gh_user} --trace-log {context.trace_log}"
    )

    elevated_exit_code = run_command(
        context,
        elevated_command,
        step_name="elevated-workflow",
        redacted_command=redacted_command,
    )
    if elevated_exit_code != 0:
        raise RepoprepError(
            f">>> Elevated workflow failed while running as {context.sudo_user}",
            elevated_exit_code,
        )


def run_installer_if_requested(context: RunContext) -> None:
    normalized_inc = (context.inc_to_run or "").strip().lower()
    if not normalized_inc:
        log_message(context, ">>> No incident/story/task provided to install")
        return

    install_script = os.path.join(context.repo_path, "install", f"{normalized_inc}.sh")
    if not os.path.isfile(install_script):
        raise RepoprepError(f">>> File {install_script} does not exist", 509)

    log_message(context, f">>> Running install/{normalized_inc}.sh with bash -x")
    installer_code = run_command(
        context,
        ["bash", "-x", install_script],
        step_name="installer",
        cwd=context.repo_path,
    )
    if installer_code != 0:
        raise RepoprepError("Installer script failed", installer_code)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare uncg repo with full output tracing for nested shell workflows."
    )
    parser.add_argument("gh_user", nargs="?", default="", help="GitHub user label for logging context")
    parser.add_argument("inc_to_run", nargs="?", default="", help="Installer script name without .sh")
    return parser


def validate_context(context: RunContext) -> None:
    if not os.path.isdir(context.repo_path):
        raise RepoprepError(f"Repo path does not exist: {context.repo_path}", 500)


def log_run_header(context: RunContext) -> None:
    log_message(context, f">>> Starting repoprep for ORACLE_SID={context.oracle_sid} branch={context.branch}")
    log_message(context, f">>> Github User is: {context.gh_user}")
    log_message(context, f">>> Main log: {context.main_log}")
    log_message(context, f">>> Trace log: {context.trace_log}")
    log_message(context, f">>> Relink log: {context.relink_log}")


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    context: Optional[RunContext] = None

    try:
        context = build_context(args)
        validate_context(context)
        log_run_header(context)

        run_elevated_workflow(context)
        run_relink_step(
            context.repo_path,
            context.banner_links,
            context.relink_log,
            context.main_log,
            context.trace_log,
        )
        run_installer_if_requested(context)

        log_message(context, f"END: repoprep exit code 0 at {now_stamp()}")
        return 0

    except RepoprepError as error:
        exit_code = error.exit_code
        fail_message = f"ERROR: {error}"

        if context is not None:
            log_message(context, fail_message)
            trace_message(context, fail_message)
            log_message(context, f"END: repoprep exit code {exit_code} at {now_stamp()}")
            trace_message(context, f"END exit code {exit_code}")
            print(f"Main log: {context.main_log}")
            print(f"Trace log: {context.trace_log}")
        else:
            print(fail_message)

        return exit_code

    except Exception as error:
        unexpected_message = f"ERROR: Unexpected failure: {error}"

        if context is not None:
            log_message(context, unexpected_message)
            trace_message(context, unexpected_message)
            log_message(context, f"END: repoprep exit code 599 at {now_stamp()}")
            trace_message(context, "END exit code 599")
            print(f"Main log: {context.main_log}")
            print(f"Trace log: {context.trace_log}")
        else:
            print(unexpected_message)

        return 599

