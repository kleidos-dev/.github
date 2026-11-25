#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""What a change may not do to a repository's tests without saying so.

The part of the testing standard (docs/testing.md) that can be held the same
way in every repository, whatever it measures:

  only       no test is marked to run alone: every other one stops running
             and the suite still passes
  skip       a test that does not run, or may fail, says why
  threshold  a coverage threshold the tools read never falls or goes against
             the base of the change, unless the change adds a [[lowered]]
             entry to .github/quality/waivers.toml that says why; what is
             compared is what the tool would use, so a file that is read
             before the one that holds it counts. And coverage.py's is in its
             configuration, not on a command line

Python is read as Python (unittest, pytest). JavaScript and TypeScript are
read as text with the comments and strings taken out (js_text.py; vitest,
node:test and what spells its markers as they do). What it cannot see, and
what each repository holds by itself, is in docs/testing.md, "What the kit
holds".

Python 3.14 or newer, git.
"""

from __future__ import annotations

import ast
import configparser
import io
import json
import math
import re
import subprocess
import tokenize
import tomllib
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import check_quality as cq
import js_text
import yaml
from js_text import JsText

PY_SUFFIXES = (".py", ".pyi")
JS_SUFFIXES = js_text.SUFFIXES


@dataclass(frozen=True)
class Problem:
    """A problem: the rule, where, and what is wrong."""

    rule: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: [{self.rule}] {self.message}"


def worded(text: str) -> bool:
    """Whether a text says something: two words at least."""
    return len(re.findall(r"[^\W\d_]{2,}", text)) >= 2


# A reason beside a marker that has no place for one.
COMMENT_REASON = re.compile(r"\bskip:\s*(?P<why>.*)", re.IGNORECASE)
NO_REASON = (
    "says no reason: give it one (two words at least), or a comment `skip: <why>` on its line"
    " or right above"
)
ONLY = "runs alone: every other test of its file stops running and the suite still passes"


def reasoned(comments: dict[int, list[str]], alone: set[int], first: int, last: int) -> bool:
    """Whether a comment on these lines, or in the lines of comment right above, says why."""
    while first - 1 in alone:
        first -= 1
    return any(
        worded(found["why"])
        for line in range(first, last + 1)
        for text in comments.get(line, ())
        for found in COMMENT_REASON.finditer(text)
    )


# --------------------------------------------------------------------------
# Python

# Where each marker takes its reason: the position of the argument, or None
# where only the keyword does. pytest.importorskip says its own (the module
# it did not find), so it is not here.
MARKERS: dict[str, int | None] = {
    "unittest.skip": 0,
    "unittest.skipIf": 1,
    "unittest.skipUnless": 1,
    "unittest.SkipTest": 0,
    "pytest.skip": 0,
    "pytest.skip.Exception": 0,
    "pytest.xfail": 0,
    "pytest.mark.skip": 0,
    "pytest.mark.skipif": None,
    "pytest.mark.xfail": None,
}
# It takes no reason at all: a comment says it.
NO_PLACE = "unittest.expectedFailure"
REASON_WORDS = ("reason", "msg")
PY_HINT = re.compile(r"skip|xfail|expectedFailure", re.IGNORECASE)
# What an expression is made of when its value is not written where it stands.
COMPUTED = (ast.Name, ast.Call, ast.Attribute, ast.Subscript, ast.Lambda, ast.comprehension)


def star_names(module: str) -> dict[str, str]:
    """The markers `from <module> import *` brings."""
    prefix = f"{module.replace('unittest.case', 'unittest')}."
    names = {m.removeprefix(prefix) for m in (*MARKERS, NO_PLACE) if m.startswith(prefix)}
    return {top: prefix + top for top in (name.partition(".")[0] for name in names)}


def imported_names(tree: ast.Module) -> dict[str, str]:
    """What each imported name stands for."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.partition(".")[0]
                out[alias.asname or top] = alias.name if alias.asname else top
        elif isinstance(node, ast.ImportFrom) and not node.level:
            for alias in node.names:
                if alias.name == "*":
                    out |= star_names(str(node.module))
                else:
                    out[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return out


def dotted(node: ast.expr, names: dict[str, str]) -> str:
    """The marker an expression names, as MARKERS spells it; empty for anything else."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if parts and parts[0] == "skipTest":
        return "unittest.SkipTest"  # self.skipTest(reason), whatever the case is called
    if not isinstance(node, ast.Name) or node.id not in names:
        return ""
    name = ".".join([names[node.id], *reversed(parts)])
    return name.replace("unittest.case.", "unittest.")


def text_says_why(reason: ast.expr) -> bool:
    """Whether an expression says why: the text it holds, unless it is made when it runs."""
    if any(isinstance(n, COMPUTED) for n in ast.walk(reason)):
        return True
    parts = (n.value for n in ast.walk(reason) if isinstance(n, ast.Constant))
    return worded("".join(p for p in parts if isinstance(p, str)))


def says_why(call: ast.Call, position: int | None) -> bool:
    """Whether a marker's call gives a reason: a text that says something, or a computed one."""
    given = [k.value for k in call.keywords if k.arg in REASON_WORDS]
    if not given and position is not None and len(call.args) > position:
        given = [call.args[position]]
    if not given:
        # It may be among what *args or **kwargs hold.
        given = [a for a in call.args if isinstance(a, ast.Starred)]
        given += [k.value for k in call.keywords if k.arg is None]
        return any(text_says_why(g) for g in given)
    return text_says_why(given[0])


def bare_markers(tree: ast.Module, names: dict[str, str]) -> Iterator[ast.expr]:
    """The markers used with no call: `@unittest.skip`, `pytest.mark.skip`, `raise SkipTest`."""
    called = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield from node.decorator_list
        elif isinstance(node, ast.Raise) and node.exc:
            yield node.exc
        elif (
            isinstance(node, ast.Attribute)
            and id(node) not in called
            and dotted(node, names).startswith("pytest.mark.")
        ):
            yield node


def python_comments(text: str) -> tuple[dict[int, list[str]], set[int]]:
    """The comments of a Python file by line, and the lines that hold nothing else."""
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    found = [t for t in tokens if t.type == tokenize.COMMENT]
    alone = {t.start[0] for t in found if not t.line[: t.start[1]].strip()}
    return {t.start[0]: [t.string] for t in found}, alone


def python_skips(text: str) -> list[int]:
    """The lines of a Python file where a test is skipped, or may fail, with no reason."""
    if not PY_HINT.search(text):
        return []
    tree = ast.parse(text)
    names = imported_names(tree)
    comments, alone = python_comments(text)
    bad: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = dotted(node.func, names)
        if name == NO_PLACE or (name in MARKERS and not says_why(node, MARKERS[name])):
            bad.add(node.lineno)
            if reasoned(comments, alone, node.lineno, node.end_lineno or node.lineno):
                bad.discard(node.lineno)
    for bare in bare_markers(tree, names):
        name = dotted(bare, names)
        known = name == NO_PLACE or name in MARKERS
        if known and not reasoned(comments, alone, bare.lineno, bare.lineno):
            bad.add(bare.lineno)
    return sorted(bad)


# --------------------------------------------------------------------------
# JavaScript and TypeScript

# A file of tests by its place or its name, or by what it imports.
TEST_FOLDERS = {"test", "tests", "__tests__", "spec", "specs", "e2e"}
TEST_NAME = re.compile(r"\.(?:test|spec|test-d|bench)\.[cm]?[jt]sx?$")
RUNNER = re.compile(
    r"""(?:\bfrom|\bimport|\brequire\s*\()\s*["'](?:node:test|vitest|bun:test|mocha|@jest/globals|@playwright/test)["']"""
)
# What a runner calls a test or a group, and what may stand between it and
# the marker (`it.concurrent.skip`, `test.describe.only`).
TEST_NAMES = r"\b(?:describe|it|test|suite|bench)(?:\s*\??\.\s*\w+)*"
TEST_CALL = TEST_NAMES + r"?\s*\??\.\s*"
TEST_CALLED = re.compile(TEST_NAMES + r"\s*$")
JS_ONLY = re.compile(TEST_CALL + r"only\b|\b(?:fit|fdescribe|ftest)\s*\(")
JS_SKIP = re.compile(
    TEST_CALL
    + r"(?:skip|todo|fails|failing|fixme|skipIf|runIf)\b|\bx(?:it|describe|test|context)\s*\("
)
# Markers that may hold their reason: t.skip("why"), { todo: "why" }.
JS_CALL_REASON = re.compile(r"\b(?:t|ctx|context|testContext)\s*\.\s*(?:skip|todo)\s*\(")
JS_OPTION = re.compile(
    r"[{,]\s*(?P<name>only|skip|todo|fails|expectFailure)\s*(?:(?P<colon>:)|(?=[,}]))"
)
JS_STRING = re.compile(r"""(["'`])((?:\\.|(?!\1)[^\\\n])*+)\1""")
# What an option may be without marking anything: off, wherever it is; and
# away from a test's own call a type, a number (`skip: 10` pages), and for
# `only` a list, an object or a text.
JS_OFF = re.compile(r"(?:false|undefined|null|0|!1|!true)\s*(?:[,}]|$)")
JS_OTHER = re.compile(
    r"(?:(?:false|undefined|null|boolean|string|number|[A-Z]\w*[a-z]\w*)(?:\s*\[\s*\])*|\d[\d._]*)"
    r"\s*(?:[,;}]|\|(?!\|)|$)"
)
JS_LITERAL = re.compile(r"""[\[{"'`]""")


def is_js_test(rel: str, text: str) -> bool:
    """Whether a JavaScript or TypeScript file holds tests."""
    path = PurePosixPath(rel)
    return (
        bool(TEST_FOLDERS & set(path.parts[:-1]))
        or bool(TEST_NAME.search(path.name))
        or bool(RUNNER.search(text))
    )


def opening_of(code: str, at: int, opener: str) -> int:
    """The bracket a place is inside of, if it is this one; -1 when it is not."""
    depth = 0
    for i in range(at - 1, -1, -1):
        if code[i] in ")]}":
            depth += 1
        elif code[i] in "([{":
            depth -= 1
            if depth < 0:
                return i if code[i] == opener else -1
    return -1


def in_test_call(code: str, at: int) -> bool:
    """Whether an option (the brace or the comma before it) is in a test's own call."""
    brace = at if code[at] == "{" else opening_of(code, at, "{")
    paren = opening_of(code, brace, "(") if brace >= 0 else -1
    if paren < 0:
        return False
    callee = code[:paren].rstrip()
    while callee.endswith(")"):  # it.each([...])(...)
        callee = callee[: max(opening_of(callee, len(callee) - 1, "("), 0)].rstrip()
    return bool(TEST_CALLED.search(callee[-200:]))


def says_js_why(value: str) -> bool:
    """Whether a value is a text that says something."""
    given = JS_STRING.match(value)
    return given is not None and worded(given[2])


def option_marks(js: JsText) -> tuple[set[int], set[int]]:
    """The lines where an option makes a test run alone, and where one skips it with no reason."""
    only: set[int] = set()
    bad: set[int] = set()
    for m in JS_OPTION.finditer(js.keyed):
        own = in_test_call(js.keyed, m.start())
        name, line, value = m["name"], js.line(m.end() - 1), js.bare[m.end() :].lstrip()
        if not m["colon"]:
            off = not own  # `{ only }` anywhere else names a variable
        else:
            off = bool(JS_OFF.match(value) or (not own and JS_OTHER.match(value)))
        if name == "only":
            if not off and (own or not JS_LITERAL.match(value)):
                only.add(line)
        elif not off and not (m["colon"] and says_js_why(value)):
            bad.add(line)
    return only, bad


def js_marks(text: str, *, jsx: bool = False) -> tuple[list[int], list[int]]:
    """The lines where a test runs alone, and where one is skipped with no reason."""
    js = JsText(text, jsx=jsx)
    only, bad = option_marks(js)
    only |= {js.line(m.end() - 1) for m in JS_ONLY.finditer(js.keyed)}
    bad |= {js.line(m.end() - 1) for m in JS_SKIP.finditer(js.keyed)}
    for m in JS_CALL_REASON.finditer(js.keyed):
        if not says_js_why(js.bare[m.end() :].lstrip()):
            bad.add(js.line(m.end() - 1))
    alone = {n for n in js.comments if js.only_comment(n)}
    return sorted(only), [n for n in sorted(bad) if not reasoned(js.comments, alone, n, n)]


# --------------------------------------------------------------------------
# Coverage thresholds

WORKFLOW = r"^\.github/(?:workflows/[^/]+|actions/(?:[^/]+/)*action)\.ya?ml$"
THRESHOLD_FILES = re.compile(
    r"(?:^|/)(?:pyproject\.toml|\.coveragerc(?:\.toml)?|setup\.cfg|tox\.ini|package\.json"
    r"|(?:vitest|vite)\.[\w.-]*config\.[cm]?[jt]s|(?:vitest|vite)\.config\.[cm]?[jt]s"
    r"|vitest\.workspace\.[cm]?[jt]s)$|" + WORKFLOW
)
# The order each tool looks for its configuration in: the first that is
# there is read, and no other.
COVERAGE_ORDER = (".coveragerc", ".coveragerc.toml", "setup.cfg", "tox.ini", "pyproject.toml")
VITEST_ORDER = tuple(
    f"{name}.config.{end}"
    for name in ("vitest", "vite")
    for end in ("ts", "mts", "cts", "js", "mjs", "cjs")
)
VITE_IMPORT = re.compile(
    r"""\b(?:from|import|require)\s*\(?\s*["'][^"'\n]*/vite\.config(?:\.[cm]?[jt]s)?["']"""
)
NODE_FLAG = re.compile(r"--test[-_]coverage[-_](lines|branches|functions)[=\s]+(\d+(?:\.\d+)?)")
# A command that prints what it is given, or does nothing with it.
NO_COMMAND = re.compile(r"\s*(?:echo|printf|true|false|:)(?:\s|$)")
# The inputs of the kit's workflows that are commands.
COMMAND_INPUTS = ("install", "types-install", "tests", "run")
SHELL_PART = re.compile(r"""'[^']*'|"(?:\\[\s\S]|[^"\\])*"|\\[\s\S]|(?<![^\s;&|()])#[^\n]*""")
# coverage.py's threshold on a command line wins over the one in its
# configuration, which is where a person looks; coverage.py takes any
# abbreviation of its options.
COV_FLAG = re.compile(r"--cov-fail-under\b")
COVERAGE_FLAG = re.compile(r"\s--fa[a-z-]*")
COVERAGE = re.compile(r"\bcoverage3?\b")
COMMAND_FILES = re.compile(
    r"(?:^|/)(?:package\.json|pyproject\.toml|setup\.cfg|tox\.ini|\.?pytest\.ini)$|" + WORKFLOW
)
MEASURES = ("lines", "functions", "branches", "statements")
UNREADABLE = float("-inf")


@dataclass
class Held:
    """The values of one threshold, each place that gives it, and the file they are read in."""

    read_in: str
    values: list[float] = field(default_factory=list)


Thresholds = dict[str, Held]


def number(value: Any) -> float | None:
    """A threshold as a number; None when it is none."""
    try:
        given = None if isinstance(value, bool) else float(value)
    except TypeError, ValueError:
        return None
    return given if given is None or math.isfinite(given) else None


def strings(value: Any, seen: set[int] | None = None) -> Iterator[str]:
    """Every text of a document, as a tool reads it; what a YAML alias repeats, once."""
    seen = set() if seen is None else seen
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict | list) and id(value) not in seen:
        seen.add(id(value))
        for item in value.values() if isinstance(value, dict) else value:
            yield from strings(item, seen)


