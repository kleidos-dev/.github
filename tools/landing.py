#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Land pull requests: those named, and Dependabot's that pass every guard (ecosystem.py land).

How a pull request lands is fast_forward.py's. What is here decides which of
Dependabot's do with nobody reading the diff: third-party code under the
owner's key, so what it accepts is narrow (docs/ecosystem.md, "Landing the
bot's pull requests"):

  - opened by Dependabot, head in the same repository, not a draft;
  - every push to its branch made by Dependabot or by the caller;
  - every commit authored by Dependabot and signed by GitHub, each saying
    what every update of it is, but for the caller's merges of main;
  - only requirements, pyproject.toml, package.json and package-lock.json
    changed, and each of their lines equal to its old one but for versions
    and checksums: a new package, a new host, an option or a script is
    left to a person, and so is a floor (a coverage threshold, the oldest
    Python or Node.js, a package index), and everything under .github/,
    where a green check proves nothing, since the pull request brings its
    own workflows;
  - no major version, as Dependabot's own commit says;
  - never the kit's repository, nor one on the hold list;
  - taken as a signed commit of the owner on today's main, in a pull request
    of its own that changes no more than the bot's, everything that runs on
    it green, the kit's gate among it.

One at a time, and each is listed with what landed. A pull request that is
named by its number lands by fast_forward.py's rules.

Python 3.14 or newer, gh, git.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import fast_forward
from fast_forward import BOT, GATE, REFUSED, at_home, kind, open_refusal

if TYPE_CHECKING:
    from ecosystem import Declared, Repository

# What may differ between a line and its old one: the group "version" is masked.
VERSION = r"\d[0-9A-Za-z.+!_-]*"
# A version of a package: pip's operators only, right after the package's name
# (and its extras), and each further bound a comma adds to that requirement.
# A bare `=` and an operator after a quote are no requirement: `fail_under =
# 90`, `--cov-fail-under=90`, `requires-python = ">=3.12"` and Poetry's
# `python = "<4,>=3.12"` are floors, never masked.
OPERATOR = r"(?:===|==|~=|!=|<=|>=|<|>)"
PINNED = re.compile(
    rf"(?P<keep>(?<![\w.-])[A-Za-z0-9][\w.-]*(?:\[[\w.,\s-]*\])?\s*{OPERATOR}\s*)"
    rf"(?P<version>{VERSION})(?P<more>(?:\s*,\s*{OPERATOR}\s*{VERSION})*)"
)
BOUND = re.compile(rf"(?P<keep>\s*,\s*{OPERATOR}\s*)(?P<version>{VERSION})")
RANGE = re.compile(
    rf'^(?P<keep>\s*"[^"]+": ")'
    rf'(?P<version>(?:(?:[\^~<>=]*\s?{VERSION}|\|\||-|\*)(?:\s|(?=")))+)(?=",?$)'
)
RESOLVED = re.compile(
    r'^(?P<keep>\s*"resolved": "https://registry\.npmjs\.org/(?:@[\w.-]+/)?[\w.-]+/-/[\w.-]+?-)'
    rf'(?P<version>{VERSION})(?=\.tgz",?$)'
)
INTEGRITY = re.compile(
    r'^(?P<keep>\s*"integrity": "sha512-)(?P<version>[A-Za-z0-9+/]{86}==)(?=",?$)'
)
HASH = re.compile(r"^(?P<keep>\s+--hash=sha256:)(?P<version>[0-9a-f]{64}(?: \\)?)(?=$)")
COMMENT = re.compile(r"^\s*#")
PYTHON, NODE = (HASH, PINNED), (RESOLVED, INTEGRITY, RANGE)
# Lines no mask may let through, whatever they hold: a floor a check holds the
# code to (coverage, the oldest Python or Node.js it runs on) and where
# packages come from. Dependabot moves versions; these are a person's to move.
PYTHON_FLOORS = re.compile(
    r"fail[_-]under|requires[_-]python|python[_-]requires|index[_-]url|find[_-]links"
    r"|trusted[_-]host|^\s*-[ifc]\b|\[\[?tool\.(?:uv|poetry|pdm|hatch)\b.*\b(?:index|source)"
    r"|^\s*python\s*=|required[_-]version",
    re.IGNORECASE,
)
ENGINES = re.compile(r'^\s*"(?:node|npm|pnpm|yarn|bun|engines|registry|packageManager)"\s*:')
NONE = re.compile(r"(?!)")
MANIFESTS = (
    (re.compile(r"^requirements(?:-[\w-]+)?\.(?:txt|in)$"), PYTHON, PYTHON_FLOORS),
    (re.compile(r"^pyproject\.toml$"), PYTHON, PYTHON_FLOORS),
    # The engines of the dependencies a lock records move with their versions.
    (re.compile(r"^package\.json$"), NODE, ENGINES),
    (re.compile(r"^package-lock\.json$"), NODE, NONE),
)
NAME_LINE = re.compile(r"^- dependency-name: ", re.MULTILINE)
# Dependabot quotes a name YAML would read otherwise (`"@types/node"`): the
# name is what is inside the quotes, and a quote left open, or closed by the
# other kind, names nothing. One group, so findall gives the names.
NAMED = re.compile(
    r"""^- dependency-name: (?:"(?=[^"'\s]+"\s*$)|'(?=[^"'\s]+'\s*$)|(?=[^"'\s]+\s*$))"""
    r"""(?P<name>[^"'\s]+)["']?\s*$""",
    re.MULTILINE,
)
# A line of package.json that names a version: its key is a package an
# update names, or it is no package's (an engine, the project's own version).
KEYED = re.compile(r'^\s*"(?P<key>[^"]+)":\s*"')
UPDATE_LINE = re.compile(
    r"^\s+update-type: version-update:semver-(major|minor|patch)\s*$", re.MULTILINE
)


