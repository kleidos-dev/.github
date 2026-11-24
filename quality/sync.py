#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""The held form of the Kleidos quality kit: copies, blocks and their releases.

From kit 3.0.0 a repository runs the kit and holds none of its code
(docs/quality.md, "How a repository runs the kit"); tools/kit_switch.py
moves it there. This script serves what has not moved yet: the kit's home,
which still records its own copies and blocks, the kit 2.x repositories'
weekly drift notice, and the kit's own release check. It goes in the first
release after no repository holds copies any more.

    sync.py --write REPO [--profiles base,python,...] [--test-dir tests]
        (kleidos-dev/.github itself, and no other) writes the copies, the
        managed blocks (the organization rules in AGENTS.md among them),
        the files seeded once (.gitleaks.toml, waivers.toml,
        .markdownlint-cli2.jsonc, the drift caller), points every call to
        a kit workflow at this checkout's commit, and records it all in
        REPO/.github/quality/SOURCE.json
    sync.py --check REPO [REPO ...]
        check_quality.py against this working tree of the kit (exit 1 on
        any problem), the way kleidos-dev/agents' sync_commit_check.py
        --check compares copies
    sync.py --release-check [--on-main] [--online]
        kleidos-dev/.github's CI: a change to what repositories receive
        bumps quality/VERSION, and a version on main is tagged and is
        where the branch v<major> is; every release tag is annotated and
        signed (--online: GitHub verifies the signature, through gh), and
        no tag is named like a branch
    sync.py --drift RECORDED_COMMIT
        the drift notice of a kit 2.x repository (its weekly job runs the
        default branch's copy of this script): key=value lines naming the
        newest release and whether RECORDED_COMMIT's kit is behind it. Being
        behind is never red (owner, 2026-11-24), and kit 3 is not taken by
        a sync, so a recorded 2.x commit is never behind.

Python 3.15 or newer; PyYAML.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

HERE = Path(__file__).resolve().parent
CENTRAL = HERE.parent
sys.path.insert(0, str(HERE))
import check_quality as cq  # noqa: E402  the sibling module, found through the path set above
import own_files  # noqa: E402  the sibling module, found through the path set above
import spdx_headers  # noqa: E402  the sibling module, found through the path set above

TOML_HEADER = r"^\s*\[\s*{table}\s*\]\s*(?:#.*)?$"
SKELETONS = {
    ".pre-commit-config.yaml": "# Install once per clone: pre-commit install\nrepos:\n",
    "pyproject.toml": "",
    ".typos.toml": "",
}


# Copies earlier kit versions made and this one does not: a sync removes them.
RETIRED_COPIES = (".github/quality/requirements-tools.txt",)
# A release is the tag v<VERSION>; before 3.0.0 it was quality-v<VERSION>.
TAG_PREFIX = "v"
OLD_TAG_PREFIX = "quality-v"
RUN_FORM_MAJOR = 3
REMOTE = "refs/remotes/origin"
# What a repository runs or receives from the kit: a change here is a kit release.
KIT_TREE = (
    "quality",
    "hooks",
    ".pre-commit-hooks.yaml",
    ".github/workflows",
    ".github/commit-check",
)
ENTRY_WORKFLOWS = ("quick.yml", "check.yml", "sonar.yml")


def git(*args: str, cwd: Path = CENTRAL) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, check=True, text=True
    ).stdout.strip()


def git_ok(*args: str, cwd: Path = CENTRAL) -> str | None:
    """A git command's output, or None when it fails."""
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


def tag_commit(tag: str, cwd: Path = CENTRAL) -> str | None:
    return git_ok("rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}", cwd=cwd)


