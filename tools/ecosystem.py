#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""What is behind, what is broken and what is undeclared, across the Kleidos repositories.

    ecosystem.py report [--all] [--out DIR] [--notify] [--summary FILE]
        the one report (docs/ecosystem.md): copies, the kit, pull requests,
        links, SonarCloud's quality gates and, with --all, settings. Without
        --all it reads the public repositories only and cannot print a line
        about any other; --all uses the caller's own gh session, is refused
        in CI and is never posted
    ecosystem.py preview [--all] [REPO ...] [--summary FILE]
        apply this checkout of the kit to throwaway clones and count what it
        finds: the kit 2.x copies as they are, and the run form after the
        mechanical switch (for a repository that has switched, as it is)
    ecosystem.py refresh RECORD [--from CHECKOUT]
        copy again what a record names, from a checkout of its source, and
        rewrite its digests, its date and the commit it notes; for the kit's
        own record, the base configurations of this checkout
    ecosystem.py land [--merge] [REPO ...]
        Dependabot's pull requests that pass the guards (landing.py); without
        --merge it only says what it would do

States: red (something is broken or differs from the declared list: the run
fails), late (a copy or a bot's pull request past its limit: first in the
list, fails nothing), amber (behind), frozen, note, green. Being behind is
never red (owner, 2026-11-24).

The declared list is ecosystem.toml beside this file; what is not published,
the Apps that may write, is ~/.config/kleidos/ecosystem.local.toml. Reads
only: git clones and GET requests through gh; only land --merge writes, and
only merges.

