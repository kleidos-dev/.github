#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""What this checkout of the kit would find in a repository, and refreshed copies.

The two verbs of ecosystem.py that run the kit's own modules: `preview`
applies the kit to throwaway clones and counts, and `refresh` copies again
what a record names.

Python 3.14 or newer, git; PyYAML.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import posixpath
import re
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import kit_switch

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / "quality"))
import agent_docs  # noqa: E402  the kit's module, found through the path set above
import check_quality as cq  # noqa: E402  the kit's module, as above
import run_form  # noqa: E402  the kit's module, as above
import spdx_headers  # noqa: E402  the kit's module, as above
import sync  # noqa: E402  the kit's module, as above


class RefreshError(Exception):
    """A copy that cannot be refreshed, and why."""


@dataclass(frozen=True)
class Found:
    """What the kit finds in one repository."""

    form: str  # "run", "2.x" or "none"
    held: str  # problems of the 2.x copies, as the repository stands
    drift: str  # what its drift notice would say
    run: Counter[str]  # problems of the run form, by check


def clone(target: str, dest: Path) -> bool:
    """A whole clone of a checkout or a slug (the years of the headers need the history)."""
    local = Path(target)
    ssh = not os.environ.get("GITHUB_ACTIONS")
    remote = f"git@github.com:{target}.git" if ssh else f"https://github.com/{target}.git"
    source = f"file://{local.resolve()}" if local.is_dir() else remote
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    done = subprocess.run(
        ["git", "clone", "-q", source, str(dest)], capture_output=True, check=False, env=env
    )
    return done.returncode == 0


def policy_problems(repo: Path, kit: cq.Kit) -> Counter[str]:
    """Every policy problem of a repository, counted by check."""
    out: Counter[str] = Counter(p.rule for p in cq.run(repo, kit=kit).problems)
    out.update(f.check for f in agent_docs.check(agent_docs.Repo(repo)) if not f.warning)
    out["spdx-headers"] += len(spdx_headers.check_repo(repo)[0])
    return +out


def examine(repo: Path, kit: cq.Kit) -> Found:
    """What the kit finds in a throwaway clone (which it changes)."""
    record = cq.record_of(cq.Repo(repo))
    if record is not None:
        return Found("run", "-", "-", policy_problems(repo, kit))
    path = repo / cq.SOURCE_JSON
    if not path.is_file():
        return Found("none", "-", "-", Counter())
    recorded = json.loads(path.read_text(encoding="utf-8"))
    commit = str(recorded.get("commit"))
    drift = sync.drift_status(commit, KIT)["behind"]
    # The 2.x form first: its copies brought to this kit, judged as 2.x was.
    sync.write(repo, commit=commit, allow_dirty=True)
    held = cq.run(repo, kit=kit).problems
    problems, _notes = spdx_headers.check_repo(repo)
    count = len(held) + len(problems)
    subprocess.run(["git", "-C", str(repo), "reset", "-q", "--hard"], check=True)
    subprocess.run(["git", "-C", str(repo), "clean", "-qfd"], check=True)
    kit_switch.switch(repo, kit, commit, dt.datetime.now(tz=dt.UTC).date())
    return Found(
        "2.x",
        str(count),
        "not behind" if drift == "false" else "behind",
        policy_problems(repo, kit),
    )


def row(target: str, found: Found | None) -> str:
    """One line of the preview's table."""
    if found is None:
        return f"| {target} | not reachable | | | |"
    if found.form == "none":
        return f"| {target} | no kit | - | - | - |"
    by_check = ", ".join(f"{name} {n}" for name, n in sorted(found.run.items()))
    switched = f"{sum(found.run.values())}" + (f" ({by_check})" if by_check else "")
    return f"| {target} | {found.form} | {found.held} | {found.drift} | {switched} |"


