#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Copy the Kleidos quality kit into a repository, check it, or preview a change.

The kit lives in kleidos-dev/.github (quality/, docs/quality.md). A
repository adopts it with one command, and takes every later kit release
with the same command in a sync pull request:

    sync.py --write REPO [--profiles base,python,...] [--test-dir tests]
        writes the copies, the managed blocks (the organization rules in
        AGENTS.md among them), the files seeded once
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

Run it from a clean checkout of kleidos-dev/.github at the release to
record: the commit is HEAD, which --write requires to be the tag
quality-v<quality/VERSION> on origin/main (--allow-untagged lifts that for a
throwaway tree), and a dirty tree is refused (--allow-dirty while
developing the kit). REPO may be kleidos-dev/.github itself, which records
commit "self".

    sync.py --release-check [--on-main]
        kleidos-dev/.github's CI: a change to what repositories receive
        bumps quality/VERSION, and a version on main is tagged
    sync.py --drift RECORDED_COMMIT
        the drift notice: key=value lines naming the newest release and
        whether RECORDED_COMMIT's kit is behind it

Python 3.15 or newer; PyYAML.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path, PurePosixPath
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


# Copies earlier kit versions made and this one does not: a sync removes them.
RETIRED_COPIES = (".github/quality/requirements-tools.txt",)
TAG_PREFIX = "quality-v"
MAIN_REF = "refs/remotes/origin/main"
# What a repository receives from the kit: a change here is a kit release.
KIT_TREE = ("quality", ".github/workflows", ".github/commit-check")


def git(*args: str, cwd: Path = CENTRAL) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, check=True, text=True
    ).stdout.strip()


def git_ok(*args: str, cwd: Path = CENTRAL) -> str | None:
    """A git command's output, or None when it fails."""
    done = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, check=False, text=True
    )
    return done.stdout.strip() if done.returncode == 0 else None


def central_commit(allow_dirty: bool) -> str:
    """This checkout's HEAD, refusing a dirty tree unless allowed."""
    if git("status", "--porcelain") and not allow_dirty:
        raise SystemExit(
            "sync: the kit checkout has uncommitted changes; commit them or pass --allow-dirty"
        )
    return git("rev-parse", "HEAD")


def tag_commit(tag: str, cwd: Path = CENTRAL) -> str | None:
    return git_ok("rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}", cwd=cwd)


def release_commit(version: str, cwd: Path = CENTRAL) -> str:
    """HEAD, if it is exactly the release tag of this VERSION and on origin/main.

    A repository records only a released kit commit: every call to a kit
    workflow carries `# quality-v<VERSION>`, and zizmor's online
    ref-version-mismatch audit fails unless that tag names the same commit.
    """
    tag = f"{TAG_PREFIX}{version}"
    head = git("rev-parse", "HEAD", cwd=cwd)
    tagged = tag_commit(tag, cwd)
    if tagged is None:
        raise SystemExit(
            f"sync: there is no tag {tag} in this kit checkout: fetch the tags and check out"
            f" the release (git fetch --tags origin && git checkout {tag}), or tag the merged"
            ' release first (docs/quality.md, "Changing the kit")'
        )
    if tagged != head:
        raise SystemExit(
            f"sync: HEAD {head[:12]} is not {tag} ({tagged[:12]}): check out the release"
            f" (git checkout {tag}); a repository records released kit commits only"
        )
    if git_ok("rev-parse", "-q", "--verify", MAIN_REF, cwd=cwd) is None:
        raise SystemExit("sync: no origin/main in this kit checkout: git fetch origin main")
    if git_ok("merge-base", "--is-ancestor", head, MAIN_REF, cwd=cwd) is None:
        raise SystemExit(f"sync: {tag} ({head[:12]}) is not on origin/main: refusing to record it")
    return head


