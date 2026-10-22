"""Offline runner tests using disposable Git repositories, never COSMIC builds."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import prepare


class PrepareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cosmic-runner-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.bundle = self.root / "bundle"
        self.sources = self.root / "sources"
        self.workspace = self.root / "prepared"
        self.bundle.mkdir()
        self.sources.mkdir()
        self.projects = []
        for name, repository in prepare.REPOSITORIES.items():
            source = self.sources / name
            source.mkdir()
            self.git(source, "init", "-q")
            (source / "example.txt").write_text("base\n", encoding="utf-8")
            self.git(source, "add", "example.txt")
            self.git(source, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "base")
            target = self.git(source, "rev-parse", "HEAD")
            (source / "example.txt").write_text("patched\n", encoding="utf-8")
            self.git(source, "add", "example.txt")
            tree = self.git(source, "write-tree")
            patch = self.bundle / f"{name}.patch"
            self.git(source, "diff", "--cached", "--binary", "HEAD", "--output=" + str(patch))
            self.projects.append({
                "name": name, "repository": repository, "target_commit": target,
                "result_tree": tree, "patch": patch.name,
                "sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
            })
        self.write_manifest()

    def git(self, repo: Path, *arguments: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(repo), *arguments], stderr=subprocess.STDOUT, text=True,
        ).strip()

    def write_manifest(self) -> None:
        (self.bundle / "manifest.json").write_text(json.dumps({
            "schema_version": 1, "projects": self.projects,
        }), encoding="utf-8")

    def prepare_workspace(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            prepare.prepare(self.bundle, self.workspace, prepare.load_bundle(self.bundle), self.sources)

    def test_offline_preparation_reproduces_both_trees(self) -> None:
        self.prepare_workspace()
        for project in self.projects:
            prepare.check_tree(self.workspace, project)
            self.assertEqual((self.workspace / project["name"] / "example.txt").read_text(), "patched\n")
            self.assertEqual(self.git(self.sources / project["name"], "rev-parse", "HEAD"), project["target_commit"])
        summary = json.loads((self.workspace / "run-summary.json").read_text())
        self.assertEqual(summary["status"], "prepared")
        with self.assertRaises(FileExistsError):
            self.prepare_workspace()

    def test_checksum_and_manifest_rejections(self) -> None:
        (self.bundle / "compositor.patch").write_text("tampered\n")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            prepare.load_bundle(self.bundle)
        self.projects[0]["patch"] = "../outside.patch"
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "simple filename"):
            prepare.load_bundle(self.bundle)

    def test_prepare_failure_is_recorded_without_deleting_files(self) -> None:
        self.projects[0]["result_tree"] = "0" * 40
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            prepare.prepare(self.bundle, self.workspace, self.projects, self.sources)
        summary = json.loads((self.workspace / "run-summary.json").read_text())
        self.assertEqual(summary["status"], "failed")
        self.assertTrue((self.workspace / "compositor" / "example.txt").exists())

    def test_build_refuses_unstaged_or_untracked_source(self) -> None:
        self.prepare_workspace()
        source = self.workspace / "portal" / "example.txt"
        source.write_text("unexpected edit\n")
        with mock.patch.object(prepare, "run") as commands:
            with self.assertRaisesRegex(ValueError, "Unstaged"):
                prepare.build(self.workspace, self.projects)
            commands.assert_not_called()
        source.write_bytes(b"patched\n")
        (source.parent / "unexpected.txt").write_text("unexpected\n")
        with mock.patch.object(prepare, "run") as commands:
            with self.assertRaisesRegex(ValueError, "untracked"):
                prepare.build(self.workspace, self.projects)
            commands.assert_not_called()

    def test_explicit_build_runs_all_checks_and_records_failure(self) -> None:
        self.prepare_workspace()
        with mock.patch.object(prepare, "run") as commands:
            prepare.build(self.workspace, self.projects)
            self.assertEqual(commands.call_count, 8)
            self.assertEqual(commands.call_args_list[0].args[0], ["cargo", "fmt", "--all", "--", "--check"])
        with mock.patch.object(prepare, "run", side_effect=ValueError("fixture failure")):
            with self.assertRaisesRegex(ValueError, "fixture failure"):
                prepare.build(self.workspace, self.projects)
        summary = json.loads((self.workspace / "run-summary.json").read_text())
        self.assertEqual(summary["status"], "build-failed")


if __name__ == "__main__":
    unittest.main()