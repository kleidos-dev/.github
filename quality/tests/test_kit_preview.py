# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""kit_preview.py: what a kit change would find, and a copy taken again from its source."""

from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

import kit_fixtures as fx
from kit_fixtures import check_quality as cq
from kit_fixtures import kit_preview as kp
from kit_fixtures import kit_switch, sync
from kit_fixtures import run_form as rf

TODAY = dt.date(2026, 11, 24)
KIT = cq.DirKit(fx.CENTRAL)


class PreviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def held(self) -> Path:
        root = fx.consumer(self.tmp / "held")
        reuse = (root / "REUSE.toml").read_text(encoding="utf-8")
        reuse += (
            '\n[[annotations]]\npath = ["**/*.json", ".python-version"]\nprecedence = "aggregate"\n'
            f'SPDX-FileCopyrightText = "2026 {fx.HOLDER}"\nSPDX-License-Identifier = "MIT"\n'
        )
        fx.write(root, "REUSE.toml", reuse)
        sync.write(root, commit=fx.FAKE_COMMIT)
        for rel in (".pre-commit-config.yaml", ".typos.toml"):
            fx.write(root, rel, fx.header() + (root / rel).read_text(encoding="utf-8"))
        fx.commit(root)
        return root

    def test_a_2x_repository_is_judged_in_both_forms(self) -> None:
        root = self.held()
        # What the first form's sync adds is gone before the second is judged.
        with mock.patch.object(kit_switch, "switch") as switch:
            switch.side_effect = lambda repo, *_: left.append(fx.git(repo, "status", "--porcelain"))
            left: list[str] = []
            with mock.patch.object(sync, "write") as write:
                write.side_effect = lambda repo, **_: fx.write(repo, "new/x.txt", "x\n")
                kp.examine(root, KIT)
        self.assertEqual(left, [""])
        fx.git(root, "reset", "-q", "--hard")
        self.assertEqual(kp.examine(root, KIT), kp.Found("2.x", "0", "not behind", Counter()))

    def test_a_license_line_is_met_at_the_switch(self) -> None:
        root = self.held()
        mail = "me" + "@" + "kleidos.dev"
        fx.write(root, "LICENSE", f"Copyright (c) 2026 {fx.HOLDER} <{mail}>\n")
        fx.commit(root)
        found = kp.examine(root, KIT)
        self.assertEqual((found.held, found.run), ("0", Counter({"spdx-headers": 1})))

    def test_a_document_that_names_what_the_switch_removes_is_counted(self) -> None:
        root = self.held()
        text = (root / "AGENTS.md").read_text(encoding="utf-8")
        named = "Run `.github/quality/md_nowrap.py`.\n\n## Other repositories"
        fx.write(root, "AGENTS.md", text.replace("## Other repositories", named))
        fx.commit(root)
        self.assertEqual(kp.examine(root, KIT).run, Counter({"paths": 1}))

    def test_what_only_one_form_sees_is_counted_there(self) -> None:
        root = self.held()
        fx.write(root, "GEMINI.md", fx.md_header())
        fx.write(root, "bare.py", "x = 1\n")
        fx.commit(root)
        found = kp.examine(root, KIT)
        self.assertEqual(found.held, "3")  # two header lines and mypy's coverage
        self.assertEqual(found.run, Counter({"spdx-headers": 2, "mypy": 1, "single": 1}))

    def test_a_drift_that_says_behind_is_shown(self) -> None:
        root = self.held()
        with mock.patch.object(sync, "drift_status", return_value={"behind": "true"}):
            self.assertEqual(kp.examine(root, KIT).drift, "behind")

    def test_a_switched_repository_is_judged_as_it_stands(self) -> None:
        root = fx.called(self.tmp / "called")
        before = fx.git(root, "rev-parse", "HEAD")
        found = kp.examine(root, KIT)
        self.assertEqual((found.form, found.held, found.drift), ("run", "-", "-"))
        self.assertNotIn("workflows", found.run)
        self.assertEqual(fx.git(root, "rev-parse", "HEAD"), before)
        self.assertEqual(fx.git(root, "status", "--porcelain"), "")

    def test_the_table(self) -> None:
        held = self.held()
        none = fx.init(self.tmp / "none")
        fx.write(none, "a.txt", "x\n")
        fx.commit(none)
        before = fx.git(held, "rev-parse", "HEAD")
        targets = [str(held), str(none)]
        with mock.patch.object(kp, "clone", wraps=kp.clone) as cloned:
            text, missed = kp.table(targets)
        self.assertEqual(missed, 0)
        self.assertEqual([c.args[0] for c in cloned.call_args_list], targets)
        self.assertIn(f"| {held} | 2.x | 0 | not behind | 0 |\n", text)
        self.assertIn(f"| {none} | no kit | - | - | - |\n", text)
        self.assertIn(f"## Quality kit {KIT.version()}: impact preview", text)
        self.assertEqual(fx.git(held, "status", "--porcelain"), "")
        self.assertEqual(fx.git(held, "rev-parse", "HEAD"), before)
        with mock.patch.object(kp, "clone", return_value=False):
            text, missed = kp.table(["x/y"])
        self.assertEqual(missed, 1)
        self.assertIn("| x/y | not reachable | | | |\n", text)
        counted = kp.Found("run", "-", "-", Counter(b=2, a=1))
        self.assertEqual(kp.row("x", counted), "| x | run | - | - | 3 (a 1, b 2) |")

    def test_where_a_clone_comes_from(self) -> None:
        for env, source in (
            ({}, "git@github.com:o/r.git"),
            ({"GITHUB_ACTIONS": "true"}, "https://github.com/o/r.git"),
        ):
            done: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess([], 0)
            with (
                mock.patch.dict("os.environ", env, clear=True),
                mock.patch.object(subprocess, "run", return_value=done) as run,
            ):
                self.assertTrue(kp.clone("o/r", self.tmp / "x"))
            self.assertEqual(run.call_args.args[0][-2], source)
        self.assertFalse(kp.clone(str(self.tmp), self.tmp / "y"))


class RefreshTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.source = fx.init(tmp / "boards")
        fx.git(self.source, "remote", "add", "origin", "git@github.com:kleidos-dev/boards.git")
        fx.write(self.source, "a/front.svg", "new\n")
        fx.write(self.source, "a/same.svg", "same\n")
        fx.commit(self.source)
        self.root = fx.init(tmp / "site")
        fx.write(self.root, "vendor/boards/a/front.svg", "old\n")
        fx.write(self.root, "vendor/boards/a/same.svg", "same\n")
        self.record = self.root / "vendor/boards/SOURCE.json"
        self.data = {
            "schema": rf.SCHEMA,
            "upstream": {"repo": "kleidos-dev/boards", "path": ".", "commit": "0" * 40},
            "mode": "follow",
            "max_age_days": 30,
            "taken": "2026-01-01",
            "files": {
                "a/front.svg": cq.sha256(b"old\n"),
                "a/same.svg": cq.sha256(b"same\n"),
            },
        }
        self.write()
        fx.commit(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, **more: object) -> None:
        self.record.write_text(json.dumps({**self.data, **more}), encoding="utf-8")

    def refuse(self, needle: str, named: Path | None = None) -> None:
        with self.assertRaisesRegex(kp.RefreshError, needle):
            kp.refresh(self.record, named, TODAY)

    def test_the_bytes_the_digests_the_date_and_the_note(self) -> None:
        self.assertEqual(kp.refresh(self.record, None, TODAY), ["refreshed a/front.svg"])
        fresh = json.loads(self.record.read_text(encoding="utf-8"))
        self.assertEqual(fresh["files"]["a/front.svg"], cq.sha256(b"new\n"))
        self.assertEqual(fresh["taken"], "2026-11-24")
        head = fx.git(self.source, "rev-parse", "HEAD").strip()
        self.assertEqual(fresh["upstream"]["commit"], head)
        self.assertEqual((self.root / "vendor/boards/a/front.svg").read_bytes(), b"new\n")
        self.assertEqual(kp.refresh(self.record, self.source, TODAY)[0][:15], "nothing changed")

    def test_the_default_date_is_today(self) -> None:
        kp.refresh(self.record, None)
        fresh = json.loads(self.record.read_text(encoding="utf-8"))
        self.assertEqual(fresh["taken"], dt.datetime.now(tz=dt.UTC).date().isoformat())

    def test_nothing_is_written_in_gits_folder_or_through_a_link(self) -> None:
        fx.write(self.source, ".GIT2/config", "evil\n")
        config = (self.root / ".git/config").read_bytes()
        fx.write(self.source, "evil", "evil\n")
        fx.commit(self.source, "Plant")
        for more, name in (
            ({"root": "."}, ".git/config"),
            ({"root": "."}, "sub/.Git/config"),
            ({}, "../../.git/config"),
        ):
            self.write(files={name: "0" * 64}, sources={name: "evil"}, **more)
            self.refuse("is in git's own folder")
        self.assertEqual((self.root / ".git/config").read_bytes(), config)
        outside = self.root.parent / "outside"
        outside.mkdir()
        fx.write(outside, "front.svg", "keep\n")
        folder = self.root / "vendor/boards/a"
        shutil.rmtree(folder)
        folder.symlink_to(outside)
        self.write()
        self.refuse("vendor/boards/a is a symbolic link")
        folder.unlink()
        folder.mkdir()
        (folder / "front.svg").symlink_to(outside / "front.svg")
        self.refuse("vendor/boards/a/front.svg is a symbolic link")
        self.assertEqual((outside / "front.svg").read_text(encoding="utf-8"), "keep\n")
        moved = outside / "SOURCE.json"
        self.record.rename(moved)
        self.record.symlink_to(moved)
        self.refuse("vendor/boards/SOURCE.json is a symbolic link")

    def test_nothing_is_written_that_github_or_the_hooks_run(self) -> None:
        """A record that names a workflow, an action or the hooks would write code that runs."""
        fx.write(self.source, "evil.yml", "on: push\n")
        fx.commit(self.source, "Plant")
        fx.write(self.root, ".github/workflows/ci.yml", "on: pull_request\n")
        fx.write(self.root, ".pre-commit-config.yaml", "repos: []\n")
        fx.commit(self.root, "Own workflow")
        kept = {
            rel: (self.root / rel).read_bytes()
            for rel in (".github/workflows/ci.yml", ".pre-commit-config.yaml")
        }
        for more, name in (
            ({"root": "."}, ".github/workflows/ci.yml"),
            ({"root": "."}, ".GitHub/Workflows/ci.yml"),
            ({"root": "."}, ".github/workflow\u017f/ci.yml"),  # long s: APFS reads workflows
            ({"root": "."}, ".github/work\ufb02ows/ci.yml"),  # the fl ligature
            ({"root": "."}, ".\uff47ithub/workflows/ci.yml"),  # a full-width g
            ({"root": "."}, "./.github/workflows/x/y.yaml"),
            ({"root": "."}, "a/../.github/workflows/ci.yml"),
            ({}, "../../.github/workflows/ci.yml"),
            ({"root": "."}, ".github/actions/setup/action.yml"),
            ({"root": "."}, ".github/dependabot.yml"),
            ({"root": "."}, ".pre-commit-config.yaml"),
            ({"root": "."}, ".PRE-COMMIT-CONFIG.yaml"),
        ):
            with self.subTest(name=name):
                self.write(files={name: "0" * 64}, sources={name: "evil.yml"}, **more)
                self.refuse("a refresh writes nothing GitHub or the hooks run")
                for rel, content in kept.items():
                    self.assertEqual((self.root / rel).read_bytes(), content, rel)
                self.assertEqual(fx.git(self.root, "status", "--porcelain", ".github"), "")
        moved = self.root / ".github/quality/SOURCE.json"
        moved.parent.mkdir(parents=True)
        self.record.rename(moved)
        self.record = moved
        self.write(files={"a/front.svg": cq.sha256(b"old\n")})
        self.refuse(".github/quality/SOURCE.json is under .github/")

    def test_what_is_never_written(self) -> None:
        """Every spelling a file system may fold, and any path the file system resolves there."""
        (self.root / ".github/workflows").mkdir(parents=True)
        (self.root / "alias").symlink_to(self.root / ".github/workflows")
        (self.root / "hooks.yaml").symlink_to(self.root / ".pre-commit-config.yaml")
        (self.root / ".pre-commit-config.yaml").write_text("repos: []\n", encoding="utf-8")
        for rel, never in (
            (".github", True),
            (".github/workflows", True),
            (".github/quality/ruff.toml", True),
            ("a/../.github/x.yml", True),
            (".gith\u00fab/x.yml", False),
            (".githubs/x.yml", False),
            ("docs/.github/workflows/x.yml", False),
            (".pre-commit-config.yaml", True),
            ("x/.pre-commit-config.yaml", False),
            (".pre-commit-config.yml", False),
            ("alias/ci.yml", True),  # the file system's own spelling of the workflows
            ("hooks.yaml", True),
            ("vendor/x.svg", False),
        ):
            with self.subTest(rel=rel):
                self.assertIs(kp.never_written(self.root, rel), never)

    def test_a_record_that_lacks_only_its_date_is_refreshed(self) -> None:
        self.write(taken="")
        self.assertEqual(len(kp.refresh(self.record, None, TODAY)), 1)

    def test_sources_rename(self) -> None:
        fx.write(self.source, "other.svg", "other\n")
        fx.commit(self.source)
        self.write(sources={"a/front.svg": "other.svg"})
        kp.refresh(self.record, None, TODAY)
        self.assertEqual((self.root / "vendor/boards/a/front.svg").read_bytes(), b"other\n")

    def test_what_it_refuses(self) -> None:
        for more, needle in (
            ({"mode": "frozen", "reason": "x"}, "is frozen: it is made again"),
            ({"upstream": {"repo": "o/r", "path": ".", "commit": None}}, "a generator's output"),
            ({"mode": "x"}, "mode must be"),
            ({"schema": "x"}, "is not a record of schema"),
            (
                {"upstream": {"repo": "o/none", "path": ".", "commit": "0" * 40}},
                "no checkout of o/none",
            ),
            ({"files": {"a/none.svg": "0" * 64}}, "has no a/none.svg"),
            ({"files": {"../../../x": "0" * 64}}, "has no"),
        ):
            with self.subTest(needle=needle):
                self.write(**more)
                self.refuse(needle)
        self.record.write_text("{", encoding="utf-8")
        self.refuse("cannot be read")

    def test_nothing_is_written_when_one_file_is_gone(self) -> None:
        files = {**self.data["files"], "a/none.svg": "0" * 64}  # type: ignore[dict-item]  # a table of strings
        self.write(files=files)
        before = self.record.read_bytes()
        self.refuse("has no a/none.svg")
        self.assertEqual(self.record.read_bytes(), before)
        self.assertEqual((self.root / "vendor/boards/a/front.svg").read_bytes(), b"old\n")

    def test_the_source_is_the_one_it_says(self) -> None:
        fx.git(self.source, "remote", "set-url", "origin", "git@github.com:evil/myboards.git")
        self.refuse("not of kleidos-dev/boards")
        fx.git(self.source, "remote", "set-url", "origin", "https://github.com/Kleidos-Dev/boards")
        kp.refresh(self.record, None, TODAY)

    def test_the_source_is_committed(self) -> None:
        fx.write(self.source, "a/front.svg", "newer\n")
        self.refuse("uncommitted changes")
        fx.git(self.source, "remote", "remove", "origin")
        self.refuse("git remote failed")

    def test_a_link_out_of_the_source_is_not_followed(self) -> None:
        outside = Path(self._tmp.name) / "secret"
        outside.write_text("secret\n", encoding="utf-8")
        (self.source / "a/front.svg").unlink()
        (self.source / "a/front.svg").symlink_to(outside)
        fx.commit(self.source)
        self.refuse("has no a/front.svg")

    def test_the_kits_own_record_takes_the_base_configurations(self) -> None:
        root = fx.called(Path(self._tmp.name) / "called")
        record = root / cq.SOURCE_JSON
        self.assertEqual(kp.refresh(record, None, TODAY), ["nothing changed"])
        fx.write(root, "run.sh", "#!/bin/sh\n" + fx.header())
        self.assertIn("wrote .shellcheckrc", kp.refresh(record, None, TODAY))


if __name__ == "__main__":
    unittest.main()
