"""Verify, prepare, or build the paired COSMIC source patches. Never installs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


REPOSITORIES = {
    "compositor": "https://github.com/pop-os/cosmic-comp.git",
    "portal": "https://github.com/pop-os/xdg-desktop-portal-cosmic.git",
}
BUILD_STEPS = (
    ("format", ["cargo", "fmt", "--all", "--", "--check"]),
    ("clippy", ["cargo", "clippy", "--release", "--all-targets", "--", "-D", "warnings"]),
    ("test", ["cargo", "test", "--release"]),
    ("build", ["cargo", "build", "--release"]),
)


def load_bundle(bundle: Path) -> list[dict]:
    """Check the manifest and both patch hashes before changing any source."""
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported bundle manifest version")
    projects = manifest.get("projects")
    if not isinstance(projects, list) or len(projects) != len(REPOSITORIES):
        raise ValueError("Bundle must contain the compositor and portal projects")
    seen: set[str] = set()
    for project in projects:
        name = project["name"]
        if name not in REPOSITORIES or name in seen:
            raise ValueError("Unexpected or duplicate project")
        seen.add(name)
        if project["repository"] != REPOSITORIES[name]:
            raise ValueError(f"Unexpected repository for {name}")
        for field in ("target_commit", "result_tree"):
            if not re.fullmatch(r"[0-9a-f]{40}", project[field]):
                raise ValueError(f"Invalid {field} for {name}")
        filename = project["patch"]
        if not re.fullmatch(r"[a-z0-9-]+\.patch", filename):
            raise ValueError("Patch must be a simple filename inside the bundle")
        patch = bundle / filename
        if patch.is_symlink() or patch.resolve().parent != bundle:
            raise ValueError("Patch must not point outside the bundle")
        digest = hashlib.sha256(patch.read_bytes()).hexdigest()
        if digest != project["sha256"]:
            raise ValueError(f"Patch checksum mismatch: {filename}")
    return projects


def git_command(workspace: Path, repo: Path | None, *arguments: str) -> list[str]:
    """Disable hooks and line-ending conversion in our isolated source trees."""
    command = [
        "git", "--no-pager", "-c", f"core.hooksPath={workspace / 'disabled-hooks'}",
        "-c", "core.fsmonitor=false", "-c", "core.autocrlf=false",
    ]
    if repo is not None:
        command.extend(["-C", str(repo)])
    return [*command, *arguments]


def run(command: list[str], log: Path, cwd: Path | None = None) -> str:
    """Keep full command output in a log and show a short failure excerpt."""
    print(f"Running: {subprocess.list2cmdline(command)}", flush=True)
    environment = os.environ.copy()
    for key in list(environment):
        if key.startswith("GIT_"):
            del environment[key]
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["CARGO_TERM_COLOR"] = "never"
    with log.open("a", encoding="utf-8") as output:
        output.write(f"\n$ {subprocess.list2cmdline(command)}\n")
        output.flush()
        result = subprocess.run(
            command, cwd=cwd, env=environment, stdout=output,
            stderr=subprocess.STDOUT, check=False,
        )
    if result.returncode:
        with log.open(encoding="utf-8", errors="replace") as output:
            excerpt = "".join(deque(output, maxlen=25))
        raise ValueError(f"Command failed ({result.returncode}); see {log}\n{excerpt}")
    return ""


def git_value(workspace: Path, repo: Path, *arguments: str) -> str:
    """Read a small Git result using the same isolated settings as preparation."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.check_output(
        git_command(workspace, repo, *arguments), env=environment,
        stderr=subprocess.STDOUT, text=True, errors="replace",
    ).strip()


def check_tree(workspace: Path, project: dict) -> None:
    """Reject source changes before any explicitly requested Cargo execution."""
    repo = workspace / project["name"]
    if Path(git_value(workspace, repo, "rev-parse", "--show-toplevel")).resolve() != repo.resolve():
        raise ValueError(f"Unexpected repository root: {repo}")
    if git_value(workspace, repo, "rev-parse", "HEAD") != project["target_commit"]:
        raise ValueError(f"Wrong target commit: {repo}")
    if git_value(workspace, repo, "write-tree") != project["result_tree"]:
        raise ValueError(f"Staged source does not match the bundle: {repo}")
    if git_value(workspace, repo, "diff", "--no-ext-diff", "--no-textconv", "--name-only"):
        raise ValueError(f"Unstaged source changes: {repo}")
    if git_value(workspace, repo, "ls-files", "--others", "--exclude-standard"):
        raise ValueError(f"Unexpected untracked files: {repo}")


