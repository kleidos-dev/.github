# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""suite_rules.py: every way a change may weaken the tests unsaid is found, and nothing else is."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import expressions
import kit_fixtures as fx
import yaml
from kit_fixtures import check_quality as cq
from kit_fixtures import suite_rules as sr


class PythonSkipTest(unittest.TestCase):
    HEAD = "import unittest\nimport pytest\nimport pytest as pt\nfrom unittest import skip\n"

    def found(self, body: str) -> list[int]:
        """The lines of the body (from 1) that are reported."""
        return [n - 4 for n in sr.python_skips(self.HEAD + body)]

    def test_a_skip_with_no_reason_is_found(self) -> None:
        for body in (
            "@unittest.skip\ndef f(): ...\n",
            '@unittest.skip("")\ndef f(): ...\n',
            '@skip("later")\ndef f(): ...\n',
            "@skip\nclass C: ...\n",
            "@unittest.skip\nasync def f(): ...\n",
            '@unittest.skipIf(True, " ")\ndef f(): ...\n',
            '@unittest.skipUnless(False, reason="x y")\ndef f(): ...\n',
            "@unittest.expectedFailure\ndef f(): ...\n",
            "f = unittest.expectedFailure(f)\n",
            "raise unittest.SkipTest\n",
            "raise unittest.SkipTest()\n",
            "raise unittest.case.SkipTest\n",
            "self.skipTest('')\n",
            "pytest.skip()\n",
            "pytest.skip(None)\n",
            "pytest.skip(1)\n",
            "pt.skip('todo')\n",
            'raise pytest.skip.Exception("")\n',
            "pytest.xfail()\n",
            "@pytest.mark.skip\ndef f(): ...\n",
            "@pytest.mark.skip()\ndef f(): ...\n",
            '@pytest.mark.skipif(True, "not a reason here")\ndef f(): ...\n',
            '@pytest.mark.skipif(True, reason="")\ndef f(): ...\n',
            "@pytest.mark.xfail\ndef f(): ...\n",
            '@pytest.mark.xfail("a condition", strict=True)\ndef f(): ...\n',
            "pytestmark = pytest.mark.skip\n",
            "x = pytest.param(1, marks=pytest.mark.xfail)\n",
            '@unittest.skip("x")  # skip:\ndef f(): ...\n',
            "@unittest.expectedFailure\n# skip: a reason for later\ndef f(): ...\n",
            "# skip: a reason for x\nx = 1\n# no more\n@unittest.expectedFailure\ndef f(): ...\n",
            '# skip: too far above it\n\n@unittest.skip("x")\ndef f(): ...\n',
        ):
            with self.subTest(body):
                self.assertEqual(len(self.found(body)), 1, body)

    def test_a_skip_that_says_why_is_let_through(self) -> None:
        for body in (
            '@unittest.skip("needs the bench")\ndef f(): ...\n',
            '@unittest.skipIf(no_git, reason="git is not installed")\ndef f(): ...\n',
            '@unittest.skipUnless(git, "git is not " "installed")\ndef f(): ...\n',
            "@unittest.skipIf(no_git, WHY)\ndef f(): ...\n",
            'raise unittest.SkipTest("no such device")\n',
            'self.skipTest(f"{name} is not installed")\n',
            "pytest.skip(message, allow_module_level=True)\n",
            "pytest.skip(*why)\n",
            "@unittest.skipIf(*why)\ndef f(): ...\n",
            "pytest.skip(**why)\n",
            'pytest.skip(msg="no power tree")\n',
            'raise pytest.skip.Exception("no power tree")\n',
            'pytest.xfail("upstream bug 12 is open")\n',
            '@pytest.mark.skip("no power tree")\ndef f(): ...\n',
            '@unittest.skipIf(True, "", reason="no power tree")\ndef f(): ...\n',
            'pytest.importorskip("pypdf")\n',
            '@pytest.mark.skipif(True, reason="kicad is not installed")\ndef f(): ...\n',
            '@pytest.mark.xfail(reason="upstream bug 12")\ndef f(): ...\n',
            "# skip: the parser is written next week\n@unittest.expectedFailure\ndef f(): ...\n",
            "# skip: the parser is written\n# next week\n@unittest.expectedFailure\ndef f(): ...\n",
            "@unittest.expectedFailure  # skip: upstream bug 12\ndef f(): ...\n",
            "@pytest.mark.skip  # Skip: no board here\ndef f(): ...\n",
            "pytest.skip(\n    # skip: no board here\n)\n",
        ):
            with self.subTest(body):
                self.assertEqual(self.found(body), [], body)

    def test_what_is_no_marker_is_left_alone(self) -> None:
        for body in (
            "except_ = pytest.raises(pytest.skip.Exception, match='x')\n",
            "try:\n    f()\nexcept unittest.SkipTest:\n    raise\n",
            "raise ValueError\n",
            "raise skipped from None\n",
            "@decorated\n@other.thing\ndef f(): ...\n",
            "@pytest.mark.slow\ndef f(): ...\n",
            "x = '@unittest.skip'  # @unittest.skip\n",
            "rows.skip(3)\nskipped()\nself.skip()\n",
            "rows[0].skip(3)\nf().mark.skip()\npytest.other.skip()\n",
        ):
            with self.subTest(body):
                self.assertEqual(self.found(body), [], body)

    def test_a_name_is_followed_to_where_it_comes_from(self) -> None:
        for text, count in (
            ("import unittest.case\n@unittest.case.skip\ndef f(): ...\n", 1),
            ("import unittest.case as c\n@c.skip\ndef f(): ...\n", 1),
            ("from unittest.case import skip as s\n@s\ndef f(): ...\n", 1),
            ("from pytest import mark\n@mark.skip\ndef f(): ...\n", 1),
            ("from .unittest import skip\n@skip\ndef f(): ...\n", 0),
            ("from other import skip\nimport other\n@skip\ndef f(): ...\n", 0),
            ("import unittest.mock as m\nm.skip('x')\n", 0),
            ("import pytest.mark\n@pytest.mark.skip\ndef f(): ...\n", 1),
            ("from . import skip\n@skip\ndef f(): ...\n", 0),
            ("def skip(f): return f\n@skip\ndef f(): ...\n", 0),
        ):
            with self.subTest(text):
                self.assertEqual(len(sr.python_skips(text)), count)

    def test_a_file_that_names_no_marker_is_not_read(self) -> None:
        self.assertEqual(sr.python_skips("this is not python ("), [])


