#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export DOCKER_HOST="unix:///run/user/$UID/podman/podman.sock"

code "$SCRIPT_DIR"
``