def masked(line: str, rules: tuple[re.Pattern[str], ...]) -> str:
    """A line with its versions and checksums left out, as its first rule that fits reads it."""
    for rule in rules:
        if rule.search(line):
            return rule.sub(lambda found: f"{found['keep']}…{bounds(found)}", line)
    return line


def bounds(found: re.Match[str]) -> str:
    """The further bounds of a requirement (`,<2`), their versions left out too."""
    more = found.groupdict().get("more") or ""
    return BOUND.sub(lambda bound: f"{bound['keep']}…", more)


def blocks(patch: str) -> list[tuple[list[str], list[str]]]:
    """The changed lines of a diff: each run of old lines with the new ones in their place."""
    found: list[tuple[list[str], list[str]]] = []
    inside = False
    for line in patch.splitlines():
        if line[:1] in ("-", "+"):
            if not inside:
                found.append(([], []))
            found[-1][line[0] == "+"].append(line[1:])
        inside = line[:1] in ("-", "+", "\\")
    return found


def line_refusal(
    patch: str, rules: tuple[re.Pattern[str], ...], floors: re.Pattern[str] = NONE
) -> str | None:
    """Why the lines of a manifest change more than versions, or None: every block of it."""
    for old, new in blocks(patch):
        moved = [line for line in [*new, *old] if line not in old or line not in new]
        floor = next((line for line in moved if floors.search(line)), None)
        if floor is not None:
            return f"changes a floor or a package index: {floor.strip()[:80]}"
        sides = []
        for lines in (old, new):
            kept: list[str] = []
            for line in lines:
                text = masked(line, rules)
                # A version's checksums are as many as its files.
                again = bool(kept) and HASH.match(line) and text == kept[-1]
                if not (rules is PYTHON and COMMENT.match(line)) and not again:
                    kept.append(text)
            sides.append(kept)
        if sides[0] != sides[1]:
            only = [line for line in sides[1] if line not in sides[0]] or sides[0]
            return f"changes more than a version: {only[0].strip()[:80]}"
    return None


def file_refusal(changed: dict[str, Any], names: frozenset[str] | None = None) -> str | None:
    """Why a changed file is more than a version, or None.

    With the names of the packages the pull request updates, a changed line
    of package.json that names a version names one of them: every child of
    `engines`, whatever the engine, is no package's.
    """
    name = str(changed["filename"])
    if name.startswith(".github/"):
        return f"{name}: a green {GATE} proves nothing about a change under .github/"
    if changed.get("status") != "modified":
        return f"{name} is {changed.get('status')}"
    base = PurePosixPath(name).name
    kind = next(
        ((rules, floors) for pattern, rules, floors in MANIFESTS if pattern.match(base)), None
    )
    if kind is None:
        return f"{name} is no manifest this reads"
    patch = str(changed.get("patch") or "")
    if not blocks(patch):
        return f"{name} shows no diff to read"
    why = line_refusal(patch, *kind)
    if why is None and names is not None and base == "package.json":
        why = unnamed(patch, names)
    return f"{name} {why}" if why else None


