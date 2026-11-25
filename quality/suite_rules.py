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
             entry to .github/quality/waivers.toml that says why; and
             coverage.py's is in its configuration, not on a command line

Python is read as Python (unittest, pytest). JavaScript and TypeScript are
read as text with the comments and strings taken out (vitest, node:test and
what spells its markers as they do). What it cannot see, and what each
repository holds by itself, is in docs/testing.md, "What the kit holds".

Python 3.14 or newer, git.
"""

from __future__ import annotations

import ast
import configparser
import io
import json
import re
import subprocess
import tokenize
import tomllib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import check_quality as cq
import yaml

PY_SUFFIXES = (".py", ".pyi")
JS_SUFFIXES = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx")


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


def reasoned(comments: dict[int, str], first: int, last: int) -> bool:
    """Whether a comment on these lines, or right above them, gives the reason."""
    while first - 1 in comments:
        first -= 1
    for line in range(first, last + 1):
        found = COMMENT_REASON.search(comments.get(line, ""))
        if found and worded(found["why"]):
            return True
    return False


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


def says_why(call: ast.Call, position: int | None) -> bool:
    """Whether a marker's call gives a reason: a text that says something, or a computed one."""
    given = [k.value for k in call.keywords if k.arg in REASON_WORDS]
    if not given and position is not None and len(call.args) > position:
        given = [call.args[position]]
    if not given:
        # What *args or **kwargs hold is made at run time.
        starred = any(isinstance(a, ast.Starred) for a in call.args)
        return starred or any(k.arg is None for k in call.keywords)
    reason = given[0]
    if isinstance(reason, ast.Constant):
        return isinstance(reason.value, str) and worded(reason.value)
    return True


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


def python_comments(text: str) -> dict[int, str]:
    """The comments of a Python file, by line."""
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    return {t.start[0]: t.string for t in tokens if t.type == tokenize.COMMENT}


def python_skips(text: str) -> list[int]:
    """The lines of a Python file where a test is skipped, or may fail, with no reason."""
    if not PY_HINT.search(text):
        return []
    tree = ast.parse(text)
    names = imported_names(tree)
    comments = python_comments(text)
    bad: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = dotted(node.func, names)
        if name == NO_PLACE or (name in MARKERS and not says_why(node, MARKERS[name])):
            bad.add(node.lineno)
            if reasoned(comments, node.lineno, node.end_lineno or node.lineno):
                bad.discard(node.lineno)
    for bare in bare_markers(tree, names):
        name = dotted(bare, names)
        known = name == NO_PLACE or name in MARKERS
        if known and not reasoned(comments, bare.lineno, bare.lineno):
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
TEST_CALL = r"\b(?:describe|it|test|suite|bench)(?:\s*\??\.\s*\w+)*?\s*\??\.\s*"
JS_ONLY = re.compile(TEST_CALL + r"only\b|\b(?:fit|fdescribe|ftest)\s*\(|[{,]\s*only\s*:\s*true\b")
JS_SKIP = re.compile(
    TEST_CALL
    + r"(?:skip|todo|fails|failing|fixme|skipIf|runIf)\b|\bx(?:it|describe|test|context)\s*\("
)
# Markers that may hold their reason: t.skip("why"), { todo: "why" }. What an
# option may be without marking anything: off, a number (`skip: 10` pages), a type.
JS_CALL_REASON = re.compile(r"\b(?:t|ctx|context|testContext)\s*\.\s*(?:skip|todo)\s*\(")
JS_OPTION_REASON = re.compile(r"[{,]\s*(?:skip|todo|fails|expectFailure)\s*:")
JS_OFF = re.compile(r"(?:false|undefined|null|boolean|string|number)\b|\d")
JS_STRING = re.compile(r"""(["'`])((?:\\.|(?!\1)[^\\\n])*+)\1""")
REGEX_AFTER = re.compile(
    r"(?:^|[(,=:\[!&|?{};+\-*%~^<>\n]|\b(?:return|typeof|case|in|of|yield|await))\s*$"
)
# A string as far as it goes on its line, a regular expression, a template's
# text up to its end or to what it computes.
JS_QUOTED = re.compile(r"""(["'])(?:\\[\s\S]|(?!\1)[^\\\n])*+\1?""")
JS_REGEX = re.compile(r"/(?:\\.|\[(?:\\.|[^\]\\\n])*+\]|[^/\\\[\n])++/")
JS_TEMPLATE = re.compile(r"(?:\\[\s\S]|(?!\$\{)[^`\\])*+(`|\$\{)")


