# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""mypy groups: one mypy run per group of folders, none of which can weaken the block."""

from __future__ import annotations

import datetime as dt
import io
import os
import stat
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import kit_fixtures as fx
from kit_fixtures import check_quality as cq
from kit_fixtures import mypy_groups as mg
from kit_fixtures import sync

TODAY = dt.date(2026, 11, 23)

GROUPS = """
[[tool.kleidos-quality.mypy-groups]]
name = "one"
files = ["videos/one"]

[[tool.kleidos-quality.mypy-groups]]
name = "two"
files = ["videos/two", "tools"]
"""

# A stand-in for mypy: records each command line and fails on a folder named
# in FAKE_MYPY_FAIL (exit 1) or FAKE_MYPY_CRASH (exit 2).
FAKE_MYPY = """\
#!{python}
import os, sys
with open(os.environ["FAKE_MYPY_LOG"], "a", encoding="utf-8") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if os.environ.get("FAKE_MYPY_CRASH", "-") in args:
    print(args[-1] + ': error: Duplicate module named "score"')
    print("Found 1 error in 1 file (errors prevented further checking)")
    sys.exit(2)
if os.environ.get("FAKE_MYPY_FAIL", "-") in args:
    print(args[-1] + "/a.py:3: error: Function is missing a type annotation  [no-untyped-def]")
    print("Found 1 error in 1 file (checked 2 source files)")
    sys.exit(1)
print("Success: no issues found in 2 source files")
"""


def parse(text: str) -> tuple[list[mg.Group], list[str]]:
    return mg.declared(tomllib.loads(text))


class DeclarationTest(unittest.TestCase):
    def test_no_table_is_one_bare_run(self) -> None:
        self.assertEqual(parse('[tool.mypy]\nfiles = ["."]\n'), ([], []))

    def test_groups_are_read_with_their_folders_normalized(self) -> None:
        groups, problems = parse(
            '[[tool.kleidos-quality.mypy-groups]]\nname = "a"\nfiles = ["./x/", "y"]\n'
        )
        self.assertEqual(problems, [])
        self.assertEqual(groups, [mg.Group("a", ("x", "y"))])

    def test_a_group_names_folders_and_nothing_else(self) -> None:
        for key, value in (
            ("strict", "false"),
            ("disable_error_code", '["no-untyped-def"]'),
            ("config_file", '"lax.toml"'),
            ("args", '["--no-strict-optional"]'),
            ("exclude", '["x/old"]'),
        ):
            with self.subTest(key=key):
                _groups, problems = parse(
                    '[[tool.kleidos-quality.mypy-groups]]\nname = "a"\nfiles = ["x"]\n'
                    f"{key} = {value}\n"
                )
                self.assertTrue(any(f"{key}: a group names its folders" in p for p in problems))

    def test_names_and_folders_are_checked(self) -> None:
        cases = {
            '[[tool.kleidos-quality.mypy-groups]]\nname = "Bad Name"\nfiles = ["x"]\n': (
                "name must match"
            ),
            '[[tool.kleidos-quality.mypy-groups]]\nname = "a"\nfiles = ["x"]\n'
            '[[tool.kleidos-quality.mypy-groups]]\nname = "a"\nfiles = ["y"]\n': "used twice",
            '[[tool.kleidos-quality.mypy-groups]]\nname = "a"\nfiles = []\n': "non-empty list",
            '[[tool.kleidos-quality.mypy-groups]]\nname = "a"\nfiles = ["/etc"]\n': "absolute",
            '[[tool.kleidos-quality.mypy-groups]]\nname = "a"\nfiles = ["x/../.."]\n': (
                "out of the repository"
            ),
            '[[tool.kleidos-quality.mypy-groups]]\nname = "a"\nfiles = ["x", "x/"]\n': (
                "listed twice"
            ),
            '[tool.kleidos-quality]\nmypy-groups = "x"\n': "one or more tables",
            "[tool.kleidos-quality]\nother = 1\n": "other is not a setting of the kit",
            '[tool.mypy]\nfiles = ["."]\n[[tool.kleidos-quality.mypy-groups]]\n'
            'name = "a"\nfiles = ["x"]\n': "files is set beside the groups",
        }
        for text, needle in cases.items():
            with self.subTest(needle=needle):
                _groups, problems = parse(text)
                self.assertTrue(any(needle in p for p in problems), problems)

    def test_each_group_has_its_own_cache_and_passes_only_folders(self) -> None:
        group = mg.Group("one", ("videos/one",))
        self.assertEqual(
            mg.command("mypy", group, ".mypy_cache"),
            ["mypy", "--cache-dir", ".mypy_cache/one", "--", "videos/one"],
        )
        self.assertEqual(mg.command("mypy", None, ".mypy_cache"), ["mypy"])


class RunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.repo = tmp / "repo"
        self.repo.mkdir()
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "mypy"
        fake.write_text(FAKE_MYPY.format(python=sys.executable), encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        self.log = tmp / "calls.log"
        self.env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_MYPY_LOG": str(self.log),
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def pyproject(self, text: str) -> None:
        (self.repo / "pyproject.toml").write_text(text, encoding="utf-8")

    def run_groups(self, *args: str, **env: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.dict(os.environ, {**self.env, **env}),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            status = mg.main(["--repo", str(self.repo), *args])
        return status, out.getvalue(), err.getvalue()

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def test_without_groups_mypy_runs_once_bare(self) -> None:
        self.pyproject('[tool.mypy]\nstrict = true\nfiles = ["."]\n')
        status, _out, _err = self.run_groups()
        self.assertEqual(status, 0)
        self.assertEqual(self.calls(), [""])

    def test_every_group_runs_even_after_one_fails(self) -> None:
        self.pyproject("[tool.mypy]\nstrict = true\n" + GROUPS)
        status, out, _err = self.run_groups(FAKE_MYPY_FAIL="videos/one")
        self.assertEqual(status, 1)
        self.assertEqual(
            self.calls(),
            [
                "--cache-dir .mypy_cache/one -- videos/one",
                "--cache-dir .mypy_cache/two -- videos/two tools",
            ],
        )
        self.assertIn("mypy one (videos/one): errors: Found 1 error", out)
        self.assertIn("mypy two (videos/two, tools): clean", out)

    def test_github_output_folds_annotates_and_summarizes(self) -> None:
        self.pyproject("[tool.mypy]\nstrict = true\ncache_dir = '.cache/mypy'\n" + GROUPS)
        summary = self.repo / "summary.md"
        status, out, _err = self.run_groups(
            "--github", GITHUB_STEP_SUMMARY=str(summary), FAKE_MYPY_CRASH="tools"
        )
        self.assertEqual(status, 2)
        self.assertIn("::group::mypy one: videos/one", out)
        self.assertIn("::endgroup::", out)
        self.assertIn("::error title=mypy two::videos/two, tools: Found 1 error", out)
        self.assertNotIn("::error title=mypy one", out)
        self.assertIn("--cache-dir .cache/mypy/one", self.calls()[0])
        table = summary.read_text(encoding="utf-8")
        self.assertIn("1 of 2 run(s) clean.", table)
        self.assertIn("| ✅ one | `videos/one` | Success", table)
        self.assertIn("| ❌ two | `videos/two, tools` | Found 1 error", table)

    def test_a_glob_is_expanded_and_one_that_matches_nothing_kept(self) -> None:
        for rel in ("videos/one/a.py", "videos/one/b.py", "videos/one/cue/c.py"):
            fx.write(self.repo, rel, "X = 1\n")
        self.pyproject(
            "[tool.mypy]\nstrict = true\n[[tool.kleidos-quality.mypy-groups]]\n"
            'name = "one"\nfiles = ["videos/one/*.py", "none/*.py"]\n'
        )
        status, _out, _err = self.run_groups()
        self.assertEqual(status, 0)
        self.assertEqual(
            self.calls(),
            ["--cache-dir .mypy_cache/one -- videos/one/a.py videos/one/b.py none/*.py"],
        )

    def test_one_group_can_be_run_alone(self) -> None:
        self.pyproject("[tool.mypy]\nstrict = true\n" + GROUPS)
        status, _out, _err = self.run_groups("--group", "two")
        self.assertEqual(status, 0)
        self.assertEqual(self.calls(), ["--cache-dir .mypy_cache/two -- videos/two tools"])
        status, _out, err = self.run_groups("--group", "three")
        self.assertEqual(status, 2)
        self.assertIn("no group named three", err)

    def test_a_bad_declaration_runs_nothing(self) -> None:
        self.pyproject(
            '[tool.mypy]\nstrict = true\n[[tool.kleidos-quality.mypy-groups]]\nname = "a"\n'
            'files = ["x"]\nstrict = false\n'
        )
        status, _out, err = self.run_groups()
        self.assertEqual(status, 2)
        self.assertIn("a group names its folders and nothing else", err)
        self.assertEqual(self.calls(), [])

    def test_mypy_missing_is_a_setup_error(self) -> None:
        self.pyproject("[tool.mypy]\nstrict = true\n" + GROUPS)
        status, _out, err = self.run_groups(PATH=str(self.repo))
        self.assertEqual(status, 2)
        self.assertIn("mypy is not on the PATH", err)


class GroupConformanceTest(unittest.TestCase):
    """check_quality.py holds every tracked Python file to exactly one mypy run."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fx.consumer(Path(self._tmp.name) / "repo")
        for rel in ("videos/one/score.py", "videos/two/score.py", "tools/cut.py"):
            fx.write(self.root, rel, fx.header() + "X = 1\n")
        pyproject = self.root / "pyproject.toml"
        text = pyproject.read_text(encoding="utf-8").replace('files = ["pkg"]\n', "")
        pyproject.write_text(text + GROUPS.replace('"tools"]', '"tools", "pkg"]'), encoding="utf-8")
        sync.write(self.root, commit=fx.FAKE_COMMIT)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def found(self) -> list[str]:
        report = cq.run(self.root, kit=cq.DirKit(fx.CENTRAL), today=TODAY)
        return [f"{p.where}: [{p.rule}] {p.message}" for p in report.problems]

    def edit(self, old: str, new: str) -> None:
        path = self.root / "pyproject.toml"
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def append(self, text: str) -> None:
        path = self.root / "pyproject.toml"
        path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")

    def assertFound(self, *needles: str) -> None:
        found = self.found()
        for needle in needles:
            self.assertTrue(any(needle in f for f in found), f"{needle!r} not in {found}")

    def test_groups_that_cover_every_file_once_are_clean(self) -> None:
        self.assertEqual(self.found(), [])
        recorded = (self.root / cq.SOURCE_JSON).read_text(encoding="utf-8")
        self.assertIn(".github/quality/mypy_groups.py", recorded)

    def test_a_file_in_no_group_is_reported(self) -> None:
        fx.write(self.root, "loose/extra.py", fx.header() + "X = 1\n")
        self.assertFound("loose/extra.py: [mypy] not checked by mypy: add its folder to one")

    def test_a_file_in_two_groups_is_reported(self) -> None:
        self.edit('files = ["videos/one"]', 'files = ["videos"]')
        self.assertFound(
            "videos/two/score.py: [mypy] is in the mypy groups one, two: every file is in"
            " exactly one group"
        )

    def test_a_folder_with_no_python_is_reported(self) -> None:
        self.edit('files = ["videos/one"]', 'files = ["videos/one", "docs"]')
        self.assertFound("mypy group one: docs holds no tracked Python file")

    def test_one_run_over_two_same_named_scripts_is_reported(self) -> None:
        self.edit('files = ["videos/one"]', 'files = ["videos/one", "videos/two"]')
        self.edit('files = ["videos/two", "tools", "pkg"]', 'files = ["tools", "pkg"]')
        self.assertFound(
            "videos/two/score.py: [mypy] is module 'score' like videos/one/score.py, in the"
            " same mypy run (group one)"
        )

    def test_without_groups_the_same_duplicate_is_reported(self) -> None:
        path = self.root / "pyproject.toml"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.split("\n[[tool.kleidos-quality")[0] + 'files = ["."]\n')
        self.assertFound("is module 'score' like videos/one/score.py, in the same mypy run")

    def test_a_namespace_folder_under_a_package_is_no_duplicate(self) -> None:
        # mypy names these pkg.a.score and pkg.b.score: a folder with no
        # __init__.py is a namespace package when the folder above is a package.
        fx.write(self.root, "pkg/a/score.py", fx.header() + "X = 1\n")
        fx.write(self.root, "pkg/b/score.py", fx.header() + "X = 1\n")
        self.assertEqual(self.found(), [])
        self.assertEqual(cq.mypy_module("pkg/a/score.py", {"pkg/__init__.py"}), "pkg.a.score")
        self.assertEqual(cq.mypy_module("pkg/a/score.py", {"pkg/__init__.py"}, False), "score")
        self.assertEqual(cq.mypy_module("pkg/video-01/score.py", {"pkg/__init__.py"}), "score")
        self.assertEqual(cq.mypy_module("pkg/__init__.py", {"pkg/__init__.py"}), "pkg")

    def test_packages_and_stubs_are_no_duplicates(self) -> None:
        fx.write(self.root, "tools/sub/__init__.py", fx.header())
        fx.write(self.root, "tools/sub/score.py", fx.header() + "X = 1\n")
        fx.write(self.root, "tools/cut.pyi", fx.header() + "X: int\n")
        self.assertEqual(self.found(), [])

    def test_a_glob_names_a_folder_without_its_subfolders(self) -> None:
        fx.write(self.root, "videos/one/cue/score.py", fx.header() + "X = 1\n")
        self.assertFound(
            "videos/one/score.py: [mypy] is module 'score' like videos/one/cue/score.py"
        )
        self.edit('files = ["videos/one"]', 'files = ["videos/one/*.py"]')
        self.append(
            '\n[[tool.kleidos-quality.mypy-groups]]\nname = "cue"\nfiles = ["videos/one/cue"]\n'
        )
        self.assertEqual(self.found(), [])
        self.edit('files = ["videos/one/*.py"]', 'files = ["videos/one/*.py", "videos/one/*.pyx"]')
        self.assertFound("mypy group one: videos/one/*.pyx holds no tracked Python file")

    def test_a_group_cannot_carry_a_setting(self) -> None:
        self.edit('name = "one"\n', 'name = "one"\nstrict = false\n')
        self.assertFound("strict: a group names its folders and nothing else", "refused")

    def test_files_beside_groups_is_refused(self) -> None:
        self.edit("[tool.mypy]\n", '[tool.mypy]\nfiles = ["pkg"]\n')
        self.assertFound("files is set beside the groups")

    def test_a_missing_runner_is_reported(self) -> None:
        with mock.patch.dict(sys.modules, {"mypy_groups": None}):
            self.assertFound("mypy_groups.py: [mypy] missing beside check_quality.py")

    def test_the_hook_and_the_workflow_run_the_runner(self) -> None:
        hooks = (self.root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        self.assertIn("entry: python3 .github/quality/mypy_groups.py", hooks)
        workflow = (fx.CENTRAL / ".github/workflows/reusable-mypy.yml").read_text()
        self.assertIn('quality/mypy_groups.py" --github', workflow)
        self.assertNotIn("run: mypy\n", workflow)


if __name__ == "__main__":
    unittest.main()
