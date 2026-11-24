#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Start one of the quality kit's hooks on a Python that can run it.

pre-commit runs a `language: script` hook on whichever python3 comes first
on the PATH, and the machines have from 3.9 (the one macOS ships) up, while
the kit's checks are written for a newer one. This starter keeps to what
3.9 reads, so it can always speak. The commit-message check keeps to it too
and runs in this Python. The others run on this Python when that is new
enough and has what the hook imports, else on the newest python3.x of the
PATH that is, else on the kit's own environment, which the line it says
otherwise makes (an externally managed Python, as Homebrew's and Debian's
are, refuses pip outside one), and fails (the CI runs the same checks, so
nobody needs the hooks).

Usage: launch.py policy|mypy
       launch.py commit-msg MESSAGE-FILE

Exit status: the hook's own, or 2 when no Python can run it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

KIT = Path(__file__).resolve().parent.parent
# The newest python3.<minor> worth asking for, with room for years of releases.
NEWEST_MINOR = 30


COMMIT_MSG = "commit-msg"


class Hook(NamedTuple):
    """One hook: the script, the oldest Python that reads it, what it imports."""

    script: str
    floor: tuple[int, int]
    module: str = ""
    requirement: str = ""


HOOKS = {
    # PEP 758 (`except A, B:`), which the kit's formatter writes, needs 3.14.
    "policy": Hook("quality/policy.py", (3, 14), "yaml", "pyyaml==6.0.4"),
    # mypy itself is the one on the PATH: the repository's environment has it.
    "mypy": Hook("quality/mypy_groups.py", (3, 14)),
}


class Python(NamedTuple):
    """One interpreter: its path, its version, and whether it imports the module."""

    path: str
    version: tuple[int, int]
    has_module: bool


def probe(path: str, module: str) -> Python | None:
    """What the interpreter at a path is, or None when it does not run."""
    code = (
        "import importlib.util as u, sys;"
        "print(sys.version_info[0], sys.version_info[1],"
        " int(not sys.argv[1] or u.find_spec(sys.argv[1]) is not None))"
    )
    try:
        done = subprocess.run(
            [path, "-c", code, module],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            cwd=str(KIT),  # python -c reads modules from here first: never the repository
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    parts = done.stdout.split()
    if done.returncode != 0 or len(parts) != 3:
        return None
    return Python(path, (int(parts[0]), int(parts[1])), parts[2] == "1")


def environment() -> Path:
    """The kit's own environment, outside every repository."""
    data = os.environ.get("XDG_DATA_HOME", "")
    base = Path(data) if os.path.isabs(data) else Path.home() / ".local" / "share"
    return base / "kleidos-kit"


def candidates(floor: tuple[int, int]) -> list[str]:
    """This interpreter, the PATH's from the newest down, then the kit's own environment's."""
    names = ["python3"] + [f"python3.{m}" for m in range(NEWEST_MINOR, floor[1] - 1, -1)]
    found = [sys.executable] + [shutil.which(name) or "" for name in names]
    found.append(str(environment() / "bin" / "python"))
    return [path for path in dict.fromkeys(found) if path]


def dotted(version: tuple[int, int]) -> str:
    """A version as people write it: 3.14."""
    return f"{version[0]}.{version[1]}"


def choose(hook: Hook, paths: list[str]) -> tuple[Python | None, str]:
    """The first Python that can run a hook, or None and the line that says what is missing."""
    seen = [python for python in (probe(path, hook.module) for path in paths) if python]
    new_enough = [python for python in seen if python.version >= hook.floor]
    for python in new_enough:
        if python.has_module:
            return python, ""
    if new_enough:
        python = new_enough[0]
        own = environment()
        return None, (
            f"{python.path} has no {hook.module} module; this makes an environment that has:"
            f" {python.path} -m venv --clear '{own}'"
            f" && '{own}/bin/python' -m pip install '{hook.requirement}'"
        )
    have = ", ".join(sorted({dotted(python.version) for python in seen})) or "none"
    return None, (
        f"needs Python {dotted(hook.floor)} or newer and the PATH has {have}: install one,"
        " or activate the repository's environment"
    )


def main(argv: list[str]) -> int:
    """Run the hook argv names, on a Python that can."""
    if len(argv) == 2 and argv[0] == COMMIT_MSG:
        sys.path.insert(0, str(KIT / "hooks"))
        import check_commit_msg

        return check_commit_msg.main(["--", argv[1]])
    hook = HOOKS.get(argv[0]) if len(argv) == 1 else None
    if hook is None:
        usage = f"usage: launch.py {'|'.join(HOOKS)}, or launch.py {COMMIT_MSG} MESSAGE-FILE"
        print(usage, file=sys.stderr)
        return 2
    python, why = choose(hook, candidates(hook.floor))
    if python is None:
        print(f"kleidos quality kit, hook {argv[0]}: {why}", file=sys.stderr)
        print("(the CI runs the same check on every pull request)", file=sys.stderr)
        return 2
    return subprocess.call([python.path, str(KIT / hook.script)])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