def shell(text: str) -> list[str]:
    """The commands of a script: no comments, its continued lines joined, its quotes taken off."""
    code = SHELL_PART.sub(lambda m: "" if m[0].startswith("#") else m[0], text)
    return re.split(r"[\n;&|]", re.sub(r"[\"'\\]", "", code.replace("\\\n", " ")))


def children(value: Any, *path: str) -> list[Any]:
    """What a document holds at a path; `*` is every one."""
    found = [value]
    for part in path:
        below: list[Any] = []
        for item in found:
            if part == "*" and isinstance(item, dict | list):
                below += item.values() if isinstance(item, dict) else item
            elif isinstance(item, dict) and part in item:
                below.append(item[part])
        found = below
    return found


def run_texts(rel: str, text: str) -> list[str]:
    """The texts of a workflow, an action or a package that run: no name, description or comment."""
    try:
        data = json.loads(text) if rel.endswith(".json") else yaml.safe_load(text)
    except yaml.YAMLError, ValueError:
        return []
    if rel.endswith(".json"):
        found = children(data, "scripts", "*")
    else:
        found = children(data, "jobs", "*", "steps", "*", "run")
        found += children(data, "runs", "steps", "*", "run")
        for name in COMMAND_INPUTS:
            found += children(data, "jobs", "*", "with", name)
    return [x for x in found if isinstance(x, str)]


