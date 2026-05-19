#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v podman >/dev/null 2>&1; then
	echo "podman is required but was not found in PATH" >&2
	exit 1
fi

# Some Dev Containers flows still call a docker CLI directly.
# Put a local docker->podman shim first in PATH for this VS Code process.
export PATH="$SCRIPT_DIR/.devcontainer/bin:$PATH"

systemctl --user start podman.socket >/dev/null 2>&1 || true
export DOCKER_HOST="unix:///run/user/$UID/podman/podman.sock"
export CONTAINER_HOST="$DOCKER_HOST"

code "$SCRIPT_DIR"