class JavaScriptTest(unittest.TestCase):
    def test_a_test_that_runs_alone_is_found(self) -> None:
        for text in (
            "it.only('x', f);",
            "describe.only('x', f);",
            "test.concurrent.only.each([1])('x', f);",
            "test.describe.only('x', f);",
            "test\n  .only('x', f);",
            "it?.only('x', f)",
            "suite . only ('x', f)",
            "bench.only('x', f)",
            "fit('x', f)",
            "fdescribe ('x', f)",
            "test('x', { only: true }, f)",
            "test('x', { skip: false, only: true }, f)",
            "const s = `${it.only('x', f)}`;",
            "const s = `${{ a: `b` }} ${fit('x', f)}`;",
            "const s = `${ [{ a: 1 }, it.only('x', f)] }`;",
            "const s = `${ [{ a: { b: 1 } }, it.only('x', f)] }\nit.only`;",
            "/* a */it.only('x', f)",
            "x = /\nit.only('x', f)",
            "// it.skip('x')\nit.only('x', f)",
            "const r = /[/'\"`]/; it.only('x', f)",
            "const half = a / 2; it.only('x', f); const b = c / 2;",
            "let s = 'one line; it.only\nit.only('x', f)",
            "x = /* it.skip */ it.only('x', f)",
            # A file it cannot read to its end is judged as it is written.
            "/* never closed\nit.only('x', f)",
            "`never closed\nit.only('x', f)",
            "const s = `it.only('x', f)`;\n`never closed",
            "const s = `it.only('x', f)`;\n`${ never closed",
            "const s = `it.only('x', f)`;\n`",
            "const s = `it.only('x', f)`;\n/* never closed",
            "`${ never closed\nit.only('x', f)",
            "const n = x /= 2; it.only('x', f)",
        ):
            with self.subTest(text):
                self.assertEqual(len(sr.js_marks(text)[0]), 1, text)

    def test_what_is_no_marker_is_left_alone(self) -> None:
        for text in (
            "it('runs only this', f);",
            "// it.only('x')\n/* describe.only('x')\n it.skip('y') */",
            "const s = 'it.only(1)' + \"it.skip(1)\" + `it.todo(${x}) it.only`;",
            "const r = /it.only(x)/;",
            "/**/ const s = 'it.only(1)';",
            "const r = '\\'it.only';",
            "readonly(x); const only = 1; limit.only(x); profit('x')",
            "f({ only: ['a'], skip: 10, todo: false, fails: undefined });",
            "type Page = { skip: number };",
            "it.skipped('x')",
            "pagination.skip(3)",
        ):
            with self.subTest(text):
                self.assertEqual(sr.js_marks(text), ([], []), text)

    def test_a_skip_with_no_reason_is_found(self) -> None:
        for text in (
            "it.skip('a name is no reason', f);",
            "describe.skipIf(cond)('x', f);",
            "test.runIf(cond)('x', f)",
            "it.todo('write this test')",
            "it.fails('x', f)",
            "test.failing('x', f)",
            "test.fixme('x', f)",
            "xit('x', f)",
            "xdescribe('x', f)",
            "t.skip()",
            "t.skip(undefined)",
            "t.skip('')",
            "t.todo('later')",
            "t.skip('never closed on its line" + "\\\\a" * 60 + ")",
            "context.skip(why)",
            "test('x', { skip: true }, f)",
            "test('x', { todo: 'later' }, f)",
            "test('x', { concurrency: 1, skip: !docker }, f)",
            "it.skip('x', f); // skip: no",
            "// skip: a reason for another line\n\nit.skip('x', f);",
        ):
            with self.subTest(text):
                self.assertEqual(len(sr.js_marks(text)[1]), 1, text)

    def test_a_skip_that_says_why_is_let_through(self) -> None:
        for text in (
            "it.skip('x', f); // skip: the runtime has no clock",
            "// skip: the runtime has no clock\nit.skip('x', f);",
            "/*\n * skip: the runtime has no clock\n */\nit.skip('x', f);",
            "t.skip('no docker here')",
            "t.skip('it\\'s never here')",
            "test('x', { skip: 'no docker here' }, f)",
            "test('x', { todo: `the second half` }, f)",
        ):
            with self.subTest(text):
                self.assertEqual(sr.js_marks(text), ([], []), text)

    def test_the_line_is_the_markers(self) -> None:
        self.assertEqual(sr.js_marks("a\n\nit.only('x')\nxit('y')\n"), ([3], [4]))
        self.assertEqual(sr.js_marks("\nit\n  .only('x')"), ([3], []))

    def test_which_files_hold_tests(self) -> None:
        for rel, text, want in (
            ("worker/test/a.ts", "", True),
            ("src/__tests__/a.js", "", True),
            ("src/a.test.ts", "", True),
            ("src/a.spec.mjs", "", True),
            ("src/a.ts", 'import { it } from "vitest";', True),
            ("src/a.mjs", "import test from 'node:test';", True),
            ("src/a.cjs", "const t = require('node:test')", True),
            ("src/test.ts", 'import { it } from "./vitest";', False),
            ("src/contest.ts", "it.only", False),
        ):
            with self.subTest(rel=rel):
                self.assertEqual(sr.is_js_test(rel, text), want)