def commands(rel: str, text: str) -> list[str]:
    """What may be a command in a file: a workflow's texts, a package's, pytest's options."""
    try:
        if rel.endswith((".yml", ".yaml")):
            found: Iterable[str] = strings(yaml.safe_load(text))
        elif rel.endswith(".json"):
            found = strings(json.loads(text))
        elif rel.endswith(".toml"):
            found = strings(tomllib.loads(text))
        else:
            found = [text]
    except yaml.YAMLError, ValueError:
        return []
    return [part for x in found for part in shell(x)]


def gives_threshold(parts: Iterable[str]) -> bool:
    """Whether a command gives coverage.py its threshold."""
    return any(
        COV_FLAG.search(part) or (COVERAGE_FLAG.search(part) and COVERAGE.search(part))
        for part in parts
    )


def table(value: Any, *path: str) -> dict[str, Any] | None:
    """A table of a TOML document; None when there is none."""
    found = children(value, *path)
    return found[0] if found and isinstance(found[0], dict) else None


def coverage_py(rel: str, text: str) -> tuple[bool, Any]:
    """Whether coverage.py stops at this file, and the fail_under it reads there."""
    name = PurePosixPath(rel).name
    own = name.startswith(".coveragerc")
    try:
        if name.endswith(".toml"):
            data = tomllib.loads(text)
            report = table(data, "tool", "coverage", "report")
            if report is None and own:
                report = table(data, "report")
            return own or bool(table(data, "tool", "coverage")), (report or {}).get("fail_under")
        ini = configparser.RawConfigParser()
        ini.read_string(text)
    except ValueError, configparser.Error:
        return True, None  # coverage.py stops here too
    sections = ["coverage:report", *(["report"] if own else [])]
    section = next((s for s in sections if ini.has_section(s)), "")
    used = own or any(s.startswith("coverage:") for s in ini.sections())
    return used, ini.get(section, "fail_under", fallback=None) if section else None


