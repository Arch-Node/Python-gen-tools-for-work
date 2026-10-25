"""Compare a Git feature and upstream against their shared historical base.

Requires Python 3.10+ and Git. Reads committed content only; never checks out,
merges, fetches, builds, or executes repository code.
"""

from __future__ import annotations

import argparse
import html
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


COSMIC_BASE = "651f701f84e46d0262a129cb9ac30537d648cb08"
COSMIC_UPSTREAM = "8cb1802caada438bb5cc7670dfabdaca5fad0502"
COSMIC_FEATURE = "d618128f5434fa02af65e1ac08bfb728caa56830"


@dataclass(frozen=True)
class FileChange:
    path: str
    feature_status: str
    upstream_status: str
    category: str


def git(repo: Path, *arguments: str, allowed_codes: tuple[int, ...] = (0,)) -> bytes:
    """Run Git without a shell, external diff drivers, or text conversion."""
    result = subprocess.run(
        ["git", "--no-pager", "--literal-pathspecs", "-C", str(repo), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode not in allowed_codes:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(detail or f"Git exited with status {result.returncode}")
    return result.stdout


def resolve_commit(repo: Path, revision: str) -> str:
    """Resolve a revision to an immutable commit, rejecting option injection."""
    return git(
        repo, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"
    ).decode("ascii").strip()


def changed_files(repo: Path, base: str, revision: str) -> dict[str, str]:
    """Read NUL-delimited paths; represent renames as a deletion and addition."""
    output = git(
        repo, "diff", "--no-ext-diff", "--no-textconv", "--no-renames",
        "--name-status", "-z", base, revision, "--",
    )
    fields = output.split(b"\0")
    changes: dict[str, str] = {}
    for index in range(0, len(fields) - 1, 2):
        status = fields[index].decode("ascii")
        path = fields[index + 1].decode("utf-8", errors="surrogateescape")
        changes[path] = status
    return changes


def collect_changes(
    repo: Path, base: str, upstream: str, feature: str,
) -> list[FileChange]:
    """Classify shared paths without pretending that file overlap is a conflict."""
    feature_changes = changed_files(repo, base, feature)
    upstream_changes = changed_files(repo, base, upstream)
    result: list[FileChange] = []
    for path in sorted(feature_changes.keys() | upstream_changes.keys()):
        feature_status = feature_changes.get(path, "")
        upstream_status = upstream_changes.get(path, "")
        if feature_status and upstream_status:
            difference = git(
                repo, "diff", "--no-ext-diff", "--no-textconv", "--no-renames",
                "--raw", upstream, feature, "--", path,
            )
            category = "Both changed: review" if difference else "Both changed: same result"
        elif feature_status:
            category = "Feature only"
        else:
            category = "Upstream only"
        result.append(FileChange(path, feature_status, upstream_status, category))
    priority = {
        "Both changed: review": 0, "Both changed: same result": 1,
        "Feature only": 2, "Upstream only": 3,
    }
    return sorted(result, key=lambda change: (priority[change.category], change.path))


def escaped(value: object) -> str:
    """Escape repository-controlled content before rendering it."""
    return html.escape(str(value), quote=True)


def render_patch(repo: Path, base: str, revision: str, path: str, max_lines: int) -> str:
    """Render a bounded unified patch while leaving the comparison itself exact."""
    patch = git(
        repo, "diff", "--no-ext-diff", "--no-textconv", "--no-color",
        "--no-renames", "--unified=3", base, revision, "--", path,
    ).decode("utf-8", errors="replace")
    if not patch:
        return '<p class="muted">Unchanged from base.</p>'
    lines = patch.splitlines()
    rendered: list[str] = []
    for line in lines[:max_lines]:
        kind = "add" if line.startswith("+") else "remove" if line.startswith("-") else "context"
        rendered.append(f'<span class="{kind}">{escaped(line)}</span>')
    note = (
        f'<p class="warning">Patch truncated: {len(lines) - max_lines:,} lines omitted.</p>'
        if len(lines) > max_lines else ""
    )
    return note + '<pre>' + "\n".join(rendered) + '</pre>'


def build_report(
    repo: Path, base: str, upstream: str, feature: str,
    changes: list[FileChange], max_lines: int, include_upstream_only: bool,
) -> str:
    """Build a standalone report with feature and upstream patches side by side."""
    counts = {
        category: sum(change.category == category for change in changes)
        for category in (
            "Both changed: review", "Both changed: same result", "Feature only", "Upstream only",
        )
    }
    metrics = "".join(
        f'<li><strong>{count}</strong> {escaped(category)}</li>'
        for category, count in counts.items()
    )
    revision_rows = []
    for label, revision in (("Base", base), ("Upstream", upstream), ("Feature", feature)):
        subject = git(repo, "show", "-s", "--format=%s", revision).decode("utf-8", errors="replace").strip()
        count = git(repo, "rev-list", "--count", f"{base}..{revision}").decode("ascii").strip()
        revision_rows.append(
            f'<tr><th>{label}</th><td><code>{revision}</code></td>'
            f'<td>{escaped(subject)}</td><td>{count}</td></tr>'
        )
    sections: list[str] = []
    for change in changes:
        if change.category == "Upstream only" and not include_upstream_only:
            continue
        patches = "".join(
            f'<section class="patch"><h3>Base to {label} '
            f'({escaped(status or "unchanged")})</h3>'
            f'{render_patch(repo, base, revision, change.path, max_lines)}</section>'
            for label, revision, status in (
                ("Feature", feature, change.feature_status),
                ("Upstream", upstream, change.upstream_status),
            )
        )
        sections.append(
            f'<details><summary>{escaped(change.path)}'
            f'<span>{escaped(change.category)}</span></summary>'
            f'<div class="patches">{patches}</div></details>'
        )
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Git Overlap Report</title><style>
:root {{ color-scheme: light; --ink: #24292f; --line: #c8cdd2; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; color: var(--ink); background: #f6f8fa; font: 15px "Segoe UI", sans-serif; letter-spacing: 0; }}
main {{ max-width: 1600px; margin: auto; padding: 28px; }}
h1 {{ font-size: 26px; margin-top: 0; }} h2 {{ font-size: 20px; }}
h3 {{ font-size: 15px; padding: 12px; margin: 0; border-bottom: 1px solid var(--line); }}
table {{ width: 100%; border-collapse: collapse; background: white; }}
th, td {{ border: 1px solid var(--line); padding: 10px; text-align: left; overflow-wrap: anywhere; }}
ul {{ display: flex; flex-wrap: wrap; gap: 12px 28px; padding: 0; list-style: none; }}
li strong {{ font-size: 22px; }}
details {{ margin: 12px 0; background: white; border: 1px solid var(--line); border-radius: 4px; }}
summary {{ cursor: pointer; padding: 12px; overflow-wrap: anywhere; }}
summary span {{ display: block; color: #57606a; margin: 6px 0 0 16px; }}
.patches {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); border-top: 1px solid var(--line); }}
.patch {{ min-width: 0; }} .patch + .patch {{ border-left: 1px solid var(--line); }}
pre {{ overflow: auto; margin: 0; padding: 12px; font: 12px/1.5 Consolas, monospace; tab-size: 4; }}
pre span {{ display: inline-block; min-width: 100%; }}
.add {{ background: #dafbe1; }} .remove {{ background: #ffebe9; }}
.muted {{ color: #57606a; padding: 12px; }} .warning {{ padding: 12px; background: #fff8c5; }}
@media (max-width: 800px) {{ main {{ padding: 14px; }} .patches {{ grid-template-columns: minmax(0, 1fr); }}
.patch + .patch {{ border-left: 0; border-top: 1px solid var(--line); }} }}
</style></head><body><main>
<h1>Git Overlap Report</h1><p>{escaped(repo)}</p>
<table><thead><tr><th>Role</th><th>Commit</th><th>Subject</th><th>Commits after base</th></tr></thead>
<tbody>{''.join(revision_rows)}</tbody></table>
<h2>Changed Files</h2><ul>{metrics}</ul>
<p>File overlap is a review candidate, not proof of a merge conflict. Different files can still interact.
This report does not establish security or runtime correctness.</p>
<p>Committed content only. Renames appear as deletion/addition pairs. Binary files show Git's binary-change notice.
Status: A added, M modified, D deleted, T type changed.
Upstream-only details: {"included" if include_upstream_only else "omitted"}.</p>
{''.join(sections) or '<p>No changes to display.</p>'}
</main></body></html>'''


def positive_int(value: str) -> int:
    """Validate the patch rendering limit."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse generic revisions, with an explicit pinned COSMIC preset."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path, help="Existing local Git repository containing all three commits")
    parser.add_argument("--base", help="Shared historical base commit")
    parser.add_argument("--upstream", help="Upstream target commit")
    parser.add_argument("--feature", help="Feature commit or fetched PR ref")
    parser.add_argument("--cosmic", action="store_true", help="Use pinned COSMIC PR #2853 revisions for unspecified roles")
    parser.add_argument("-o", "--output", type=Path, default=Path("git_overlap_report.html"))
    parser.add_argument("--max-patch-lines", type=positive_int, default=2000)
    parser.add_argument("--include-upstream-only", action="store_true")
    args = parser.parse_args(argv)
    for role, preset in (("base", COSMIC_BASE), ("upstream", COSMIC_UPSTREAM), ("feature", COSMIC_FEATURE)):
        if getattr(args, role) is None:
            if not args.cosmic:
                parser.error(f"--{role} is required unless --cosmic is supplied")
            setattr(args, role, preset)
    return args


def main(argv: list[str] | None = None) -> int:
    """Validate ancestry and write a report without changing repository state."""
    args = parse_args(argv)
    try:
        repo = args.repo.expanduser().resolve()
        base, upstream, feature = (
            resolve_commit(repo, revision)
            for revision in (args.base, args.upstream, args.feature)
        )
        for label, revision in (("upstream", upstream), ("feature", feature)):
            try:
                git(repo, "merge-base", "--is-ancestor", base, revision)
            except ValueError as error:
                raise ValueError(f"Base must be an ancestor of {label}: {error}") from error
        changes = collect_changes(repo, base, upstream, feature)
        report = build_report(
            repo, base, upstream, feature, changes,
            args.max_patch_lines, args.include_upstream_only,
        )
        output = args.output.expanduser().resolve()
        output.write_text(report, encoding="utf-8", errors="replace")
        print(f"Wrote {output}")
        print(f"Feature files: {sum(bool(change.feature_status) for change in changes)}")
        print(f"Overlapping files: {sum(bool(change.feature_status and change.upstream_status) for change in changes)}")
        return 0
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())