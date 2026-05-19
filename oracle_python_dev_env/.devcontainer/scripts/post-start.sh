#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STARTUP_APT_FILE="$ROOT_DIR/.devcontainer/startup-apt-packages.txt"
STARTUP_PIP_FILE="$ROOT_DIR/.devcontainer/startup-pip-tools.txt"
ORACLE_LINK_DIR="/opt/oracle/instantclient"

# Keep user-installed Python script entrypoints available during startup tasks.
export PATH="$HOME/.local/bin:$PATH"

ensure_python_dirs_writable() {
  local pip_cache_dir="$HOME/.cache/pip"
  local user_base_dir="$HOME/.local"

  mkdir -p "$pip_cache_dir" "$user_base_dir"

  if [[ ! -w "$pip_cache_dir" || ! -w "$user_base_dir" ]]; then
    sudo chown -R "$(id -u):$(id -g)" "$HOME/.cache" "$user_base_dir"
  fi
}

read_list_file() {
  local file_path="$1"
  if [[ -f "$file_path" ]]; then
    grep -Ev '^[[:space:]]*($|#)' "$file_path" || true
  fi
}

append_env_words() {
  local env_value="$1"
  if [[ -z "$env_value" ]]; then
    return
  fi

  local item
  for item in $env_value; do
    printf '%s\n' "$item"
  done
}

install_missing_apt_packages() {
  local -a packages=("$@")
  local -a missing=()
  local package_name

  for package_name in "${packages[@]}"; do
    if dpkg -s "$package_name" >/dev/null 2>&1; then
      continue
    fi
    missing+=("$package_name")
  done

  if (( ${#missing[@]} == 0 )); then
    return
  fi

  echo "Installing missing apt packages: ${missing[*]}"
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends "${missing[@]}"
}

pip_tool_installed() {
  local package_name="$1"
  python -m pip show "$package_name" >/dev/null 2>&1
}

install_missing_pip_tools() {
  local -a tools=("$@")
  local tool

  if (( ${#tools[@]} == 0 )); then
    return
  fi

  for tool in "${tools[@]}"; do
    if pip_tool_installed "$tool"; then
      continue
    fi

    echo "Installing missing Python package: $tool"
    python -m pip install --user "$tool"
  done
}

mapfile -t startup_apt < <(read_list_file "$STARTUP_APT_FILE")
mapfile -t startup_pip < <(read_list_file "$STARTUP_PIP_FILE")
mapfile -t env_apt < <(append_env_words "${EXTRA_APT_PACKAGES:-}")
mapfile -t env_pip < <(append_env_words "${EXTRA_PIP_TOOLS:-}")

startup_apt+=("${env_apt[@]}")
startup_pip+=("${env_pip[@]}")

ensure_python_dirs_writable
install_missing_apt_packages "${startup_apt[@]}"
install_missing_pip_tools "${startup_pip[@]}"

if [[ -L "$ORACLE_LINK_DIR" || -d "$ORACLE_LINK_DIR" ]]; then
  echo "Oracle Instant Client ready at $ORACLE_LINK_DIR"
else
  echo "Oracle Instant Client not installed yet; rebuild container or rerun post-create after adding archives."
fi

echo "post-start checks complete"
