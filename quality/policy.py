#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Every policy check of the quality kit, on one repository.

The `kleidos-kit` hook runs it from the kit's hook repository, and the lint
and licensing jobs of the entry workflow quick.yml from the kit's own
checkout, so the checks a person runs and the ones the CI runs are one
program. The repository holds none of it (docs/quality.md, "The hooks").

  kit           check_quality.py: the repository against the kit
  agent-docs    agent_docs.py: AGENTS.md and CLAUDE.md
  md-nowrap     md_nowrap.py: Markdown prose is never hard-wrapped
  spdx-headers  spdx_headers.py: both licensing lines, the owner's statement

On a failure it prints the version of the kit that ran and the revision of
the kit's hook entry it found: the CI runs the branch and the hooks a
release, so the two can differ for a while, and a person sees at once
which one complained.

Usage:
    policy.py [--repo DIR] [--only CHECK ...] [--without CHECK ...]
              [--lint-skip IDS] [--github] [--summary FILE] [--kit-sha SHA]

Exit status: 0 clean, 1 problems, 2 the checks cannot run.

Python 3.14 or newer; PyYAML.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import agent_docs
import check_quality as cq
import md_nowrap
import run_form
import spdx_headers

KIT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Options:
    """What the command line says."""

    repo: Path
    lint_skip: str = ""
    github: bool = False
    summary: Path | None = None
    kit_sha: str = ""


def kit_check(opts: Options) -> list[str]:
    """check_quality.py, with this kit as the kit of the run form and of its home."""
    kit = cq.DirKit(KIT)
    report = cq.run(opts.repo, kit=kit)
    repo = cq.Repo(opts.repo)
    if repo.root != KIT and not repo.runs_the_kit():
        # Which form a repository has is not its own choice here: kit 2.x
        # copies are judged by the kit they were taken from.
        report.add(
            "record",
            cq.SOURCE_JSON,
            "is not a record of the run form: a repository that runs the kit holds none of it"
            " (tools/kit_switch.py)",
        )
    refused = cq.refused_skips(opts.lint_skip, cq.kit_block_hook_ids(kit) | set(run_form.KIT_HOOKS))
    for hook in refused:
        report.add("workflows", "skip", f"names the kit hook {hook}: only the repository's own")
    for note in report.notes:
        print(f"note: {note}")
    for weak, waiver in report.waived:
        print(f"waived: {weak.tool} {weak.what} ({weak.where}): {waiver.get('reason')}")
    if opts.summary:
        with opts.summary.open("a", encoding="utf-8") as fh:
            fh.write(cq.render_markdown(report))
    return [f"{p.where}: [{p.rule}] {p.message}" for p in report.problems]


def agent_docs_check(opts: Options) -> list[str]:
    """agent_docs.py; its warnings are printed and fail nothing."""
    found = agent_docs.check(agent_docs.Repo(opts.repo))
    for finding in found:
        if finding.warning:
            print(f"warning: {finding}")
        if opts.github:
            print(agent_docs.annotation(finding))
    return [str(f) for f in found if not f.warning]


def md_nowrap_check(opts: Options) -> list[str]:
    """md_nowrap.py over every Markdown file git knows of.

    A top-level `exclude` of .pre-commit-config.yaml is respected, as it is
    for every hook: the kit check asks a waiver for it.
    """
    repo = cq.Repo(opts.repo)
    excluded = re.compile(run_form.global_exclude(repo) or r"\Z.")
    return [
        f"{rel}:{num}: hard-wrapped prose (join it to the line above)"
        for rel in repo.files
        if rel.endswith(".md") and not excluded.search(rel)
        for num in md_nowrap.wrapped_lines(
            repo.path(rel).read_text(encoding="utf-8", errors="replace")
        )
    ]


def spdx_check(opts: Options) -> list[str]:
    """spdx_headers.py over the whole tree."""
    found, notes = spdx_headers.check_repo(opts.repo.resolve())
    for note in notes:
        print(f"note: {note}")
    return found


CHECKS: dict[str, Callable[[Options], list[str]]] = {
    "kit": kit_check,
    "agent-docs": agent_docs_check,
    "md-nowrap": md_nowrap_check,
    "spdx-headers": spdx_check,
}


def kit_line(sha: str = "") -> str:
    """The kit that runs, as `kit v3.0.0 (0123abcdef01)`."""
    if not sha:
        done = subprocess.run(
            ["git", "-C", str(KIT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        sha = done.stdout.strip() if done.returncode == 0 else "no commit"
    return f"kit v{cq.DirKit(KIT).version()} ({sha[:12]})"


def main(argv: list[str] | None = None) -> int:
    """Run the chosen checks; every one runs even after one fails."""
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo", type=Path, default=Path())
    ap.add_argument("--only", action="append", choices=list(CHECKS), default=[])
    ap.add_argument("--without", action="append", choices=list(CHECKS), default=[])
    ap.add_argument("--lint-skip", default="", help="the lint job's skip input")
    ap.add_argument("--github", action="store_true", help="also print GitHub annotations")
    ap.add_argument("--summary", type=Path, help="append the kit check's report here")
    ap.add_argument("--kit-sha", default="", help="the commit of the kit, where git cannot say")
    ap.add_argument("files", nargs="*", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    opts = Options(args.repo, args.lint_skip, args.github, args.summary, args.kit_sha)
    chosen = [c for c in (args.only or CHECKS) if c not in args.without]
    total = 0
    for name in chosen:
        try:
            found = CHECKS[name](opts)
        except (cq.SetupError, agent_docs.NotAWorkTreeError) as exc:
            print(f"policy {name}: {exc}", file=sys.stderr)
            return 2
        for line in found:
            print(f"{name}: {line}")
        total += len(found)
    which = kit_line(args.kit_sha)
    if total:
        rev = run_form.hook_rev(cq.Repo(args.repo))
        print(f"{total} problem(s) found by {which}, the hooks here are at {rev}")
        print("the rules are in kleidos-dev/.github, docs/quality.md")
        return 1
    print(f"clean: {', '.join(chosen)} ({which})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
