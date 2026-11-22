# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""sync.py: a write brings a repository to the kit, and the check catches drift."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import kit_fixtures as fx
from kit_fixtures import check_quality as cq
from kit_fixtures import sync


def problems(root: Path) -> list[str]:
    report = cq.run(root, kit=cq.DirKit(fx.CENTRAL))
    return [f"{p.where}: [{p.rule}] {p.message}" for p in report.problems]


class WriteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fx.consumer(Path(self._tmp.name) / "repo")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def sync(self, test_dir: str | None = None) -> list[str]:
        return sync.write(self.root, commit=fx.FAKE_COMMIT, test_dir=test_dir)

    def test_a_synced_repository_keeps_every_rule(self) -> None:
        self.sync()
        self.assertEqual(problems(self.root), [])

    def test_the_record_names_the_commit_profiles_and_digests(self) -> None:
        self.sync()
        record = json.loads((self.root / cq.SOURCE_JSON).read_text(encoding="utf-8"))
        self.assertEqual(record["commit"], fx.FAKE_COMMIT)
        self.assertEqual(record["profiles"], ["base", "python", "actions"])
        paths = {f["path"] for f in record["files"]}
        self.assertIn(".github/quality/check_quality.py", paths)
        self.assertIn(".github/quality/spdx_headers.py", paths)
        self.assertIn(".gitleaks-mac.toml", paths)
        for entry in record["files"]:
            data = (self.root / entry["path"]).read_bytes()
            self.assertEqual(cq.sha256(data), entry["sha256"], entry["path"])
        self.assertEqual(
            {b["id"] for b in record["blocks"]},
            {"pre-commit-base", "pre-commit-python", "pre-commit-actions", "mypy", "typos"},
        )

    def test_a_second_write_changes_nothing(self) -> None:
        self.sync()
        before = {
            p: p.read_bytes() for p in self.root.rglob("*") if p.is_file() and ".git" not in p.parts
        }
        self.sync()
        after = {
            p: p.read_bytes() for p in self.root.rglob("*") if p.is_file() and ".git" not in p.parts
        }
        self.assertEqual(before, after)

    def test_every_kit_workflow_call_names_the_recorded_commit(self) -> None:
        self.sync()
        text = (self.root / ".github/workflows/check.yml").read_text(encoding="utf-8")
        self.assertNotIn("0" * 40, text)
        self.assertIn(f"reusable-lint.yml@{fx.FAKE_COMMIT} # quality-v", text)

    def test_an_edited_copy_is_caught(self) -> None:
        self.sync()
        path = self.root / ".github/quality/ruff.toml"
        path.write_text(path.read_text(encoding="utf-8") + 'ignore = ["E501"]\n', encoding="utf-8")
        found = problems(self.root)
        self.assertTrue(any("[copies]" in p and "ruff.toml" in p for p in found), found)

    def test_an_edited_block_is_caught(self) -> None:
        self.sync()
        path = self.root / "pyproject.toml"
        text = path.read_text(encoding="utf-8").replace(
            "strict = true", "strict = true\nwarn_unreachable = true"
        )
        path.write_text(text, encoding="utf-8")
        found = problems(self.root)
        self.assertTrue(any("[blocks]" in p and "block mypy" in p for p in found), found)

    def test_a_removed_hook_block_is_caught(self) -> None:
        self.sync()
        path = self.root / ".pre-commit-config.yaml"
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        kept = []
        inside = False
        for line in lines:
            if "# >>> kleidos-quality pre-commit-actions" in line:
                inside = True
            if not inside:
                kept.append(line)
            if "# <<< kleidos-quality pre-commit-actions" in line:
                inside = False
        path.write_text("".join(kept), encoding="utf-8")
        found = problems(self.root)
        self.assertTrue(any("block pre-commit-actions is missing" in p for p in found), found)

    def test_a_call_at_another_commit_is_caught(self) -> None:
        self.sync()
        path = self.root / ".github/workflows/check.yml"
        other = "f" * 40
        path.write_text(
            path.read_text(encoding="utf-8").replace(fx.FAKE_COMMIT, other), encoding="utf-8"
        )
        found = problems(self.root)
        self.assertTrue(any("not the recorded kit commit" in p for p in found), found)

    def test_a_local_key_the_block_sets_moves_into_the_block(self) -> None:
        path = self.root / "pyproject.toml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "[tool.mypy]\n", "[tool.mypy]\nstrict = false\n"
            ),
            encoding="utf-8",
        )
        log = self.sync()
        self.assertTrue(any("strict = false" in line for line in log), log)
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("strict = false", text)
        self.assertEqual(problems(self.root), [])

    def test_the_agents_commit_check_copies_are_replaced_and_own_ones_kept(self) -> None:
        fx.write(
            self.root,
            ".github/workflows/commit-check.yml",
            "# Vendored from kleidos-dev/agents\nname: x\n",
        )
        own = "# mine\nname: Commit check comment\n"
        fx.write(self.root, ".github/workflows/commit-check-comment.yml", own)
        self.sync()
        replaced = (self.root / ".github/workflows/commit-check.yml").read_text(encoding="utf-8")
        self.assertIn("reusable-commit-check.yml@" + fx.FAKE_COMMIT, replaced)
        kept = (self.root / ".github/workflows/commit-check-comment.yml").read_text(
            encoding="utf-8"
        )
        self.assertEqual(kept, own)

    def test_a_seeded_file_carries_the_year_it_is_written(self) -> None:
        self.sync()
        year = str(dt.datetime.now(tz=dt.UTC).year)
        text = (self.root / cq.WAIVERS).read_text(encoding="utf-8")
        self.assertIn(f"{fx.COPYRIGHT} {year} {fx.HOLDER}", text)

    def test_the_drift_test_copy_passes_in_the_repository(self) -> None:
        self.sync(test_dir="tests")
        test = self.root / "tests" / "test_quality_kit.py"
        self.assertTrue(test.is_file())
        fx.commit(self.root)
        done = subprocess.run(
            [sys.executable, "-m", "unittest", "-q", "tests.test_quality_kit"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_the_drift_test_copy_fails_on_an_edited_copy(self) -> None:
        self.sync(test_dir="tests")
        md = self.root / ".github/quality/md_nowrap.py"
        md.write_text(md.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
        done = subprocess.run(
            [sys.executable, "-m", "unittest", "-q", "tests.test_quality_kit"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("md_nowrap.py", done.stdout + done.stderr)

    def test_a_shell_script_adds_the_shell_profile(self) -> None:
        fx.write(self.root, "tools/run.sh", "#!/bin/sh\n" + fx.header() + "echo hi\n")
        self.sync()
        record = json.loads((self.root / cq.SOURCE_JSON).read_text(encoding="utf-8"))
        self.assertIn("shell", record["profiles"])
        self.assertTrue((self.root / ".shellcheckrc").is_file())


class PlaceBlockTest(unittest.TestCase):
    def test_a_table_is_created_when_the_file_has_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".typos.toml"
            path.write_text("[files]\nextend-exclude = []\n", encoding="utf-8")
            entry = {
                "id": "typos",
                "source": "quality/typos/block.toml",
                "table": "default",
                "kind": "toml",
            }
            sync.place_block(path, entry, 'locale = "en-us"\n')
            text = path.read_text(encoding="utf-8")
            self.assertIn("[default]\n# >>> kleidos-quality typos", text)
            found = cq.find_block(text, "typos")
            assert found is not None
            self.assertEqual(found[2], 'locale = "en-us"\n')

    def test_a_pre_commit_block_goes_after_repos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".pre-commit-config.yaml"
            path.write_text("repos:\n  - repo: local\n    hooks: []\n", encoding="utf-8")
            entry = {
                "id": "pre-commit-base",
                "source": ".pre-commit-config.yaml",
                "kind": "pre-commit",
            }
            sync.place_block(path, entry, "  - repo: local\n    hooks: []\n")
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "repos:")
            self.assertTrue(lines[1].startswith("  # >>> kleidos-quality pre-commit-base"))

    def test_a_repos_key_with_a_comment_is_kept_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".pre-commit-config.yaml"
            path.write_text(
                "repos: # local hooks\n  - repo: local\n    hooks: []\n", encoding="utf-8"
            )
            entry = {
                "id": "pre-commit-base",
                "source": ".pre-commit-config.yaml",
                "kind": "pre-commit",
            }
            sync.place_block(path, entry, "  - repo: local\n    hooks: []\n")
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("repos:"), 1, text)


class CentralTest(unittest.TestCase):
    def test_the_kit_home_is_in_sync_with_itself(self) -> None:
        self.assertEqual(sync.check([fx.CENTRAL]), 0)

    def test_every_manifest_source_exists(self) -> None:
        manifest = cq.DirKit(fx.CENTRAL).manifest()
        for kind in ("copy", "block", "seed"):
            for entry in manifest.get(kind, []):
                self.assertTrue((fx.CENTRAL / entry["source"]).is_file(), entry["source"])
                self.assertIn(entry["profile"], cq.KNOWN_PROFILES, entry)


if __name__ == "__main__":
    unittest.main()
