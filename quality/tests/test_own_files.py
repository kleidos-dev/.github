# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""own_files.py: what a tool writes into a repository stays there."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

import kit_fixtures as fx
from kit_fixtures import own_files


class WriteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_it_says_whether_it_changed_the_file(self) -> None:
        self.assertIs(own_files.write(self.root, "a/b.txt", "é\n"), True)
        self.assertEqual((self.root / "a/b.txt").read_bytes(), "é\n".encode())
        self.assertIs(own_files.write(self.root, "a/b.txt", "é\n".encode()), False)
        self.assertTrue(own_files.write(self.root, "a/b.txt", b"\r\n"))
        self.assertEqual((self.root / "a/b.txt").read_bytes(), b"\r\n")

    def test_what_leads_elsewhere_is_refused(self) -> None:
        outside = self.root.parent / "outside"
        outside.mkdir()
        (self.root / "link").symlink_to(outside)
        (self.root / "file").symlink_to(outside / "x")
        (self.root / ".git").mkdir(exist_ok=True)
        (self.root / "gitlink").symlink_to(self.root / ".git")
        for rel, why in (
            (".git/config", "is in git's own folder"),
            (".\uff27it/config", "is in git's own folder"),  # a full-width G
            ("gitlink/config", "is in git's own folder"),  # the file system's own spelling
            ("sub/.GIT/hooks/x", "is in git's own folder"),
            (".git", "is in git's own folder"),
            ("link/x", "link is a symbolic link"),
            ("link/new/x", "link is a symbolic link"),
            ("file", "file is a symbolic link"),
            ("../outside/x", "is not in the repository"),
            ("a/../../outside/x", "is not in the repository"),
            (str(outside / "x"), "is not in the repository"),
            ("", "is not in the repository"),
            (".", "is not in the repository"),
        ):
            with self.subTest(rel=rel), self.assertRaisesRegex(own_files.RefusedError, why):
                own_files.write(self.root, rel, "evil")
        self.assertEqual(list(outside.iterdir()), [])
        self.assertIsNone(own_files.problem(self.root, ".gitignore"))
        self.assertIsNone(own_files.problem(self.root, "a/.github/x"))
        self.assertEqual(own_files.own_file(self.root, "new/x"), self.root / "new/x")

    def test_nothing_else_of_the_tools_writes_into_a_repository(self) -> None:
        """Each other write of the kit and the tools, named with where it goes."""
        known = {
            # A report, where the caller's command line says.
            "tools/ecosystem.py": ["(args.out /"],
            # The header lines, into a file git lists, opened by the path git gave.
            "quality/spdx_headers.py": ["path."],
            # A binary in the folder the caller names, and a plant in a temporary one.
            "quality/fetch_tool.py": ["staged."],
            "quality/check_quality.py": ["(folder / name)", "args.json."],
            "quality/deny_hooks.py": ["config."],
            "quality/own_files.py": ["path."],
        }
        found: dict[str, list[str]] = {}
        for folder in ("quality", "tools", "hooks"):
            for path in sorted((fx.CENTRAL / folder).glob("*.py")):
                for line in path.read_text(encoding="utf-8").splitlines():
                    if re.search(r"\.write_(?:text|bytes)\(", line):
                        rel = path.relative_to(fx.CENTRAL).as_posix()
                        found.setdefault(rel, []).append(line.strip())
        for rel, lines in found.items():
            for line in lines:
                self.assertTrue(line.startswith(tuple(known.get(rel, ()))), f"{rel}: {line}")
        self.assertEqual(found.keys(), known.keys())


if __name__ == "__main__":
    unittest.main()
