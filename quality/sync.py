#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Copy the Kleidos quality kit into a repository, check it, or preview a change.

The kit lives in kleidos-dev/.github (quality/, docs/quality.md). A
repository adopts it with one command, and takes every later kit release
with the same command in a sync pull request:

    sync.py --write REPO [--profiles base,python,...] [--test-dir tests]
        writes the copies, the managed blocks, the files seeded once
        (.gitleaks.toml, waivers.toml, .markdownlint-cli2.jsonc, the drift
        caller), points every call to a kit workflow at this checkout's
        commit, and records it all in REPO/.github/quality/SOURCE.json
    sync.py --check REPO [REPO ...]
        check_quality.py against this working tree of the kit (exit 1 on
        any problem), the way kleidos-dev/agents' sync_commit_check.py
        --check compares copies
    sync.py --preview [--tools] REPO_OR_SLUG [...]
        applies --write to a throwaway clone and reports what the kit would
        find there (with --tools, ruff and zizmor too); never fails

Run it from a clean checkout of kleidos-dev/.github at the commit to
record: the commit is HEAD, and a dirty tree is refused for --write (pass
--allow-dirty while developing the kit). REPO may be kleidos-dev/.github
itself, which records commit "self".

Python 3.11 or newer; PyYAML.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CENTRAL = HERE.parent
sys.path.insert(0, str(HERE))
import check_quality as cq  # noqa: E402  the sibling module, found through the path set above
import spdx_headers  # noqa: E402  the sibling module, found through the path set above

TOML_HEADER = r"^\s*\[\s*{table}\s*\]\s*(?:#.*)?$"
SKELETONS = {
    ".pre-commit-config.yaml": "# Install once per clone: pre-commit install\nrepos:\n",
    "pyproject.toml": "",
    ".typos.toml": "",
}


def git(*args: str, cwd: Path = CENTRAL) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, check=True, text=True
    ).stdout.strip()


def central_commit(allow_dirty: bool) -> str:
    """This checkout's HEAD, refusing a dirty tree unless allowed."""
    if git("status", "--porcelain") and not allow_dirty:
        raise SystemExit(
            "sync: the kit checkout has uncommitted changes; commit them or pass --allow-dirty"
        )
    return git("rev-parse", "HEAD")


