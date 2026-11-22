# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""md_nowrap.py and fetch_tool.py, offline."""

from __future__ import annotations

import hashlib
import io
import shutil
import tarfile
import tempfile
import tomllib
import unittest
from pathlib import Path

import kit_fixtures as fx
from kit_fixtures import check_quality as cq
from kit_fixtures import fetch_tool, md_nowrap


class NoWrapTest(unittest.TestCase):
    def test_a_wrapped_paragraph_is_found(self) -> None:
        self.assertEqual(md_nowrap.wrapped_lines("One line\ncontinued here.\n"), [2])

    def test_lists_tables_code_and_comments_keep_their_layout(self) -> None:
        text = (
            "<!--\nSPDX header line\nsecond line\n-->\n\n"
            "- one\n- two\n\n| a | b |\n| --- | --- |\n\n```\ncode\nmore code\n```\n"
        )
        self.assertEqual(md_nowrap.wrapped_lines(text), [])

    def test_a_longer_fence_holds_a_shorter_one(self) -> None:
        text = "````md\n```\ninner\nmore\n```\nstill code\n````\n"
        self.assertEqual(md_nowrap.wrapped_lines(text), [])

    def test_quoted_fences_and_tags_over_lines_keep_their_layout(self) -> None:
        self.assertEqual(md_nowrap.wrapped_lines("> ```\n> a\n> b\n> ```\n"), [])
        self.assertEqual(md_nowrap.wrapped_lines('<div\n  class="a"\n  id="b">\n</div>\n'), [])

    def test_a_hard_break_is_not_a_wrap(self) -> None:
        self.assertEqual(md_nowrap.wrapped_lines("Line one  \nline two\n"), [])


class FetchToolTest(unittest.TestCase):
    def test_the_lock_pins_https_urls_and_digests(self) -> None:
        for name, entry in fetch_tool.load().items():
            with self.subTest(tool=name):
                self.assertTrue(str(entry["url"]).startswith("https://"))
                self.assertRegex(str(entry["sha256"]), r"^[0-9a-f]{64}$")
                self.assertIn(str(entry["version"]), str(entry["url"]))

    def test_a_wrong_digest_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            fetch_tool.verify(b"data", "0" * 64)
        fetch_tool.verify(b"data", hashlib.sha256(b"data").hexdigest())

    def test_a_member_comes_out_of_a_tarball(self) -> None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo("tool")
            info.size = 3
            tar.addfile(info, io.BytesIO(b"bin"))
        self.assertEqual(fetch_tool.extract(buf.getvalue(), {"member": "tool"}), b"bin")

    def test_a_plain_http_url_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            fetch_tool._get("http://example.invalid/x")


class MacRulesTest(unittest.TestCase):
    @unittest.skipIf(shutil.which("gitleaks") is None, "gitleaks is not installed")
    def test_the_mac_rules_fire_on_real_shapes_and_spare_fakes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = fx.init(Path(tmp) / "repo")
            shutil.copy(fx.CENTRAL / "quality/gitleaks/mac.toml", root / ".gitleaks-mac.toml")
            self.assertEqual(cq.plant_mac(cq.Repo(root)), [])

    def test_the_mac_config_extends_nothing(self) -> None:
        cfg = tomllib.loads((fx.CENTRAL / "quality/gitleaks/mac.toml").read_text(encoding="utf-8"))
        self.assertNotIn("extend", cfg)
        self.assertTrue(cfg.get("rules"))


if __name__ == "__main__":
    unittest.main()