Pairs = list[tuple[str, float]]
JS_MEMBER = re.compile(r"""\s*(?:([\w$]+)|(["'])((?:(?!\2).)*)\2)\s*:""")


def vitest_value(name: str, value: str) -> Pairs:
    """What one measure of a thresholds object gives."""
    if name == "100":
        given = {"true": 100.0, "false": None}.get(value, UNREADABLE)
        return [] if given is None else [(m, given) for m in MEASURES]
    if name == "perFile":
        return [(name, {"true": 1.0, "false": 0.0}.get(value, UNREADABLE))]
    plain = re.fullmatch(r"-?\d+(?:\.\d+)?", value)
    return [(name, float(value) if plain else UNREADABLE)]


def vitest_member(js: JsText, name: str, start: int, end: int, *, glob: bool) -> Pairs | None:
    """What one member of a thresholds object gives; None when it may give anything."""
    value = js.bare[start:end].strip()
    if name in MEASURES or name in ("100", "perFile"):
        return vitest_value(name, value)
    if glob or name == "autoUpdate":
        return []
    opening = end - len(js.bare[start:end].lstrip())
    if not value.startswith("{") or js_text.braced(js.code, opening) != opening + len(value) - 1:
        return None
    return [(f"{name} {m}", v) for m, v in vitest_object(js, opening, glob=True)]