def unnamed(patch: str, names: frozenset[str]) -> str | None:
    """A changed version line of package.json whose key no update names, or None."""
    for old, new in blocks(patch):
        for line in [*old, *new]:
            key = KEYED.match(line)
            if key and RANGE.match(line) and key["key"] not in names:
                return f"changes {key['key']}, which no update of it names: {line.strip()[:80]}"
    return None


def commit_refusal(commit: dict[str, Any], viewer: str) -> str | None:
    """Why a commit is not Dependabot's own, or None."""
    sha = commit["sha"][:7]
    verification = commit["commit"]["verification"]
    if not verification.get("verified"):
        return f"commit {sha} is not signed by GitHub ({verification.get('reason')})"
    author = (commit.get("author") or {}).get("login")
    committer = (commit.get("committer") or {}).get("login")
    if committer != "web-flow":
        return f"commit {sha} was not made on GitHub ({committer})"
    merge = len(commit.get("parents") or ()) == 2
    if author != BOT and not (merge and author == viewer):
        return f"commit {sha} is {author}'s"
    return None


def update_refusal(commits: list[dict[str, Any]]) -> str | None:
    """Why the versions are not all minor or patch, as each of Dependabot's commits states them."""
    for commit in commits:
        text = commit["commit"]["message"]
        levels = UPDATE_LINE.findall(text)
        if not levels or len(levels) != len(NAME_LINE.findall(text)):
            return f"commit {commit['sha'][:7]} does not say what every update is"
        if "major" in levels:
            return "it holds a major version"
    return None


def updated(commits: list[dict[str, Any]]) -> frozenset[str]:
    """The packages Dependabot's commits say they update."""
    return frozenset(n for c in commits for n in NAMED.findall(c["commit"]["message"]))


def push_refusal(pushes: list[dict[str, Any]], head: str, viewer: str) -> str | None:
    """Why the record of the pushes to a branch is not Dependabot's and the caller's, or None."""
    if len(pushes) >= 100:
        return "too many pushes to its branch to read whole"
    for push in pushes:
        actor = (push.get("actor") or {}).get("login")
        if actor not in (BOT, viewer):
            return f"{push.get('activity_type')} of its branch by {actor}"
    if head not in [push.get("after") for push in pushes]:
        return "its head is not on the record of pushes"
    return None


def refusal(
    pull: dict[str, Any],
    commits: list[dict[str, Any]],
    files: list[dict[str, Any]],
    pushes: list[dict[str, Any]],
    viewer: str,
    read: bool = False,
) -> str | None:
    """Why a pull request is not landed, or None: the first guard it fails. One that a person
    read whole is held to who wrote it, not to what it changes."""
    if pull["user"]["login"] != BOT or pull["user"]["type"] != "Bot":
        return f"opened by {pull['user']['login']}"
    if not at_home(pull):
        return "its branch is not in this repository"
    if len(commits) >= 100 or len(files) >= 100:
        return "too large to read whole"
    reasons = [push_refusal(pushes, pull["head"]["sha"], viewer)]
    reasons += [commit_refusal(c, viewer) for c in commits]
    if not read:
        names = updated(commits)
        reasons += [file_refusal(f, names) for f in files]
    if not commits or not files:
        reasons.append("it changes nothing")
    if not read:
        own = [c for c in commits if len(c.get("parents") or ()) == 1]
        reasons.append(update_refusal(own))
    return next((r for r in reasons if r), None)


