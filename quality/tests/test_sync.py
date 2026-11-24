# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""sync.py: a write brings a repository to the kit, and the check catches drift."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
            {
                "pre-commit-base",
                "pre-commit-python",
                "pre-commit-actions",
                "mypy",
                "typos",
                "organization-rules",
            },
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
        self.assertIn(
            f"reusable-lint.yml@{fx.FAKE_COMMIT} # v{cq.DirKit(fx.CENTRAL).version()}", text
        )

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

    def test_the_commit_check_manifest_drops_the_replaced_workflows(self) -> None:
        for rel in (
            ".github/workflows/commit-check.yml",
            ".github/workflows/commit-check-comment.yml",
        ):
            fx.write(self.root, rel, "# Vendored from kleidos-dev/agents\nname: x\n")
        fx.write(self.root, ".github/commit-check/check_commit_msg.py", "# x\n")
        manifest = {
            "files": [
                {"path": ".github/commit-check/check_commit_msg.py", "sha256": "a"},
                {"path": ".github/workflows/commit-check.yml", "sha256": "b"},
                {"path": ".github/workflows/commit-check-comment.yml", "sha256": "c"},
            ]
        }
        fx.write(self.root, cq.COMMIT_CHECK_SOURCE, json.dumps(manifest))
        log = self.sync()
        left = json.loads((self.root / cq.COMMIT_CHECK_SOURCE).read_text(encoding="utf-8"))
        self.assertEqual(
            [e["path"] for e in left["files"]], [".github/commit-check/check_commit_msg.py"]
        )
        self.assertTrue(any("test_commit_check_copy.py" in line for line in log), log)

    def test_a_copy_the_kit_no_longer_makes_is_removed(self) -> None:
        self.sync()
        path = self.root / cq.SOURCE_JSON
        record = json.loads(path.read_text(encoding="utf-8"))
        record["files"].append(
            {
                "path": ".github/quality/requirements-tools.txt",
                "source_path": "quality/requirements-tools.txt",
                "sha256": "0",
            }
        )
        path.write_text(json.dumps(record), encoding="utf-8")
        fx.write(self.root, ".github/quality/requirements-tools.txt", "# old\n")
        log = self.sync()
        self.assertFalse((self.root / ".github/quality/requirements-tools.txt").exists())
        self.assertTrue(any("no longer copies" in line for line in log), log)
        self.assertEqual(problems(self.root), [])

    def test_a_retired_copy_never_reaches_outside_the_kit_targets(self) -> None:
        self.sync()
        outside = self.root.parent / "victim.txt"
        outside.write_text("keep\n", encoding="utf-8")
        own = fx.write(self.root, "pkg/data.txt", "keep\n")
        path = self.root / cq.SOURCE_JSON
        record = json.loads(path.read_text(encoding="utf-8"))
        for rel in (".github/quality/../../victim.txt", "pkg/data.txt"):
            record["files"].append({"path": rel, "source_path": "x", "sha256": "0"})
        path.write_text(json.dumps(record), encoding="utf-8")
        self.sync()
        self.assertTrue(outside.is_file())
        self.assertTrue(own.is_file())

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