def vitest_object(js: JsText, opening: int, *, glob: bool = False) -> Pairs:
    """What a thresholds object gives; the last of two members with one name is the one read."""
    closing = js_text.braced(js.code, opening)
    if closing is None:
        return []
    places: dict[str, tuple[int, int]] = {}
    rest = js.code[closing + 1 :].lstrip()
    known = glob or not rest or rest[0] in ",}"
    for start, end in js_text.members(js.code, opening, closing):
        if named := JS_MEMBER.match(js.bare[start:end]):
            places[named[1] or named[3] or ""] = (start + named.end(), end)
        elif js.bare[start:end].strip():
            known = False  # a spread, a computed name, a variable's own
    out: Pairs = []
    for name, (start, end) in places.items():
        given = vitest_member(js, name, start, end, glob=glob)
        known = known and given is not None
        out += given or []
    return out if known else [(name, UNREADABLE) for name, _value in out]


def vitest(text: str) -> Pairs:
    """The thresholds of a vitest configuration, each glob's under its name."""
    js = JsText(text)
    if not js.whole:
        return []
    found = re.finditer(r"(?:^|[{,])\s*thresholds\s*:\s*\{", js.keyed)
    return [pair for m in found for pair in vitest_object(js, m.end() - 1)]


def node_flags(rel: str, text: str) -> Pairs:
    """The thresholds the commands of a file give Node, the last of each name in each."""
    parts = [p for x in run_texts(rel, text) for p in shell(x) if not NO_COMMAND.match(p)]
    return [(name, float(v)) for p in parts for name, v in dict(NODE_FLAG.findall(p)).items()]


