#!/usr/bin/env python3
"""Oracle Wallet and SQL*Plus helpers for the repoprep_lib package.

Provides:
    get_tns_admin()       -- resolve and validate the Oracle Wallet path
    run_sqlplus()         -- execute a single SQL script via sqlplus
"""

import os
from typing import Dict, List, Optional, Tuple

from repoprep_lib.common import RepoprepError, log_message, run_required_command, trace_message


# Default wallet path used at UNCG.  Can be overridden via the TNS_ADMIN
# environment variable or by passing tns_admin explicitly to run_sqlplus().
DEFAULT_TNS_ADMIN = "/banvol/wallet/deploy"


def get_tns_admin(override: Optional[str] = None) -> str:
    """Return the TNS_ADMIN path to use, validating that it exists.

    Resolution order:
      1. override argument (if provided)
      2. TNS_ADMIN environment variable (if set)
      3. DEFAULT_TNS_ADMIN constant

    Raises RepoprepError (exit 520) if the resolved path does not exist.
    """
    resolved = (
        override
        or os.environ.get("TNS_ADMIN", "").strip()
        or DEFAULT_TNS_ADMIN
    )
    if not os.path.isdir(resolved):
        raise RepoprepError(
            f"Oracle Wallet directory not found: {resolved}", 520
        )
    return resolved


def build_sqlplus_command(
    script_path: str,
    *,
    connect_string: str,
    tns_admin: Optional[str] = None,
) -> Tuple[List[str], Dict[str, str], str]:
    """Build the sqlplus command, subprocess environment, and working directory."""
    if not os.path.isfile(script_path):
        raise RepoprepError(f"SQL script not found: {script_path}", 521)

    wallet_path = get_tns_admin(tns_admin)
    env = os.environ.copy()
    env["TNS_ADMIN"] = wallet_path

    command = ["sqlplus", "-l", "-s", connect_string, f"@{script_path}"]
    cwd = os.path.dirname(script_path)
    return command, env, cwd


def execute_sqlplus_command(
    command: List[str],
    *,
    script_path: str,
    cwd: str,
    env: Dict[str, str],
    trace_log: Optional[str] = None,
    main_log: Optional[str] = None,
) -> None:
    """Execute a prepared sqlplus command and raise RepoprepError on failure."""
    log_message(f">>> Running SQL script: {script_path}", main_log)
    trace_message(trace_log, f"TNS_ADMIN={env.get('TNS_ADMIN', '')}")

    run_required_command(
        command,
        step_name="sqlplus",
        failure_message=f">>> sqlplus failed for {script_path}",
        exit_code=522,
        cwd=cwd,
        trace_log=trace_log,
        env=env,
    )

    log_message(f">>> SQL script completed: {os.path.basename(script_path)}", main_log)


def run_sqlplus(
    script_path: str,
    *,
    connect_string: str,
    tns_admin: Optional[str] = None,
    trace_log: Optional[str] = None,
    main_log: Optional[str] = None,
) -> None:
    """Build and execute a SQL script via sqlplus.

    Args:
        script_path:     Absolute path to the .sql file to run.
        connect_string:  sqlplus connection string, e.g. "[UNCGMGR]/@deploy",
                         "[BANINST1]/@deploy", "/nolog", etc.  Required --
                         no default since the schema varies per job.
        tns_admin:       Override for the Wallet directory.  If None, resolved
                         via get_tns_admin().
        trace_log:       Optional path to the trace log file.
        main_log:        Optional path to the main log file.

    Raises:
        RepoprepError (exit 521) if the script file does not exist.
        RepoprepError (exit 522) if sqlplus exits non-zero.
    """
    command, env, cwd = build_sqlplus_command(
        script_path,
        connect_string=connect_string,
        tns_admin=tns_admin,
    )
    execute_sqlplus_command(
        command,
        script_path=script_path,
        cwd=cwd,
        env=env,
        trace_log=trace_log,
        main_log=main_log,
    )
