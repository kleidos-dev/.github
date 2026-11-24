# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""md_nowrap.py and fetch_tool.py, offline."""

from __future__ import annotations

import contextlib
import hashlib
import io
import itertools
import os
import re
import shutil
import tarfile
import tempfile
import time
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

    def test_a_path_out_of_the_repository_is_refused(self) -> None:
        """A path an agent or a script wrote is read only inside the working directory."""
        with tempfile.TemporaryDirectory() as tmp:
            root = fx.init(Path(tmp) / "repo")
            outside = Path(tmp) / "outside.md"
            outside.write_text("One\nwrapped\n", encoding="utf-8")
            sibling = Path(tmp) / "repo-evil" / "x.md"
            sibling.parent.mkdir()
            sibling.write_text("One\nwrapped\n", encoding="utf-8")
            (root / "sub").mkdir()
            (root / "link.md").symlink_to(outside)
            (root / "sub" / "inner.md").write_text("One\n", encoding="utf-8")
            (root / "inner-link.md").symlink_to(root / "sub" / "inner.md")
            with contextlib.chdir(root):
                for argv in (
                    ["../outside.md"],
                    [str(outside)],
                    ["link.md"],
                    ["sub/../../outside.md"],
                    ["../repo-evil/x.md"],
                    [str(sibling)],
                ):
                    with contextlib.redirect_stdout(io.StringIO()) as out:
                        self.assertEqual(md_nowrap.main(argv), 1, argv)
                    self.assertEqual(
                        out.getvalue(), f"{argv[0]}: refused: it leads out of the repository\n"
                    )
                for argv in (["inner-link.md"], ["sub/inner.md"], ["sub/../sub/inner.md"]):
                    with contextlib.redirect_stdout(io.StringIO()) as out:
                        self.assertEqual(md_nowrap.main(argv), 0, argv)
                    self.assertEqual(out.getvalue(), "")
                self.assertIsNone(md_nowrap.in_repository(root), "the repository is no file of it")
                self.assertIsNone(md_nowrap.in_repository(Path(".")))


#: The patterns the scans replaced (SonarCloud S8786: each could backtrack
#: for a time that grows faster than the line); the scans must read every
#: line exactly as they did.
OLD_FENCE = re.compile(r"^[ \t]*(?:>[ \t]?)*[ \t]*(?P<fence>`{3,}|~{3,})")
OLD_QUOTE = re.compile(r"^\s*(>\s?)+(.*)$")


class LineScanTest(unittest.TestCase):
    def test_the_scans_read_every_short_line_as_the_patterns_did(self) -> None:
        """Every line of up to six characters from the ones that matter, both ways."""
        alphabet = (" ", "\t", ">", "`", "~", "a", "\u2003")
        for size in range(7):
            for chars in itertools.product(alphabet, repeat=size):
                line = "".join(chars)
                fence = OLD_FENCE.match(line)
                self.assertEqual(md_nowrap.fence_of(line), fence["fence"] if fence else "", line)
                quote = OLD_QUOTE.match(line)
                self.assertEqual(md_nowrap.quoted(line), quote[2] if quote else None, line)

    def test_a_long_line_is_read_in_linear_time(self) -> None:
        """A run the old patterns took quadratic time over is read in one pass."""
        size = 200_000
        lines = (
            " " * size + "x",
            "\t" * size,
            "> " * size + "x",
            ">" + " " * size + "x",
            " " * size + ">" * size,
            "> \u2003" * size,
        )
        start = time.perf_counter()
        for line in lines:
            md_nowrap.fence_of(line)
            md_nowrap.quoted(line)
            md_nowrap.wrapped_lines(f"{line}\n{line}\n")
        self.assertLess(time.perf_counter() - start, 5.0)


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
        self.assertEqual(target, Path(os.path.realpath(self.dest), "tool"))
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

    def test_the_file_takes_the_lock_s_name(self) -> None:
        """A name the lock cannot give a file is refused before anything is fetched."""
        for name in ("../tool", "a/b", "Tool", ".tool", "-tool", "tool\n", ""):
            self.lock.write_text(
                f'["{name.encode("unicode_escape").decode()}"]\nurl = "{self.URL}"\nsha256 = "x"\n',
                encoding="utf-8",
            )
            with (
                self.subTest(name=name),
                mock.patch.object(fetch_tool, "_get") as get,
                self.assertRaisesRegex(ValueError, "which is no file name"),
            ):
                fetch_tool.install(name, self.dest, self.lock)
            get.assert_not_called()
        self.assertFalse(self.dest.exists())

    def test_a_folder_out_of_the_allowed_ones_is_refused(self) -> None:
        """DEST_DIR resolves into the working, temporary or runner's directory, or is refused."""
        work, temp, runner, elsewhere = (self.tmp / n for n in ("work", "temp", "runner", "else"))
        siblings = [self.tmp / n for n in ("work2", "temp-x", "runner2")]
        for folder in (work, temp, runner, elsewhere, *siblings):
            folder.mkdir()
        (work / "out").symlink_to(elsewhere)
        with (
            contextlib.chdir(work),
            mock.patch.object(tempfile, "gettempdir", return_value=str(temp)),
            mock.patch.dict("os.environ", {"RUNNER_TEMP": str(runner)}),
        ):
            for dest in (
                elsewhere,
                elsewhere / "bin",
                work / "out",
                work / "out" / "bin",
                Path("out/bin"),
                Path("../else/bin"),
                work / ".." / "else",
                Path("/"),
                self.tmp,
                *siblings,
                Path("../work2/bin"),
            ):
                with (
                    self.subTest(dest=dest),
                    mock.patch.object(fetch_tool, "_get") as get,
                    self.assertRaisesRegex(ValueError, "refusing to install into"),
                ):
                    fetch_tool.install("tool", dest, self.lock)
                get.assert_not_called()
            for folder in (elsewhere, *siblings):
                self.assertEqual(list(folder.iterdir()), [], folder)
            for dest, where in (
                (Path("bin"), work / "bin"),
                (Path("."), work),
                (temp / "bin", temp / "bin"),
                (runner, runner),
                (runner / "a" / ".." / "bin", runner / "bin"),
            ):
                self.dest = dest
                with self.subTest(dest=dest):
                    self.assertEqual(self.install(), Path(os.path.realpath(where)) / "tool")
            with mock.patch.dict("os.environ", {"RUNNER_TEMP": ""}):
                self.assertEqual(
                    fetch_tool.install_roots(),
                    [os.path.realpath(work), os.path.realpath(temp)],
                )
                self.dest = runner
                with self.assertRaisesRegex(ValueError, "refusing to install into"):
                    self.install()

    def test_a_link_in_the_file_s_place_is_replaced_not_followed(self) -> None:
        """DEST_DIR/NAME that is a link to a file elsewhere: the link goes, the file stays."""
        victim = self.tmp / "victim"
        victim.write_bytes(b"theirs")
        self.dest.mkdir(parents=True)
        (self.dest / "tool").symlink_to(victim)
        target = self.install()
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_bytes(), self.DATA)
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)
        self.assertEqual(victim.read_bytes(), b"theirs")
        self.assertEqual(victim.stat().st_mode & 0o111, 0)
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), ["tool"])

    def test_a_failed_rename_leaves_nothing_behind(self) -> None:
        with (
            mock.patch.object(os, "replace", side_effect=OSError("no")),
            self.assertRaisesRegex(OSError, "no"),
        ):
            self.install()
        self.assertEqual(list(self.dest.iterdir()), [])

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
