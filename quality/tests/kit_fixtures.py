# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Tiny consumer repositories for the quality kit's tests.

Each fixture is a real git work tree in a temporary directory, so the
checker's `git ls-files` and the header check's `git log` see what they see
in a repository that adopts the kit. The kit's modules are imported here,
once quality/ is on the path, and the tests take them from this module.
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

QUALITY = Path(__file__).resolve().parents[1]
CENTRAL = QUALITY.parent
for folder in (CENTRAL / "tools", CENTRAL / "hooks", QUALITY):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import agent_docs  # noqa: E402  found through the path set above
import check_commit_msg  # noqa: E402  found through the path set above
import check_quality  # noqa: E402  found through the path set above
import commit_identity  # noqa: E402  found through the path set above
import coverage_floor  # noqa: E402  found through the path set above
import deny_hooks  # noqa: E402  found through the path set above
import ecosystem  # noqa: E402  found through the path set above
import fast_forward  # noqa: E402  found through the path set above
import fetch_tool  # noqa: E402  found through the path set above
import js_text  # noqa: E402  found through the path set above
import kit_preview  # noqa: E402  found through the path set above
import kit_switch  # noqa: E402  found through the path set above
import landing  # noqa: E402  found through the path set above
import latest_releases  # noqa: E402  found through the path set above
import launch  # noqa: E402  found through the path set above
import md_nowrap  # noqa: E402  found through the path set above
import mypy_groups  # noqa: E402  found through the path set above
import own_files  # noqa: E402  found through the path set above
import policy  # noqa: E402  found through the path set above
import run_form  # noqa: E402  found through the path set above
import spdx_headers  # noqa: E402  found through the path set above
import suite_rules  # noqa: E402  found through the path set above
import supplier_fields  # noqa: E402  found through the path set above
import sync  # noqa: E402  found through the path set above

__all__ = [
    "CENTRAL",
    "COPYRIGHT",
    "FAKE_COMMIT",
    "HOLDER",
    "LICENSE",
    "QUALITY",
    "agent_docs",
    "agent_files",
    "check_commit_msg",
    "check_quality",
    "commit",
    "commit_identity",
    "called",
    "consumer",
    "coverage_floor",
    "deny_hooks",
    "ecosystem",
    "fast_forward",
    "fetch_tool",
    "git",
    "header",
    "init",
    "kit_preview",
    "kit_switch",
    "landing",
    "js_text",
    "latest_releases",
    "launch",
    "md_header",
    "md_nowrap",
    "mypy_groups",
    "policy",
    "run_form",
    "own_files",
    "spdx_headers",
    "suite_rules",
    "supplier_fields",
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
    # Nothing of the git that runs the tests (a hook sets GIT_INDEX_FILE and
    # GIT_DIR for the commit in progress) reaches the git of a test's repository.
    outer = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env = {**outer, **GIT_ENV}
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
        + '\n[tool.ruff]\nextend = ".github/quality/ruff.toml"\ntarget-version = "py315"\n'
        + '\n[tool.mypy]\npython_version = "3.15"\nfiles = ["pkg"]\n',
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
    write(root, ".python-version", "3.15\n")
    write(
        root, ".github/workflows/check.yml", (QUALITY / "templates/workflows/check.yml").read_text()
    )
    write(
        root,
        "README.md",
        f"<!--\n{COPYRIGHT} 2026 {HOLDER}\n{LICENSE} MIT\n-->\n\n# Demo\n\nOne line.\n",
    )
    agent_files(root)
    return root


def md_header() -> str:
    return f"<!--\n{COPYRIGHT} 2026 {HOLDER}\n{LICENSE} MIT\n-->\n\n"


def agent_files(root: Path, rules: str = "- Run the tests in `pkg/`.\n") -> None:
    """AGENTS.md and CLAUDE.md as docs/agent-docs.md describes them, and the ignore line."""
    write(
        root,
        "AGENTS.md",
        md_header()
        + "# AGENTS.md\n\n## What this repository is\n\nA demo.\n\n"
        + f"## Rules of this repository\n\n{rules}\n## Other repositories\n\nNone.\n",
    )
    write(root, "CLAUDE.md", md_header() + "@AGENTS.md\n")
    write(root, ".gitignore", header() + "\nCLAUDE.local.md\n")


def called(root: Path) -> Path:
    """The same repository in the run form, as the switch leaves it, committed."""
    consumer(root)
    sync.write(root, commit=FAKE_COMMIT)
    commit(root, "Hold the kit")
    kit_switch.switch(
        root, check_quality.DirKit(CENTRAL), FAKE_COMMIT, dt.datetime.now(tz=dt.UTC).date()
    )
    commit(root, "Run the kit")
    return root