class JsText:
    """A file of JavaScript or TypeScript: its code with the rest blanked, its comments by line.

    Comments, strings and regular expressions are replaced by blanks of the
    same length, so a place in the code is the same place in the file. What
    a template literal computes (`${...}`) stays code. A file that ends
    inside a comment or a template was not read right, and then it is judged
    as it is written.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.comments: dict[int, str] = {}
        self._out = list(text)
        self._depth: list[int] = []  # the braces open inside each template's ${...}
        self._template = False
        self._at = 0
        whole = True
        while self._at < len(text) and whole:
            whole = self._step()
        self.code = "".join(self._out) if whole and not (self._template or self._depth) else text

    def line(self, at: int) -> int:
        """The line a place is on."""
        return self.text.count("\n", 0, at) + 1

    def _blank(self, end: int) -> None:
        self._out[self._at : end] = " " * (end - self._at)
        self._at = end

    def _step(self) -> bool:
        """Read one thing; False when it never ends."""
        if self._template:
            return self._in_template()
        here, text = self._at, self.text
        two = text[here : here + 2]
        if two == "//":
            end = text.find("\n", here)
            end = len(text) if end < 0 else end
            self.comments[self.line(here)] = text[here:end]
            self._blank(end)
        elif two == "/*":
            end = text.find("*/", here + 2)
            if end < 0:
                return False
            for i, part in enumerate(text[here:end].split("\n")):
                self.comments[self.line(here) + i] = part
            self._blank(end + 2)
        elif quoted := JS_QUOTED.match(text, here):
            self._blank(quoted.end())
        elif text[here] == "/" and REGEX_AFTER.search(text, max(0, here - 40), here):
            closed = JS_REGEX.match(text, here)
            self._blank(closed.end() if closed else here + 1)
        elif text[here] == "`":
            self._template = True
            self._blank(here + 1)
        else:
            self._brace(text[here])
            self._at += 1
        return True

    def _brace(self, char: str) -> None:
        if self._depth and char == "{":
            self._depth[-1] += 1
        elif self._depth and char == "}":
            self._depth[-1] -= 1
            if self._depth[-1] < 0:
                self._depth.pop()
                self._template = True

    def _in_template(self) -> bool:
        found = JS_TEMPLATE.match(self.text, self._at)
        if found is None:
            return False
        self._blank(found.end())
        self._template = False
        if found[1] == "${":
            self._depth.append(0)
        return True


def is_js_test(rel: str, text: str) -> bool:
    """Whether a JavaScript or TypeScript file holds tests."""
    path = PurePosixPath(rel)
    return (
        bool(TEST_FOLDERS & set(path.parts[:-1]))
        or bool(TEST_NAME.search(path.name))
        or bool(RUNNER.search(text))
    )


def js_marks(text: str) -> tuple[list[int], list[int]]:
    """The lines where a test runs alone, and where one is skipped with no reason."""
    js = JsText(text)
    only = {js.line(m.end() - 1) for m in JS_ONLY.finditer(js.code)}
    bad = {js.line(m.end() - 1) for m in JS_SKIP.finditer(js.code)}
    for pattern in (JS_CALL_REASON, JS_OPTION_REASON):
        for m in pattern.finditer(js.code):
            # Its text is blank in the code: read it where it is written.
            value = text[m.end() :].lstrip()
            given = JS_STRING.match(value)
            if pattern is JS_OPTION_REASON and JS_OFF.match(value):
                continue
            if given is None or not worded(given[2]):
                bad.add(js.line(m.end() - 1))
    return sorted(only), [n for n in sorted(bad) if not reasoned(js.comments, n, n)]


# --------------------------------------------------------------------------
# Coverage thresholds

THRESHOLD_FILES = re.compile(
    r"(?:^|/)(?:pyproject\.toml|\.coveragerc(?:\.toml)?|setup\.cfg|tox\.ini|package\.json"
    r"|(?:vitest|vite)\.[\w.-]*config\.[cm]?[jt]s|(?:vitest|vite)\.config\.[cm]?[jt]s"
    r"|vitest\.workspace\.[cm]?[jt]s)$|^\.github/workflows/[^/]+\.ya?ml$"
)
NODE_FLAG = re.compile(r"--test-coverage-(lines|branches|functions)[=\s]+['\"]?(\d+(?:\.\d+)?)")
# coverage.py's threshold on a command line wins over the one in its
# configuration, which is where a person looks.
COV_FLAG = re.compile(r"--cov-fail-under\b")
COVERAGE_FLAG = re.compile(r"\s--fail-under\b")
COVERAGE = re.compile(r"\bcoverage3?\b")
COMMAND_FILES = re.compile(
    r"(?:^|/)(?:package\.json|pyproject\.toml|setup\.cfg|tox\.ini|\.?pytest\.ini)$"
    r"|^\.github/workflows/[^/]+\.ya?ml$"
)
Thresholds = dict[str, float]


def number(value: Any) -> float | None:
    """A threshold as a number; None when it is none."""
    try:
        return None if isinstance(value, bool) else float(value)
    except TypeError, ValueError:
        return None


def strings(value: Any) -> Iterator[str]:
    """Every text of a document, as a tool reads it."""
    if isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, str):
        yield value


def uncommented(text: str) -> str:
    """A script with its comment lines taken out and its continued lines joined."""
    lines = (x for x in text.split("\n") if not x.lstrip().startswith("#"))
    return "\n".join(lines).replace("\\\n", " ")


def commands(rel: str, text: str) -> str:
    """The texts of a file that may be commands: a workflow's, a package's, pytest's options."""
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
        return ""
    return "\n".join(uncommented(x) for x in found)