def folders(files: Iterable[str], order: tuple[str, ...]) -> dict[str, list[str]]:
    """The files a tool looks for, by folder, in the order it looks for them."""
    out: dict[str, list[str]] = {}
    for rel in files:
        path = PurePosixPath(rel)
        if path.name in order:
            out.setdefault(str(path.parent), []).append(rel)
    return {
        folder: sorted(found, key=lambda rel: order.index(PurePosixPath(rel).name))
        for folder, found in out.items()
    }


def place(folder: str, tool: str) -> str:
    """How a tool's thresholds in a folder are named."""
    return tool if folder == "." else f"{folder}/{tool}"


def coverage_thresholds(files: list[str], reader: Callable[[str], str]) -> Thresholds:
    """coverage.py's threshold in each folder, in the file it would read there."""
    out: Thresholds = {}
    for folder, found in folders(files, COVERAGE_ORDER).items():
        for rel in found:
            used, given = coverage_py(rel, reader(rel).removeprefix("\ufeff"))
            value = number(given)
            if used:
                out[f"{place(folder, 'coverage')} fail_under"] = Held(
                    rel, [] if value is None else [value]
                )
                break
    return out


def vitest_thresholds(files: list[str], reader: Callable[[str], str]) -> Thresholds:
    """vitest's thresholds: in each folder those of the file it would read, and any other file's."""
    sources: list[tuple[str, str]] = []
    defaults: set[str] = set()
    for folder, found in folders(files, VITEST_ORDER).items():
        defaults.update(found)
        for rel in found:
            sources.append((place(folder, "vitest"), rel))
            # One that imports the next (for mergeConfig) does not hide it.
            if not VITE_IMPORT.search(JsText(reader(rel)).bare):
                break
    sources += [
        (rel, rel) for rel in files if rel.endswith(js_text.SUFFIXES) and rel not in defaults
    ]
    out: Thresholds = {}
    for name, rel in sources:
        for measure, value in vitest(reader(rel)):
            out.setdefault(f"{name} {measure}", Held(rel)).values.append(value)
    return out