def expected_entries(
    kit: cq.Kit, profiles: list[str], options: dict[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Copies, blocks and seeds of kit.toml for these profiles and options."""
    copies, blocks = cq.expected(kit, profiles, options)
    seeds = [s for s in kit.manifest().get("seed", []) if s["profile"] in profiles]
    return copies, blocks, seeds


# --------------------------------------------------------------------------
# Managed blocks


def _strip_local_duplicates(
    lines: list[str], table: str, keys: set[str]
) -> tuple[list[str], list[str]]:
    """Remove the table's own settings of keys the block now sets; return (lines, removed)."""
    header = re.compile(TOML_HEADER.format(table=re.escape(table)))
    out: list[str] = []
    removed: list[str] = []
    in_table = False
    in_block = False
    skipping_depth = 0
    for line in lines:
        bare = line.rstrip("\n")
        if cq.MARK_START.match(bare):
            in_block = True
        elif cq.MARK_END.match(bare):
            in_block = False
        elif re.match(r"^\s*\[", bare) and not in_block and skipping_depth == 0:
            in_table = bool(header.match(bare))
        if skipping_depth:
            skipping_depth += bare.count("[") - bare.count("]")
            removed.append(bare)
            continue
        m = re.match(r"^\s*([A-Za-z0-9_-]+)\s*=", bare)
        if in_table and not in_block and m and m.group(1) in keys:
            removed.append(bare)
            value = bare.split("=", 1)[1].split("#", 1)[0]
            skipping_depth = max(0, value.count("[") - value.count("]"))
            continue
        out.append(line)
    return out, removed


def place_block(path: Path, entry: dict[str, Any], inner: str) -> list[str]:
    """Write one managed block into path (created if missing).

    Returns the repository's own lines the block displaced (a key it now sets).
    """
    block_id = str(entry["id"])
    text = path.read_text(encoding="utf-8") if path.is_file() else SKELETONS.get(path.name, "")
    if text and not text.endswith("\n"):
        text += "\n"
    lines = text.splitlines(keepends=True)
    indent = "  " if entry.get("kind") == "pre-commit" else ""
    start_marker, end_marker = cq.block_markers(block_id, str(entry["source"]), indent)
    removed: list[str] = []
    found = cq.find_block(text, block_id)
    if found is not None:
        start, end, _old = found
        lines[start : end + 1] = [start_marker, inner, end_marker]
    elif entry.get("kind") == "pre-commit":
        at = _pre_commit_insert_point(lines)
        lines[at:at] = [start_marker, inner, end_marker]
    else:
        table = str(entry["table"])
        keys = set(tomllib.loads(inner))
        lines, removed = _strip_local_duplicates(lines, table, keys)
        header = re.compile(TOML_HEADER.format(table=re.escape(table)))
        after = next((i + 1 for i, ln in enumerate(lines) if header.match(ln.rstrip("\n"))), None)
        if after is None:
            if lines and lines[-1].strip():
                lines.append("\n")
            lines += [f"[{table}]\n", start_marker, inner, end_marker]
        else:
            lines[after:after] = [start_marker, inner, end_marker]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    return removed


def _pre_commit_insert_point(lines: list[str]) -> int:
    """After the last kit block already in the file, else right after `repos:`."""
    last_end = None
    for i, ln in enumerate(lines):
        if cq.MARK_END.match(ln.rstrip("\n")):
            last_end = i + 1
    if last_end is not None:
        return last_end
    for i, ln in enumerate(lines):
        if re.match(r"^repos:\s*(?:#.*)?$", ln):
            return i + 1
    lines.append("repos:\n")
    return len(lines)


# --------------------------------------------------------------------------
# Kit workflow references


def rewrite_uses(repo: Path, commit: str, version: str) -> list[str]:
    """Point every call to a kit workflow at commit; return the files changed."""
    changed: list[str] = []
    wf_dir = repo / ".github" / "workflows"
    if not wf_dir.is_dir():
        return changed
    pattern = re.compile(
        r"(kleidos-dev/\.github/\.github/workflows/[\w.-]+\.ya?ml@)[^\s#'\"]+([\"']?)(?:\s*#.*)?$"
    )
    for path in sorted(wf_dir.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        new = "".join(
            pattern.sub(
                lambda m: f"{m.group(1)}{commit}{m.group(2)} # quality-v{version}", ln.rstrip("\n")
            )
            + ("\n" if ln.endswith("\n") else "")
            for ln in text.splitlines(keepends=True)
        )
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(path.relative_to(repo).as_posix())
    return changed


# --------------------------------------------------------------------------
# --write


def write(
    repo: Path,
    profiles: list[str] | None = None,
    commit: str | None = None,
    test_dir: str | None = None,
    allow_dirty: bool = False,
) -> list[str]:
    """Bring repo to this kit checkout; return a log of what was written."""
    repo = repo.resolve()
    kit = cq.DirKit(CENTRAL)
    version = kit.version()
    is_central = repo == CENTRAL.resolve()
    if commit is None:
        commit = "self" if is_central else central_commit(allow_dirty)
    old: dict[str, Any] = {}
    source_path = repo / cq.SOURCE_JSON
    if source_path.is_file():
        old = json.loads(source_path.read_text(encoding="utf-8"))
    chosen = (
        set(profiles or old.get("profiles") or []) | cq.detect_profiles(cq.Repo(repo)) | {"base"}
    )
    ordered = [p for p in cq.KNOWN_PROFILES if p in chosen]
    options: dict[str, str] = dict(old.get("options") or {})
    if test_dir is not None:
        options["test_dir"] = test_dir.strip("/")
    log: list[str] = []
    copies, blocks, seeds = expected_entries(kit, ordered, options)
    files_rec = []
    for c in copies:
        data = kit.read(str(c["source"]))
        target = repo / str(c["target"])
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.read_bytes() != data:
            target.write_bytes(data)
            log.append(f"copied {c['target']}")
        if os.access(CENTRAL / str(c["source"]), os.X_OK):
            target.chmod(0o755)
        files_rec.append(
            {"path": c["target"], "source_path": c["source"], "sha256": cq.sha256(data)}
        )
    blocks_rec = []
    for b in blocks:
        inner = cq.canonical_block(kit, b)
        removed = place_block(repo / str(b["target"]), b, inner)
        log.append(f"block {b['id']} in {b['target']}")
        log.extend(
            f"  moved into the block, removed from {b['target']}: {line.strip()}"
            for line in removed
        )
        rec: dict[str, Any] = {
            "id": b["id"],
            "path": b["target"],
            "source_path": b["source"],
            "sha256": cq.sha256(inner.encode("utf-8")),
        }
        if b.get("table"):
            rec["table"] = b["table"]
        blocks_rec.append(rec)
    year = str(dt.datetime.now(tz=dt.UTC).year)
    for s in seeds:
        if s.get("consumer_only") and is_central:
            continue
        target = repo / str(s["target"])
        mark = s.get("replace_if")
        replace = (
            bool(mark) and target.is_file() and str(mark) in target.read_text(encoding="utf-8")
        )
        if not target.exists() or replace:
            target.parent.mkdir(parents=True, exist_ok=True)
            text = spdx_headers.set_year(kit.read(str(s["source"])).decode("utf-8"), year)
            target.write_text(text, encoding="utf-8")
            verb = "replaced the copy at" if replace else "seeded"
            log.append(f"{verb} {s['target']} (the repository's own from now on)")
    if not is_central:
        log.extend(
            f"pointed kit workflow calls in {f} at {commit[:12]}"
            for f in rewrite_uses(repo, commit, version)
        )
    record = {
        "$comment": (
            "Written by kleidos-dev/.github quality/sync.py --write; never edit it or the"
            " files and blocks it lists: change the kit there and sync again (docs/quality.md)."
        ),
        "source": cq.KIT_URL,
        "version": version,
        "commit": commit,
        "profiles": ordered,
        "options": options,
        "files": files_rec,
        "blocks": blocks_rec,
    }
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    log.append(f"recorded kit {version} at {commit[:12]} in {cq.SOURCE_JSON}")
    return log


# --------------------------------------------------------------------------
# --check and --preview


def check(repos: list[Path]) -> int:
    failed = False
    kit = cq.DirKit(CENTRAL)
    for repo in repos:
        report = cq.run(repo, kit=kit)
        for p in report.problems:
            print(f"{repo}: {p.where}: [{p.rule}] {p.message}")
        if not report.problems:
            print(f"{repo}: in sync")
        failed = failed or bool(report.problems)
    return 1 if failed else 0


def _clone(target: str, dest: Path) -> None:
    local = Path(target)
    src = f"file://{local.resolve()}" if local.exists() else f"https://github.com/{target}.git"
    subprocess.run(["git", "clone", "-q", "--depth", "1", src, str(dest)], check=True)


def _count(cmd: list[str], cwd: Path) -> str:
    exe = shutil.which(cmd[0])
    if exe is None:
        return "n/a"
    out = subprocess.run([exe, *cmd[1:]], cwd=cwd, capture_output=True, text=True, check=False)
    lines = [ln for ln in out.stdout.splitlines() if re.match(r"^\S+:\d+:\d+: ", ln)]
    return str(len(lines))


def preview(targets: list[str], tools: bool, allow_dirty: bool) -> str:
    """A Markdown table of what the kit would find in each target."""
    commit = central_commit(allow_dirty)
    rows = [
        "| Repository | Kit problems | Weakenings to waive or fix"
        " | ruff findings | ruff format (files) | zizmor findings |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for target in targets:
            dest = Path(tmp) / re.sub(r"[^\w.-]", "_", target)
            try:
                _clone(target, dest)
            except subprocess.CalledProcessError:
                rows.append(f"| {target} | not reachable | | | | |")
                continue
            write(dest, commit=commit, allow_dirty=True)
            report = cq.run(dest, kit=cq.DirKit(CENTRAL))
            unwaived = sum(1 for p in report.problems if "has no waiver" in p.message)
            ruff = fmt = ziz = "-"
            if tools:
                ruff = _count(
                    ["ruff", "check", "--output-format", "concise", "--exit-zero", "."], dest
                )
                fmt_out = subprocess.run(
                    [shutil.which("ruff") or "ruff", "format", "--check", "."],
                    cwd=dest,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                fmt = str(
                    sum(1 for ln in fmt_out.stdout.splitlines() if ln.startswith("Would reformat"))
                )
                ziz_out = subprocess.run(
                    [shutil.which("zizmor") or "zizmor", "--format", "json", "--offline", "."],
                    cwd=dest,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                try:
                    ziz = str(len(json.loads(ziz_out.stdout or "[]")))
                except ValueError:
                    ziz = "n/a"
            rows.append(
                f"| {target} | {len(report.problems) - unwaived} | {unwaived}"
                f" | {ruff} | {fmt} | {ziz} |"
            )
    head = (
        f"## Quality kit impact preview ({cq.DirKit(CENTRAL).version()} at {commit[:12]})\n\n"
        "mypy is not counted here: it needs each repository's dependencies,"
        " and every sync pull request measures and fixes it.\n\n"
    )
    return head + "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", type=Path, metavar="REPO")
    group.add_argument("--check", type=Path, nargs="+", metavar="REPO")
    group.add_argument("--preview", nargs="+", metavar="REPO_OR_SLUG")
    ap.add_argument(
        "--profiles", help="comma-separated; base is always on, and detected languages are added"
    )
    ap.add_argument(
        "--test-dir", help="also copy the drift test (test_quality_kit.py) into this directory"
    )
    ap.add_argument(
        "--tools", action="store_true", help="--preview also counts ruff and zizmor findings"
    )
    ap.add_argument(
        "--allow-dirty",
        action="store_true",
        help="record HEAD even if the kit checkout has changes",
    )
    ap.add_argument("--summary", type=Path, help="--preview appends its table here")
    args = ap.parse_args(argv)
    if args.write:
        if not args.write.is_dir():
            print(f"sync: {args.write} is not a directory", file=sys.stderr)
            return 2
        profiles = [p.strip() for p in args.profiles.split(",")] if args.profiles else None
        for line in write(
            args.write, profiles=profiles, test_dir=args.test_dir, allow_dirty=args.allow_dirty
        ):
            print(line)
        return check([args.write])
    if args.check:
        return check(args.check)
    targets: list[str] = []
    for target in args.preview:
        if target.startswith("@"):
            targets.extend(cq.DirKit(CENTRAL).manifest().get("consumers", {}).get(target[1:], []))
        else:
            targets.append(target)
    table = preview(targets, args.tools, args.allow_dirty)
    print(table)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