class ThresholdsTest(unittest.TestCase):
    def test_every_place_a_tool_reads_one(self) -> None:
        run = "node --test --test-coverage-lines=100 --test-coverage-branches 95.5"
        for rel, text, want in (
            ("pyproject.toml", "[tool.coverage.report]\nfail_under = 100\n", {"fail_under": 100}),
            (
                "host/pyproject.toml",
                "[tool.coverage.report]\nfail_under = 9.5",
                {"fail_under": 9.5},
            ),
            ("pyproject.toml", "[report]\nfail_under = 100\n", {}),
            ("pyproject.toml", "[tool.coverage.report]\nfail_under = true\n", {}),
            ("pyproject.toml", "tool = 1\n", {}),
            ("pyproject.toml", "not toml", {}),
            (".coveragerc.toml", "[tool.coverage.report]\nfail_under = 7\n", {"fail_under": 7}),
            (".coveragerc.toml", "[report]\nfail_under = 8\n", {"fail_under": 8}),
            (".coveragerc", "[report]\nfail_under = 90\n", {"fail_under": 90}),
            (".coveragerc", "[report]\nfail_under = many\n", {}),
            (".coveragerc", "fail_under = 90\n", {}),
            ("setup.cfg", "[coverage:report]\nfail_under = 80%\n", {}),
            ("setup.cfg", "[coverage:report]\nfail_under = 80\n", {"fail_under": 80}),
            ("tox.ini", "[report]\nfail_under = 80\n", {}),
            ("package.json", json.dumps({"scripts": {"t": run}}), {"lines": 100, "branches": 95.5}),
            ("package.json", "{", {}),
            (
                ".github/workflows/ci.yml",
                f"# {run}\njobs:\n  a:\n    steps:\n    - run: |\n        # {run}\n"
                "        node --test-coverage-lines=99 && node --test-coverage-lines=100\n",
                {"lines": 99},
            ),
            (".github/workflows/ci.yml", "a: [", {}),
            (
                "worker/vitest.config.ts",
                "// thresholds: { lines: 1 }\nexport default { coverage: { thresholds: {\n"
                "  lines: 100, 'src/**': { functions: 90, lines: 95 }, a: true }, m: 2 }, n: 3 };",
                {"lines": 95, "functions": 90},
            ),
            ("vitest.config.ts", "thresholds: { lines: 100", {"lines": 100}),
            ("vite.config.ts", "thresholds: { a: { b: 1 }, c: 2 }, n: 3", {"b": 1, "c": 2}),
            ("vite.config.ts", "thresholds: { a: { b: 1 }, c: 22 }, n: 3", {"b": 1, "c": 22}),
            ("vitest.config.ts", "thresholds: limits", {}),
        ):
            with self.subTest(rel=rel, text=text):
                found = sr.thresholds([rel], {rel: text}.__getitem__)
                self.assertEqual(found, {f"{rel} {k}": v for k, v in want.items()})

    def test_only_those_files_are_read(self) -> None:
        def refuse(rel: str) -> str:
            raise AssertionError(rel)

        names = ["src/a.py", "node_modules/x/package.json", "docs/ci.yml", "a/vitest.txt"]
        self.assertEqual(sr.thresholds(names, refuse), {})

    def test_a_fall_is_found_and_a_rise_is_not(self) -> None:
        old = {"a": 100.0, "b": 90.0, "c": 5.0}
        new = {"a": 99.0, "b": 95.0, "d": 1.0}
        self.assertEqual(sr.fallen(old, new), [("a", 100.0, 99.0), ("c", 5.0, None)])
        self.assertEqual(sr.fallen(old, old), [])

    def test_an_entry_accepts_the_fall_it_names_and_no_other(self) -> None:
        good = {"threshold": "a", "to": 99, "reason": "the reader moved out", "decided": "owner"}
        self.assertTrue(sr.accepts(good, "a", 99.0))
        self.assertTrue(sr.accepts(good | {"to": "gone"}, "a", None))
        for wrong in (
            {"threshold": "b"},
            {"to": 98},
            {"to": "gone"},
            {"to": "soon"},
            {"reason": "why"},
            {"decided": " "},
        ):
            with self.subTest(wrong):
                self.assertFalse(sr.accepts(good | wrong, "a", 99.0))
        self.assertFalse(sr.accepts(good, "a", None))
        self.assertFalse(sr.accepts(good | {"to": "soon"}, "a", None))
        for key in good:
            with self.subTest(missing=key):
                self.assertFalse(sr.accepts({k: v for k, v in good.items() if k != key}, "a", 99.0))

    def test_the_entries_of_a_waivers_file(self) -> None:
        for text, count in (
            ("", 0),
            ("[[lowered]]\n[[lowered]]\n", 2),
            ("[lowered]\n", 0),
            ("lowered = [1]\n", 0),
            ("[[", 0),
        ):
            with self.subTest(text):
                self.assertEqual(len(sr.lowered_entries(text)), count)


