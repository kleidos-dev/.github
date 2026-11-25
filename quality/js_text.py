#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""JavaScript and TypeScript as text: what is code, what is a comment, what is a string.

Not a parser: it tells the parts of a file apart, so that suite_rules.py
searches the code and not what is written about it. A file it cannot tell
apart for certain (a quote or a template that never ends, a `/` that may be
a division or a regular expression, JSX) is judged as it is written,
comments and strings included: that may refuse too much, and hides nothing.

Python 3.14 or newer.
"""

from __future__ import annotations

import bisect
import re
from itertools import pairwise

# A string as far as it goes on its line, a regular expression, a template's
# text up to its end or to what it computes, a name or a number.
QUOTED = re.compile(r"""(["'])(?:\\[\s\S]|(?!\1)[^\\\n])*+(\1?)""")
REGEX = re.compile(r"/(?![*/])(?:\\.|\[(?:\\.|[^\]\\\n])*+\]|[^/\\\[\n])++/")
TEMPLATE = re.compile(r"(?:\\[\s\S]|(?!\$\{)[^`\\])*+(`|\$\{)")
WORD = re.compile(r"[\w$]+")
SPACE = re.compile(r"\s+")
COMMENT = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/")
HASHBANG = re.compile(r"#![^\n]*")
JSX = re.compile(r"</[\w.$:-]*\s*>|/>")
SUFFIXES = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx")
JSX_SUFFIXES = (".jsx", ".tsx")
NAME_STRING = re.compile(r"""(["'`])([\w$]+)\1""")

# After these words a `/` opens a regular expression; after these others it
# may, or the word may be a name like any other.
REGEX_WORDS = frozenset(
    ("return", "typeof", "case", "in", "instanceof", "new", "delete", "void", "throw", "else", "do")
)
MAYBE_WORDS = frozenset(("of", "yield", "await"))
CONTROL_WORDS = frozenset(("if", "while", "for", "with"))
VALUE = "value"  # the last thing read was a string, a template or a regular expression
CONTROL = "control)"  # the `)` of an `if`, a `while`, a `for` or a `with`
# After these a `/` divides, and after these nobody knows without a parser.
ENDS_VALUE = frozenset((VALUE, ")", "]"))
UNCLEAR = frozenset(("}", "++", "--", "postfix!", ".", "?.", "<", "unmatched)"))
KEY_AFTER = frozenset("{,")
MEMBER_OF = frozenset("_$.)]")
TWO = frozenset(("++", "--", "?."))


class JsText:
    """A file of JavaScript or TypeScript, taken apart.

    `code` has its comments, strings, templates and regular expressions
    blanked, `bare` its comments, `keyed` is `code` with the keys and members
    written as a string (`{ "only": true }`, `it["only"]`) spelled plainly.
    All three keep their length, so a place in one is the same place in the
    file. What a template computes (`${...}`) stays code. `whole` says
    whether the file was told apart for certain; if not, all three are the
    file as it is written.
    """

    def __init__(self, text: str, *, jsx: bool = False) -> None:
        self.text = text
        self.comments: dict[int, list[str]] = {}
        self._starts = [0, *(m.end() for m in re.finditer("\n", text)), len(text) + 1]
        self._code = list(text)
        self._bare = list(text)
        self._strings: list[tuple[int, int]] = []
        self._depth: list[int] = []  # the braces open inside each template's ${...}
        self._parens: list[bool] = []  # of each ( open, whether a control word is before it
        self._template = False
        self._last: tuple[str, str] = ("", "")  # the last two things read that are code
        hashbang = HASHBANG.match(text)
        self._at = hashbang.end() if hashbang else 0
        self._code[: self._at] = self._bare[: self._at] = " " * self._at
        self.whole = not (jsx and JSX.search(text))
        while self._at < len(text) and self.whole:
            self.whole = self._step()
        self.whole = self.whole and not (self._template or self._depth)
        if not self.whole:
            self._as_written()
        self.code = "".join(self._code) if self.whole else text
        self.bare = "".join(self._bare) if self.whole else text
        self.keyed = self._spell_keys()

    def line(self, at: int) -> int:
        """The line a place is on."""
        return bisect.bisect_right(self._starts, at)

    def only_comment(self, line: int) -> bool:
        """Whether a line holds nothing but comments."""
        start, end = self._starts[line - 1], self._starts[line]
        return not "".join(self._bare[start:end]).strip()

    def _as_written(self) -> None:
        """Take what looks like a comment or a string for one, wherever it is."""
        self.comments = {}
        self._bare = list(self.text)
        for found in COMMENT.finditer(self.text):
            self._at = found.start()
            self._comment()
        self._strings = [m.span() for m in NAME_STRING.finditer(self.text)]

    def _blank(self, end: int, *, comment: bool = False) -> None:
        blanks = [c if c == "\n" else " " for c in self.text[self._at : end]]
        self._code[self._at : end] = blanks
        if comment:
            self._bare[self._at : end] = blanks
        self._at = end

    def _read(self, thing: str) -> None:
        self._last = (self._last[1], thing)

    def _step(self) -> bool:
        """Read one thing; False when it never ends, or could be two."""
        if self._template:
            return self._in_template()
        here, text = self._at, self.text
        if space := SPACE.match(text, here):
            self._at = space.end()
        elif text.startswith(("//", "/*"), here):
            return self._comment()
        elif quoted := QUOTED.match(text, here):
            self._strings.append(quoted.span())
            self._blank(quoted.end())
            self._read(VALUE)
            return bool(quoted[2])
        elif text[here] == "/":
            return self._slash()
        elif text[here] == "`":
            self._template = True
            self._blank(here + 1)
        elif word := WORD.match(text, here):
            self._at = word.end()
            self._read(word[0])
        else:
            self._mark(text[here : here + 2] if text[here : here + 2] in TWO else text[here])
        return True

    def _comment(self) -> bool:
        found = COMMENT.match(self.text, self._at)
        if found is None:
            return False
        for i, part in enumerate(found[0].removesuffix("*/").split("\n"), self.line(self._at)):
            self.comments.setdefault(i, []).append(part)
        self._blank(found.end(), comment=True)
        return True

    def _opens_regex(self) -> bool | None:
        """Whether a `/` opens a regular expression here; None when it may or may not."""
        before, last = self._last
        if last in UNCLEAR:
            return None
        if last in ENDS_VALUE:
            return False
        if WORD.fullmatch(last) is None:
            return True  # nothing yet, an operator, or what closes a control word's condition
        if before in (".", "?."):
            return False
        return True if last in REGEX_WORDS else None if last in MAYBE_WORDS else False

    def _slash(self) -> bool:
        opens = self._opens_regex()
        closed = None if opens is False else REGEX.match(self.text, self._at)
        if closed is None:
            self._mark("/")
            return opens is not True  # a regular expression that never ends
        self._blank(closed.end())
        self._read(VALUE)
        return opens is True

    def _mark(self, mark: str) -> None:
        """Read a sign of the language."""
        thing = mark
        if mark == "(":
            before, last = self._last
            control = last in CONTROL_WORDS or self._last == ("for", "await")
            self._parens.append(control and before not in (".", "?."))
        elif mark == ")":
            thing = self._close()
        elif mark == "!" and self._opens_regex() is not True:
            thing = "postfix!"
        self._brace(mark)
        self._at += len(mark)
        self._read(thing)

    def _close(self) -> str:
        if not self._parens:
            return "unmatched)"
        return CONTROL if self._parens.pop() else ")"

    def _brace(self, mark: str) -> None:
        if self._depth and mark == "{":
            self._depth[-1] += 1
        elif self._depth and mark == "}":
            self._depth[-1] -= 1
            if self._depth[-1] < 0:
                self._depth.pop()
                self._template = True

    def _in_template(self) -> bool:
        found = TEMPLATE.match(self.text, self._at)
        if found is None:
            return False
        self._template = False
        if found[1] == "${":
            self._depth.append(0)
            self._read("(")
        else:
            self._strings.append((self._at - 1, found.end()))
            self._read(VALUE)
        self._blank(found.end())
        return True

    def _beside(self, at: int, step: int) -> tuple[int, str]:
        """The place and the character beside one, blanks apart; -1 and nothing at an end."""
        at += step
        while 0 <= at < len(self.code) and self.code[at].isspace():
            at += step
        return (at, self.code[at]) if 0 <= at < len(self.code) else (-1, "")

    def _spell_keys(self) -> str:
        out = list(self.code)
        for start, end in self._strings:
            name = self.text[start + 1 : end - 1]
            if not WORD.fullmatch(name):
                continue
            (left, before), (right, after) = self._beside(start, -1), self._beside(end - 1, 1)
            if before == "[" and after == "]":
                opener, closer = self._beside(left, -1)[1], self._beside(right, 1)[1]
                key = opener in KEY_AFTER and closer == ":"
                if not key and not (opener.isalnum() or opener in MEMBER_OF):
                    continue
                # `it["only"]` is it.only; `it?.["only"]` has its point already.
                out[left] = " " if key or opener == "." else "."
                out[right] = " "
            elif before not in KEY_AFTER or after != ":":
                continue
            out[start:end] = f" {name} "
        return "".join(out)


def is_jsx(rel: str) -> bool:
    """Whether a file may hold JSX, by its name."""
    return rel.endswith(JSX_SUFFIXES)


def braced(code: str, opening: int) -> int | None:
    """Where the bracket open at a place closes; None when it does not."""
    depth = 0
    for at in range(opening, len(code)):
        depth += (code[at] in "([{") - (code[at] in ")]}")
        if not depth:
            return at
    return None


def members(code: str, opening: int, closing: int) -> list[tuple[int, int]]:
    """Where each member of an object or a list is, between its brackets."""
    cuts, depth = [opening], 0
    for at in range(opening + 1, closing):
        depth += (code[at] in "([{") - (code[at] in ")]}")
        if code[at] == "," and not depth:
            cuts.append(at)
    return [(a + 1, b) for a, b in pairwise([*cuts, closing])]
