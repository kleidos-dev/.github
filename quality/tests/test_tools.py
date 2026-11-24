# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""md_nowrap.py and fetch_tool.py, offline."""

from __future__ import annotations

import contextlib
import hashlib
import io
import shutil
import tarfile
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

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
        self.assertEqual(md_nowrap.wrapped_lines("Line one\\\nline two\n"), [])

    def test_what_is_wrapped_and_what_is_not(self) -> None:
        for text, lines in (
            ("---\na: b\nc: d\n---\nOne\nwrapped\n", [6]),
            ("---\na: b\nc: d\n", [3]),  # front matter that never closes is prose
            ("a\n---\nb: c\n", []),
            ("> quoted\n> wrapped\n", [2]),
            ("> quoted\n> - item\n> > deeper\n", [3]),
            ("> quoted  \n> after a break\n", []),
            ("> [!NOTE]\n> One line.\n", []),
            ("> one\n>\n> two\n", []),
            ("> # heading\n> text\n", []),
            ("plain\n> quoted\n", []),
            ("> quoted\nlazy\n", []),
            ("- item\nwrapped\n", [2]),
            ("- item\n  wrapped\n  twice\n", [2, 3]),
            ("1. item\n2) item\n* item\n+ item\n", []),
            ("# heading\ntext\n", []),
            ("| a |\ntext\n", []),
            ("[x]: https://y\ntext\n", []),
            ("text\n\n    code\n    more\n\n    still\n", []),
            ("text\n    continued\n", [2]),
            ("text\n\n    - deep item\n", []),
            ("```\ncode\n~~~\nmore\n```\ntext\nwrapped\n", [7]),
            ("~~~\ncode\n```\nmore\n~~~\n", []),
            ("<!-- one --> x\ny\n", []),
            ("<!-- open\nprose\nmore -->\ntext\nwrapped\n", [5]),
            ('<a\n  href="x"\n>\ntext\nwrapped\n', [5]),
            ("one\n\ntwo\n", []),
            ("", []),
        ):
            with self.subTest(text=text):
                self.assertEqual(md_nowrap.wrapped_lines(text), lines)

    def test_the_command_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = fx.init(Path(tmp) / "repo")
            fx.write(root, "a.md", "One\nwrapped\n")
            fx.write(root, "b.md", "One\n")
            fx.write(root, "c.txt", "One\nwrapped\n")
            fx.write(root, "d.md", "One\nwrapped\n")
            fx.write(root, ".gitignore", "d.md\n")
            with contextlib.chdir(root):
                for argv, status, said in (
                    ([], 1, "a.md:2: hard-wrapped prose (join it to the line above)\n"),
                    (["b.md"], 0, ""),
                    (["c.txt", "none.md"], 0, ""),
                    (
                        ["a.md", "b.md"],
                        1,
                        "a.md:2: hard-wrapped prose (join it to the line above)\n",
                    ),
                ):
                    with contextlib.redirect_stdout(io.StringIO()) as out:
                        self.assertEqual(md_nowrap.main(argv), status, argv)
                    self.assertEqual(out.getvalue(), said)
                fx.git(root, "add", "a.md")
                (root / "a.md").unlink()
                self.assertEqual(md_nowrap.main([]), 0)
                with mock.patch("sys.argv", ["md_nowrap.py", "b.md"]):
                    self.assertEqual(md_nowrap.main(), 0)


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

    def test_a_member_that_is_no_file_is_refused(self) -> None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            folder = tarfile.TarInfo("tool")
            folder.type = tarfile.DIRTYPE
            tar.addfile(folder)
        with self.assertRaisesRegex(ValueError, "tool is not a file in the archive"):
            fetch_tool.extract(buf.getvalue(), {"member": "tool"})
        with self.assertRaises(KeyError):
            fetch_tool.extract(buf.getvalue(), {"member": "other"})
        self.assertEqual(fetch_tool.extract(b"plain", {}), b"plain")


