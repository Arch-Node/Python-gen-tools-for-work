#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE_DIR="$HOME/.cache/rust-dev-env"
LAST_UPDATE_FILE="$STATE_DIR/last_update_epoch"
STARTUP_APT_FILE="$ROOT_DIR/.devcontainer/startup-apt-packages.txt"
STARTUP_CARGO_FILE="$ROOT_DIR/.devcontainer/startup-cargo-tools.txt"

ensure_toolchain_dirs_writable() {
  local cargo_home="${CARGO_HOME:-$HOME/.cargo}"
  local rustup_home="${RUSTUP_HOME:-$HOME/.rustup}"

  mkdir -p "$cargo_home" "$rustup_home"

  if [[ ! -w "$cargo_home" || ! -w "$rustup_home" ]]; then
    sudo chown -R "$(id -u):$(id -g)" "$cargo_home" "$rustup_home"
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

install_apt_packages() {
  local -a packages=("$@")
  if (( ${#packages[@]} == 0 )); then
    return
  fi

  echo "Startup apt install: ${packages[*]}"
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends "${packages[@]}"
}

install_cargo_tools() {
  local -a tools=("$@")
  local tool
  if (( ${#tools[@]} == 0 )); then
    return
  fi

  for tool in "${tools[@]}"; do
    if cargo install --list | grep -q "^${tool} v"; then
      continue
    fi

    echo "Startup cargo install: $tool"
    cargo install --locked "$tool" || cargo install "$tool"
  done
}

maybe_update_toolchain() {
  if [[ "${RUST_AUTO_UPDATE:-1}" != "1" ]]; then
    return
  fi

  local update_hours
  local now_epoch
  local last_epoch=0
  update_hours="${AUTO_UPDATE_HOURS:-24}"
  now_epoch="$(date +%s)"

  mkdir -p "$STATE_DIR"
  if [[ -f "$LAST_UPDATE_FILE" ]]; then
    last_epoch="$(cat "$LAST_UPDATE_FILE" 2>/dev/null || echo 0)"
  fi

  if (( now_epoch - last_epoch < update_hours * 3600 )); then
    return
  fi

  echo "Running scheduled rustup update"
  rustup update stable
  rustup component add rustfmt clippy
  echo "$now_epoch" > "$LAST_UPDATE_FILE"
}

mapfile -t startup_apt < <(read_list_file "$STARTUP_APT_FILE")
mapfile -t startup_cargo < <(read_list_file "$STARTUP_CARGO_FILE")

mapfile -t env_apt < <(append_env_words "${EXTRA_APT_PACKAGES:-}")
mapfile -t env_cargo < <(append_env_words "${EXTRA_CARGO_TOOLS:-}")

startup_apt+=("${env_apt[@]}")
startup_cargo+=("${env_cargo[@]}")

ensure_toolchain_dirs_writable
maybe_update_toolchain
install_apt_packages "${startup_apt[@]}"
install_cargo_tools "${startup_cargo[@]}"

echo "post-start checks complete"