def read(repo: cq.Repo, rel: str) -> str:
    """A file of the tree, whatever its bytes."""
    return repo.path(rel).read_text(encoding="utf-8", errors="replace")


def thresholds(files: Iterable[str], reader: Callable[[str], str]) -> Thresholds:
    """Every threshold of a tree, by the tool and its folder, or by the file that gives it."""
    named = [x for x in files if THRESHOLD_FILES.search(x) and "node_modules/" not in x]
    out = coverage_thresholds(named, reader) | vitest_thresholds(named, reader)
    for rel in named:
        if rel.endswith((".yml", ".yaml", ".json")):
            for name, value in node_flags(rel, reader(rel)):
                out.setdefault(f"{rel} {name}", Held(rel)).values.append(value)
    return out


def lowered_entries(text: str) -> list[dict[str, Any]]:
    """The [[lowered]] entries of a waivers file."""
    try:
        found = tomllib.loads(text).get("lowered")
    except tomllib.TOMLDecodeError:
        return []  # the kit check says it
    return [e for e in found if isinstance(e, dict)] if isinstance(found, list) else []


def shown(value: float | None) -> str:
    """A threshold's new value, as a [[lowered]] entry gives it."""
    if value is None:
        return '"gone"'
    return '"unreadable"' if value == UNREADABLE else f"{value:.12g}"


def accepts(entry: dict[str, Any], key: str, value: float | None) -> bool:
    """Whether a [[lowered]] entry is for this fall: the threshold, its new value, who and why."""
    to = entry.get("to")
    given = f'"{to}"' if isinstance(to, str) else shown(number(to))
    return (
        entry.get("threshold") == key
        and given == shown(value)
        and worded(str(entry.get("reason", "")))
        and bool(str(entry.get("decided", "")).strip())
    )


def falls(old: Sequence[float], new: Sequence[float]) -> list[tuple[float, float | None]]:
    """The values of one threshold below what they were, or gone: each then, and now."""
    then = sorted((v for v in old if v != UNREADABLE), reverse=True)
    now = sorted(new, reverse=True)
    out = [
        (was, now[i] if i < len(now) else None)
        for i, was in enumerate(then)
        # Below 0 vitest counts what may be missed: no percentage is more than that but 100.
        if i >= len(now) or now[i] < was or (was < 0 <= now[i] < 100)
    ]
    if then and not out and now[-1] < then[-1]:
        out = [(then[-1], now[-1])]  # one more place, with less than any had
    return list(dict.fromkeys(out))


def fallen(old: Thresholds, new: Thresholds) -> list[tuple[str, float, float | None]]:
    """The thresholds below what they were, or gone: the key, then, now."""
    none = Held("")
    return [
        (key, was, value)
        for key, held in sorted(old.items())
        for was, value in falls(held.values, new.get(key, none).values)
    ]


def git(repo: cq.Repo, *args: str) -> str | None:
    """A git command's output in the repository; None when it fails."""
    done = subprocess.run(["git", "-C", str(repo.root), *args], capture_output=True, check=False)
    return done.stdout.decode("utf-8", errors="replace") if done.returncode == 0 else None


