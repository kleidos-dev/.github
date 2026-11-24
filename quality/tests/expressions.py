# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""GitHub's expression language, as far as the kit's workflows use it, for their tests.

The conditions and the values a workflow computes are tested by what they
decide, not by their text: a condition rewritten so that it never holds, or
always does, keeps the words a contract compares and changes what runs.
This reads literals, contexts, `!`, `==`, `!=`, `&&`, `||` and parentheses,
with GitHub's rules: strings compare without regard to case, `&&` and `||`
give one of their operands, and '', 0, false and null are false. Anything
else (a function, an index, a comparison of order) is refused, so a
condition written with it is noticed, not misread.
"""

from __future__ import annotations

import re
from typing import Any

TOKEN = re.compile(
    r"\s*(?:(?P<string>'(?:[^']|'')*')|(?P<number>-?\d+(?:\.\d+)?)"
    r"|(?P<op>==|!=|&&|\|\||!|\(|\))|(?P<word>[A-Za-z_][\w-]*(?:\.[A-Za-z_*][\w-]*)*))"
)


class ExpressionError(Exception):
    """An expression this reader does not know."""


def tokens(text: str) -> list[tuple[str, str]]:
    """The tokens of an expression: (kind, text)."""
    out = []
    at = 0
    text = text.strip()
    while at < len(text):
        found = TOKEN.match(text, at)
        if not found or found.end() == at:
            raise ExpressionError(f"cannot read {text[at:]!r}")
        kind = next(k for k, v in found.groupdict().items() if v is not None)
        out.append((kind, found[kind]))
        at = found.end()
    return out


def truthy(value: Any) -> bool:
    """GitHub's truth: '', 0, false and null are false."""
    return value not in ("", 0, False, None)


def number(value: Any) -> float:
    """GitHub's coercion to a number, for `==` between two types: null 0, '' 0, 'x' NaN."""
    if value is None:
        return 0.0
    if isinstance(value, (bool, int, float)):
        return float(value)
    try:
        return float(str(value).strip() or 0)
    except ValueError:
        return float("nan")


def equal(left: Any, right: Any) -> bool:
    """`==`: strings without regard to case; two types as numbers (NaN equals nothing)."""
    if isinstance(left, str) and isinstance(right, str):
        return left.casefold() == right.casefold()
    if type(left) is type(right):
        return bool(left == right)
    return number(left) == number(right)


class Reader:
    """A recursive descent over the tokens, with the contexts to look names up in."""

    def __init__(self, text: str, context: dict[str, Any]) -> None:
        self.tokens = tokens(text)
        self.at = 0
        self.context = context

    def peek(self) -> str:
        return self.tokens[self.at][1] if self.at < len(self.tokens) else ""

    def take(self) -> tuple[str, str]:
        if self.at >= len(self.tokens):
            raise ExpressionError("the expression ends too soon")
        self.at += 1
        return self.tokens[self.at - 1]

    def value(self) -> Any:
        found = self.either()
        if self.at != len(self.tokens):
            raise ExpressionError(f"cannot read on from {self.peek()!r}")
        return found

    def either(self) -> Any:
        left = self.both()
        while self.peek() == "||":
            self.take()
            right = self.both()
            left = left if truthy(left) else right
        return left

    def both(self) -> Any:
        left = self.compared()
        while self.peek() == "&&":
            self.take()
            right = self.compared()
            left = right if truthy(left) else left
        return left

    def compared(self) -> Any:
        left = self.unary()
        while self.peek() in ("==", "!="):
            op = self.take()[1]
            right = self.unary()
            left = equal(left, right) == (op == "==")
        return left

    def unary(self) -> Any:
        if self.peek() == "!":
            self.take()
            return not truthy(self.unary())
        return self.atom()

    def atom(self) -> Any:
        kind, text = self.take()
        if text == "(":
            inner = self.either()
            if self.take()[1] != ")":
                raise ExpressionError("a parenthesis is not closed")
            return inner
        if kind == "string":
            return text[1:-1].replace("''", "'")
        if kind == "number":
            return float(text) if "." in text else int(text)
        if kind == "word":
            if self.peek() == "(":
                raise ExpressionError(f"the function {text} is not read here")
            return self.lookup(text)
        raise ExpressionError(f"unexpected {text!r}")

    def lookup(self, name: str) -> Any:
        literal = {"true": True, "false": False, "null": None}
        if name in literal:
            return literal[name]
        value: Any = self.context
        for part in name.split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value


def evaluate(text: str, context: dict[str, Any]) -> Any:
    """The value of an expression, with or without its `${{ }}`."""
    inner = re.fullmatch(r"\s*\$\{\{(.*)\}\}\s*", text, re.S)
    return Reader(inner[1] if inner else text, context).value()


def runs(condition: str | None, context: dict[str, Any]) -> bool:
    """Whether a job or a step with this `if:` runs (none: it runs)."""
    return condition is None or truthy(evaluate(str(condition), context))