class InstallTest(unittest.TestCase):
    """The binaries every repository's CI runs: what is installed is what the lock pins."""

    DATA = b"the binary"
    URL = "https://example.invalid/tool"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.lock = self.tmp / "tools.lock"
        self.pin(hashlib.sha256(self.DATA).hexdigest())
        self.dest = self.tmp / "a" / "bin"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def pin(self, digest: str) -> None:
        self.lock.write_text(
            f'[tool]\nversion = "1.0"\nrepo = "o/r"\nurl = "{self.URL}"\nsha256 = "{digest}"\n',
            encoding="utf-8",
        )

    def install(self, name: str = "tool") -> Path:
        with mock.patch.object(fetch_tool, "_get", return_value=self.DATA) as get:
            target = fetch_tool.install(name, self.dest, self.lock)
        get.assert_called_once_with(self.URL)
        return target

    def test_the_pinned_bytes_are_installed(self) -> None:
        target = self.install()
        self.assertEqual(target, self.dest / "tool")
        self.assertEqual(target.read_bytes(), self.DATA)
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)
        self.assertEqual(self.install(), target)  # a folder that is there already

    def test_a_wrong_digest_installs_nothing(self) -> None:
        for digest in ("0" * 64, hashlib.sha256(b"other").hexdigest(), ""):
            self.pin(digest)
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                self.install()
            self.assertFalse(self.dest.exists())

    def test_the_member_of_an_archive_is_installed_from_verified_bytes(self) -> None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo("tool")
            info.size = 3
            tar.addfile(info, io.BytesIO(b"bin"))
        self.DATA = buf.getvalue()
        self.pin(hashlib.sha256(self.DATA).hexdigest())
        with self.lock.open("a", encoding="utf-8") as fh:
            fh.write('member = "tool"\n')
        self.assertEqual(self.install().read_bytes(), b"bin")

    def test_an_unknown_tool_is_refused_by_name(self) -> None:
        with self.assertRaisesRegex(KeyError, r"other is not in tools.lock \(known: tool\)"):
            self.install("other")

    def main(self, *argv: str) -> tuple[int, str, str]:
        with (
            contextlib.redirect_stdout(io.StringIO()) as out,
            contextlib.redirect_stderr(io.StringIO()) as err,
        ):
            try:
                status = fetch_tool.main(list(argv))
            except SystemExit as stop:
                status = int(stop.code or 0)
        return status, out.getvalue(), err.getvalue()

    def test_the_command_line(self) -> None:
        with mock.patch.object(fetch_tool, "install", return_value=self.dest) as install:
            self.assertEqual(self.main("tool", "bin"), (0, f"{self.dest}\n", ""))
        install.assert_called_once_with("tool", Path("bin"))
        for error in (ValueError("SHA-256 mismatch: x"), KeyError("x is not in tools.lock")):
            with mock.patch.object(fetch_tool, "install", side_effect=error):
                status, out, err = self.main("tool", "bin")
            self.assertEqual((status, out), (1, ""))
            self.assertIn("fetch_tool: ", err)
        for argv in ((), ("tool",)):
            status, _out, err = self.main(*argv)
            self.assertEqual(status, 2)
            self.assertIn("NAME and DEST_DIR are required", err)

    def test_the_releases_of_the_tools(self) -> None:
        for tag, lines in (("v1.0", []), ("1.0", []), ("v1.1", ["tool: pinned 1.0, latest 1.1"])):
            answer = f'{{"tag_name": "{tag}"}}'.encode()
            with mock.patch.object(fetch_tool, "_get", return_value=answer) as get:
                self.assertEqual(fetch_tool.outdated(self.lock), lines)
            url, headers = get.call_args.args
            self.assertEqual(url, "https://api.github.com/repos/o/r/releases/latest")
            self.assertEqual(headers["Accept"], "application/vnd.github+json")
        for env, sent in (
            ({"GH_TOKEN": "a"}, "Bearer a"),
            ({"GITHUB_TOKEN": "b"}, "Bearer b"),
            ({}, None),
        ):
            with (
                mock.patch.dict("os.environ", env, clear=True),
                mock.patch.object(fetch_tool, "_get", return_value=b'{"tag_name": "1.0"}') as get,
            ):
                fetch_tool.outdated(self.lock)
            self.assertEqual(get.call_args.args[1].get("Authorization"), sent)
        for lines, status in ((["x"], 1), ([], 0)):
            with mock.patch.object(fetch_tool, "outdated", return_value=lines):
                said = "".join(f"{line}\n" for line in lines)
                self.assertEqual(self.main("--outdated"), (status, said, ""))

    def test_what_is_asked_is_https_with_a_bound(self) -> None:
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b"x"
            self.assertEqual(fetch_tool._get("https://example.invalid/x", {"A": "b"}), b"x")
        request = urlopen.call_args.args[0]
        self.assertEqual(
            (request.full_url, request.get_header("A")), ("https://example.invalid/x", "b")
        )
        self.assertEqual(urlopen.call_args.kwargs, {"timeout": 60})


