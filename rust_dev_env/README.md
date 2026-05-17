# Rust Dev Environment for VS Code + Podman

This folder provides a Dev Container setup that works with Podman and automates:

- Rust toolchain bootstrap and updates
- One-time package install at container creation
- Dynamic package install on each container start

## Files

- `.devcontainer/devcontainer.json`: VS Code devcontainer config
- `.devcontainer/Containerfile`: base image + base system packages
- `.devcontainer/scripts/post-create.sh`: runs once after container is created
- `.devcontainer/scripts/post-start.sh`: runs each container start
- `.devcontainer/apt-packages.txt`: apt packages installed once
- `.devcontainer/cargo-tools.txt`: cargo tools installed once
- `.devcontainer/startup-apt-packages.txt`: apt packages checked each startup
- `.devcontainer/startup-cargo-tools.txt`: cargo tools checked each startup

## Podman Prereqs (Linux)

Install Podman and enable the user socket:

```bash
sudo apt-get install -y podman
systemctl --user enable --now podman.socket
```

Optional (if VS Code expects docker CLI naming):

```bash
sudo apt-get install -y podman-docker
```

Ensure this is set in your shell startup file (`~/.bashrc`, `~/.zshrc`, etc):

```bash
export DOCKER_HOST=unix:///run/user/$UID/podman/podman.sock
```

The workspace setting `.vscode/settings.json` already points Dev Containers to Podman.

You can also use the included launcher to ensure `DOCKER_HOST` is always correct:

```bash
./open-vscode-podman.sh
```

## How to Use

1. Open the `rust_dev_env` folder in VS Code.
2. Run: `Dev Containers: Reopen in Container`.
3. On first creation, `post-create.sh` runs:
   - Installs `apt-packages.txt`
   - Updates rustup stable and adds `rustfmt` + `clippy`
   - Installs `cargo-tools.txt`
4. On each start, `post-start.sh` runs:
   - Optional rust toolchain auto-update (interval based)
   - Installs any missing startup packages/tools

If Dev Containers still invokes `docker`, verify VS Code process has:

```bash
echo "$DOCKER_HOST"
```

Expected:

```bash
unix:///run/user/$UID/podman/podman.sock
```

Note: Dev Containers log messages still say `docker ...` even when it is using
Podman via `DOCKER_HOST`. Confirm by checking the log for `Host:
unix:///run/user/<uid>/podman/podman.sock` and `Server: ... Podman Engine`.

## Dynamic Startup Installs

### Option A: File-driven

Add entries to either file, then restart the container:

- `.devcontainer/startup-apt-packages.txt`
- `.devcontainer/startup-cargo-tools.txt`

### Option B: Env-driven

Set these in `devcontainer.json` under `containerEnv` (or export manually before startup):

```json
{
  "EXTRA_APT_PACKAGES": "ripgrep jq",
  "EXTRA_CARGO_TOOLS": "bacon cargo-nextest"
}
```

These are parsed each start and only missing packages/tools are installed.

## Automated Update Behavior

`post-start.sh` updates rust toolchain only when needed based on:

- `RUST_AUTO_UPDATE` (default: `1`)
- `AUTO_UPDATE_HOURS` (default: `24`)

Examples:

- Disable auto update: `RUST_AUTO_UPDATE=0`
- Update check every 6 hours: `AUTO_UPDATE_HOURS=6`

## Recommended Build/Update Workflow

- Change `Containerfile` or base dependencies: `Dev Containers: Rebuild Container`
- Change startup package files only: restart/reopen container (no rebuild needed)
- Update rust/cargo tools: edit package files and restart

This gives fast daily updates without paying rebuild cost each time.

## If You Hit Cargo Permission Errors

If you previously used older mounts under `/usr/local/cargo`, run a full rebuild so
the new user-owned mounts are applied:

- `Dev Containers: Rebuild Container`

The scripts now also self-repair ownership for `CARGO_HOME` and `RUSTUP_HOME`
when Podman creates root-owned volumes.

## If You Hit .git/index.lock Permission Errors

If you see errors like:

`Unable to create ... .git/index.lock: Permission denied`

the container likely mounted your parent repository Git root. This setup now pins
the workspace to your opened folder only by disabling Git-root auto-mount.

Apply it with:

- `Dev Containers: Rebuild Container`
