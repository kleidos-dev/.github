# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""suite_rules.py: every way a change may weaken the tests unsaid is found, and nothing else is."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path

import expressions
import kit_fixtures as fx
import yaml
from kit_fixtures import check_quality as cq
from kit_fixtures import js_text
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
            # The comment beside another statement is that statement's.
            "x = 1  # skip: a reason for x\n@unittest.expectedFailure\ndef f(): ...\n",
            "@unittest.expectedFailure  # skip: upstream bug 12\ndef f(): ...  #\n"
            "x = 1  #\n@unittest.expectedFailure\ndef g(): ...\n",
            # A reason with nothing in it, however it is put together.
            "@unittest.skip('' + '')\ndef f(): ...\n",
            "@unittest.skip(f'')\ndef f(): ...\n",
            "@unittest.skip(f\"{''}\")\ndef f(): ...\n",
            "@unittest.skip('x' * 20)\ndef f(): ...\n",
            "@unittest.skip('' if 1 else 'x')\ndef f(): ...\n",
            "@unittest.skip(*[''])\ndef f(): ...\n",
            "@unittest.skipIf(*[True, ''])\ndef f(): ...\n",
            "pytest.skip(**{'reason': ''})\n",
            "pytest.skip(allow_module_level=flag)\n",
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
            "pytest.skip(*['needs the bench'])\n",
            "pytest.skip('needs ' + 'the bench')\n",
            "pytest.skip(f'needs the {1}')\n",
            "pytest.skip(why[0])\npytest.skip(why.text)\npytest.skip(why())\n",
            "pytest.skip((lambda: 1) or '')\npytest.skip([x for x in ()])\n",
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
            ("from unittest import *\n@skip('')\ndef f(): ...\n", 1),
            ("from unittest import *\n@expectedFailure\ndef f(): ...\n", 1),
            ("from unittest.case import *\nraise SkipTest\n", 1),
            ("from pytest import *\n@mark.skip\ndef f(): ...\n", 1),
            ("from pytest import *\nxfail()\nskip.Exception()\n", 2),
            ("from unittest.mock import *\n@skip\ndef f(): ...\n", 0),
            ("from other import *\n@skip\ndef f(): ...\n", 0),
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
            "let s = 'one line;\nit.only('x', f)",
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
            # A regular expression after `)`, and a quote inside it.
            "if (globalThis) /'/.test('a'); it.only('x', f); /'/",
            "if (x) /`/.test(y);\nit.only('a');\nif (x) /`/.test(y);",
            "while (x()) /'/.test(y); it.only('a'); '",
            "for await (const x of y) /'/.test(x); it.only('a'); '",
            "do {} while (x) /'/.test(y); it.only('a'); '",
            "f(x) / 2; it.only('a'); g(x) / 2",
            "a.if(x) / 2; it.only('a'); g / 2",
            "a?.while(x) / 2; it.only('a'); g / 2",
            # What only a parser can tell: judged as it is written.
            "if (x) {} /'/.test(y); it.only('a'); /'/.test(y)",
            "i++ / 2; it.only('a'); j / 2",
            "i-- / 2; it.only('a'); j / 2",
            "x! / 2; it.only('a'); y! / 2",
            "const h = 1. / 2; it.only('a'); const k = 3 / 1",
            "of / 2; it.only('a'); yield / 2; await / 2",
            "a < /'/; it.only('a'); '",
            ") / 2; it.only('a'); b / 2",
            # A word that is a property, a value that is a name, a string or a list.
            "x.return / 2; it.only('a'); y / 2",
            "x?.in / 2; it.only('a'); y / 2",
            "'a' / 2; it.only('a'); y / 2",
            "`a` / 2; it.only('a'); y / 2",
            "/a/ / 2; it.only('a'); y / 2",
            "x[0] / 2; it.only('a'); y / 2",
            "return /'/.test(x); it.only('a'); /'/",
            "#!/usr/bin/env node's\nit.only('a')",
            "const s = `${/'/.test(x)}`; it.only('a'); '`'",
            "x = /`\nit.only('a'); `",
            "yield /'/.test(x); it.only('a'); /'/",
            "(c ? it['only'] : it)('a')",
            # The key or the member written as a string.
            "it('a', { \"only\": true }, f)",
            "it('a', { 'skip': false, 'only': true }, f)",
            "it('a', { ['only']: true }, f)",
            "it('a', { `only`: true }, f); it['only']('b', f)",
            "it['only']('a', f)",
            "it[ `only` ]('a', f)",
            "it?.['only']('a', f)",
            "it['concurrent']['only']('a', f)",
            # Any value that is on, in a test's own call.
            "it('a', { only: !0 }, f)",
            "it('a', { only: 1 }, f)",
            "it('a', { only: ALONE }, f)",
            "it('a', { only: ['x'] }, f)",
            "it('a', { only: 'x' }, f)",
            "it('a', { only: /* c */ true }, f)",
            "it('a', { only: false || true }, f)",
            "it('a', { only }, f)",
            "it('a', { timeout: 1, only, }, f)",
            "it('a', { only() {} }, f)",
            "it<Foo>('a', { only: ['x'] }, f)",
            "it({ only: ['x'] }, f)",
            "it.each([1])('a', { only: Alone }, f)",
            "t.test('a', { only: !0 }, f)",
            "const opts = { only: !0 };",
            "describe('a', { only: x && y }, f)",
            "const opts = { only: ALONE };",
            "const opts = { only: false || true };",
            'const opts = { "only": true };',
            "])({ only: true })",
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
            "it('a', { only: false }, f); it('b', { only: undefined, skip: !1 }, f)",
            "it('a', { only: null, skip: 0, todo: false }, f)",
            "f({ only: { a: 1 } }); f({ only: 'a' }); f({ only: `a` })",
            "it('a', () => { f({ only: ['a'] }); g([{ only: ['b'] }]); })",
            "it('a', f([{ only: ['a'] }])); f({ b: { only: ['a'] } })",
            "const { only, skip } = f(); pick({ only, skip })",
            "type A = { todo: Item[]; only: Item };",
            "type A = { only: string[] | null, skip: boolean };",
            "const r = { 'only': 1 }['only']; x['only'](1); y = ['only'];",
            "const skip = { skip: 10, todo: 1_0.5 };",
            "const o = { only: [1], 'a-b': 'c' }; const p = cond ? 'only' : 'b';",
            "case 'only': f()",
            "if (x) /it.only/.test(y)",
            "x = y ? /it.only/ : 1; typeof /it.skip/; !/it.only/",
            "#!/usr/bin/env node --x='\n// it.only",
            "a / 2; b / 2; // it.only",
            "const half = a / 2; // it.only",
            "f(x) / 2; g(x) / 2; // it.only",
            "f({ 'x, only': true }); g({ 'it.only': 1 })",
            "x = it['only', f]; f([it, 'only'])",
            "const z = it ?['only'] : 1; const q = 'it'.only; f(a, 'it'.only)",
            "x = '</b>'; y = '<br/>'; // it.only",
            "const o = { only: ['a'] }; it;",
            "it('a', () => { skip(); }); it('b', function () { only(1); });",
            "it('a', () => ({ only: ['a'] })); it('a', b ? { only: ['a'] } : c)",
            "[1, { only: ['a'] }]; it;",
            "x = it[`${a}only`]; x = { [`${a}only`]: true }",
            "a = `b`; it.skipped(`${c}`, /`/); // it.only",
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
            "f(); // skip: a reason for f\nit.skip('x', f);",
            "it.skip('a', f); // skip: waits for x\nit.skip('b', f);",
            "const a = `\n// skip: a reason in a text\n`; it.skip('x', f)",
            "test('x', { \"skip\": true }, f)",
            "test('x', { 'todo': 'later' }, f)",
            "test('x', { skip: 10 }, f)",
            "test('x', { skip }, f)",
            "test('x', { skip() {} }, f)",
            "test('x', { skip: Reason }, f)",
            "it['skip']('x', f)",
            "const o = { skip: false || x };",
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
            "test('x', { 'skip': 'no docker here' }, f)",
            "test('x', { skip: /* here */ 'no docker here' }, f)",
            "/* skip: waits for x */ it.skip('a', f) // note",
            "it.skip('a', f) /* note */ // skip: waits for x",
            "f(`never closed\n// skip: waits for x\nit.skip('a', f)",
            "`never closed\nit('a', { skip: 'see http://a.b for why' }, f)",
        ):
            with self.subTest(text):
                self.assertEqual(sr.js_marks(text), ([], []), text)

    def test_the_line_is_the_markers(self) -> None:
        self.assertEqual(sr.js_marks("a\n\nit.only('x')\nxit('y')\n"), ([3], [4]))
        self.assertEqual(sr.js_marks("\nit\n  .only('x')"), ([3], []))

    def test_jsx_is_judged_as_it_is_written(self) -> None:
        text = "render(<p>'</p>); it.only('x', f); render(<p>'</p>)"
        self.assertEqual(sr.js_marks(text, jsx=True)[0], [1])
        self.assertEqual(len(sr.js_marks("<br/>; // it.only", jsx=True)[0]), 1)
        # With no element in it, it is read as any other.
        self.assertEqual(sr.js_marks("f<T>(x) // it.only", jsx=True), ([], []))
        said = "// skip: waits for x\nit.skip('x', () => <br/>); /* never closed"
        self.assertEqual(sr.js_marks(said, jsx=True), ([], []))
        for rel, want in (("a.tsx", True), ("a.jsx", True), ("a.ts", False), ("a.js", False)):
            self.assertIs(js_text.is_jsx(rel), want)

    def test_a_long_file_is_read_in_one_pass(self) -> None:
        text = "x(); // a comment\n" * 20_000 + "it.only('x', f);"
        self.assertEqual(sr.js_marks(text), ([20_001], []))

    def test_every_place_keeps_its_length(self) -> None:
        for text in (
            "/* a\nb */ it['only']('x', { \"skip\": `a\n${'b'}` }) // c",
            "#!x\n/a\\/[/]b/g; '\\\n'",
            "it['only'] // never `",
            "`never",
        ):
            with self.subTest(text):
                js = js_text.JsText(text)
                for view in (js.code, js.bare, js.keyed):
                    self.assertEqual(len(view), len(text))
                    self.assertEqual(
                        [i for i, c in enumerate(view) if c == "\n"],
                        [i for i, c in enumerate(text) if c == "\n"],
                    )

    def test_where_brackets_close(self) -> None:
        self.assertEqual(js_text.braced("{[()]}x", 0), 5)
        self.assertIsNone(js_text.braced("{[()]", 0))
        self.assertEqual(js_text.members("{a,[b,c],{d,e}}", 0, 14), [(1, 2), (3, 8), (9, 14)])
        self.assertEqual(js_text.members("{}", 0, 1), [(1, 1)])

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


