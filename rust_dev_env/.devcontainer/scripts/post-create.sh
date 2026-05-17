#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APT_FILE="$ROOT_DIR/.devcontainer/apt-packages.txt"
CARGO_FILE="$ROOT_DIR/.devcontainer/cargo-tools.txt"

ensure_toolchain_dirs_writable() {
  local cargo_home="${CARGO_HOME:-$HOME/.cargo}"
  local rustup_home="${RUSTUP_HOME:-$HOME/.rustup}"

  mkdir -p "$cargo_home" "$rustup_home"

  # Podman volumes can be root-owned on first mount; repair ownership once.
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

install_apt_packages() {
  local -a packages=("$@")
  if (( ${#packages[@]} == 0 )); then
    return
  fi

  echo "Installing apt packages: ${packages[*]}"
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
      echo "Cargo tool already installed: $tool"
      continue
    fi

    echo "Installing cargo tool: $tool"
    cargo install --locked "$tool" || cargo install "$tool"
  done
}

mapfile -t apt_packages < <(read_list_file "$APT_FILE")
mapfile -t cargo_tools < <(read_list_file "$CARGO_FILE")

install_apt_packages "${apt_packages[@]}"
ensure_toolchain_dirs_writable

rustup update stable
rustup default stable
rustup component add rustfmt clippy

install_cargo_tools "${cargo_tools[@]}"

echo "post-create setup complete"