Python 3.14 or newer, git and gh; PyYAML for preview and refresh.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CENTRAL = HERE.parent
DECLARED = HERE / "ecosystem.toml"
# What is declared but not published: the Apps that may write.
LOCAL = Path.home() / ".config" / "kleidos" / "ecosystem.local.toml"
STATES = ("red", "late", "amber", "frozen", "note", "green")
TITLES = {
    "red": "Red: broken, or not what is declared",
    "late": "Late: behind for longer than its limit (fails nothing)",
    "amber": "Amber: behind",
    "frozen": "Frozen inputs that differ from their source (no limit)",
    "note": "Notes",
    "green": "Green",
}
RECORD_NAMES = ("SOURCE.json", "KIT.json", "boards.json", "mirror.json", "meter-registry.lock.json")
KIT_CALL = re.compile(
    r"^\s*(?:-\s+)?uses:\s*['\"]?kleidos-dev/\.github/\.github/workflows/[\w.-]+@(?P<ref>[^\s'\"#]+)",
    re.MULTILINE,
)
KIT_REV = re.compile(
    r"repo:\s*['\"]?https://github\.com/kleidos-dev/\.github(?:\.git)?['\"]?\s*\n"
    r"(?:\s*#.*\n)*\s*rev:\s*['\"]?(?P<rev>[^\s'\"#]+)"
)
RELEASE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
LINK = re.compile(
    r"\]\((https://[^\s)]+)\)|(?:src|srcset|href)=\"(https://[^\s\"]+)|<(https://[^\s>]+)>"
)
BAD_CHECKS = ("failure", "timed_out", "startup_failure")
LOCAL_ONLY = (
    "Only the local run (report --all) reads: the settings and rulesets in full, the Apps, the"
    " deploy keys, the Workers, whether each SonarQube Cloud project exists, and every"
    " repository that is not public."
)
SONAR_GATE = "https://sonarcloud.io/api/qualitygates/project_status?projectKey={key}&branch=main"
# A link that reads from a repository: its page on GitHub, or a file of it served raw.
REPOSITORY_LINK = re.compile(
    r"^https://(?:github\.com|raw\.githubusercontent\.com)/(?P<slug>[\w.-]+/[\w.-]+)(?:[/?#]|$)",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# The declared list


@dataclass(frozen=True)
class Repository:
    """One declared repository."""

    slug: str
    public: bool
    cla: bool = False
    sonar: str = ""
    folds_into: str = ""
    hold: bool = False


@dataclass(frozen=True)
class Declared:
    """ecosystem.toml, read."""

    repositories: tuple[Repository, ...]
    raw: dict[str, Any]

    @property
    def login(self) -> str:
        """The organization."""
        return str(self.raw["organization"]["login"])

    @property
    def kit(self) -> str:
        """The repository of the quality kit."""
        return str(self.raw["organization"]["kit"])

    def limit(self, source: str) -> int:
        """How many days a copy of a source may be behind before it is late."""
        limits = self.raw["limits"]
        return int(limits.get("source", {}).get(source, limits["copy"]))

    def days(self, name: str) -> int:
        """One of the other limits, in days."""
        return int(self.raw["limits"][name])


def load(path: Path = DECLARED) -> Declared:
    """The declared list."""
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return Declared(tuple(Repository(**entry) for entry in raw["repository"]), raw)


# --------------------------------------------------------------------------
# Reading: gh, git, the web


class Reader:
    """Everything read from outside: GitHub's API, the repositories' files, web pages."""

    def __init__(self, folder: Path, ssh: bool) -> None:
        self.folder, self.ssh = folder, ssh
        self.unread: list[str] = []
        self._files: dict[str, dict[str, str]] = {}

    def api(self, path: str, pages: bool = False) -> Any:
        """A GET of GitHub's API; None when it is absent or not readable (which is listed)."""
        cmd = ["gh", "api", "--method", "GET", path]
        done = subprocess.run(
            cmd + (["--paginate", "--slurp"] if pages else []),
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            if not any(known in done.stderr for known in ("HTTP 404", "Upgrade to")):
                self.unread.append(f"{path}: {done.stderr.strip()[:120]}")
            return None
        data = json.loads(done.stdout) if done.stdout.strip() else None
        if pages and isinstance(data, list):
            return [item for page in data for item in page]
        return data

    def items(self, path: str, key: str = "") -> list[Any]:
        """A list from the API: every page of it, or the list under a key; [] when unreadable."""
        data = self.api(path, pages=not key)
        found = data.get(key) if key and isinstance(data, dict) else data
        return found if isinstance(found, list) else []

    def fetch(self, slug: str) -> bool:
        """Clone a repository's newest commit without its files' contents; whether it worked."""
        dest = self.folder / slug.replace("/", "__")
        base = "git@github.com:" if self.ssh else "https://github.com/"
        cmd = ["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout"]
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        done = subprocess.run(
            [*cmd, f"{base}{slug}.git", str(dest)], capture_output=True, check=False, env=env
        )
        if done.returncode != 0:
            self.unread.append(f"{slug}: cannot be cloned")
        return done.returncode == 0

    def _git(self, slug: str, *args: str, stdin: bytes | None = None) -> bytes | None:
        dest = self.folder / slug.replace("/", "__")
        done = subprocess.run(
            ["git", "-C", str(dest), *args], capture_output=True, check=False, input=stdin
        )
        return done.stdout if done.returncode == 0 else None

    def _listing(self, slug: str) -> dict[str, str]:
        """Path -> blob id of the files of a repository's main."""
        if slug not in self._files:
            listed = (self._git(slug, "ls-tree", "-r", "-z", "HEAD") or b"").decode("utf-8")
            rows = [row.partition("\t") for row in listed.split("\0") if row]
            self._files[slug] = {path: meta.split()[2] for meta, _tab, path in rows}
        return self._files[slug]

    def files(self, slug: str) -> list[str]:
        """The files of a repository's main."""
        return list(self._listing(slug))

    def prefetch(self, slug: str, paths: Iterable[str]) -> None:
        """Fetch these files' contents in one request instead of one each (git's own lazy way)."""
        listing = self._listing(slug)
        blobs = sorted({listing[path] for path in paths if path in listing})
        options = ("--no-tags", "--no-write-fetch-head", "--filter=blob:none", "--stdin")
        noop = ("-c", "fetch.negotiationAlgorithm=noop")
        if blobs:
            self._git(
                slug, *noop, "fetch", "-q", *options, "origin", stdin="\n".join(blobs).encode()
            )

    def read(self, slug: str, path: str) -> bytes | None:
        """A file's bytes on a repository's main."""
        return self._git(slug, "show", f"HEAD:{path}")

    def tree(self, slug: str, path: str) -> str:
        """The tree id of a folder of a repository's main."""
        return (self._git(slug, "rev-parse", f"HEAD:{path}") or b"").decode().strip()

    def status(self, url: str) -> int:
        """The HTTP status a page answers, 0 when nothing answers."""
        request = urllib.request.Request(  # noqa: S310  https only: LINK and ecosystem.toml
            url, headers={"User-Agent": "link-check"}
        )
        for attempt in range(2):
            try:
                with urllib.request.urlopen(request, timeout=20) as answer:  # noqa: S310  as above
                    return int(answer.status)
            except urllib.error.HTTPError as exc:
                with exc:
                    return exc.code
            except OSError:
                time.sleep(attempt)
        return 0

    def page(self, url: str) -> bytes | None:
        """A web page's bytes, None when it does not answer 200."""
        try:
            with urllib.request.urlopen(url, timeout=20) as answer:  # noqa: S310  as above
                data: bytes = answer.read()
                return data
        except urllib.error.HTTPError as exc:
            exc.close()
            return None
        except OSError:
            return None


# --------------------------------------------------------------------------
# The report


@dataclass(frozen=True)
class Row:
    """One line of the report."""

    state: str
    kind: str
    text: str


@dataclass
class Report:
    """The lines, and what the lines are about."""

    declared: Declared
    reader: Reader
    now: dt.datetime
    everything: bool
    local: Path = LOCAL
    rows: list[Row] = field(default_factory=list)
    withheld: int = 0

    @property
    def repositories(self) -> list[Repository]:
        """The repositories this run may read: the public ones, or all of them."""
        return [r for r in self.declared.repositories if r.public or self.everything]

    def add(self, state: str, kind: str, text: str) -> None:
        """One more line; a public run withholds one that names a private repository."""
        if not self.everything and names_private(self.declared, text):
            self.withheld += 1
            return
        self.rows.append(Row(state, kind, text))

    def age(self, stamp: str) -> int:
        """Whole days since a date or a time."""
        when = dt.datetime.fromisoformat(stamp)
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.UTC)
        return (self.now - when).days


def names_private(declared: Declared, text: str) -> bool:
    """Whether a text names a repository that is not public."""
    lowered = text.lower()
    return any(
        re.search(rf"{re.escape(r.slug.lower())}(?:\.git)?(?![\w-]|\.\w)", lowered)
        for r in declared.repositories
        if not r.public
    )


def sha256(data: bytes) -> str:
    """A digest as the records write it."""
    return hashlib.sha256(data).hexdigest()


# --- Copies ---------------------------------------------------------------


@dataclass(frozen=True)
class Copy:
    """One record of copies, whatever its dialect."""

    consumer: str
    source: str
    record: str
    mode: str  # "follow", "frozen" or "kit" (the base configurations)
    limit: int | None
    taken: str
    # copied path in the consumer ("" when no bytes are copied) -> (source path, digest);
    # a source path of "" means the source is a generator's output.
    files: tuple[tuple[str, str, str], ...]


def slug_of(url: str) -> str:
    """owner/name of a repository URL (or of a slug)."""
    return "/".join(url.removesuffix(".git").rstrip("/").split("/")[-2:])


def vendored(consumer: str, rel: str, data: dict[str, Any], kit: str) -> Copy:
    """A record of schema kleidos.vendored-copy/1."""
    upstream = data["upstream"]
    base = "" if data.get("root") == "." else posixpath.dirname(rel)
    sources = data.get("sources") or {}
    generated = upstream.get("commit") is None
    files = []
    for name, digest in data["files"].items():
        path = "" if generated else posixpath.normpath(posixpath.join(upstream["path"], name))
        files.append(
            (posixpath.normpath(posixpath.join(base, name)), sources.get(name, path), digest)
        )
    source = str(upstream["repo"])
    mode = "kit" if source == kit else str(data.get("mode", "follow"))
    return Copy(
        consumer,
        source,
        rel,
        mode,
        data.get("max_age_days"),
        str(data.get("taken", "")),
        tuple(files),
    )


def copies_of(consumer: str, rel: str, data: Any, kit: str) -> Copy | None:
    """What a record says, in any of the dialects in use, or None for another file."""
    if not isinstance(data, dict):
        return None
    folder = posixpath.dirname(rel)
    if data.get("schema") == "kleidos.vendored-copy/1":
        return vendored(consumer, rel, data, kit)
    name = posixpath.basename(rel)
    if name == "KIT.json" and str(data.get("kit", "")).startswith("kleidos-kicad/"):
        files = [(posixpath.join(folder, n), f"kicad/{n}", d) for n, d in data["files"].items()]
        return Copy(consumer, slug_of(data["source"]), rel, "frozen", None, "", tuple(files))
    if name == "boards.json" and "boards" in data and "commit" in data:
        files = [
            (posixpath.join(folder, f"{n}.svg"), b["from"], b["sha256"])
            for n, b in data["boards"].items()
        ]
        return Copy(consumer, slug_of(data["repository"]), rel, "frozen", None, "", tuple(files))
    if name == "mirror.json" and "files" in data:
        files = [("", n, d) for n, d in data["files"].items()]
        return Copy(consumer, "jmrplens/kleidos", rel, "frozen", None, "", tuple(files))
    if name == "meter-registry.lock.json":
        files = [("", "calibration/index.json", data["index_sha256"])]
        return Copy(
            consumer, data["repo"], rel, "follow", None, data.get("taken", ""), tuple(files)
        )
    return None


def find_copies(report: Report) -> Iterator[Copy]:
    """Every record of copies of the repositories this run reads."""
    for repo in report.repositories:
        files = report.reader.files(repo.slug)
        report.reader.prefetch(
            repo.slug,
            (
                p
                for p in files
                if p.startswith(".github/")
                or ("/" not in p and not p.endswith((".png", ".svg")))
                or posixpath.basename(p) in RECORD_NAMES
            ),
        )
        for rel in files:
            if posixpath.basename(rel) not in RECORD_NAMES or "fixtures" in rel.split("/"):
                continue
            raw = report.reader.read(repo.slug, rel)
            try:
                found = copies_of(repo.slug, rel, json.loads(raw or b"null"), report.declared.kit)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                report.add("red", "copy", f"{repo.slug} {rel}: not a record that reads: {exc!r}")
                continue
            if found is not None:
                yield found


def taken_date(report: Report, copy: Copy) -> str:
    """When a copy was taken: its own date, else when its record last changed."""
    if copy.taken:
        return copy.taken
    path = f"repos/{copy.consumer}/commits?path={copy.record}&per_page=1"
    commits = report.reader.api(path)
    return str(commits[0]["commit"]["committer"]["date"]) if commits else ""


def judge_copy(report: Report, copy: Copy) -> None:
    """One line for one record, and one more when a copy was edited in place."""
    read = report.reader.read
    label = f"{copy.consumer} <- {copy.source} {copy.record}"
    report.reader.prefetch(copy.consumer, (target for target, _source, _digest in copy.files))
    edited = [
        target
        for target, _source, digest in copy.files
        if target and sha256(read(copy.consumer, target) or b"") != digest
    ]
    if edited:
        report.add("red", "copy", f"{label}: edited in place, or gone: {named(edited)}")
    readable = {r.slug for r in report.repositories}
    if copy.source not in readable or any(not source for _t, source, _d in copy.files):
        if report.everything:
            report.add(
                "note", "copy", f"{label}: {len(copy.files)} held, its source not comparable"
            )
        return
    report.reader.prefetch(copy.source, (source for _t, source, _d in copy.files))
    now = {source: read(copy.source, source) for _t, source, _d in copy.files}
    gone = [source for source, data in now.items() if data is None]
    if gone and copy.mode != "kit":
        report.add("red", "copy", f"{label}: the source no longer has {named(gone)}")
    differ = [s for _t, s, d in copy.files if now[s] is not None and sha256(now[s] or b"") != d]
    if not differ:
        if not gone:
            report.add("green", "copy", f"{label}: {len(copy.files)} equal")
        return
    stamp = taken_date(report, copy)
    age = report.age(stamp) if stamp else 0
    text = f"{label}: {len(differ)} of {len(copy.files)} differ, taken {age} d ago: {named(differ)}"
    limit = copy.limit or report.declared.limit(copy.source)
    if copy.mode == "frozen":
        report.add("frozen", "copy", text)
    elif copy.mode == "kit" or age <= limit:
        report.add("amber", "copy", text)
    else:
        report.add("late", "copy", f"{text} [limit {limit} d]")


def named(paths: Iterable[str]) -> str:
    """The first three of a list of paths."""
    listed = sorted(paths)
    return ", ".join(listed[:3]) + (f" and {len(listed) - 3} more" if len(listed) > 3 else "")


# --- The kit --------------------------------------------------------------


def check_kit(report: Report) -> None:
    """Who runs the kit, at which name, and whether the names are sound."""
    kit = report.declared.kit
    tags = [str(t["name"]) for t in report.reader.items(f"repos/{kit}/tags?per_page=100")]
    branches = [str(b["name"]) for b in report.reader.items(f"repos/{kit}/branches?per_page=100")]
    for name in sorted(set(tags) & set(branches)):
        report.add("red", "kit", f"{kit}: a tag and a branch are both named {name}: the tag wins")
    releases = [(int(m[1]), int(m[2]), int(m[3])) for m in map(RELEASE_TAG.match, tags) if m]
    if not releases:
        report.add("note", "kit", f"{kit}: no v<major>.<minor>.<patch> release yet")
        return
    newest = max(releases)
    branch = f"v{newest[0]}"
    if branch not in branches:
        report.add("red", "kit", f"{kit}: no branch {branch}, which every repository calls")
    else:
        compared = report.reader.api(f"repos/{kit}/compare/{branch}...main")
        if compared and compared["behind_by"]:
            report.add("red", "kit", f"{kit}: {branch} is not on main")
        else:
            report.add(
                "green", "kit", f"{kit}: {branch} is on main, newest release v{dotted(newest)}"
            )
    for repo in report.repositories:
        if repo.slug != kit and not repo.folds_into:
            judge_kit(report, repo, branch, newest)


def dotted(version: tuple[int, ...]) -> str:
    """3.0.0"""
    return ".".join(str(n) for n in version)


def judge_kit(report: Report, repo: Repository, branch: str, newest: tuple[int, ...]) -> None:
    """How one repository calls the kit."""
    read = report.reader.read
    text = "\n".join(
        (read(repo.slug, rel) or b"").decode("utf-8", "replace")
        for rel in report.reader.files(repo.slug)
        if rel.startswith(".github/workflows/")
    )
    refs = {m["ref"] for m in KIT_CALL.finditer(text)}
    if not refs:
        report.add("amber", "kit", f"{repo.slug}: does not call the kit yet")
        return
    if refs != {branch}:
        what = "kit 2.x copies" if all(len(r) == 40 for r in refs) else ", ".join(sorted(refs))
        report.add("amber", "kit", f"{repo.slug}: {what}, not {branch}")
        return
    hooks = (read(repo.slug, ".pre-commit-config.yaml") or b"").decode("utf-8", "replace")
    found = KIT_REV.search(hooks)
    rev = found["rev"] if found else "none"
    if rev != f"v{dotted(newest)}":
        report.add(
            "amber", "kit", f"{repo.slug}: at {branch}, hooks at {rev}, newest v{dotted(newest)}"
        )
        return
    report.add("green", "kit", f"{repo.slug}: at {branch}, hooks at {rev}")


def check_pins(report: Report, outdated: Callable[[], list[str]]) -> None:
    """The kit's own pins that have a newer release (quality/latest_releases.py)."""
    try:
        behind = outdated()
    except (OSError, ValueError, KeyError) as exc:
        report.add("note", "pin", f"the kit's pins could not be compared: {exc}")
        return
    for line in behind:
        report.add("amber", "pin", line)
    if not behind:
        report.add("green", "pin", "every kit pin is at its latest release")


# --- Pull requests and links ----------------------------------------------


def check_pulls(report: Report) -> None:
    """The open pull requests of bots: failing is red, waiting too long is late."""
    limit = report.declared.days("bot_pull")
    for repo in report.repositories:
        for pull in report.reader.items(f"repos/{repo.slug}/pulls?state=open&per_page=100"):
            if pull["user"]["type"] != "Bot":
                continue
            runs = report.reader.items(
                f"repos/{repo.slug}/commits/{pull['head']['sha']}/check-runs?per_page=100",
                key="check_runs",
            )
            failing = sorted({r["name"] for r in runs if r["conclusion"] in BAD_CHECKS})
            age = report.age(pull["created_at"])
            text = f"{repo.slug}#{pull['number']} open {age} d: {pull['title'][:60]}"
            if failing:
                report.add("red", "pull", f"{text} [failing: {named(failing)}]")
            else:
                report.add("late" if age > limit else "amber", "pull", text)


def links_in(text: str) -> list[str]:
    """The https links and pictures of a Markdown file, each once."""
    found = (m[1] or m[2] or m[3] for m in LINK.finditer(text))
    return list(dict.fromkeys(url.partition("#")[0].split(" ")[0] for url in found))


def leaving_slug(url: str, leaving: dict[str, str]) -> str:
    """The repository a link reads from, when it is one that moves out ("" otherwise)."""
    found = REPOSITORY_LINK.match(url)
    slug = found["slug"].lower().removesuffix(".git") if found else ""
    return slug if slug in leaving else ""


def check_links(report: Report) -> None:
    """Every link and banner of the public READMEs answers, and none reads a repository that leaves.

    A repository with `folds_into` is deleted once its content has moved, so
    a README of any repository this run reads that still links to it, or
    shows a banner served from it, is red until it is pointed elsewhere; a
    repository that leaves itself is not read for it.
    """
    leaving = {r.slug.lower(): r.folds_into for r in report.declared.repositories if r.folds_into}
    urls: dict[str, str] = {}
    for repo in report.repositories:
        for rel in ("README.md", "profile/README.md"):
            text = (report.reader.read(repo.slug, rel) or b"").decode("utf-8", "replace")
            for url in links_in(text):
                slug = leaving_slug(url, leaving)
                if slug and not repo.folds_into:
                    report.add(
                        "red",
                        "leaving",
                        f"{repo.slug} {rel}: {url} reads {slug},"
                        f" which moves into {leaving[slug]} and is deleted",
                    )
                if repo.public:
                    urls.setdefault(url, f"{repo.slug} {rel}")
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        answers = dict(zip(urls, pool.map(report.reader.status, urls), strict=True))
    for url, status in answers.items():
        if status in (404, 410):
            report.add("red", "link", f"{urls[url]}: {url} answers {status}")
        elif status == 0 or status >= 500:
            report.add("note", "link", f"{urls[url]}: {url} did not answer ({status})")
    fine = sum(1 for s in answers.values() if 0 < s < 500 and s not in (404, 410))
    report.add("green", "link", f"{fine} of {len(answers)} links and banners answer")


def check_sonar(report: Report) -> None:
    """SonarCloud's quality gate on main of every public repository with a project.

    The kit's analysis job proves only that SonarCloud accepted the analysis;
    the gate is judged by SonarCloud's GitHub App, which no ruleset requires.
    Read here, a red gate on main is red in the report, whatever the job said.
    """
    passed = 0
    for repo in report.repositories:
        if not repo.public or not repo.sonar or repo.folds_into:
            continue
        page = report.reader.page(SONAR_GATE.format(key=repo.sonar))
        try:
            status = json.loads(page or b"")["projectStatus"]
            verdict = str(status["status"])
            conditions = status.get("conditions")
        except ValueError, KeyError, TypeError:
            report.add("note", "sonar", f"{repo.slug}: SonarCloud gave no quality gate")
            continue
        if not isinstance(conditions, list):
            conditions = []
        if verdict == "OK":
            passed += 1
            continue
        failed = sorted(
            str(c.get("metricKey"))
            for c in conditions
            if isinstance(c, dict) and c.get("status") == "ERROR"
        )
        report.add(
            "red",
            "sonar",
            f"{repo.slug}: SonarCloud's quality gate on main is {verdict}"
            + (f" ({', '.join(failed)})" if failed else ""),
        )
    report.add("green", "sonar", f"{passed} quality gates on main pass")


# --- Settings (the local run) ---------------------------------------------


def branch_rules(
    rulesets: list[dict[str, Any]], include: str
) -> tuple[set[str], set[str], dict[str, Any], set[str]]:
    """The rules on one ref pattern.

    The rule types, the bypass actors, the required checks, and of those the
    ones no ruleset requires without anybody who may bypass it.
    """
    chosen = [
        r
        for r in rulesets
        if r["enforcement"] == "active" and include in r["conditions"]["ref_name"]["include"]
    ]
    types = {rule["type"] for r in chosen for rule in r["rules"]}
    who = {b["actor_type"] for r in chosen for b in r.get("bypass_actors") or []}
    checks: dict[str, Any] = {}
    firm = set()
    for found in chosen:
        for rule in found["rules"]:
            if rule["type"] != "required_status_checks":
                continue
            for check in rule["parameters"]["required_status_checks"]:
                checks[check["context"]] = check.get("integration_id")
                if not found.get("bypass_actors"):
                    firm.add(check["context"])
    return types, who, checks, set(checks) - firm


def check_rules(
    report: Report,
    where: str,
    found: tuple[set[str], set[str], dict[str, Any], set[str]],
    wanted: list[str],
) -> None:
    """A ruleset against the rules and the bypass the list declares."""
    types, who, _checks, _loose = found
    lacking = sorted(set(wanted) - types)
    if lacking:
        report.add("red", "setting", f"{where}: no rule {', '.join(lacking)}")
    extra = who - set(report.declared.raw["organization"]["bypass"])
    if extra:
        report.add("red", "setting", f"{where}: {', '.join(sorted(extra))} may bypass the rules")


def check_repository(report: Report, repo: Repository, served: set[str]) -> None:
    """The settings of one public repository."""
    raw, read = report.declared.raw, report.reader
    listed = read.items(f"repos/{repo.slug}/rulesets")
    rulesets = [r for r in (read.api(f"repos/{repo.slug}/rulesets/{i['id']}") for i in listed) if r]
    main = branch_rules([r for r in rulesets if r["target"] == "branch"], "~DEFAULT_BRANCH")
    check_rules(report, f"{repo.slug} main", main, raw["rules"]["main"])
    for context, app in raw["required_checks"].items():
        if main[2].get(context) != app:
            report.add(
                "red", "setting", f"{repo.slug} main: {context} of App {app} is not required"
            )
        elif context in main[3]:
            report.add("red", "setting", f"{repo.slug} main: {context} may be bypassed")
    if repo.cla and repo.slug not in served:
        report.add("red", "setting", f"{repo.slug}: the CLA does not serve it")
    if repo.slug != report.declared.kit:
        return
    branches = branch_rules([r for r in rulesets if r["target"] == "branch"], "refs/heads/v[0-9]*")
    check_rules(report, f"{repo.slug} v[0-9]*", branches, raw["rules"]["kit_branch"])
    tags = branch_rules([r for r in rulesets if r["target"] == "tag"], "~ALL")
    check_rules(report, f"{repo.slug} tags", tags, raw["rules"]["kit_tags"])
    immutable = read.api(f"repos/{repo.slug}/immutable-releases") or {}
    if not immutable.get("enabled"):
        report.add("note", "setting", f"{repo.slug}: immutable releases are off")


def check_settings(report: Report) -> None:
    """The organization's settings against the declared list (the caller's own session)."""
    declared, read = report.declared, report.reader
    org = read.api(f"orgs/{declared.login}") or {}
    if (
        org.get("deploy_keys_enabled_for_repositories")
        != declared.raw["organization"]["deploy_keys"]
    ):
        report.add("red", "setting", f"{declared.login}: deploy keys are not as declared")
    config = json.loads(read.read("kleidos-dev/cla", "registry/config.json") or b"{}")
    served = set(config.get("served_repositories") or ())
    for repo in declared.repositories:
        if repo.public and not repo.folds_into:
            check_repository(report, repo, served)
        for key in read.items(f"repos/{repo.slug}/keys"):
            report.add("red", "setting", f"{repo.slug}: a deploy key, {key['title']!r}")
        text = (read.read(repo.slug, ".github/dependabot.yml") or b"").decode("utf-8", "replace")
        if not repo.folds_into and "package-ecosystem: pre-commit" not in text:
            report.add("amber", "setting", f"{repo.slug}: Dependabot moves no hook revision")
        if repo.sonar:
            url = f"https://sonarcloud.io/api/components/show?component={repo.sonar}"
            if read.status(url) != 200:
                report.add(
                    "red", "setting", f"{repo.slug}: no SonarQube Cloud project {repo.sonar}"
                )
    listed = {r.slug.lower() for r in declared.repositories}
    for found in read.items(f"orgs/{declared.login}/repos?per_page=100"):
        if found["full_name"].lower() not in listed:
            report.add("red", "setting", f"{found['full_name']} is not in the declared list")


def check_apps(report: Report) -> None:
    """The installed Apps that can write, against the local list."""
    if not report.local.is_file():
        report.add("note", "setting", f"no list of the Apps that may write at {report.local}")
        return
    declared = tomllib.loads(report.local.read_text(encoding="utf-8"))["apps"]
    path = f"orgs/{report.declared.login}/installations?per_page=100"
    for app in report.reader.items(path, key="installations"):
        watched = ("actions", "administration", "checks", "contents", "statuses", "workflows")
        writes = {p for p in watched if app["permissions"].get(p) == "write"}
        extra = sorted(writes - set(declared.get(app["app_slug"], ())))
        if extra:
            report.add("red", "setting", f"the App {app['app_slug']} can write {', '.join(extra)}")


def check_workers(report: Report) -> None:
    """Each deployed Worker against the tree of its main."""
    limit = report.declared.days("worker")
    for worker in report.declared.raw.get("worker", ()):
        label = f"{worker['repository']} {worker['url']}"
        page = report.reader.page(worker["url"])
        try:
            answer = json.loads(page or b"null")
            tree, built = str(answer["tree"]), str(answer["built"])
            age = report.age(built)
        except ValueError, KeyError, TypeError:
            report.add("note", "worker", f"{label}: does not say what it was deployed from")
            continue
        if tree == report.reader.tree(worker["repository"], worker["path"]):
            report.add("green", "worker", f"{label}: deployed from main's {worker['path']}/")
        else:
            state = "red" if age > limit else "amber"
            report.add(state, "worker", f"{label}: not main's {worker['path']}/, built {age} d ago")


def last_public_run(report: Report) -> str:
    """The age of the public report, and a red line when its schedule seems off."""
    kit = report.declared.kit
    path = (
        f"repos/{kit}/actions/workflows/ecosystem.yml/runs?branch=main&status=completed&per_page=1"
    )
    runs = report.reader.items(path, key="workflow_runs")
    if not runs:
        report.add("note", "schedule", f"{kit}: the public report has not run yet")
        return "no public run yet"
    age = report.age(runs[0]["created_at"])
    if age > report.declared.days("public_run"):
        report.add(
            "red", "schedule", f"{kit}: the public report is {age} days old: its schedule is off"
        )
    return f"public run {age} d ago ({runs[0]['conclusion']})"


# --- Building and printing ------------------------------------------------


def build(report: Report, outdated: Callable[[], list[str]]) -> str:
    """Read everything, fill the report, and return its first line."""
    head = f"Kleidos ecosystem, {report.now:%Y-%m-%d %H:%M} UTC"
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        list(pool.map(report.reader.fetch, [r.slug for r in report.repositories]))
    for copy in find_copies(report):
        judge_copy(report, copy)
    check_kit(report)
    check_pins(report, outdated)
    check_pulls(report)
    check_links(report)
    check_sonar(report)
    if report.everything:
        check_settings(report)
        check_apps(report)
        check_workers(report)
        head += f", every repository; {last_public_run(report)}"
    else:
        head += ", the public repositories"
    for line in report.reader.unread:
        report.add("note", "unread", line)
    for repo in report.repositories:
        if repo.folds_into:
            report.add(
                "note", "leaving", f"{repo.slug} moves into {repo.folds_into} and is deleted"
            )
    return head


def render(report: Report, head: str) -> str:
    """The report as Markdown, the worst first."""
    out = [f"# {head}", ""]
    for state in STATES:
        rows = [r for r in report.rows if r.state == state]
        if not rows:
            continue
        out += [f"## {TITLES[state]} ({len(rows)})", ""]
        out += [f"- `{r.kind}` {r.text}" for r in rows]
        out.append("")
    if not report.everything:
        out += [LOCAL_ONLY, ""]
    return "\n".join(out)


def notify(title: str, text: str) -> None:
    """Tell the person at this machine, when it has a way to."""
    if shutil.which("osascript"):
        script = "on run a\ndisplay notification (item 2 of a) with title (item 1 of a)\nend run"
        subprocess.run(["osascript", "-e", script, title, text], check=False)
    elif shutil.which("notify-send"):
        subprocess.run(["notify-send", title, text], check=False)


def kit_pins_behind() -> list[str]:
    """quality/latest_releases.py over the kit's own pins."""
    if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        # gh's own session, so the lookups are not counted as anonymous ones.
        token = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=False
        ).stdout.strip()
        if token:
            os.environ["GH_TOKEN"] = token
    sys.path.insert(0, str(CENTRAL / "quality"))
    import latest_releases

    return latest_releases.outdated()