def kit_fingerprint(ref: str, cwd: Path = CENTRAL) -> str:
    """A digest of everything a repository receives from the kit at one commit.

    quality/ (but its tests), the reusable workflows, the commit-message
    checker, and the bytes of the kit's managed blocks; nothing else of this
    repository (its own CI, its media hooks, its docs) moves the kit.
    """
    listing = git("ls-tree", "-r", ref, "--", *KIT_TREE, cwd=cwd)
    digest = hashlib.sha256()
    for line in sorted(listing.splitlines()):
        meta, _, path = line.partition("\t")
        if path.startswith("quality/tests/"):
            continue
        if path.startswith(".github/workflows/") and not PurePosixPath(path).name.startswith(
            "reusable-"
        ):
            continue
        if path.startswith(".github/commit-check/") and not path.endswith("check_commit_msg.py"):
            continue
        digest.update(f"{path}\0{meta.split()[-1]}\n".encode())
    kit = cq.GitKit(cwd, ref)
    for entry in kit.manifest().get("block", []):
        digest.update(f"block {entry['id']}\0".encode())
        digest.update(cq.canonical_block(kit, entry).encode("utf-8"))
    return digest.hexdigest()


def release_tags(cwd: Path = CENTRAL) -> list[str]:
    """The kit's release tags, newest first."""
    out = git("tag", "-l", f"{TAG_PREFIX}*", "--sort=-v:refname", cwd=cwd)
    return [t for t in out.splitlines() if re.fullmatch(rf"{TAG_PREFIX}\d+\.\d+\.\d+", t)]