class Lander(fast_forward.Lander):
    """The walk over the repositories."""

    def pulls(self, slug: str) -> list[dict[str, Any]]:
        """The open pull requests, whole, the oldest first."""
        listed = self.api.get(f"repos/{slug}/pulls?state=open&per_page=100&direction=asc")
        return [self.pull(slug, p["number"]) for p in listed]

    def judge(self, slug: str, pull: dict[str, Any], read: bool = False) -> str | None:
        """The guards of a pull request of Dependabot's; with read, who wrote it alone."""
        base = f"repos/{slug}/pulls/{pull['number']}"
        commits = self.api.get(f"{base}/commits?per_page=100")
        files = self.api.get(f"{base}/files?per_page=100")
        branch = quote(f"refs/heads/{pull['head']['ref']}", safe="")
        pushes = self.api.get(f"repos/{slug}/activity?ref={branch}&per_page=100")
        why = refusal(pull, commits, files, pushes, self.viewer, read)
        if why:
            return why
        for commit in commits:
            for parent in commit["parents"][1:]:
                main = pull["base"]["ref"]
                compared = self.api.get(f"repos/{slug}/compare/{main}...{parent['sha']}")
                if compared["ahead_by"]:
                    return f"commit {commit['sha'][:7]} merges what is not on {main}"
        return None

    def bot(self, slug: str, pull: dict[str, Any], read: str = "") -> bool:
        """Land an update of Dependabot's, or say why not; whether it landed.

        One whose diff a person read whole (read is its head) is only taken:
        its own pull request is landed by name, as any other.
        """
        label = self.label(slug, pull)
        whole = read == pull["head"]["sha"]
        why = open_refusal(pull, slug, self.identity) or self.judge(slug, pull, whole)
        if why:
            return self.left(label, why)
        taken = self.take(slug, pull)
        if taken is None or whole:
            return False
        names = updated(self.pages(f"repos/{slug}/pulls/{pull['number']}/commits"))
        for changed in self.pages(f"repos/{slug}/pulls/{taken['number']}/files"):
            why = file_refusal(changed, names)
            if why:
                return self.left(self.label(slug, taken), why)
        return self.own(slug, taken)

    def land(self, slug: str, number: int, kit: bool, read: str) -> bool:
        """Land the pull request that was named; whether it landed or was taken."""
        pull = self.pull(slug, number)
        what = kind(pull, self.viewer)
        if what == "own":
            return self.own(slug, pull, read)
        if what == "person":
            return self.person(slug, pull, read)
        if what == "bot" and not kit:
            return self.bot(slug, pull, read)
        who = "the kit's releases are made by hand" if kit else pull["user"]["login"]
        return self.left(self.label(slug, pull), f"opened by a bot: {who}")


def land(
    declared: Declared,
    only: list[str],
    merge: bool,
    lander: Lander | None = None,
    read: str = "",
) -> int:
    """Land what is named (OWNER/NAME#N), or walk Dependabot's pull requests of the declared
    repositories (or of those named); 0 unless something named did not land or was refused."""
    lander = lander or Lander(fast_forward.Api(), fast_forward.Git(), merge)
    known = {repo.slug: repo for repo in declared.repositories}
    for one in only:
        slug, mark, number = one.partition("#")
        if slug not in known or (mark and not number.isdecimal()):
            lander.say(f"unknown: {one}")
            return 2
    results = [by_name(declared, one, lander, read) for one in only if "#" in one]
    chosen = [r for r in declared.repositories if not only or r.slug in only]
    results += [walk(declared, repo, lander) for repo in chosen]
    return 0 if all(results) else 1


def by_name(declared: Declared, one: str, lander: Lander, read: str) -> bool:
    """Land one pull request, OWNER/NAME#N; whether that was not refused."""
    slug, _mark, number = one.partition("#")
    if any(repo.hold for repo in declared.repositories if repo.slug == slug):
        lander.say(f"skipped: {one}: on hold")
        return False
    try:
        done = lander.land(slug, int(number), slug == declared.kit, read)
    except REFUSED as exc:
        lander.say(f"stopped: {one}: {exc}")
        return False
    return done or not lander.merge


def walk(declared: Declared, repo: Repository, lander: Lander) -> bool:
    """Walk Dependabot's pull requests of one repository; whether GitHub refused nothing."""
    why = (
        "the kit's releases are made by hand"
        if repo.slug == declared.kit
        else "on hold"
        if repo.hold
        else f"it moves into {repo.folds_into}"
        if repo.folds_into
        else ""
    )
    if why:
        lander.say(f"skipped: {repo.slug}: {why}")
        return True
    try:
        for pull in lander.pulls(repo.slug):
            lander.bot(repo.slug, pull)
    except REFUSED as exc:
        lander.say(f"stopped: {repo.slug}: {exc}")
        return False
    return True