def kit_fingerprint(ref: str, cwd: Path = CENTRAL) -> str:
    """A digest of everything a repository receives from the kit at one commit.

    quality/ (but its tests), the hooks, the entry and reusable workflows,
    and the bytes of the kit's managed blocks; nothing else of this
    repository (its own CI, its media hooks, its tools, its docs) moves the kit.
    """
    listing = git("ls-tree", "-r", ref, "--", *KIT_TREE, cwd=cwd)
    digest = hashlib.sha256()
    for line in sorted(listing.splitlines()):
        meta, _, path = line.partition("\t")
        if path.startswith("quality/tests/"):
            continue
        name = PurePosixPath(path).name
        if path.startswith(".github/workflows/") and not (
            name.startswith("reusable-") or name in ENTRY_WORKFLOWS
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


def version_of(tag: str) -> tuple[int, ...]:
    """The version a release tag names, as integers."""
    return tuple(int(n) for n in tag.rpartition("v")[2].split("."))


def release_tags(cwd: Path = CENTRAL) -> list[str]:
    """The kit's release tags (v3.0.0, quality-v2.3.0), newest version first."""
    out = git("tag", "-l", cwd=cwd).splitlines()
    tags = [t for t in out if re.fullmatch(rf"(?:{OLD_TAG_PREFIX}|{TAG_PREFIX})\d+\.\d+\.\d+", t)]
    return sorted(tags, key=version_of, reverse=True)


# A signed tag carries its signature after the message; GitHub verifies it.
SIGNATURE = re.compile(r"^-----BEGIN (?:PGP|SSH) SIGNATURE-----$", re.MULTILINE)
# The kit's branches are v<major>: a tag of that form would hide one.
BRANCH_NAME = re.compile(rf"{TAG_PREFIX}\d+")


def verified_on_github(tag_object: str) -> bool | None:
    """Whether GitHub verifies a tag object's signature (gh, the CI's token); None if unknown."""
    done = subprocess.run(
        [
            *("gh", "api", f"repos/{cq.KIT_REPO}/git/tags/{tag_object}"),
            *("--jq", ".verification.verified"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return {"true": True, "false": False}.get(done.stdout.strip()) if not done.returncode else None


def clash(name: str, release: bool) -> str:
    """What to do about a tag and a branch of one name: the release tag always stays."""
    if release:  # never deleted or moved (docs/quality.md, "Changing the kit")
        return (
            f"::error title=A tag named like a branch::the branch {name} is named like the"
            f" release tag {name}, which hides it (GitHub resolves the tag first) and is never"
            f" deleted or moved: delete the branch, git push origin :refs/heads/{name}"
        )
    return (
        f"::error title=A tag named like a branch::the tag {name} hides the branch of"
        f" that name (GitHub resolves the tag first): delete it, git push origin"
        f" :refs/tags/{name}"
    )


def tag_problems(
    cwd: Path = CENTRAL, verified: Callable[[str], bool | None] | None = None
) -> list[str]:
    """What is wrong with the tags: one named like a branch, a release tag not signed.

    A release tag is the hooks' `rev` in every repository and the release a
    record notes, so it is annotated and signed, as docs/quality.md
    "Changing the kit" writes it; a lightweight one, or one with no
    signature, was pushed by a hand that skipped -s. With `verified`,
    GitHub's verdict on each signature is asked too.
    """
    branches = set(
        git("for-each-ref", "--format=%(refname:lstrip=3)", REMOTE, cwd=cwd).splitlines()
    )
    releases = release_tags(cwd)
    out = [
        clash(name, name in releases)
        for name in git("tag", "-l", cwd=cwd).splitlines()
        if BRANCH_NAME.fullmatch(name) or name in branches
    ]
    for tag in releases:
        kind = git_ok("cat-file", "-t", f"refs/tags/{tag}", cwd=cwd)
        body = git("cat-file", "tag", f"refs/tags/{tag}", cwd=cwd) if kind == "tag" else ""
        if not SIGNATURE.search(body):
            what = "a lightweight tag" if kind != "tag" else "an annotated tag with no signature"
            out.append(
                f"::error title=Release tag not signed::{tag} is {what}: release tags are"
                f" signed (git tag -s {tag} -m 'Quality kit"
                f" {'.'.join(map(str, version_of(tag)))}' <its commit>)"
            )
        elif verified is not None:
            answer = verified(git("rev-parse", f"refs/tags/{tag}", cwd=cwd))
            if answer is not True:
                said = "does not verify" if answer is False else "could not be asked to verify"
                out.append(
                    f"::error title=Release tag not verified::GitHub {said} {tag}'s signature"
                )
    return out


def release_check(
    on_main: bool, cwd: Path = CENTRAL, verified: Callable[[str], bool | None] | None = None
) -> tuple[int, list[str]]:
    """Whether this commit's kit is a release: (exit status, lines to print).

    A pull request that changes what repositories receive bumps
    quality/VERSION and adds its CHANGELOG entry; once merged to main, the
    release is tagged at the merge commit, which is what repositories record.
    Every tag is held to tag_problems first.
    """
    version = (cwd / "quality" / "VERSION").read_text(encoding="utf-8").strip()
    tag = f"{TAG_PREFIX}{version}"
    head = git("rev-parse", "HEAD", cwd=cwd)
    tags = release_tags(cwd)
    lines: list[str] = tag_problems(cwd, verified)
    if lines:
        return 1, lines
    if tag in tags:
        tagged = tag_commit(tag, cwd) or ""
        if kit_fingerprint(tagged, cwd) != kit_fingerprint(head, cwd):
            lines.append(
                f"::error title=Kit changed without a release::what repositories receive"
                f" changed since {tag} ({tagged[:12]}): bump quality/VERSION and add its"
                ' quality/CHANGELOG.md entry (docs/quality.md, "Versions")'
            )
            return 1, lines
        branch = f"v{version.split('.')[0]}"
        at = git_ok("rev-parse", "-q", "--verify", f"{REMOTE}/{branch}", cwd=cwd)
        if on_main and at != tagged:
            lines.append(
                f"::error title=Branch not moved::{tag} is {tagged[:12]} and {branch}, which every"
                f" repository runs, is at {(at or 'nothing')[:12]}: git fetch origin && git push"
                f" origin {tag}^{{commit}}:refs/heads/{branch}, then re-run this job"
            )
            return 1, lines
        lines.append(f"kit at {tag} ({tagged[:12]}): released")
        return 0, lines
    changelog = (cwd / "quality" / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## {re.escape(version)}\b", changelog, re.MULTILINE):
        lines.append(f"::error title=No changelog entry::quality/CHANGELOG.md has no ## {version}")
        return 1, lines
    if tags and tuple(map(int, version.split("."))) <= version_of(tags[0]):
        lines.append(
            f"::error title=Version not newer::quality/VERSION {version} is not newer than"
            f" the newest release {tags[0]}"
        )
        return 1, lines
    if on_main:
        lines.append(
            f"::error title=Release not tagged::quality/VERSION is {version} and no tag"
            f" {tag} exists: release it (git fetch origin && git tag -s {tag} -m 'Quality kit"
            f" {version}' origin/main && git push origin {tag}"
            f" refs/remotes/origin/main:refs/heads/v{version.split('.')[0]}),"
            " then re-run this job"
        )
        return 1, lines
    lines.append(f"::notice title=Kit release {version}::tag {tag} at the merge commit once merged")
    return 0, lines


def recorded_major(recorded: str, cwd: Path = CENTRAL) -> int | None:
    """The major version of the kit at a recorded commit, None when it cannot be read."""
    known = cq.SHA40.match(recorded)
    text = git_ok("show", f"{recorded}:quality/VERSION", cwd=cwd) if known else None
    found = re.match(r"(\d+)\.", text or "")
    return int(found.group(1)) if found else None


def drift_status(recorded: str, cwd: Path = CENTRAL) -> dict[str, str]:
    """For a kit 2.x repository's drift notice: the newest release, and "not behind".

    Only a repository that held copies of a kit 3 release could be behind it,
    and there is none to hold: the kit is run from 3.0.0 on. A commit this
    clone cannot read (its history was squashed away) is not behind either.
    """
    tags = release_tags(cwd)
    if not tags:
        return {"behind": "false", "tag": "", "commit": "", "version": ""}
    newest = tags[0]
    commit = tag_commit(newest, cwd) or ""
    major = recorded_major(recorded, cwd)
    behind = (
        major is not None
        and major >= RUN_FORM_MAJOR
        and kit_fingerprint(recorded, cwd) != kit_fingerprint(commit, cwd)
    )
    return {
        "behind": "true" if behind else "false",
        "tag": newest,
        "commit": commit,
        "version": ".".join(map(str, version_of(newest))),
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


def place_block(repo: Path, entry: dict[str, Any], inner: str) -> list[str]:
    """Write one managed block into its file (created if missing).

    Returns the repository's own lines the block displaced (a key it now sets).
    """
    block_id = str(entry["id"])
    path = own_files.own_file(repo, str(entry["target"]))
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
    own_files.write(repo, str(entry["target"]), "".join(lines))
    return removed


def _markdown_headings(lines: list[str]) -> list[int]:
    """The indexes of the heading lines a reader sees: none in a fenced block or an HTML comment."""
    found: list[int] = []
    fenced = False
    in_comment = False
    for i, line in enumerate(lines):
        if not in_comment and re.match(r"^\s*(```|~~~)", line):
            fenced = not fenced
        elif fenced:
            continue
        elif in_comment or line.lstrip().startswith("<!--"):
            in_comment = "-->" not in line
        elif re.match(r"^#{1,6}\s", line):
            found.append(i)
    return found


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
    headings = _markdown_headings(lines)
    at = next((i for i in headings if same and same.match(lines[i].rstrip("\n"))), None)
    removed: list[str] = []
    if at is not None:
        # The section ends at the next heading of its level or above, or the file's end.
        end = next((i for i in headings if i > at and re.match(r"^#{1,2}\s", lines[i])), len(lines))
        removed = [ln.rstrip("\n") for ln in lines[at:end] if ln.strip()]
        del lines[at:end]
    else:
        at = next(
            (
                i
                for i in headings
                if re.match(r"^##\s+(?:\d+\.\s+)?Other repositories\s*$", lines[i])
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
                lambda m: f"{m.group(1)}{commit}{m.group(2)} # {TAG_PREFIX}{version}",
                ln.rstrip("\n"),
            )
            + ("\n" if ln.endswith("\n") else "")
            for ln in text.splitlines(keepends=True)
        )
        rel = path.relative_to(repo).as_posix()
        if new != text and own_files.write(repo, rel, new):
            changed.append(rel)
    return changed


# --------------------------------------------------------------------------
# --write


def write(
    repo: Path,
    profiles: list[str] | None = None,
    commit: str | None = None,
    test_dir: str | None = None,
) -> list[str]:
    """Bring repo to this kit checkout's held form; return a log of what was written.

    Only the kit's home records itself ("self"); for a throwaway tree of
    another repository (the preview) the caller names the commit.
    """
    repo = repo.resolve()
    kit = cq.DirKit(CENTRAL)
    version = kit.version()
    is_central = repo == CENTRAL.resolve()
    if commit is None and is_central:
        commit = "self"
    elif commit is None:
        raise SystemExit("sync: kit 3 is run, not copied: nothing but its home is written")
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
        target = own_files.own_file(repo, str(c["target"]))
        if own_files.write(repo, str(c["target"]), data):
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
            removed = place_block(repo, b, inner)
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
            text = spdx_headers.set_year(kit.read(str(s["source"])).decode("utf-8"), year)
            own_files.write(repo, str(s["target"]), text)
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
    own_files.write(repo, cq.SOURCE_JSON, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
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
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    own_files.write(repo, cq.COMMIT_CHECK_SOURCE, text)
    return [
        f"dropped {', '.join(sorted(replaced))} from {cq.COMMIT_CHECK_SOURCE}: the repository's"
        " commit-check digest test (tests/ci/test_commit_check_copy.py) now expects the"
        " checker alone; edit its path set in this pull request"
    ]


# --------------------------------------------------------------------------
# --check


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", type=Path, metavar="REPO")
    group.add_argument("--check", type=Path, nargs="+", metavar="REPO")
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
        "--on-main", action="store_true", help="--release-check: this is a commit on main"
    )
    ap.add_argument(
        "--online",
        action="store_true",
        help="--release-check: GitHub verifies each release tag's signature (gh, GH_TOKEN)",
    )
    args = ap.parse_args(argv)
    if args.release_check:
        status, lines = release_check(
            args.on_main, verified=verified_on_github if args.online else None
        )
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
        if args.write.resolve() != CENTRAL.resolve():
            print(
                "sync: kit 3 is run, not copied: move the repository with tools/kit_switch.py"
                ' (docs/quality.md, "Switching from kit 2.x")',
                file=sys.stderr,
            )
            return 2
        profiles = [p.strip() for p in args.profiles.split(",")] if args.profiles else None
        for line in write(
            args.write,
            profiles=profiles,
            test_dir=args.test_dir,
        ):
            print(line)
        return check([args.write])
    return check(args.check)


if __name__ == "__main__":
    sys.exit(main())