class RepositoryTest(unittest.TestCase):
    CONFIG = "[tool.coverage.report]\nfail_under = {}\n"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fx.init(Path(self._tmp.name) / "repo")
        fx.write(self.root, "pyproject.toml", self.CONFIG.format(100))
        fx.write(self.root, cq.WAIVERS, fx.header())
        fx.commit(self.root)
        self.base = fx.git(self.root, "rev-parse", "HEAD").strip()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def check(self, base: str | None = None) -> list[str]:
        found, _notes = sr.check(cq.Repo(self.root), self.base if base is None else base)
        return [str(p) for p in found]

    def entry(self, to: str) -> str:
        return (
            f'\n[[lowered]]\nthreshold = "pyproject.toml fail_under"\nto = {to}\n'
            'reason = "the reader moved out"\ndecided = "owner 2026-11-25"\n'
        )

    def test_a_threshold_that_falls_is_found(self) -> None:
        self.assertEqual(self.check(), [])
        fx.write(self.root, "pyproject.toml", self.CONFIG.format(99.5))
        (found,) = self.check()
        self.assertTrue(found.startswith("pyproject.toml fail_under: [threshold] went from 100 "))
        self.assertIn("to = 99.5, reason, decided)", found)
        fx.commit(self.root)
        self.assertEqual(len(self.check()), 1)

    def test_a_threshold_that_goes_is_found(self) -> None:
        fx.write(self.root, "pyproject.toml", fx.header())
        (found,) = self.check()
        self.assertIn('went from 100 to "gone" since', found)
        self.assertIn('to = "gone"', found)
        (self.root / "pyproject.toml").unlink()
        self.assertEqual(len(self.check()), 1)

    def test_a_rise_passes(self) -> None:
        fx.write(self.root, "pyproject.toml", self.CONFIG.format(100.5))
        self.assertEqual(self.check(), [])

    def test_a_new_entry_says_it_and_an_old_one_does_not(self) -> None:
        fx.write(self.root, "pyproject.toml", self.CONFIG.format(99))
        fx.write(self.root, cq.WAIVERS, fx.header() + self.entry("99"))
        self.assertEqual(self.check(), [])
        (note,) = sr.check(cq.Repo(self.root), self.base)[1]
        self.assertIn("lowered: pyproject.toml fail_under went from 100 to 99 since", note)
        self.assertTrue(note.endswith(": the reader moved out (owner 2026-11-25)"), note)
        fx.commit(self.root)
        lowered = fx.git(self.root, "rev-parse", "HEAD").strip()
        # What was said of one fall says nothing of the next, to the same value.
        fx.write(self.root, "pyproject.toml", self.CONFIG.format(100))
        fx.commit(self.root)
        raised = fx.git(self.root, "rev-parse", "HEAD").strip()
        fx.write(self.root, "pyproject.toml", self.CONFIG.format(99))
        self.assertEqual(len(self.check(raised)), 1)
        self.assertEqual(self.check(lowered), [])

    def test_a_tree_with_no_waivers_file_is_compared_too(self) -> None:
        (self.root / cq.WAIVERS).unlink()
        self.assertEqual(self.check(), [])
        fx.commit(self.root)
        bare = fx.git(self.root, "rev-parse", "HEAD").strip()
        fx.write(self.root, "pyproject.toml", self.CONFIG.format(1))
        self.assertEqual(len(self.check(bare)), 1)

    def test_what_the_change_is_compared_with(self) -> None:
        repo = cq.Repo(self.root)
        self.assertEqual(sr.base_of(repo, self.base), self.base)
        # A push that made the branch names no commit, a schedule nothing.
        for named in ("", "0" * 40):
            self.assertIsNone(sr.base_of(repo, named))
            self.assertEqual(
                sr.check(repo, named)[1], ["no base to compare the coverage thresholds with"]
            )
        fx.git(self.root, "update-ref", "refs/remotes/origin/main", self.base)
        fx.write(self.root, "pyproject.toml", self.CONFIG.format(50))
        fx.commit(self.root)
        self.assertEqual(sr.base_of(repo, ""), self.base)
        self.assertEqual(len(self.check("")), 1)
        with self.assertRaisesRegex(cq.SetupError, "is not in this clone"):
            sr.base_of(repo, "d" * 40)

    def test_coverage_py_takes_its_threshold_from_no_command_line(self) -> None:
        for rel, text, count in (
            (".github/workflows/a.yml", "run: pytest --cov-fail-under=0\n", 1),
            (".github/workflows/a.yml", "run: python -m coverage report --fail-under 0\n", 1),
            (".github/workflows/a.yml", "run: |\n  coverage report \\\n    --fail-under=0\n", 1),
            (".github/workflows/a.yml", "run: >-\n  coverage report\n  --fail-under=0\n", 1),
            (".github/workflows/a.yml", "run: |\n  # pytest --cov-fail-under=0\n", 0),
            (".github/workflows/a.yml", "run: coverage report && pylint --fail-under=9\n", 0),
            ("package.json", '{"//--cov-fail-under": "its place is the configuration"}', 0),
            ("a/pyproject.toml", "a = 1  # pytest --cov-fail-under=1\n", 0),
            ("package.json", '{"scripts": {"t": "pytest --cov-fail-under=1"}}', 1),
            ("a/pyproject.toml", '[tool.pytest]\naddopts = ["--cov-fail-under=1"]\n', 1),
            ("pytest.ini", "[pytest]\naddopts = --cov-fail-under=1\n", 1),
            ("docs/pytest.md", "pytest --cov-fail-under=1\n", 0),
        ):
            with self.subTest(text):
                path = fx.write(self.root, rel, text)
                self.assertEqual(len(self.check()), count)
                path.unlink()

    def test_the_markers_of_a_tree(self) -> None:
        fx.write(self.root, "tests/test_a.py", "import pytest\npytest.skip()\n")
        fx.write(self.root, "tests/a.test.ts", "it.only('x');\nit.skip('y');\n")
        fx.write(self.root, "src/a.ts", "it.only('x');\n")
        fx.write(self.root, "tests/broken.py", "pytest.skip(\n")
        fx.write(self.root, "node_modules/x/a.test.js", "it.only('x');\n")
        rules = [(p.rule, p.where) for p in sr.check(cq.Repo(self.root), self.base)[0]]
        self.assertEqual(
            rules,
            [
                ("skip", "tests/broken.py"),
                ("skip", "tests/test_a.py:2"),
                ("only", "tests/a.test.ts:1"),
                ("skip", "tests/a.test.ts:2"),
            ],
        )


class WorkflowBaseTest(unittest.TestCase):
    """The lint job says which commit a change is compared with."""

    def test_the_base_of_each_event(self) -> None:
        path = fx.CENTRAL / ".github/workflows/reusable-lint.yml"
        job = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]["lint"]
        self.assertEqual(job["steps"][0]["with"]["fetch-depth"], 0)
        (step,) = [s for s in job["steps"] if "BASE" in s.get("env", {})]
        self.assertIn('--base "${BASE}"', step["run"])
        said = step["env"]["BASE"].removeprefix("${{").removesuffix("}}").strip()
        for event, want in (
            ({"pull_request": {"base": {"sha": "b"}}, "before": "a"}, "b"),
            ({"before": "a", "forced": False}, "a"),
            ({"before": "a", "forced": True}, ""),
            ({}, ""),
        ):
            with self.subTest(event):
                context = {"github": {"event": event}}
                self.assertEqual(expressions.evaluate(said, context), want)


if __name__ == "__main__":
    unittest.main()