def gives_threshold(text: str) -> bool:
    """Whether a command gives coverage.py its threshold."""
    return any(
        COV_FLAG.search(part) or (COVERAGE_FLAG.search(part) and COVERAGE.search(part))
        for part in re.split(r"[\n;&|]", text)
    )


def coverage_py(rel: str, text: str) -> Any:
    """coverage.py's fail_under, as its configuration file gives it."""
    name = PurePosixPath(rel).name
    try:
        if name.endswith(".toml"):
            data = tomllib.loads(text)
            data = data.get("tool", {}).get("coverage", data if name != "pyproject.toml" else {})
            return data.get("report", {}).get("fail_under")
        ini = configparser.ConfigParser(interpolation=None)
        ini.read_string(text)
    except AttributeError, ValueError, configparser.Error:
        return None
    sections = ("report", "coverage:report") if name == ".coveragerc" else ("coverage:report",)
    return next((ini[s]["fail_under"] for s in sections if ini.has_option(s, "fail_under")), None)


def vitest(text: str) -> Iterator[tuple[str, str]]:
    """The thresholds of a vitest configuration, the ones of a glob included."""
    code = JsText(text).code
    for m in re.finditer(r"\bthresholds\s*:\s*\{", code):
        depth, end = 1, m.end()
        while end < len(code) and depth:
            depth += {"{": 1, "}": -1}.get(code[end], 0)
            end += 1
        yield from re.findall(r"\b(\w+)\s*:\s*(-?\d+(?:\.\d+)?)", code[m.end() : end])


def thresholds_of(rel: str, text: str) -> Thresholds:
    """The thresholds a file gives, each at its lowest: a run would use any of them."""
    pairs: list[tuple[str, Any]] = []
    if rel.endswith((".yml", ".yaml", ".json")):
        pairs += NODE_FLAG.findall(commands(rel, text))
    elif rel.endswith(JS_SUFFIXES):
        pairs += vitest(text)
    else:
        pairs.append(("fail_under", coverage_py(rel, text)))
    out: Thresholds = {}
    for name, value in pairs:
        given = number(value)
        if given is not None:
            key = f"{rel} {name}"
            out[key] = min(out.get(key, given), given)
    return out


def read(repo: cq.Repo, rel: str) -> str:
    """A file of the tree, whatever its bytes."""
    return repo.path(rel).read_text(encoding="utf-8", errors="replace")


def thresholds(files: Iterable[str], reader: Callable[[str], str]) -> Thresholds:
    """Every threshold of a tree, by file and name."""
    out: Thresholds = {}
    for rel in files:
        if THRESHOLD_FILES.search(rel) and "node_modules/" not in rel:
            out.update(thresholds_of(rel, reader(rel)))
    return out


def lowered_entries(text: str) -> list[dict[str, Any]]:
    """The [[lowered]] entries of a waivers file."""
    try:
        found = tomllib.loads(text).get("lowered")
    except tomllib.TOMLDecodeError:
        return []  # the kit check says it
    return [e for e in found if isinstance(e, dict)] if isinstance(found, list) else []


def accepts(entry: dict[str, Any], key: str, value: float | None) -> bool:
    """Whether a [[lowered]] entry is for this fall: the threshold, its new value, who and why."""
    to = entry.get("to")
    same = to == "gone" if value is None else number(to) == value
    return (
        entry.get("threshold") == key
        and same
        and worded(str(entry.get("reason", "")))
        and bool(str(entry.get("decided", "")).strip())
    )


def fallen(old: Thresholds, new: Thresholds) -> list[tuple[str, float, float | None]]:
    """The thresholds below what they were, or gone: the key, then, now."""
    return [
        (key, was, new.get(key))
        for key, was in sorted(old.items())
        if new.get(key, float("-inf")) < was
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
    new = thresholds(repo.files, lambda rel: read(repo, rel))
    for key, was, value in fallen(thresholds(names, before), new):
        to = '"gone"' if value is None else f"{value:.12g}"
        move = f"went from {was:.12g} to {to} since {base[:12]}"
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
            only, bad = js_marks(text)
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