def release_check(on_main: bool, cwd: Path = CENTRAL) -> tuple[int, list[str]]:
    """Whether this commit's kit is a release: (exit status, lines to print).

    A pull request that changes what repositories receive bumps
    quality/VERSION and adds its CHANGELOG entry; once merged to main, the
    release is tagged at the merge commit, which is what repositories record.
    """
    version = (cwd / "quality" / "VERSION").read_text(encoding="utf-8").strip()
    tag = f"{TAG_PREFIX}{version}"
    head = git("rev-parse", "HEAD", cwd=cwd)
    tags = release_tags(cwd)
    lines: list[str] = []
    if tag in tags:
        tagged = tag_commit(tag, cwd) or ""
        if kit_fingerprint(tagged, cwd) != kit_fingerprint(head, cwd):
            lines.append(
                f"::error title=Kit changed without a release::what repositories receive"
                f" changed since {tag} ({tagged[:12]}): bump quality/VERSION and add its"
                ' quality/CHANGELOG.md entry (docs/quality.md, "Versions")'
            )
            return 1, lines
        lines.append(f"kit at {tag} ({tagged[:12]}): released")
        return 0, lines
    changelog = (cwd / "quality" / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## {re.escape(version)}\b", changelog, re.MULTILINE):
        lines.append(f"::error title=No changelog entry::quality/CHANGELOG.md has no ## {version}")
        return 1, lines
    if tags:
        newest = tags[0].removeprefix(TAG_PREFIX)
        if tuple(map(int, version.split("."))) <= tuple(map(int, newest.split("."))):
            lines.append(
                f"::error title=Version not newer::quality/VERSION {version} is not newer than"
                f" the newest release {tags[0]}"
            )
            return 1, lines
    if on_main:
        lines.append(
            f"::error title=Release not tagged::quality/VERSION is {version} and no tag"
            f" {tag} exists: tag this commit, signed (git tag -s {tag} -m 'Quality kit"
            f" {version}' {head} && git push origin {tag}), then re-run this job"
        )
        return 1, lines
    lines.append(f"::notice title=Kit release {version}::tag {tag} at the merge commit once merged")
    return 0, lines


def drift_status(recorded: str, cwd: Path = CENTRAL) -> dict[str, str]:
    """For a repository's drift notice: the newest release and whether it is behind it."""
    tags = release_tags(cwd)
    if not tags:
        return {"behind": "false", "tag": "", "commit": "", "version": ""}
    newest = tags[0]
    commit = tag_commit(newest, cwd) or ""
    behind = recorded != commit
    if behind and git_ok("cat-file", "-e", f"{recorded}^{{commit}}", cwd=cwd) is not None:
        behind = kit_fingerprint(recorded, cwd) != kit_fingerprint(commit, cwd)
    return {
        "behind": "true" if behind else "false",
        "tag": newest,
        "commit": commit,
        "version": newest.removeprefix(TAG_PREFIX),
    }


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
    kind = str(entry.get("kind") or "")
    indent = "  " if kind == "pre-commit" else ""
    start_marker, end_marker = cq.block_markers(block_id, str(entry["source"]), indent, kind)
    removed: list[str] = []
    found = cq.find_block(text, block_id)
    if found is not None:
        start, end, _old = found
        lines[start : end + 1] = [start_marker, inner, end_marker]
    elif kind == "markdown":
        lines, removed = _place_markdown(lines, [start_marker, inner, end_marker], inner)
    elif kind == "pre-commit":
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


def _section_end(lines: list[str], start: int) -> int:
    """The line after a `## ` section that opens at start: the next `#`/`##` heading or the end."""
    fenced = False
    for i in range(start + 1, len(lines)):
        if re.match(r"^\s*(```|~~~)", lines[i]):
            fenced = not fenced
        elif not fenced and re.match(r"^#{1,2}\s", lines[i]):
            return i
    return len(lines)


def _place_markdown(lines: list[str], block: list[str], inner: str) -> tuple[list[str], list[str]]:
    """Put a Markdown block in place of the section it replaces, else before a later one.

    A section with the block's own heading (`## Organization rules`, numbered
    or not, pasted by hand before the kit managed it) is replaced and returned
    as removed; without one the block goes before the heading the standard
    puts after it (`## Other repositories`), else at the end. One blank line
    separates it from its neighbors.
    """
    heading = next((ln for ln in inner.splitlines() if ln.startswith("#")), None)
    same = None
    if heading:
        level, _, title = heading.partition(" ")
        # The same heading, numbered or not (`## 5. Organization rules`).
        same = re.compile(rf"^{level}\s+(?:\d+\.\s+)?{re.escape(title.strip())}\s*$")
    at = next((i for i, ln in enumerate(lines) if same and same.match(ln.rstrip("\n"))), None)
    removed: list[str] = []
    if at is not None:
        end = _section_end(lines, at)
        removed = [ln.rstrip("\n") for ln in lines[at:end] if ln.strip()]
        del lines[at:end]
    else:
        at = next(
            (
                i
                for i, ln in enumerate(lines)
                if re.match(r"^##\s+(?:\d+\.\s+)?Other repositories\s*$", ln)
            ),
            len(lines),
        )
    before, after = lines[:at], lines[at:]
    while before and not before[-1].strip():
        before.pop()
    while after and not after[0].strip():
        after.pop(0)
    out = [*before, "\n"] if before else []
    out += block
    if after:
        out += ["\n", *after]
    return out, removed


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
    allow_untagged: bool = False,
) -> list[str]:
    """Bring repo to this kit checkout; return a log of what was written.

    With no commit given, a repository records HEAD, which must be the
    release tag of quality/VERSION on origin/main (allow_untagged lifts that
    for a throwaway tree, never for a sync pull request).
    """
    repo = repo.resolve()
    kit = cq.DirKit(CENTRAL)
    version = kit.version()
    is_central = repo == CENTRAL.resolve()
    if commit is None and is_central:
        commit = "self"
    elif commit is None:
        commit = central_commit(allow_dirty)
        if not allow_untagged:
            commit = release_commit(version)
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
        if b.get("kind") == "markdown" and not (repo / str(b["target"])).is_file():
            # The repository writes its own AGENTS.md (docs/agent-docs.md); the
            # check reports the block missing until it does.
            log.append(f"skipped block {b['id']}: there is no {b['target']} (docs/agent-docs.md)")
        else:
            removed = place_block(repo / str(b["target"]), b, inner)
            log.append(f"block {b['id']} in {b['target']}")
            if b.get("kind") == "markdown" and removed:
                log.append(f"  replaced the hand-written section {removed[0].strip()!r}")
            else:
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
    kept = {str(f["path"]) for f in files_rec}
    for entry in old.get("files") or []:
        rel = str(entry.get("path", ""))
        if rel in kept or not (cq.is_kit_target(rel) or rel in RETIRED_COPIES):
            continue
        target = repo / rel
        if ".." in PurePosixPath(rel).parts or not target.parent.resolve().is_relative_to(repo):
            continue
        if target.is_symlink() or target.is_file():
            target.unlink()  # a symlink itself, never the file it points to
        log.append(f"removed {rel}: the kit no longer copies it")
    year = str(dt.datetime.now(tz=dt.UTC).year)
    replaced: list[str] = []
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
            if replace:
                replaced.append(str(s["target"]))
    log.extend(forget_commit_check_copies(repo, replaced))
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