class MacRulesTest(unittest.TestCase):
    @unittest.skipIf(shutil.which("gitleaks") is None, "gitleaks is not installed")
    def test_the_mac_rules_fire_on_real_shapes_and_spare_fakes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = fx.init(Path(tmp) / "repo")
            shutil.copy(fx.CENTRAL / "quality/gitleaks/mac.toml", root / ".gitleaks-mac.toml")
            self.assertEqual(cq.plant_mac(cq.Repo(root)), [])
            self.assertEqual(
                self.plant(root), (0, "plant-mac: every real shape found, every fake spared\n")
            )
            # Rules that find nothing, and rules that spare nothing.
            config = root / ".gitleaks-mac.toml"
            for rule, needle in (
                ('regex = "no such text anywhere"', "a real MAC shape was not found"),
                ('regex = "."', "a fake MAC shape was reported"),
            ):
                config.write_text(
                    f'title = "x"\n[[rules]]\nid = "r"\ndescription = "d"\n{rule}\n',
                    encoding="utf-8",
                )
                status, said = self.plant(root)
                self.assertEqual(status, 1, said)
                self.assertIn(needle, said)
                self.assertIn("plant-mac: FAILED", said)

    def plant(self, root: Path) -> tuple[int, str]:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            return cq.main(["--plant-mac", "--repo", str(root)]), out.getvalue()

    def test_the_verdict_of_the_plants_is_the_status(self) -> None:
        """Without gitleaks too: what plant_mac found is what --plant-mac exits with."""
        with tempfile.TemporaryDirectory() as tmp:
            root = fx.init(Path(tmp) / "repo")
            for wrong, status in (([], 0), (["colon: a real MAC shape was not found"], 1)):
                with mock.patch.object(cq, "plant_mac", return_value=wrong):
                    found, said = self.plant(root)
                self.assertEqual(found, status)
                self.assertEqual("FAILED" in said, bool(wrong))
            with mock.patch.object(shutil, "which", return_value=None):
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(cq.main(["--plant-mac", "--repo", str(root)]), 2)
                self.assertIn("gitleaks is not on PATH", err.getvalue())
            with mock.patch.object(shutil, "which", return_value="/bin/true"):
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(cq.main(["--plant-mac", "--repo", str(root)]), 2)
                self.assertIn(".gitleaks-mac.toml is missing", err.getvalue())

    def test_each_plant_is_judged_for_what_it_is(self) -> None:
        """Every real shape must be found and every fake spared, one by one."""
        with tempfile.TemporaryDirectory() as tmp:
            root = fx.init(Path(tmp) / "repo")
            shutil.copy(fx.CENTRAL / "quality/gitleaks/mac.toml", root / ".gitleaks-mac.toml")
            for reported in ("[]", '[{"RuleID": "r"}]'):

                def gitleaks(cmd: list[str], said: str = reported, **_more: object) -> None:
                    Path(cmd[-1]).write_text(said, encoding="utf-8")

                with (
                    mock.patch.object(shutil, "which", return_value="/gitleaks"),
                    mock.patch("subprocess.run", side_effect=gitleaks),
                    mock.patch.object(cq, "Repo") as repo,
                ):
                    repo.path.return_value = root / ".gitleaks-mac.toml"
                    wrong = cq.plant_mac(repo)
                labels = {line.split(":")[0] for line in wrong}
                if reported == "[]":
                    real = {"colon", "dash", "upper", "dotted", "bare", "svg", "allow-comment"}
                    self.assertEqual(labels, real)
                else:
                    fakes = {"zeros", "broadcast", "test-range", "spelled", "hash"}
                    self.assertEqual(labels, fakes)

    def test_the_mac_config_extends_nothing(self) -> None:
        cfg = tomllib.loads((fx.CENTRAL / "quality/gitleaks/mac.toml").read_text(encoding="utf-8"))
        self.assertNotIn("extend", cfg)
        self.assertTrue(cfg.get("rules"))


if __name__ == "__main__":
    unittest.main()