def run_report(args: argparse.Namespace) -> int:
    """The report verb: 1 when something is red."""
    if args.all and os.environ.get("GITHUB_ACTIONS"):
        print("ecosystem: report --all is for a person's machine, never for CI", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="ecosystem-") as tmp:
        reader = Reader(Path(tmp), ssh=args.all)
        now = dt.datetime.now(dt.UTC)
        report = Report(load(args.declared), reader, now, args.all, args.local)
        head = build(report, kit_pins_behind)
    text = render(report, head)
    if not report.everything and names_private(report.declared, text):
        print("ecosystem: the public report would name a private repository", file=sys.stderr)
        return 2
    print(text)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(text)
    counts = {state: sum(1 for r in report.rows if r.state == state) for state in STATES}
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / f"ecosystem-{report.now:%Y-%m-%d}.md").write_text(text, encoding="utf-8")
    if args.notify:
        notify("Kleidos ecosystem", f"{counts['red']} red, {counts['late']} late")
    return 1 if counts["red"] else 0


# --------------------------------------------------------------------------
# preview, refresh, land: the modules beside this one


def run_preview(args: argparse.Namespace) -> int:
    """The preview verb: a table, 1 when a repository could not be previewed."""
    if args.all and os.environ.get("GITHUB_ACTIONS"):
        print("ecosystem: preview --all is for a person's machine, never for CI", file=sys.stderr)
        return 2
    import kit_preview

    declared = load(args.declared)
    chosen = [r.slug for r in declared.repositories if r.public or args.all]
    chosen = args.repositories or [s for s in chosen if s != declared.kit]
    text, missed = kit_preview.table(chosen)
    print(text)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(text)
    return 1 if missed else 0