def table(targets: list[str]) -> tuple[str, int]:
    """The preview of these repositories, and how many could not be reached."""
    kit = cq.DirKit(KIT)
    rows = [
        "| Repository | Form | 2.x copies: problems | Its drift notice"
        " | Run form, after the mechanical switch: problems |",
        "| --- | --- | --- | --- | --- |",
    ]
    missed = 0
    with tempfile.TemporaryDirectory(prefix="kit-preview-") as tmp:
        for target in targets:
            dest = Path(tmp) / re.sub(r"[^\w.-]", "_", target)
            found = examine(dest, kit) if clone(target, dest) else None
            missed += found is None
            rows.append(row(target, found))
    head = (
        f"## Quality kit {kit.version()}: impact preview\n\n"
        "Types, tests, the third-party hooks and the online audits run in each repository's own"
        " CI and are not counted.\n\n"
    )
    return head + "\n".join(rows) + "\n", missed


# --------------------------------------------------------------------------
# refresh


def git_out(repo: Path, *args: str) -> str:
    """A git command's output in a checkout."""
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise RefreshError(f"git {args[0]} failed in {repo}: {done.stderr.strip()[:200]}")
    return done.stdout.strip()


def source_checkout(named: Path | None, record: Path, repo: str) -> Path:
    """The checkout a record's source is read from: the one named, else a sibling."""
    top = Path(git_out(record.parent, "rev-parse", "--show-toplevel"))
    found = named or top.parent / repo.partition("/")[2]
    if not (found / ".git").exists():
        raise RefreshError(f"no checkout of {repo} at {found}: name one with --from")
    origin = git_out(found, "remote", "get-url", "origin").removesuffix(".git")
    if not origin.lower().endswith((f"/{repo.lower()}", f":{repo.lower()}")):
        raise RefreshError(f"{found} is a checkout of {origin}, not of {repo}")
    if git_out(found, "status", "--porcelain"):
        raise RefreshError(f"{found} has uncommitted changes: what is copied is committed first")
    return found


def refresh(record: Path, named: Path | None, today: dt.date | None = None) -> list[str]:
    """Copy again what a record names; return what changed."""
    today = today or dt.datetime.now(tz=dt.UTC).date()
    try:
        data: Any = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RefreshError(f"{record} cannot be read: {exc}") from exc
    if not run_form.is_record(data):
        raise RefreshError(f"{record} is not a record of schema {run_form.SCHEMA}")
    problems = [p for p in run_form.record_problems(data, today) if not p.startswith("taken")]
    if problems:
        raise RefreshError(f"{record}: {problems[0]}")
    upstream = data["upstream"]
    if upstream["repo"] == cq.KIT_REPO:
        top = Path(git_out(record.parent, "rev-parse", "--show-toplevel"))
        commit = git_out(KIT, "rev-parse", "HEAD")
        return kit_switch.write_configs(top, cq.DirKit(KIT), commit, today) or ["nothing changed"]
    if data["mode"] == "frozen" or upstream.get("commit") is None:
        what = "frozen" if data["mode"] == "frozen" else "a generator's output"
        raise RefreshError(f"{record} is {what}: it is made again, not refreshed")
    source = source_checkout(named, record, upstream["repo"])
    root = Path(git_out(record.parent, "rev-parse", "--show-toplevel"))
    rel = record.resolve().relative_to(root.resolve()).as_posix()
    log = []
    fresh: dict[str, bytes] = {}
    targets = run_form.record_targets(rel, data)
    for name in data["files"]:
        path = posixpath.normpath(
            posixpath.join(upstream["path"], data.get("sources", {}).get(name, name))
        )
        target = targets[name]
        origin = (source / path).resolve()
        if target is None or not origin.is_relative_to(source.resolve()) or not origin.is_file():
            raise RefreshError(f"{upstream['repo']} has no {path}")
        fresh[name] = origin.read_bytes()
    for name, content in fresh.items():
        digest = cq.sha256(content)
        if digest != data["files"][name]:
            log.append(f"refreshed {name}")
        data["files"][name] = digest
        (root / str(targets[name])).write_bytes(content)
    upstream["commit"] = git_out(source, "rev-parse", "HEAD")
    data["taken"] = today.isoformat()
    record.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return log or ["nothing changed but the date and the commit it notes"]
