#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APT_FILE="$ROOT_DIR/.devcontainer/apt-packages.txt"
PIP_FILE="$ROOT_DIR/.devcontainer/pip-tools.txt"
ORACLE_DROP_DIR="$ROOT_DIR/.devcontainer/oracle"
ORACLE_INSTALL_ROOT="/opt/oracle"
ORACLE_LINK_DIR="$ORACLE_INSTALL_ROOT/instantclient"
ORACLE_DOWNLOAD_BASE="${ORACLE_DOWNLOAD_BASE:-https://download.oracle.com/otn_software/linux/instantclient}"
ORACLE_PACKAGE_VERSION="${ORACLE_PACKAGE_VERSION:-}"
ORACLE_PACKAGE_ARCH="${ORACLE_PACKAGE_ARCH:-linux.x64}"
ORACLE_DOWNLOAD_SUBDIR="${ORACLE_DOWNLOAD_SUBDIR:-}"

# Keep user-installed Python script entrypoints (for example ipython, black)
# available in both interactive shells and post-create script runs.
export PATH="$HOME/.local/bin:$PATH"

ensure_python_dirs_writable() {
  local pip_cache_dir="$HOME/.cache/pip"
  local user_base_dir="$HOME/.local"

  mkdir -p "$pip_cache_dir" "$user_base_dir"

  # Podman volumes can be root-owned on first mount; repair ownership once.
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

  python -m pip install --user --upgrade pip

  for tool in "${tools[@]}"; do
    if pip_tool_installed "$tool"; then
      echo "Python package already installed: $tool"
      continue
    fi

    echo "Installing Python package: $tool"
    python -m pip install --user "$tool"
  done
}