def save_summary(workspace: Path, summary: dict) -> None:
    summary["updated_utc"] = datetime.now(timezone.utc).isoformat()
    (workspace / "run-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8",
    )


def prepare(bundle: Path, workspace: Path, projects: list[dict], source_root: Path | None) -> None:
    """Clone committed history into new directories and apply the exact patches."""
    workspace.mkdir(parents=True, exist_ok=False)
    (workspace / "disabled-hooks").mkdir()
    (workspace / "logs").mkdir()
    summary = {"schema_version": 1, "phase": "prepare", "status": "running", "projects": {}}
    save_summary(workspace, summary)
    try:
        for project in projects:
            name = project["name"]
            repo = workspace / name
            log = workspace / "logs" / f"{name}-prepare.log"
            summary["projects"][name] = {"status": "running", "log": str(log)}
            save_summary(workspace, summary)
            source = str(source_root / name) if source_root else project["repository"]
            run(git_command(workspace, None, "clone", "--no-checkout", "--no-hardlinks", "--", source, str(repo)), log)
            run(git_command(workspace, repo, "checkout", "--detach", project["target_commit"]), log)
            patch = str(bundle / project["patch"])
            run(git_command(workspace, repo, "apply", "--check", "--index", "--whitespace=error", patch), log)
            run(git_command(workspace, repo, "apply", "--index", "--whitespace=error", patch), log)
            run(git_command(workspace, repo, "diff", "--cached", "--check"), log)
            check_tree(workspace, project)
            summary["projects"][name].update({
                "status": "prepared", "target_commit": project["target_commit"],
                "result_tree": project["result_tree"], "patch_sha256": project["sha256"],
            })
            save_summary(workspace, summary)
        summary["status"] = "prepared"
    except Exception as error:
        summary.update(status="failed", error=str(error))
        raise
    finally:
        save_summary(workspace, summary)


def build(workspace: Path, projects: list[dict]) -> None:
    """Run development checks only; never copy binaries into system paths."""
    summary = json.loads((workspace / "run-summary.json").read_text(encoding="utf-8"))
    if summary.get("schema_version") != 1 or summary.get("status") not in {"prepared", "built", "build-failed"}:
        raise ValueError("Workspace was not successfully prepared by this script")
    for project in projects:
        check_tree(workspace, project)
    summary.update(phase="build", status="running")
    save_summary(workspace, summary)
    try:
        for project in projects:
            name = project["name"]
            steps = summary["projects"][name]["build_steps"] = {}
            for label, command in BUILD_STEPS:
                log = workspace / "logs" / f"{name}-{label}.log"
                steps[label] = {"status": "running", "log": str(log)}
                save_summary(workspace, summary)
                run(command, log, cwd=workspace / name)
                steps[label]["status"] = "passed"
                save_summary(workspace, summary)
        summary["status"] = "built"
    except Exception as error:
        summary.update(status="build-failed", error=str(error))
        raise
    finally:
        save_summary(workspace, summary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("verify", "prepare", "build"))
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--workspace", type=Path, help="New source workspace for prepare; prepared workspace for build")
    parser.add_argument("--source-root", type=Path, help="Offline source clones named compositor and portal; prepare only")
    args = parser.parse_args(argv)
    if args.action != "verify" and args.workspace is None:
        parser.error("--workspace is required for prepare and build")
    if args.source_root is not None and args.action != "prepare":
        parser.error("--source-root is only valid for prepare")
    try:
        bundle = args.bundle.expanduser().resolve()
        projects = load_bundle(bundle)
        print("Both patch checksums and manifest fields verified.", flush=True)
        if args.action == "verify":
            return 0
        workspace = args.workspace.expanduser().resolve()
        if args.action == "prepare":
            source_root = args.source_root.expanduser().resolve() if args.source_root else None
            prepare(bundle, workspace, projects, source_root)
        else:
            build(workspace, projects)
        print(f"Completed {args.action}; summary: {workspace / 'run-summary.json'}")
        print("No software was installed. Runtime and package compatibility remain unverified.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())