def given(files: dict[str, str]) -> dict[str, list[float]]:
    """The thresholds of a tree, with no file they are read in."""
    return {k: h.values for k, h in sr.thresholds(files, files.__getitem__).items()}


class ThresholdsTest(unittest.TestCase):
    def test_every_place_a_tool_reads_one(self) -> None:
        run = "node --test --test-coverage-lines=100 --test-coverage-branches 95.5"
        for rel, text, want in (
            ("pyproject.toml", "[tool.coverage.report]\nfail_under = 100\n", [100]),
            ("pyproject.toml", "[tool.coverage.report]\nfail_under = true\n", []),
            ("pyproject.toml", "[tool.coverage.report]\nfail_under = nan\n", []),
            ("pyproject.toml", "[tool.coverage.report]\nfail_under = [1]\n", []),
            ("pyproject.toml", "[tool.coverage.run]\nbranch = true\n", []),
            ("pyproject.toml", "not toml", []),
            (
                "pyproject.toml",
                "[tool.coverage.run]\nbranch = true\n[report]\nfail_under = 100\n",
                [],
            ),
            ("setup.cfg", "[coverage:run]\nbranch = 1\n[report]\nfail_under = 80\n", []),
            ("pyproject.toml", "[report]\nfail_under = 100\n", None),
            ("pyproject.toml", "tool = 1\n", None),
            ("pyproject.toml", "[tool]\ncoverage = 1\n", None),
            (".coveragerc.toml", "[tool.coverage.report]\nfail_under = 7\n", [7]),
            (".coveragerc.toml", "[report]\nfail_under = 8\n", [8]),
            (".coveragerc.toml", "", []),
            (".coveragerc", "[report]\nfail_under = 90\n", [90]),
            (".coveragerc", "\ufeff[report]\nfail_under = 90\n", [90]),
            (".coveragerc", "[coverage:report]\nfail_under = 4\n[report]\nfail_under = 9\n", [4]),
            (".coveragerc", "[coverage:report]\na = 4\n[report]\nfail_under = 9\n", []),
            (".coveragerc", "[report]\nfail_under = many\n", []),
            (".coveragerc", "[report]\nfail_under = 9%\n", []),
            (".coveragerc", "fail_under = 90\n", []),
            (".coveragerc", "", []),
            ("setup.cfg", "[coverage:report]\nfail_under = 80\n", [80]),
            ("setup.cfg", "[coverage:run]\nbranch = true\n", []),
            ("setup.cfg", "[report]\nfail_under = 80\n", None),
            ("tox.ini", "[report]\nfail_under = 80\n", None),
        ):
            with self.subTest(rel=rel, text=text):
                key = "coverage fail_under"
                self.assertEqual(given({rel: text}), {} if want is None else {key: want})
                host = {} if want is None else {f"host/{key}": want}
                self.assertEqual(given({f"host/{rel}": text}), host)
        for rel, text, flags in (
            (
                "package.json",
                json.dumps({"scripts": {"t": run}}),
                {"lines": [100], "branches": [95.5]},
            ),
            ("package.json", "{", {}),
            ("package.json", "[]", {}),
            ("package.json", '{"scripts": 1}', {}),
            ("package.json", '{"a": {"thresholds": {"lines": 9}}}', {}),
            ("package.json", json.dumps({"description": run, "config": {"t": run}}), {}),
            (
                "package.json",
                json.dumps({"scripts": {"a": run, "b": run, "c": 1}}),
                {"lines": [100, 100], "branches": [95.5, 95.5]},
            ),
            ("package.json", json.dumps({"scripts": [run]}), {"lines": [100], "branches": [95.5]}),
            (
                ".github/workflows/ci.yml",
                f"# {run}\njobs:\n  a:\n    steps:\n    - run: |\n        # {run}\n"
                "        node --test-coverage-lines=99 && node '--test_coverage_lines=100'\n"
                "        node x # --test-coverage-lines=98\n"
                "        node y;# --test-coverage-lines=9\n"
                "        echo --test-coverage-lines=97\n        : --test-coverage-lines=96\n"
                "        node --x='#' --test-coverage-lines=95 --test-coverage-lines=94\n"
                f"    - name: {run}\n      env:\n        A: {run}\n",
                {"lines": [99, 100, 94]},
            ),
            (
                ".github/workflows/ci.yml",
                f"jobs:\n  a:\n    uses: x\n    with:\n      tests: {run}\n      name: {run}\n",
                {"lines": [100], "branches": [95.5]},
            ),
            (
                ".github/actions/a/b/action.yml",
                f"runs:\n  steps:\n  - run: {run}\n",
                {"lines": [100], "branches": [95.5]},
            ),
            (".github/workflows/ci.yml", "a: [", {}),
            (".github/workflows/ci.yml", "jobs: [1]", {}),
        ):
            with self.subTest(rel=rel, text=text):
                self.assertEqual(given({rel: text}), {f"{rel} {k}": v for k, v in flags.items()})

    def test_the_thresholds_of_vitest(self) -> None:
        bad = sr.UNREADABLE
        every = ("lines", "functions", "branches", "statements")
        for text, want in (
            ("{ lines: 100 }", {"lines": [100]}),
            ("{ lines: -10, branches: 9.5, }", {"lines": [-10], "branches": [9.5]}),
            ("{ 'lines': 100, \"branches\": 9 }", {"lines": [100], "branches": [9]}),
            ("{ lines: 100, 'lines': 1 }", {"lines": [1]}),
            ("{ lines: /* 100 */ 1 }", {"lines": [1]}),
            ("{ lines: 100 - 50 }", {"lines": [bad]}),
            ("{ lines: 1_00 }", {"lines": [bad]}),
            ("{ lines: LOW }", {"lines": [bad]}),
            ("{ lines: '100' }", {"lines": [bad]}),
            ("{ lines: 100, ...LOW }", {"lines": [bad]}),
            ("{ lines: 100, ['lines']: 1 }", {"lines": [bad]}),
            ("{ lines: 100, l\\u0069nes: 1 }", {"lines": [bad]}),
            ("{ lines: 100, '\\x6cines': 1 }", {"lines": [bad]}),
            ("{ lines: 100, 1e2: 1 }", {"lines": [bad]}),
            ("{ lines }", {}),
            ("{ lines: 100 } && LOW", {"lines": [bad]}),
            ("{ lines: 100", {}),
            ("{ 100: true }", {m: [100] for m in every}),
            ("{ '100': true }", {m: [100] for m in every}),
            ("{ 100: false }", {}),
            ("{ 100: true, '100': false }", {}),
            ("{ 100: YES }", {m: [bad] for m in every}),
            ("{ perFile: true, autoUpdate: true }", {"perFile": [1]}),
            ("{ perFile: false }", {"perFile": [0]}),
            ("{ perFile: x }", {"perFile": [bad]}),
            ("{ lines: 90, 'src/a/**': { lines: 100 } }", {"lines": [90], "src/a/** lines": [100]}),
            ("{ 'a': { lines: 9 }, 'a': { branches: 8, m: 1 } }", {"a branches": [8]}),
            ("{ a: { 100: true } }", {f"a {m}": [100] for m in every}),
            ("{ a: { lines: 9, ...LOW }, lines: 8 }", {"a lines": [bad], "lines": [8]}),
            ("{ lines: 9, a: LOW }", {"lines": [bad]}),
            ("{ lines: 9, a: { lines: 8 } && LOW }", {"lines": [bad]}),
            ("{ lines: 9 }, thresholds: { lines: 8 }", {"lines": [9, 8]}),
            ("limits", {}),
        ):
            for start in ("thresholds: ", "x({ a: 1, 'thresholds': ", '{ "thresholds" : '):
                with self.subTest(start + text):
                    end = " }" if not text.endswith("100") and "{" in start else ""
                    found = given({"vitest.config.ts": start + text + end})
                    self.assertEqual(found, {f"vitest {k}": v for k, v in want.items()})
        for text in (
            "// thresholds: { lines: 100 }",
            "const s = 'thresholds: { lines: 100 }';",
            "const s = {}['thresholds: { lines: 100 }'];",
            "x = { mythresholds: { lines: 100 } }",
            "x = { a: 1 /*, thresholds: { lines: 100 } */ } `never closed",
        ):
            with self.subTest(text):
                self.assertEqual(given({"vitest.config.ts": text}), {})

    def test_the_file_that_is_read_is_the_one_that_counts(self) -> None:
        held = "[tool.coverage.report]\nfail_under = 100\n"
        key = "coverage fail_under"
        want: Sequence[float] | None
        for first, text, want in (
            (".coveragerc", "[run]\nbranch = true\n", []),
            (".coveragerc", "[report]\nfail_under = 0\n", [0]),
            (".coveragerc", "not a configuration", []),
            (".coveragerc.toml", "", []),
            ("setup.cfg", "[coverage:run]\nbranch = true\n", []),
            ("tox.ini", "[coverage:report]\nfail_under = 1\n", [1]),
            ("tox.ini", "[tox]\n", [100]),
            ("setup.cfg", "[metadata]\n", [100]),
            ("host/.coveragerc", "", [100]),
        ):
            with self.subTest(first=first, text=text):
                found = given({"pyproject.toml": held, first: text})
                self.assertEqual(found[key], want)
        config = "x = { thresholds: { lines: %d } }"
        for files, want in (
            ({"vite.config.mjs": 100, "vitest.config.mjs": None}, None),
            ({"vite.config.ts": 100, "vitest.config.cjs": 5}, [5]),
            ({"vitest.config.mts": 1, "vitest.config.ts": 2}, [2]),
            ({"vitest.config.cjs": 1, "vitest.config.mjs": 2, "vite.config.ts": 3}, [2]),
        ):
            with self.subTest(files):
                found = given({k: "x = {}" if v is None else config % v for k, v in files.items()})
                self.assertEqual(found, {} if want is None else {"vitest lines": want})
        # One that takes in the next does not hide it, and one a command names is its own.
        merged = "import base from './vite.config'; export default mergeConfig(base, {})"
        found = given({"a/vitest.config.ts": merged, "a/vite.config.ts": config % 7})
        self.assertEqual(found, {"a/vitest lines": [7]})
        self.assertEqual(given({"vitest.config.ts": merged}), {})
        for text in ("// from './vite.config'", "x = 'vite.config'", "const a = './vite.config'"):
            with self.subTest(text):
                self.assertEqual(
                    given({"vitest.config.ts": text, "vite.config.ts": config % 7}), {}
                )
        found = given({"vitest.config.ts": config % 7, "vitest.ci.config.mjs": config % 8})
        self.assertEqual(found, {"vitest lines": [7], "vitest.ci.config.mjs lines": [8]})

    def test_only_those_files_are_read(self) -> None:
        def refuse(rel: str) -> str:
            raise AssertionError(rel)

        names = ["src/a.py", "node_modules/x/package.json", "docs/ci.yml", "a/vitest.txt"]
        self.assertEqual(sr.thresholds(names, refuse), {})

    def test_a_fall_is_found_and_a_rise_is_not(self) -> None:
        bad = sr.UNREADABLE
        old: Sequence[float]
        new: Sequence[float]
        for old, new, want in (
            ([100], [99], [(100, 99)]),
            ([90], [95], []),
            ([5], [], [(5, None)]),
            ([], [5], []),
            ([100], [100], []),
            # Losing one of several, and one more with less than any had.
            ([100, 100], [100], [(100, None)]),
            ([100, 90], [90, 100], []),
            ([100, 90], [100], [(90, None)]),
            ([100, 100], [99, 99], [(100, 99)]),
            ([100, 90], [95, 90], [(100, 95)]),
            ([100, 90], [100, 91, 90], []),
            ([100], [100, 1], [(100, 1)]),
            # What cannot be read holds nothing.
            ([100], [bad], [(100, bad)]),
            ([100], [100, bad], [(100, bad)]),
            ([bad], [], []),
            ([bad], [bad], []),
            ([bad], [1], []),
            # vitest counts below 0.
            ([-10], [-5], []),
            ([-5], [-10], [(-5, -10)]),
            ([-1], [1], [(-1, 1)]),
            ([-1], [0], [(-1, 0)]),
            ([-1], [100], []),
            ([0], [1], []),
        ):
            with self.subTest(old=old, new=new):
                self.assertEqual(sr.falls(old, new), want)
        before = {k: sr.Held("f", [v]) for k, v in (("a", 100.0), ("b", 90.0), ("c", 5.0))}
        now = {"a": sr.Held("f", [99.0]), "b": sr.Held("f", [95.0]), "d": sr.Held("f", [1.0])}
        self.assertEqual(sr.fallen(before, now), [("a", 100.0, 99.0), ("c", 5.0, None)])
        self.assertEqual(sr.fallen(before, before), [])

    def test_an_entry_accepts_the_fall_it_names_and_no_other(self) -> None:
        good = {"threshold": "a", "to": 99, "reason": "the reader moved out", "decided": "owner"}
        self.assertTrue(sr.accepts(good, "a", 99.0))
        self.assertTrue(sr.accepts(good | {"to": "gone"}, "a", None))
        self.assertTrue(sr.accepts(good | {"to": "unreadable"}, "a", sr.UNREADABLE))
        self.assertTrue(sr.accepts(good | {"to": 99.0}, "a", 99.0))
        self.assertFalse(sr.accepts(good, "a", sr.UNREADABLE))
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
            f'\n[[lowered]]\nthreshold = "coverage fail_under"\nto = {to}\n'
            'reason = "the reader moved out"\ndecided = "owner 2026-11-25"\n'
        )

    def test_a_threshold_that_falls_is_found(self) -> None:
        self.assertEqual(self.check(), [])
        fx.write(self.root, "pyproject.toml", self.CONFIG.format(99.5))
        (found,) = self.check()
        move = "went from 100 in pyproject.toml to 99.5 in pyproject.toml since"
        self.assertTrue(found.startswith(f"coverage fail_under: [threshold] {move} "), found)
        self.assertIn("to = 99.5, reason, decided)", found)
        fx.commit(self.root)
        self.assertEqual(len(self.check()), 1)

    def test_a_threshold_that_goes_is_found(self) -> None:
        fx.write(self.root, "pyproject.toml", fx.header())
        (found,) = self.check()
        self.assertIn('went from 100 in pyproject.toml to "gone" since', found)
        self.assertIn('to = "gone"', found)
        (self.root / "pyproject.toml").unlink()
        self.assertEqual(len(self.check()), 1)

    def test_a_rise_passes(self) -> None:
        fx.write(self.root, "pyproject.toml", self.CONFIG.format(100.5))
        self.assertEqual(self.check(), [])

    def test_a_file_that_is_read_first_is_found(self) -> None:
        fx.write(self.root, ".coveragerc", fx.header() + "[run]\nbranch = true\n")
        (found,) = self.check()
        self.assertIn('from 100 in pyproject.toml to "gone" in .coveragerc since', found)
        fx.write(self.root, ".coveragerc", fx.header() + "[report]\nfail_under = 100\n")
        self.assertEqual(self.check(), [])
        # The threshold moves with the file it is read in.
        fx.commit(self.root)
        moved = fx.git(self.root, "rev-parse", "HEAD").strip()
        (self.root / ".coveragerc").unlink()
        fx.write(self.root, "pyproject.toml", self.CONFIG.format(99))
        self.assertEqual(len(self.check(moved)), 1)

    def test_a_flag_that_leaves_one_of_its_commands_is_found(self) -> None:
        flag = "--test-coverage-lines=100"
        before = {"scripts": {"a": f"node {flag} a", "b": f"node {flag} b"}}
        workflow = "jobs:\n  t:\n    steps:\n    - run: node --test {} a\n"
        fx.write(self.root, "package.json", json.dumps(before))
        path = ".github/workflows/t.yml"
        fx.write(self.root, path, workflow.format(flag))
        fx.commit(self.root)
        base = fx.git(self.root, "rev-parse", "HEAD").strip()
        self.assertEqual(self.check(base), [])
        for rel, text in (
            ("package.json", json.dumps({"scripts": before["scripts"] | {"b": "node b"}})),
            ("package.json", json.dumps({"scripts": {"a": f"node {flag}"}, "description": flag})),
            (path, workflow.format("a #" + flag)),
            (path, workflow.format("a") + f"      name: node --test {flag}\n"),
        ):
            with self.subTest(text):
                old = (self.root / rel).read_text(encoding="utf-8")
                fx.write(self.root, rel, text)
                self.assertEqual(len(self.check(base)), 1)
                fx.write(self.root, rel, old)

    def test_a_new_entry_says_it_and_an_old_one_does_not(self) -> None:
        fx.write(self.root, "pyproject.toml", self.CONFIG.format(99))
        fx.write(self.root, cq.WAIVERS, fx.header() + self.entry("99"))
        self.assertEqual(self.check(), [])
        (note,) = sr.check(cq.Repo(self.root), self.base)[1]
        move = "went from 100 in pyproject.toml to 99 in pyproject.toml since"
        self.assertIn(f"lowered: coverage fail_under {move}", note)
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
            (".github/workflows/a.yml", "run: coverage report --fail-un=0\n", 1),
            (".github/workflows/a.yml", "run: coverage report --fa 0\n", 1),
            (".github/workflows/a.yml", "run: [coverage report --fail-under=0\n", 0),
            (".github/workflows/a.yml", "run: coverage report --format=total\n", 0),
            (".github/workflows/a.yml", "run: coverage report '--fail-'under=0\n", 1),
            (".github/workflows/a.yml", "run: coverage report # --fail-under=0\n", 0),
            (".github/workflows/a.yml", "a: &a\n  b: *a\n  c: coverage xml --fail-under=0\n", 1),
            (".github/actions/a/action.yaml", "run: pytest --cov-fail-under=0\n", 1),
            (".github/workflows/a.yml", "run: coverage report && pylint --fail-under=9\n", 0),
            ("package.json", '{"//--cov-fail-under": "its place is the configuration"}', 0),
            ("a/pyproject.toml", "a = 1  # pytest --cov-fail-under=1\n", 0),
            ("a/pyproject.toml", 'a = "--cov-fail-\\u0075nder=1"\n', 1),
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
        fx.write(self.root, "tests/b.test.tsx", "f(<br/>); // it.only\n")
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
                ("only", "tests/b.test.tsx:1"),
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
