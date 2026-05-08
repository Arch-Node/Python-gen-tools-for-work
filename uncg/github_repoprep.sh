#!/bin/bash
# Wrapper for the Python repoprep workflow.
# Usage:
#   github_repoprep.sh [gh_user] [inc_to_run]
#
# PSEUDOCODE (FULL LIBRARY FLOW)
#
# 1) Parse script args:
#      GH_USER   = optional first arg
#      INC_TO_RUN= optional second arg
#
# 2) Execute Python entrypoint:
#      python3 repoprep_traced.py GH_USER INC_TO_RUN
#
# 3) repoprep_traced.py delegates to repoprep_lib.traced_main.main(), which:
#      a) Builds run context from env vars and SID mapping
#         - reads ORACLE_SID, BANNER_HOME, BANNER_LINKS
#         - resolves branch + sudo user from SID_CONFIG
#         - reads GitHub token from ~/.secure/github.app
#         - builds log paths
#      b) Runs elevated workflow in one sudo boundary:
#         sudo -i -u <sudo_user> python -m repoprep_lib.exe_elevated_cmd ...
#      c) Runs relink step via repoprep_lib.relink.run_relink_step(...)
#      d) If INC_TO_RUN is present, runs install/<inc_to_run>.sh
#
# 4) repoprep_lib.exe_elevated_cmd.main() orchestrates git steps from
#    repoprep_lib.git_commands:
#      - git checkout .
#      - git clean -f
#      - git remote set-url origin <auth_url>
#      - git checkout <branch>
#      - git pull origin <branch>
#      - git remote set-url origin <public_url>
#      - git config core.filemode false
#      - chmod repo files (775)
#
# 5) repoprep_lib.common provides shared infrastructure:
#      - RepoprepError
#      - timestamped logging helpers
#      - subprocess run helpers with trace logging
#
# 6) Exit with propagated status code and write final log footer.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GH_USER="${1:-}"
INC_TO_RUN="${2:-}"

exec python3 "${SCRIPT_DIR}/repoprep_traced.py" "${GH_USER}" "${INC_TO_RUN}"
