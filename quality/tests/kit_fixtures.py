# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Tiny consumer repositories for the quality kit's tests.

Each fixture is a real git work tree in a temporary directory, so the
checker's `git ls-files` and the header check's `git log` see what they see
in a repository that adopts the kit. The kit's modules are imported here,
once quality/ is on the path, and the tests take them from this module.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

QUALITY = Path(__file__).resolve().parents[1]
CENTRAL = QUALITY.parent
if str(QUALITY) not in sys.path:
    sys.path.insert(0, str(QUALITY))

import check_quality  # noqa: E402  found through the path set above
import fetch_tool  # noqa: E402  found through the path set above
import md_nowrap  # noqa: E402  found through the path set above
import mypy_groups  # noqa: E402  found through the path set above
import spdx_headers  # noqa: E402  found through the path set above
import sync  # noqa: E402  found through the path set above

__all__ = [
    "CENTRAL",
    "COPYRIGHT",
    "FAKE_COMMIT",
    "HOLDER",
    "LICENSE",
    "QUALITY",
    "check_quality",
    "commit",
    "consumer",
    "fetch_tool",
    "git",
    "header",
    "init",
    "md_nowrap",
    "mypy_groups",
    "spdx_headers",
    "sync",
    "write",
]

FAKE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
HOLDER = "José M. Requena Plens"
COPYRIGHT = "SPDX-" + "FileCopyrightText:"
LICENSE = "SPDX-" + "License-Identifier:"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Kit Test",
    "GIT_AUTHOR_EMAIL": "kit@example.invalid",
    "GIT_COMMITTER_NAME": "Kit Test",
    "GIT_COMMITTER_EMAIL": "kit@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def git(root: Path, *args: str, date: str | None = None) -> str:
    env = {**os.environ, **GIT_ENV}
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=True, text=True, env=env
    ).stdout


def header(license_expr: str = "MIT", year: str = "2026", prefix: str = "# ") -> str:
    return f"{prefix}{COPYRIGHT} {year} {HOLDER}\n{prefix}{LICENSE} {license_expr}\n"


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def init(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    return root


def commit(root: Path, message: str = "Add files", date: str | None = None) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "--no-gpg-sign", "-m", message, date=date)


def consumer(root: Path) -> Path:
    """A minimal Python repository that keeps every kit rule once synced."""
    init(root)
    write(root, "pkg/__init__.py", header())
    write(
        root,
        "pkg/mod.py",
        header() + '"""A module."""\n\n\ndef add(x: int) -> int:\n    return x + 1\n',
    )
    write(
        root,
        "pyproject.toml",
        header()
        + '\n[tool.ruff]\nextend = ".github/quality/ruff.toml"\ntarget-version = "py311"\n'
        + '\n[tool.mypy]\npython_version = "3.11"\nfiles = ["pkg"]\n',
    )
    write(
        root,
        "REUSE.toml",
        'version = 1\n\n[[annotations]]\npath = ["**"]\nprecedence = "aggregate"\n'
        f'SPDX-FileCopyrightText = "2026 {HOLDER}"\nSPDX-License-Identifier = "MIT"\n',
    )
    write(
        root,
        ".github/dependabot.yml",
        header()
        + "version: 2\nupdates:\n"
        + "  - package-ecosystem: github-actions\n    directory: /\n"
        + "    schedule:\n      interval: weekly\n"
        + "    cooldown:\n      default-days: 7\n"
        + '    ignore:\n      - dependency-name: "kleidos-dev/.github*"\n'
        + "  - package-ecosystem: pip\n    directory: /\n"
        + "    schedule:\n      interval: weekly\n"
        + "    cooldown:\n      default-days: 7\n",
    )
    write(root, ".python-version", "3.11\n")
    write(
        root, ".github/workflows/check.yml", (QUALITY / "templates/workflows/check.yml").read_text()
    )
    write(
        root,
        "README.md",
        f"<!--\n{COPYRIGHT} 2026 {HOLDER}\n{LICENSE} MIT\n-->\n\n# Demo\n\nOne line.\n",
    )
    return root