def forget_commit_check_copies(repo: Path, replaced: list[str]) -> list[str]:
    """Drop the replaced workflows from .github/commit-check/SOURCE.json; return a log.

    The commit-message checker stays kleidos-dev/agents' copy (the
    commit-msg hook runs it); the two workflows become thin callers of the
    kit, which the repository owns, so its commit-check manifest and the
    digest test that reads it stop listing them.
    """
    path = repo / cq.COMMIT_CHECK_SOURCE
    if not replaced or not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    files = data.get("files") or []
    left = [e for e in files if str(e.get("path")) not in replaced]
    if len(left) == len(files):
        return []
    data["files"] = left
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return [
        f"dropped {', '.join(sorted(replaced))} from {cq.COMMIT_CHECK_SOURCE}: the repository's"
        " commit-check digest test (tests/ci/test_commit_check_copy.py) now expects the"
        " checker alone; edit its path set in this pull request"
    ]


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


def format_count(tree: Path) -> str:
    """How many files `ruff format` would change in a tree (from its JSON report)."""
    exe = shutil.which("ruff")
    if exe is None:
        return "n/a"
    out = subprocess.run(
        [exe, "format", "--check", "--output-format", "json", "."],
        cwd=tree,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        found = json.loads(out.stdout or "[]")
    except ValueError:
        return "n/a"
    return str(len({d.get("filename") for d in found if d.get("code") == "unformatted"}))


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
                fmt = format_count(dest)
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
    group.add_argument(
        "--release-check",
        action="store_true",
        help="kleidos-dev/.github CI: is this commit's kit a tagged release (or a new one)?",
    )
    group.add_argument(
        "--drift",
        metavar="RECORDED_COMMIT",
        help="the drift notice: the newest release, and whether a recorded commit is behind it",
    )
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
    ap.add_argument(
        "--allow-untagged",
        action="store_true",
        help="--write: record HEAD even if it is not the release tag (throwaway trees only)",
    )
    ap.add_argument(
        "--on-main", action="store_true", help="--release-check: this is a commit on main"
    )
    ap.add_argument("--summary", type=Path, help="--preview appends its table here")
    args = ap.parse_args(argv)
    if args.release_check:
        status, lines = release_check(args.on_main)
        print("\n".join(lines))
        return status
    if args.drift:
        for key, value in drift_status(args.drift).items():
            print(f"{key}={value}")
        return 0
    if args.write:
        if not args.write.is_dir():
            print(f"sync: {args.write} is not a directory", file=sys.stderr)
            return 2
        profiles = [p.strip() for p in args.profiles.split(",")] if args.profiles else None
        for line in write(
            args.write,
            profiles=profiles,
            test_dir=args.test_dir,
            allow_dirty=args.allow_dirty,
            allow_untagged=args.allow_untagged,
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