class MarkdownBlockTest(unittest.TestCase):
    """The organization rules: a Markdown block in AGENTS.md, between HTML comments."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fx.consumer(Path(self._tmp.name) / "repo")
        self.agents = self.root / "AGENTS.md"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def sync(self) -> list[str]:
        return sync.write(self.root, commit=fx.FAKE_COMMIT)

    def block(self) -> str:
        return (fx.CENTRAL / "quality/agents/block.md").read_text(encoding="utf-8")

    def test_the_block_goes_before_other_repositories(self) -> None:
        self.sync()
        text = self.agents.read_text(encoding="utf-8")
        start = "<!-- >>> kleidos-quality organization-rules (synced from kleidos-dev/.github"
        self.assertIn("- Run the tests in `pkg/`.\n\n" + start, text)
        found = cq.find_block(text, "organization-rules")
        assert found is not None
        self.assertEqual(found[2], self.block())
        self.assertIn(
            "<!-- <<< kleidos-quality organization-rules -->\n\n## Other repositories", text
        )
        self.assertEqual(problems(self.root), [])

    def test_a_hand_written_section_is_replaced(self) -> None:
        fx.agent_files(
            self.root,
            rules="- Mine.\n\n## Organization rules\n\nAn old copy.\n\n- Old rule.\n",
        )
        log = self.sync()
        text = self.agents.read_text(encoding="utf-8")
        self.assertNotIn("Old rule", text)
        self.assertEqual(text.count("## Organization rules"), 1)
        self.assertIn("- Mine.\n\n<!-- >>> kleidos-quality organization-rules", text)
        self.assertTrue(any("replaced the hand-written section" in line for line in log), log)

    def test_a_numbered_section_is_replaced_before_a_numbered_later_one(self) -> None:
        fx.write(
            self.root,
            "AGENTS.md",
            fx.md_header()
            + "# AGENTS.md\n\n## 4. Rules\n\n- Mine.\n\n## 5. Organization rules\n\n- Old.\n\n"
            + "## 6. Other repositories\n\nNone.\n",
        )
        self.sync()
        text = self.agents.read_text(encoding="utf-8")
        self.assertNotIn("5. Organization rules", text)
        self.assertIn("-->\n\n## 6. Other repositories", text)
        self.assertIn("- Mine.\n\n<!-- >>> kleidos-quality organization-rules", text)

    def test_a_heading_in_code_or_a_comment_is_not_the_section(self) -> None:
        fx.write(
            self.root,
            "AGENTS.md",
            fx.md_header()
            + "# AGENTS.md\n\n## Example\n\n```md\n## Organization rules\n```\n\n"
            + "<!--\n## Organization rules\n-->\n\n## Rules\n\n- Keep me.\n\n"
            + "```md\n## Other repositories\n```\n",
        )
        log = self.sync()
        text = self.agents.read_text(encoding="utf-8")
        self.assertIn("- Keep me.", text)
        self.assertEqual(text.count("```md\n## Organization rules\n```"), 1)
        self.assertFalse(any("replaced the hand-written" in line for line in log), log)
        self.assertTrue(text.endswith("<!-- <<< kleidos-quality organization-rules -->\n"), text)

    def test_without_a_later_section_the_block_ends_the_file(self) -> None:
        fx.write(self.root, "AGENTS.md", fx.md_header() + "# AGENTS.md\n\nRules.\n")
        self.sync()
        text = self.agents.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("<!-- <<< kleidos-quality organization-rules -->\n"), text)
        self.assertIn("Rules.\n\n<!-- >>> kleidos-quality organization-rules", text)

    def test_a_second_write_leaves_agents_md_alone(self) -> None:
        self.sync()
        before = self.agents.read_bytes()
        self.sync()
        self.assertEqual(self.agents.read_bytes(), before)

    def test_without_agents_md_the_block_is_reported_missing(self) -> None:
        self.agents.unlink()
        log = self.sync()
        self.assertFalse(self.agents.exists())
        self.assertTrue(any("skipped block organization-rules" in line for line in log), log)
        found = problems(self.root)
        self.assertTrue(any("AGENTS.md: [blocks] missing" in p for p in found), found)

    def test_an_edited_block_is_caught(self) -> None:
        self.sync()
        text = self.agents.read_text(encoding="utf-8")
        self.agents.write_text(text.replace("never a force push", "rarely"), encoding="utf-8")
        found = problems(self.root)
        self.assertTrue(any("block organization-rules differs" in p for p in found), found)

    def test_the_synced_repository_passes_the_agent_docs_guard(self) -> None:
        self.sync()
        fx.commit(self.root)
        self.assertEqual(fx.agent_docs.check(fx.agent_docs.Repo(self.root)), [])


class PlaceBlockTest(unittest.TestCase):
    def test_a_table_is_created_when_the_file_has_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".typos.toml"
            path.write_text("[files]\nextend-exclude = []\n", encoding="utf-8")
            entry = {
                "id": "typos",
                "source": "quality/typos/block.toml",
                "target": ".typos.toml",
                "table": "default",
                "kind": "toml",
            }
            sync.place_block(Path(tmp), entry, 'locale = "en-us"\n')
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
                "target": ".pre-commit-config.yaml",
                "kind": "pre-commit",
            }
            sync.place_block(Path(tmp), entry, "  - repo: local\n    hooks: []\n")
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "repos:")
            self.assertTrue(lines[1].startswith("  # >>> kleidos-quality pre-commit-base"))

    def test_markdown_markers_are_html_comments(self) -> None:
        start, end = cq.block_markers(
            "organization-rules", "quality/agents/block.md", "", "markdown"
        )
        self.assertTrue(start.startswith("<!-- >>> kleidos-quality organization-rules ("))
        self.assertTrue(start.endswith("; do not edit) -->\n"))
        self.assertEqual(end, "<!-- <<< kleidos-quality organization-rules -->\n")
        text = f"# A\n\n{start}## B\n{end}"
        self.assertEqual(cq.find_block(text, "organization-rules"), (2, 4, "## B\n"))

    def test_a_repos_key_with_a_comment_is_kept_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".pre-commit-config.yaml"
            path.write_text(
                "repos: # local hooks\n  - repo: local\n    hooks: []\n", encoding="utf-8"
            )
            entry = {
                "id": "pre-commit-base",
                "source": ".pre-commit-config.yaml",
                "target": ".pre-commit-config.yaml",
                "kind": "pre-commit",
            }
            sync.place_block(Path(tmp), entry, "  - repo: local\n    hooks: []\n")
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("repos:"), 1, text)


class ReleaseTest(unittest.TestCase):
    """A repository records a tagged release; central's CI keeps releases honest."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        # A kit clone with this checkout's tree as one commit on main.
        self.kit = fx.init(tmp / "kit")
        for rel in sync.git("ls-files", "--cached", "--others", "--exclude-standard").splitlines():
            src = fx.CENTRAL / rel
            if src.is_file():
                dest = self.kit / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(src.read_bytes())
        fx.commit(self.kit, "Kit")
        self.head = fx.git(self.kit, "rev-parse", "HEAD").strip()
        self.version = (self.kit / "quality" / "VERSION").read_text(encoding="utf-8").strip()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def tag(self, name: str, ref: str = "HEAD", kind: str = "signed") -> None:
        """A tag as a release is made (signed), or as a hand that skipped -s makes one."""
        if kind == "lightweight":
            fx.git(self.kit, "tag", name, ref)
            return
        message = f"Quality kit {name}"
        if kind == "signed":  # the shape of a signature; GitHub's verdict is asked apart
            message += (
                "\n-----BEGIN PGP SIGNATURE-----\n\niHUEABYKAB0WIQQ=\n-----END PGP SIGNATURE-----"
            )
        fx.git(self.kit, "tag", "-a", "--cleanup=verbatim", name, ref, "-m", message)

    def test_a_kit_change_needs_a_new_version_and_main_needs_its_tag(self) -> None:
        status, lines = sync.release_check(on_main=False, cwd=self.kit)
        self.assertEqual(status, 0, lines)
        status, lines = sync.release_check(on_main=True, cwd=self.kit)
        self.assertEqual(status, 1, lines)
        self.assertIn("git tag -s", "\n".join(lines))
        self.tag(f"v{self.version}")
        fx.git(self.kit, "update-ref", "refs/remotes/origin/v3", "HEAD")
        self.assertEqual(sync.release_check(on_main=True, cwd=self.kit)[0], 0)
        # Central's own files move nothing a repository receives.
        fx.write(self.kit, "docs/note.md", "x\n")
        fx.write(self.kit, "quality/tests/extra.txt", "x\n")
        fx.commit(self.kit, "Docs")
        self.assertEqual(sync.release_check(on_main=True, cwd=self.kit)[0], 0)
        # A kit change without a version bump is refused.
        rel = "quality/ruff/ruff.toml"
        fx.write(self.kit, rel, (self.kit / rel).read_text(encoding="utf-8") + "# more\n")
        fx.commit(self.kit, "Kit change")
        status, lines = sync.release_check(on_main=False, cwd=self.kit)
        self.assertEqual(status, 1, lines)
        self.assertIn("bump quality/VERSION", "\n".join(lines))

    def test_a_change_to_the_hooks_or_an_entry_workflow_is_a_kit_change(self) -> None:
        self.tag(f"v{self.version}")
        before = sync.kit_fingerprint("HEAD", self.kit)
        for rel in ("hooks/launch.py", ".pre-commit-hooks.yaml", ".github/workflows/quick.yml"):
            with self.subTest(rel=rel):
                path = self.kit / rel
                path.write_text(path.read_text(encoding="utf-8") + "# more\n", encoding="utf-8")
                fx.commit(self.kit, "Kit change")
                after = sync.kit_fingerprint("HEAD", self.kit)
                self.assertNotEqual(before, after)
                before = after
        for rel in (".github/workflows/ci.yml", "tools/ecosystem.py"):
            with self.subTest(rel=rel):
                path = self.kit / rel
                path.write_text(path.read_text(encoding="utf-8") + "# more\n", encoding="utf-8")
                fx.commit(self.kit, "Own change")
                self.assertEqual(before, sync.kit_fingerprint("HEAD", self.kit))

    def test_the_newest_release_is_found_under_both_prefixes(self) -> None:
        for name in (
            "quality-v2.3.0",
            "v3.0.0",
            "v3.10.0",
            "v3.9.0",
            "v3",
            "vx",
            "v3.1",
            "nightly",
        ):
            self.tag(name)
        self.assertEqual(
            sync.release_tags(self.kit), ["v3.10.0", "v3.9.0", "v3.0.0", "quality-v2.3.0"]
        )

    def test_a_version_no_newer_than_an_old_release_is_refused(self) -> None:
        self.tag("quality-v99.0.0")
        status, lines = sync.release_check(on_main=False, cwd=self.kit)
        self.assertEqual(status, 1, lines)
        self.assertIn("quality-v99.0.0", lines[0])

    def test_a_version_without_its_changelog_entry_is_refused(self) -> None:
        fx.write(self.kit, "quality/VERSION", "77.0.0\n")
        fx.commit(self.kit, "Version")
        status, lines = sync.release_check(on_main=False, cwd=self.kit)
        self.assertEqual(status, 1, lines)
        self.assertIn("No changelog entry", lines[0])

    def test_the_release_line_also_moves_the_branch(self) -> None:
        _status, lines = sync.release_check(on_main=True, cwd=self.kit)
        self.assertIn("git fetch origin && git tag -s", lines[0])
        self.assertIn(
            f"git push origin v{self.version} refs/remotes/origin/main:refs/heads/v3", lines[0]
        )

    def test_a_release_whose_branch_was_not_moved_is_red_on_main(self) -> None:
        old = self.head
        self.tag(f"v{self.version}")
        for where in (None, old):
            if where is not None:
                fx.write(self.kit, "docs/note.md", "x\n")
                fx.commit(self.kit, "Docs")
                fx.git(self.kit, "update-ref", "refs/remotes/origin/v3", "HEAD")
            status, lines = sync.release_check(on_main=True, cwd=self.kit)
            self.assertEqual(status, 1, lines)
            self.assertIn("Branch not moved", lines[0])
            self.assertIn(f"git push origin v{self.version}^{{commit}}:refs/heads/v3", lines[0])
            self.assertEqual(sync.release_check(on_main=False, cwd=self.kit)[0], 0)
        fx.git(self.kit, "update-ref", "refs/remotes/origin/v3", old)
        status, lines = sync.release_check(on_main=True, cwd=self.kit)
        self.assertEqual((status, "released" in lines[0]), (0, True), lines)

    def test_a_release_tag_that_is_not_signed_is_refused(self) -> None:
        for kind, said in (
            ("lightweight", "is a lightweight tag"),
            ("annotated", "is an annotated tag with no signature"),
        ):
            for name in (f"v{self.version}", "v3.0.0", "quality-v2.3.0"):
                with self.subTest(kind=kind, name=name):
                    self.tag(name, kind=kind)
                    for on_main in (False, True):
                        status, lines = sync.release_check(on_main=on_main, cwd=self.kit)
                        self.assertEqual(status, 1, lines)
                        self.assertIn(f"{name} {said}", lines[0])
                        self.assertIn(f"git tag -s {name}", lines[0])
                    fx.git(self.kit, "tag", "-d", name)
        # A tag that is no release (a note, a nightly) need not be signed.
        self.tag("nightly", kind="lightweight")
        self.assertEqual(sync.tag_problems(self.kit), [])

    def test_a_tag_named_like_a_branch_is_refused(self) -> None:
        fx.git(self.kit, "update-ref", "refs/remotes/origin/main", "HEAD")
        fx.git(self.kit, "update-ref", "refs/remotes/origin/feature", "HEAD")
        for name in ("v3", "v4", "v12", "main", "feature"):
            with self.subTest(name=name):
                self.tag(name)
                status, lines = sync.release_check(on_main=False, cwd=self.kit)
                self.assertEqual(status, 1, lines)
                self.assertIn(f"the tag {name} hides the branch", lines[0])
                self.assertIn(f"git push origin :refs/tags/{name}", lines[0])
                fx.git(self.kit, "tag", "-d", name)
        for name in ("v3.0", "v3x", "va", "HEAD-tag"):
            with self.subTest(name=name):
                self.tag(name)
                self.assertEqual(sync.tag_problems(self.kit), [], name)
                fx.git(self.kit, "tag", "-d", name)

    def test_githubs_verdict_on_each_signature_is_asked_online(self) -> None:
        self.tag("quality-v2.3.0", kind="signed")
        self.tag(f"v{self.version}", kind="signed")
        fx.git(self.kit, "update-ref", "refs/remotes/origin/v3", "HEAD")
        objects = {
            name: fx.git(self.kit, "rev-parse", f"refs/tags/{name}").strip()
            for name in ("quality-v2.3.0", f"v{self.version}")
        }
        asked: list[str] = []
        for answer, wanted in ((True, 0), (False, 1), (None, 1)):
            with self.subTest(answer=answer):
                asked.clear()

                def verdict(sha: str, answer: bool | None = answer) -> bool | None:
                    asked.append(sha)
                    return answer

                status, lines = sync.release_check(True, cwd=self.kit, verified=verdict)
                self.assertEqual(status, wanted, lines)
                self.assertEqual(sorted(asked), sorted(objects.values()))
                if answer is False:
                    self.assertIn("GitHub does not verify", lines[0])
                if answer is None:
                    self.assertIn("could not be asked to verify", lines[0])
        self.assertEqual(sync.release_check(True, cwd=self.kit)[0], 0)  # offline: the shape only

    def test_github_is_asked_through_gh(self) -> None:
        for out, status, wanted in (
            ("true\n", 0, True),
            ("false\n", 0, False),
            ("", 1, None),
            ("true\n", 1, None),
            ("maybe\n", 0, None),
        ):
            with self.subTest(out=out, status=status):
                done = subprocess.CompletedProcess([], status, out, "")
                with mock.patch("subprocess.run", return_value=done) as run:
                    self.assertIs(sync.verified_on_github("abc123"), wanted)
                cmd = run.call_args.args[0]
                self.assertEqual(
                    cmd[:3], ["gh", "api", "repos/kleidos-dev/.github/git/tags/abc123"]
                )
                self.assertEqual(cmd[3:], ["--jq", ".verification.verified"])

    def test_the_command_line_asks_online_only_when_told(self) -> None:
        for argv, online in ((["--release-check"], False), (["--release-check", "--online"], True)):
            with self.subTest(argv=argv):
                with (
                    mock.patch.object(sync, "release_check", return_value=(0, ["ok"])) as check,
                    mock.patch("builtins.print"),
                ):
                    self.assertEqual(sync.main(argv), 0)
                verified = check.call_args.kwargs["verified"]
                self.assertIs(verified, sync.verified_on_github if online else None)

    def old_kit(self, version: str) -> str:
        """A commit whose kit is a 2.x one."""
        fx.write(self.kit, "quality/VERSION", f"{version}\n")
        fx.commit(self.kit, "Old kit")
        return fx.git(self.kit, "rev-parse", "HEAD").strip()

    def test_a_2x_repository_is_never_behind(self) -> None:
        old = self.old_kit("2.3.0")
        self.assertEqual(sync.drift_status(old, self.kit)["behind"], "false")  # no release yet
        self.tag("quality-v2.3.0", old)
        fx.write(self.kit, "quality/VERSION", "3.0.0\n")
        rel = ".github/workflows/reusable-lint.yml"
        fx.write(self.kit, rel, (self.kit / rel).read_text(encoding="utf-8") + "# more\n")
        fx.commit(self.kit, "Kit 3")
        newest = fx.git(self.kit, "rev-parse", "HEAD").strip()
        self.assertEqual(sync.drift_status(old, self.kit)["behind"], "false")  # before the tag
        self.tag("v3.0.0")
        status = sync.drift_status(old, self.kit)
        self.assertEqual(
            status, {"behind": "false", "tag": "v3.0.0", "commit": newest, "version": "3.0.0"}
        )

    def test_a_commit_the_kit_no_longer_has_is_not_behind(self) -> None:
        self.tag("v3.0.0")
        for recorded in ("f" * 40, "", "None"):
            self.assertEqual(sync.drift_status(recorded, self.kit)["behind"], "false")

    def test_copies_of_a_kit_3_would_be_behind(self) -> None:
        self.tag("v3.0.0")
        held = self.head
        self.assertEqual(sync.drift_status(held, self.kit)["behind"], "false")
        rel = "quality/ruff/ruff.toml"
        fx.write(self.kit, rel, (self.kit / rel).read_text(encoding="utf-8") + "# more\n")
        fx.commit(self.kit, "Kit change")
        self.tag("v3.1.0")
        self.assertEqual(sync.drift_status(held, self.kit)["behind"], "true")

    def test_the_drift_lines_are_what_the_2x_drift_job_reads(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(sync.main(["--drift", "f" * 40]), 0)
        self.assertIn("behind=false", out.getvalue().splitlines())
        self.assertTrue(all("=" in line for line in out.getvalue().splitlines()))


class CommandTest(unittest.TestCase):
    """The command line: kit 3 is never written into another repository by a sync."""

    def test_write_is_refused_outside_the_kit_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = fx.consumer(Path(tmp) / "repo")
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(sync.main(["--write", str(root)]), 2)
            self.assertIn("kit_switch.py", err.getvalue())
            self.assertFalse((root / cq.SOURCE_JSON).exists())
            with self.assertRaisesRegex(SystemExit, "run, not copied"):
                sync.write(root)
            self.assertFalse((root / cq.SOURCE_JSON).exists())


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
