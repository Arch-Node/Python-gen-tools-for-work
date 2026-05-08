#!/usr/bin/env python3
"""Relinking step for the repo-prep workflow.

Creates hard links from every file under the repo tree into the Banner links
directory. Excluded directories are skipped entirely during the walk.

This module is imported by traced_main and can be called independently.
"""

import os
from typing import Optional

from uncg.repoprep_lib.common import (
    RepoprepError,
    append_line,
    log_message,
    now_stamp,
    trace_message,
)


# ---------------------------------------------------------------------------
# Directories skipped during the repo walk
# ---------------------------------------------------------------------------

RELINK_EXCLUDED_DIRECTORIES = {
    ".git", "install", "java", "templates", "utility", "retired"
}


# ---------------------------------------------------------------------------
# Relink step functions
# ---------------------------------------------------------------------------

def ensure_relink_target_exists(banner_links: str) -> None:
    """Raise RepoprepError if the Banner links directory does not exist."""
    if not os.path.isdir(banner_links):
        raise RepoprepError(
            f">>> Banner links directory does not exist: {banner_links}", 508
        )


def relink_file(
    source_path: str,
    banner_links: str,
    relink_log: Optional[str],
) -> None:
    """Create a hard link for a single file into banner_links."""
    destination_path = os.path.join(banner_links, os.path.basename(source_path))
    append_line(relink_log, f"[{now_stamp()}] {source_path}")

    if os.path.lexists(destination_path):
        os.remove(destination_path)

    os.link(source_path, destination_path)
    append_line(relink_log, f"[{now_stamp()}] LINKED {source_path} -> {destination_path}")


def run_relink_step(
    repo_path: str,
    banner_links: str,
    relink_log: Optional[str],
    main_log: Optional[str],
    trace_log: Optional[str],
) -> None:
    """Walk repo_path and hard-link every file into banner_links."""
    log_message(">>> Relinking uncg code tree", main_log)
    trace_message(trace_log, f"RUN [relink] repo_path={repo_path} banner_links={banner_links}")
    ensure_relink_target_exists(banner_links)

    try:
        if relink_log:
            with open(relink_log, "w", encoding="utf-8"):
                pass

        linked_file_count = 0
        for current_root, dir_names, file_names in os.walk(repo_path):
            dir_names[:] = [
                d for d in dir_names if d not in RELINK_EXCLUDED_DIRECTORIES
            ]
            for file_name in file_names:
                source_path = os.path.join(current_root, file_name)
                relink_file(source_path, banner_links, relink_log)
                linked_file_count += 1

        trace_message(trace_log, f"EXIT [relink] 0 linked_files={linked_file_count}")
        log_message(f">>> Relink succeeded. Output: {relink_log}", main_log)

    except OSError as exc:
        append_line(relink_log, f"[{now_stamp()}] ERROR {exc}")
        trace_message(trace_log, f"EXIT [relink] 1 error={exc}")
        log_message(f">>> Relink failed. Output: {relink_log}", main_log)
        raise RepoprepError("Relink failed", 508) from exc
