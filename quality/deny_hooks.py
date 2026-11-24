#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Run a repository's own hooks that read the private deny-list, and nothing else.

The job that calls it (reusable-deny.yml) holds the deny-list in its
environment, so no third party's code may run in it. pre-commit is given a
configuration of its own that holds the named hooks and no hook repository,
in a file outside the tree; a hook is one the repository itself defines
(`repo: local`), runs what is on the machine (`language: system` or `script`)
and installs nothing. Anything else is refused before a hook runs.

Usage: deny_hooks.py ID[,ID ...]   (from the top of the repository)

Exit status: 0 every hook passed, 1 a hook failed, 2 a hook is refused.

Python 3.14 or newer; PyYAML and pre-commit (the kit's hashed tools).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

CONFIG = ".pre-commit-config.yaml"
# What pre-commit runs as it is on the machine, under its old and new names.
LANGUAGES = ("system", "script", "unsupported", "unsupported_script")


class RefusedError(Exception):
    """A hook that may not run beside the deny-list, and why."""


def local_hooks(text: str) -> dict[str, dict[str, Any]]:
    """The hooks a configuration itself defines, by id."""
    parsed = yaml.safe_load(text)
    repos = parsed.get("repos") if isinstance(parsed, dict) else None
    return {
        str(hook["id"]): hook
        for entry in (repos if isinstance(repos, list) else ())
        if isinstance(entry, dict) and entry.get("repo") == "local"
        for hook in entry.get("hooks") or ()
        if isinstance(hook, dict) and "id" in hook
    }


def refusal(hook_id: str, hooks: dict[str, dict[str, Any]]) -> str | None:
    """Why a hook may not run beside the deny-list, or None."""
    hook = hooks.get(hook_id)
    if hook is None:
        return f"{hook_id} is not a local hook"
    if hook.get("language") not in LANGUAGES:
        return f"{hook_id} is language {hook.get('language')}: it may install something"
    if hook.get("additional_dependencies"):
        return f"{hook_id} installs {hook['additional_dependencies']}"
    if "pre-commit" not in (hook.get("stages") or ["pre-commit"]):
        return f"{hook_id} does not run at the pre-commit stage"
    return None


def chosen(names: str, hooks: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The named hooks, in order."""
    ids = names.replace(",", " ").split()
    if not ids:
        raise RefusedError("no hook is named")
    for hook_id in ids:
        why = refusal(hook_id, hooks)
        if why:
            raise RefusedError(why)
    return [hooks[hook_id] for hook_id in ids]


def main(argv: list[str]) -> int:
    """Run the named hooks on every file."""
    try:
        if len(argv) != 1:
            raise RefusedError("usage: deny_hooks.py ID[,ID ...]")
        hooks = chosen(argv[0], local_hooks(Path(CONFIG).read_text(encoding="utf-8")))
    except (RefusedError, OSError, yaml.YAMLError) as exc:
        print(f"deny_hooks: {exc}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="kleidos-deny-") as tmp:
        config = Path(tmp) / "config.yaml"
        config.write_text(
            yaml.safe_dump({"repos": [{"repo": "local", "hooks": hooks}]}), encoding="utf-8"
        )
        cmd = ["pre-commit", "run", "--config", str(config), "--all-files", "--color", "always"]
        done = subprocess.run([*cmd, "--show-diff-on-failure"], check=False)
    return 1 if done.returncode else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