download_oracle_archives() {
  local download_dir="$1"
  local url
  local file_name
  local downloaded_any=1
  local derived_subdir=""
  local major=""
  local minor=""
  local -a base_candidates=()
  local -a basic_candidates=()
  local -a sdk_candidates=()
  local -a sqlplus_candidates=()
  local basic_url="${ORACLE_BASIC_URL:-}"
  local sdk_url="${ORACLE_SDK_URL:-}"
  local sqlplus_url="${ORACLE_SQLPLUS_URL:-}"

  try_download_url() {
    local candidate_url="$1"
    local out_file="$2"
    if [[ -z "$candidate_url" ]]; then
      return 1
    fi
    if curl -fsSL "$candidate_url" -o "$out_file"; then
      return 0
    fi
    echo "WARNING: Download failed for $candidate_url"
    return 1
  }

  # Build candidate download bases. Oracle often serves zips from a version
  # subdirectory (for example /1927000). Try subdir first, then base path.
  if [[ -n "$ORACLE_DOWNLOAD_SUBDIR" ]]; then
    base_candidates+=("$ORACLE_DOWNLOAD_BASE/$ORACLE_DOWNLOAD_SUBDIR")
  elif [[ -n "$ORACLE_PACKAGE_VERSION" ]]; then
    major="${ORACLE_PACKAGE_VERSION%%.*}"
    minor="${ORACLE_PACKAGE_VERSION#*.}"
    minor="${minor%%.*}"
    if [[ "$major" =~ ^[0-9]+$ && "$minor" =~ ^[0-9]+$ ]]; then
      derived_subdir="$(( major * 100000 + minor * 1000 ))"
      base_candidates+=("$ORACLE_DOWNLOAD_BASE/$derived_subdir")
    fi
  fi
  base_candidates+=("$ORACLE_DOWNLOAD_BASE")

  if [[ -n "$basic_url" ]]; then
    basic_candidates+=("$basic_url")
  elif [[ -n "$ORACLE_PACKAGE_VERSION" ]]; then
    for url in "${base_candidates[@]}"; do
      basic_candidates+=("$url/instantclient-basic-${ORACLE_PACKAGE_ARCH}-${ORACLE_PACKAGE_VERSION}.zip")
    done
  fi

  if [[ -n "$sdk_url" ]]; then
    sdk_candidates+=("$sdk_url")
  elif [[ -n "$ORACLE_PACKAGE_VERSION" ]]; then
    for url in "${base_candidates[@]}"; do
      sdk_candidates+=("$url/instantclient-sdk-${ORACLE_PACKAGE_ARCH}-${ORACLE_PACKAGE_VERSION}.zip")
    done
  fi

  if [[ -n "$sqlplus_url" ]]; then
    sqlplus_candidates+=("$sqlplus_url")
  elif [[ -n "$ORACLE_PACKAGE_VERSION" ]]; then
    for url in "${base_candidates[@]}"; do
      sqlplus_candidates+=("$url/instantclient-sqlplus-${ORACLE_PACKAGE_ARCH}-${ORACLE_PACKAGE_VERSION}.zip")
    done
  fi

  echo "Oracle download settings:"
  echo "  ORACLE_DOWNLOAD_BASE=$ORACLE_DOWNLOAD_BASE"
  echo "  ORACLE_PACKAGE_VERSION=${ORACLE_PACKAGE_VERSION:-<empty>}"
  echo "  ORACLE_PACKAGE_ARCH=${ORACLE_PACKAGE_ARCH:-<empty>}"
  echo "  ORACLE_DOWNLOAD_SUBDIR=${ORACLE_DOWNLOAD_SUBDIR:-<empty>}"
  if [[ -n "$derived_subdir" ]]; then
    echo "  Derived subdir from version: $derived_subdir"
  fi
  echo "  BASIC URL candidates:   ${basic_candidates[*]:-<not set>}"
  echo "  SDK URL candidates:     ${sdk_candidates[*]:-<not set>}"
  echo "  SQLPLUS URL candidates: ${sqlplus_candidates[*]:-<not set>}"

  for url in "${basic_candidates[@]}"; do
    file_name="$(basename "${url%%\?*}")"
    echo "Downloading Oracle archive: $file_name"
    if try_download_url "$url" "$download_dir/$file_name"; then
      downloaded_any=0
      break
    fi
  done

  for url in "${sdk_candidates[@]}"; do
    file_name="$(basename "${url%%\?*}")"
    echo "Downloading Oracle archive: $file_name"
    if try_download_url "$url" "$download_dir/$file_name"; then
      downloaded_any=0
      break
    fi
  done

  for url in "${sqlplus_candidates[@]}"; do
    file_name="$(basename "${url%%\?*}")"
    echo "Downloading Oracle archive: $file_name"
    if try_download_url "$url" "$download_dir/$file_name"; then
      downloaded_any=0
      break
    fi
  done

  if [[ ${#basic_candidates[@]} -eq 0 && ${#sdk_candidates[@]} -eq 0 && ${#sqlplus_candidates[@]} -eq 0 ]]; then
    echo "No Oracle download URLs were generated."
    echo "Set ORACLE_PACKAGE_VERSION or explicit ORACLE_*_URL values."
  fi

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
    echo "WARNING: No Oracle Instant Client archives were found."
    echo "To install SQL*Plus + thick client, do one of the following:"
    echo "  1) Add zip files under $ORACLE_DROP_DIR"
    echo "  2) Set ORACLE_BASIC_URL and ORACLE_SQLPLUS_URL in devcontainer.json"
    echo "  3) Set ORACLE_PACKAGE_VERSION (plus optional ORACLE_DOWNLOAD_BASE/ORACLE_PACKAGE_ARCH)"
    echo "Then rerun: bash .devcontainer/scripts/post-create.sh"
    echo "Current ORACLE_PACKAGE_VERSION is '${ORACLE_PACKAGE_VERSION:-<empty>}'"
    return 1
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

  return 0
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

ensure_python_dirs_writable
install_apt_packages "${apt_packages[@]}"
install_pip_tools "${pip_tools[@]}"

if install_oracle_instant_client; then
  validate_oracle_python
else
  echo "Skipping thick-mode validation until Oracle Instant Client is installed."
fi

echo "post-create setup complete"
