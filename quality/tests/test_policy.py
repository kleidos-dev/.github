# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""policy.py: every policy check, and what it prints when one fails."""

from __future__ import annotations

import contextlib
import io
import subprocess
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import kit_fixtures as fx
from kit_fixtures import check_quality as cq
from kit_fixtures import policy


class PolicyTest(unittest.TestCase):
    _template: tempfile.TemporaryDirectory[str]
    root: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls._template = tempfile.TemporaryDirectory()
        cls.root = fx.called(Path(cls._template.name) / "repo")
        reuse = (cls.root / "REUSE.toml").read_text(encoding="utf-8")
        for pattern in ("**/*.json", "**/.python-version", ".python-version"):
            reuse += (
                f'\n[[annotations]]\npath = ["{pattern}"]\nprecedence = "aggregate"\n'
                f'SPDX-FileCopyrightText = "2026 {fx.HOLDER}"\nSPDX-License-Identifier = "MIT"\n'
            )
        fx.write(cls.root, "REUSE.toml", reuse)
        for rel in (".pre-commit-config.yaml", ".typos.toml"):
            text = (cls.root / rel).read_text(encoding="utf-8")
            fx.write(cls.root, rel, fx.header() + "\n" + text)
        fx.commit(cls.root, "State the licenses")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._template.cleanup()

    def run_policy(self, *argv: str) -> tuple[int, str]:
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(out):
            status = policy.main(["--repo", str(self.root), *argv])
        return status, out.getvalue()

    @contextlib.contextmanager
    def planted(self, rel: str, text: str) -> Iterator[None]:
        path = self.root / rel
        before = path.read_bytes() if path.is_file() else None
        fx.write(self.root, rel, text)
        try:
            yield
        finally:
            if before is None:
                path.unlink()
            else:
                path.write_bytes(before)

    def test_a_clean_repository_is_clean(self) -> None:
        status, said = self.run_policy()
        self.assertEqual(status, 0, said)
        self.assertIn("clean: kit, agent-docs, md-nowrap, spdx-headers (kit v3.", said)
        self.assertNotIn("the hooks here are at", said)
        self.assertEqual(self.run_policy("a-file-pre-commit-names.py")[0], 0)

    def test_each_check_finds_its_own(self) -> None:
        for rel, text, check in (
            (".github/quality/x.py", fx.header(), "kit"),
            ("GEMINI.md", fx.md_header() + "x\n", "agent-docs"),
            ("wrapped.md", fx.md_header() + "One\nline.\n", "md-nowrap"),
            ("bare.py", "x = 1\n", "spdx-headers"),
        ):
            with self.subTest(check=check), self.planted(rel, text):
                fx.git(self.root, "add", "-N", rel)
                status, said = self.run_policy("--only", check)
                fx.git(self.root, "reset", "-q", rel)
                self.assertEqual(status, 1, said)
                self.assertIn(f"\n{check}: ", "\n" + said)
                self.assertIn("problem(s) found by kit v3.", said)
                for other in policy.CHECKS.keys() - {check}:
                    self.assertNotIn(f"\n{other}: ", "\n" + said)

    def test_every_check_runs_even_after_one_fails(self) -> None:
        with self.planted("wrapped.md", "One\nline.\n"):
            status, said = self.run_policy()
        self.assertEqual(status, 1)
        self.assertIn("md-nowrap: wrapped.md:2", said)
        self.assertIn("spdx-headers: wrapped.md", said)

    def test_a_check_can_be_left_to_another_job(self) -> None:
        with self.planted("wrapped.md", fx.md_header() + "One\nline.\n"):
            status, said = self.run_policy("--without", "md-nowrap")
            self.assertEqual(status, 0, said)
            self.assertIn("clean: kit, agent-docs, spdx-headers", said)

    def test_a_failure_names_the_kit_and_the_hooks_it_found(self) -> None:
        with self.planted(".github/quality/x.py", fx.header()):
            status, said = self.run_policy("--only", "kit", "--kit-sha", "d" * 40)
        self.assertEqual(status, 1)
        self.assertIn("the hooks here are at v3.", said)
        self.assertIn(f"({'d' * 12})", said)

    def test_a_skipped_kit_hook_is_refused(self) -> None:
        for skip, count in (("own,", 0), (",kleidos-kit", 1), ("gitleaks-mac,typos", 2)):
            status, said = self.run_policy("--only", "kit", "--lint-skip", skip)
            self.assertEqual(status, int(count > 0), said)
            self.assertEqual(said.count("names the kit hook"), count, said)

    def test_the_global_exclude_counts_for_markdown(self) -> None:
        config = (self.root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        excluded = config.replace("repos:\n", "exclude: '^legal/'\nrepos:\n", 1)
        with self.planted("legal/text.md", fx.md_header() + "One\nline.\n"):
            self.assertEqual(self.run_policy("--only", "md-nowrap")[0], 1)
            with self.planted(".pre-commit-config.yaml", excluded):
                self.assertEqual(self.run_policy("--only", "md-nowrap")[0], 0)

    def test_a_file_that_is_not_utf8_is_read_all_the_same(self) -> None:
        path = self.root / "latin.md"
        path.write_bytes(b"a\xe9\nb\n")
        try:
            self.assertEqual(self.run_policy("--only", "md-nowrap")[0], 1)
        finally:
            path.unlink()

    def test_the_summary_and_the_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "summary"
            with self.planted("GEMINI.md", fx.md_header() + "x\n"):
                fx.git(self.root, "add", "-N", "GEMINI.md")
                _status, said = self.run_policy("--github", "--summary", str(summary))
                fx.git(self.root, "reset", "-q", "GEMINI.md")
            self.assertIn("::error file=GEMINI.md", said)
            self.assertIn("## Quality kit", summary.read_text(encoding="utf-8"))
        with self.planted("GEMINI.md", fx.md_header() + "x\n"):
            fx.git(self.root, "add", "-N", "GEMINI.md")
            _status, said = self.run_policy("--only", "agent-docs")
            fx.git(self.root, "reset", "-q", "GEMINI.md")
        self.assertIn("agent-docs: GEMINI.md", said)
        self.assertNotIn("::error", said)

    def test_a_warning_fails_nothing(self) -> None:
        long = (self.root / "AGENTS.md").read_text(encoding="utf-8") + "\n" + "- Rule.\n" * 3000
        with self.planted("AGENTS.md", long):
            status, said = self.run_policy("--only", "agent-docs")
        self.assertEqual(status, 0, said)
        self.assertIn("warning: AGENTS.md", said)

    def test_a_waiver_is_said(self) -> None:
        waiver = (self.root / cq.WAIVERS).read_text(encoding="utf-8") + (
            '\n[[waiver]]\ntool = "pre-commit"\nwhat = "reuse:files:x"\nreason = "why"\n'
            'decided = "d"\n'
        )
        config = (self.root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        narrowed = config.replace("      - id: reuse\n", "      - id: reuse\n        files: x\n")
        with self.planted(cq.WAIVERS, waiver), self.planted(".pre-commit-config.yaml", narrowed):
            status, said = self.run_policy("--only", "kit")
        self.assertEqual(status, 0, said)
        self.assertIn("waived: pre-commit reuse:files:x", said)

    def test_outside_a_work_tree_it_cannot_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for check in ("kit", "agent-docs"):
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(policy.main(["--repo", tmp, "--only", check]), 2)
                self.assertIn(f"policy {check}:", err.getvalue())

    def test_the_kits_own_commit_is_said_where_git_knows_it(self) -> None:
        head = fx.sync.git("rev-parse", "HEAD")
        self.assertEqual(policy.kit_line(), f"kit v{cq.DirKit(fx.CENTRAL).version()} ({head[:12]})")
        gone = subprocess.CompletedProcess([], 128, "", "")
        with mock.patch.object(subprocess, "run", return_value=gone):
            self.assertTrue(policy.kit_line().endswith("(no commit)"))


if __name__ == "__main__":
    unittest.main()