def run_refresh(args: argparse.Namespace) -> int:
    """The refresh verb."""
    import kit_preview

    try:
        for line in kit_preview.refresh(args.record, args.source):
            print(line)
    except kit_preview.RefreshError as exc:
        print(f"ecosystem: {exc}", file=sys.stderr)
        return 2
    return 0


def run_land(args: argparse.Namespace) -> int:
    """The land verb."""
    import landing

    declared = load(args.declared)
    return landing.land(declared, args.repositories, merge=args.merge)


def main(argv: list[str] | None = None) -> int:
    """The command line."""
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--declared", type=Path, default=DECLARED, help="another declared list")
    verbs = ap.add_subparsers(dest="verb", required=True)
    report = verbs.add_parser("report", help="what is behind, broken or undeclared")
    report.add_argument("--all", action="store_true", help="every repository (a person's machine)")
    report.add_argument("--local", type=Path, default=LOCAL, help="another local list")
    report.add_argument("--out", type=Path, help="also write it here, as ecosystem-<date>.md")
    report.add_argument("--notify", action="store_true", help="also raise a desktop notification")
    report.add_argument("--summary", type=Path, help="also append it here (GITHUB_STEP_SUMMARY)")
    report.set_defaults(run=run_report)
    preview = verbs.add_parser("preview", help="what this kit would find in the repositories")
    preview.add_argument("--all", action="store_true", help="the private ones too (locally)")
    preview.add_argument("--summary", type=Path, help="also append it here (GITHUB_STEP_SUMMARY)")
    preview.add_argument("repositories", nargs="*", help="slugs or checkouts, instead of the list")
    preview.set_defaults(run=run_preview)
    refresh = verbs.add_parser("refresh", help="copy again what a record names")
    refresh.add_argument("record", type=Path, help="the SOURCE.json")
    refresh.add_argument("--from", dest="source", type=Path, help="a checkout of the source")
    refresh.set_defaults(run=run_refresh)
    land = verbs.add_parser("land", help="Dependabot's pull requests that pass the guards")
    land.add_argument("--merge", action="store_true", help="merge them (else only say so)")
    land.add_argument("repositories", nargs="*", help="slugs, instead of every one")
    land.set_defaults(run=run_land)
    args = ap.parse_args(argv)
    status: int = args.run(args)
    return status


if __name__ == "__main__":
    sys.exit(main())
