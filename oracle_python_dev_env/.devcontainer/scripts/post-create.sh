#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APT_FILE="$ROOT_DIR/.devcontainer/apt-packages.txt"
PIP_FILE="$ROOT_DIR/.devcontainer/pip-tools.txt"
ORACLE_DROP_DIR="$ROOT_DIR/.devcontainer/oracle"
ORACLE_INSTALL_ROOT="/opt/oracle"
ORACLE_LINK_DIR="$ORACLE_INSTALL_ROOT/instantclient"

read_list_file() {
  local file_path="$1"
  if [[ -f "$file_path" ]]; then
    grep -Ev '^[[:space:]]*($|#)' "$file_path" || true
  fi
}

install_apt_packages() {
  local -a packages=("$@")
  if (( ${#packages[@]} == 0 )); then
    return
  fi

  echo "Installing apt packages: ${packages[*]}"
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends "${packages[@]}"
}

pip_tool_installed() {
  local package_name="$1"
  python -m pip show "$package_name" >/dev/null 2>&1
}

install_pip_tools() {
  local -a tools=("$@")
  local tool
  if (( ${#tools[@]} == 0 )); then
    return
  fi

  python -m pip install --upgrade pip

  for tool in "${tools[@]}"; do
    if pip_tool_installed "$tool"; then
      echo "Python package already installed: $tool"
      continue
    fi

    echo "Installing Python package: $tool"
    python -m pip install "$tool"
  done
}

download_oracle_archives() {
  local download_dir="$1"
  local url
  local file_name
  local downloaded_any=1

  for url in "${ORACLE_BASIC_URL:-}" "${ORACLE_SDK_URL:-}" "${ORACLE_SQLPLUS_URL:-}"; do
    if [[ -z "$url" ]]; then
      continue
    fi

    file_name="$(basename "${url%%\?*}")"
    echo "Downloading Oracle archive: $file_name"
    curl -fsSL "$url" -o "$download_dir/$file_name"
    downloaded_any=0
  done

  return $downloaded_any
}

install_oracle_instant_client() {
  local temp_dir
  local extracted_dir
  local -a archives=()

  mkdir -p "$ORACLE_DROP_DIR"
  sudo mkdir -p "$ORACLE_INSTALL_ROOT"

  shopt -s nullglob
  archives=("$ORACLE_DROP_DIR"/*.zip)
  shopt -u nullglob

  if (( ${#archives[@]} == 0 )); then
    temp_dir="$(mktemp -d)"
    if download_oracle_archives "$temp_dir"; then
      shopt -s nullglob
      archives=("$temp_dir"/*.zip)
      shopt -u nullglob
    fi
  else
    temp_dir=""
  fi

  if (( ${#archives[@]} == 0 )); then
    echo "No Oracle Instant Client archives were found."
    echo "Add zip files under $ORACLE_DROP_DIR or set ORACLE_BASIC_URL / ORACLE_SDK_URL / ORACLE_SQLPLUS_URL."
    exit 1
  fi

  echo "Installing Oracle Instant Client from: ${archives[*]}"
  sudo rm -rf "$ORACLE_INSTALL_ROOT"/instantclient_*

  local archive
  for archive in "${archives[@]}"; do
    sudo unzip -oq "$archive" -d "$ORACLE_INSTALL_ROOT"
  done

  extracted_dir="$(find "$ORACLE_INSTALL_ROOT" -mindepth 1 -maxdepth 1 -type d -name 'instantclient_*' | sort | head -n 1)"
  if [[ -z "$extracted_dir" ]]; then
    echo "Oracle Instant Client extraction failed: no instantclient_* directory found."
    exit 1
  fi

  sudo ln -sfn "$extracted_dir" "$ORACLE_LINK_DIR"
  printf '%s\n' "$ORACLE_LINK_DIR" | sudo tee /etc/ld.so.conf.d/oracle-instantclient.conf >/dev/null
  sudo ldconfig

  if [[ -n "$temp_dir" ]]; then
    rm -rf "$temp_dir"
  fi
}

validate_oracle_python() {
  python - <<'PY'
import os
import oracledb

lib_dir = os.environ.get("ORACLE_HOME", "/opt/oracle/instantclient")
oracledb.init_oracle_client(lib_dir=lib_dir)
print(f"python-oracledb thick mode initialized using {lib_dir}")
PY
}

mapfile -t apt_packages < <(read_list_file "$APT_FILE")
mapfile -t pip_tools < <(read_list_file "$PIP_FILE")

install_apt_packages "${apt_packages[@]}"
install_oracle_instant_client
install_pip_tools "${pip_tools[@]}"
validate_oracle_python

echo "post-create setup complete"