def base_of(repo: cq.Repo, named: str) -> str | None:
    """The commit a change is compared with: the one named, else where it left main."""
    if named.strip("0"):
        found = git(repo, "rev-parse", "-q", "--verify", f"{named}^{{commit}}")
        if found is None:
            raise cq.SetupError(
                f"the base {named} is not in this clone: the thresholds cannot be compared"
            )
        return found.strip()
    found = git(repo, "merge-base", "HEAD", "refs/remotes/origin/main")
    return found.strip() if found else None


def threshold_moves(repo: cq.Repo, base: str) -> tuple[list[Problem], list[str]]:
    """What fell between the base and the tree: what is not said, and what is."""
    names = [x for x in (git(repo, "ls-tree", "-rz", "--name-only", base) or "").split("\0") if x]

    def before(rel: str) -> str:
        return git(repo, "show", f"{base}:{rel}") or ""

    known = lowered_entries(before(cq.WAIVERS))
    now = lowered_entries(read(repo, cq.WAIVERS)) if repo.exists(cq.WAIVERS) else []
    entries = [e for e in now if e not in known]
    problems: list[Problem] = []
    said: list[str] = []
    old = thresholds(names, before)
    new = thresholds(repo.files, lambda rel: read(repo, rel))
    for key, was, value in fallen(old, new):
        to = shown(value)
        there = f" in {new[key].read_in}" if key in new else ""
        move = f"went from {was:.12g} in {old[key].read_in} to {to}{there} since {base[:12]}"
        entry = next((e for e in entries if accepts(e, key, value)), None)
        if entry:
            said.append(f"lowered: {key} {move}: {entry['reason']} ({entry['decided']})")
        else:
            problems.append(
                Problem(
                    "threshold",
                    key,
                    f"{move}: a change that lowers a coverage threshold adds its [[lowered]] entry"
                    f' to {cq.WAIVERS} (threshold = "{key}", to = {to}, reason, decided)',
                )
            )
    return problems, said


# --------------------------------------------------------------------------


def command_line_problems(repo: cq.Repo) -> list[Problem]:
    """coverage.py's threshold on a command line."""
    return [
        Problem(
            "threshold",
            rel,
            "gives coverage.py its threshold on a command line, which wins over the configuration:"
            " fail_under in the configuration is its one place",
        )
        for rel in repo.own(("",))
        if COMMAND_FILES.search(rel) and gives_threshold(commands(rel, read(repo, rel)))
    ]


def marker_problems(repo: cq.Repo) -> list[Problem]:
    """Every test marked to run alone, and every skip with no reason."""
    out = []
    for rel in repo.own(PY_SUFFIXES):
        try:
            lines = python_skips(repo.text(rel))
        except (SyntaxError, ValueError, tokenize.TokenError) as exc:
            out.append(Problem("skip", rel, f"cannot be read as Python: {exc}"))
            continue
        out += [
            Problem("skip", f"{rel}:{n}", f"a test that does not run {NO_REASON}") for n in lines
        ]
    for rel in repo.own(JS_SUFFIXES):
        text = read(repo, rel)
        if is_js_test(rel, text):
            only, bad = js_marks(text, jsx=js_text.is_jsx(rel))
            out += [Problem("only", f"{rel}:{n}", f"a test {ONLY}") for n in only]
            out += [
                Problem("skip", f"{rel}:{n}", f"a test that does not run {NO_REASON}") for n in bad
            ]
    return out


def check(repo: cq.Repo, base: str = "") -> tuple[list[Problem], list[str]]:
    """Check one repository; the problems, and the notes that fail nothing."""
    found = marker_problems(repo) + command_line_problems(repo)
    against = base_of(repo, base)
    if against is None:
        return found, ["no base to compare the coverage thresholds with"]
    problems, notes = threshold_moves(repo, against)
    return found + problems, notes
