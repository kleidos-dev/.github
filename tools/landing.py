#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Merge Dependabot's pull requests that pass every guard (ecosystem.py land).

It merges third-party code under the caller's own credential with nobody
reading the diff, so what it accepts is narrow (docs/ecosystem.md, "Landing
the bot's pull requests"):

  - opened by Dependabot, head in the same repository, not a draft;
  - every commit authored by Dependabot and signed by GitHub, but for the
    merges of main this script's own update made;
  - only manifests, lock files, `uses:` lines of workflows and `rev:` lines
    of the hook list changed;
  - no major version, as Dependabot's own commit says;
  - never the kit's repository, nor one on the hold list;
  - a fresh run against today's main, all of it green.

One at a time, and each is listed with what it merged.

Python 3.14 or newer, gh.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ecosystem import Declared

BOT = "dependabot[bot]"
MANIFESTS = re.compile(
    r"^(?:requirements[\w.-]*\.(?:txt|in)|[\w.-]+\.in|pyproject\.toml|uv\.lock|package(?:-lock)?\.json"
    r"|pnpm-lock\.yaml|pnpm-workspace\.yaml)$"
)
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*\S+@[0-9a-f]{40}\s*(?:#.*)?$")
REV = re.compile(r"^\s*rev:\s*\S+\s*(?:#.*)?$")
NAME_LINE = re.compile(r"^- dependency-name: ", re.MULTILINE)
UPDATE_LINE = re.compile(
    r"^\s+update-type: version-update:semver-(major|minor|patch)\s*$", re.MULTILINE
)
PASSED = ("success", "skipped", "neutral")
POLL_SECONDS = 20
WAIT_SECONDS = 3600


class ApiError(Exception):
    """A request GitHub refused."""


class Api:
    """GitHub's REST API through gh."""

    def get(self, path: str) -> Any:
        """One GET."""
        return self._run("GET", path, {})

    def put(self, path: str, fields: dict[str, str]) -> Any:
        """One PUT."""
        return self._run("PUT", path, fields)

    def _run(self, method: str, path: str, fields: dict[str, str]) -> Any:
        cmd = ["gh", "api", "--method", method, path]
        for name, value in fields.items():
            cmd += ["-f", f"{name}={value}"]
        done = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            raise ApiError(f"{method} {path}: {done.stderr.strip()[:200]}")
        return json.loads(done.stdout) if done.stdout.strip() else {}


def file_refusal(changed: dict[str, Any]) -> str | None:
    """Why a changed file is more than a version, or None."""
    path = PurePosixPath(changed["filename"])
    if changed.get("status") != "modified":
        return f"{path} is {changed.get('status')}"
    if MANIFESTS.match(path.name):
        return None
    if changed["filename"].startswith(".github/workflows/") and path.suffix in (".yml", ".yaml"):
        allowed = USES
    elif changed["filename"] == ".pre-commit-config.yaml":
        allowed = REV
    else:
        return f"{path} is neither a manifest, a workflow nor the hook list"
    patch = changed.get("patch")
    if not patch:
        return f"{path} shows no diff to read"
    used: dict[str, list[str]] = {"+": [], "-": []}
    for line in str(patch).splitlines():
        if line[:1] not in used:
            continue
        if not allowed.match(line[1:]):
            return f"{path} changes more than a version: {line[:80]}"
        used[line[0]].append(line[1:].partition("uses:")[2].partition("@")[0].strip())
    if allowed is USES and sorted(used["+"]) != sorted(used["-"]):
        return f"{path} calls another action than before"
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
    """Why the versions are not all minor or patch, as Dependabot's commits state them."""
    text = "\n".join(c["commit"]["message"] for c in commits)
    levels = UPDATE_LINE.findall(text)
    if not levels or len(levels) != len(NAME_LINE.findall(text)):
        return "Dependabot's commit does not say what every update is"
    return "it holds a major version" if "major" in levels else None


def refusal(
    pull: dict[str, Any], commits: list[dict[str, Any]], files: list[dict[str, Any]], viewer: str
) -> str | None:
    """Why a pull request is not landed, or None: the first guard it fails."""
    if pull["user"]["login"] != BOT or pull["user"]["type"] != "Bot":
        return f"opened by {pull['user']['login']}"
    if pull["draft"]:
        return "a draft"
    head = pull["head"]["repo"]
    if head is None or head["full_name"] != pull["base"]["repo"]["full_name"]:
        return "its branch is not in this repository"
    if pull["base"]["ref"] != pull["base"]["repo"]["default_branch"]:
        return f"against {pull['base']['ref']}, not the default branch"
    if len(commits) >= 100 or len(files) >= 100:
        return "too large to read whole"
    reasons = [commit_refusal(c, viewer) for c in commits] + [file_refusal(f) for f in files]
    if not commits or not files:
        reasons.append("it changes nothing")
    reasons.append(update_refusal([c for c in commits if len(c.get("parents") or ()) == 1]))
    return next((r for r in reasons if r), None)


def check_state(workflows: list[dict[str, Any]], checks: list[dict[str, Any]]) -> str:
    """ "pending", "green", or what failed, of everything that ran on a commit.

    The workflow runs are asked, not only the check runs: between two stages
    of a workflow every check run there is has finished.
    """
    own = [w for w in workflows if w["event"] == "pull_request"]
    if not own or any(r["status"] != "completed" for r in [*workflows, *checks]):
        return "pending"
    failed = sorted({r["name"] for r in [*workflows, *checks] if r["conclusion"] not in PASSED})
    if failed:
        return f"failing: {', '.join(failed[:3])}"
    return "green" if any(w["conclusion"] == "success" for w in own) else "nothing ran on it"


class Lander:
    """The walk over the repositories, with what it needs of the outside."""

    def __init__(
        self,
        api: Api,
        merge: bool,
        sleep: Callable[[float], object] = time.sleep,
        say: Callable[[str], object] = print,
    ) -> None:
        self.api, self.merge, self.sleep, self.say = api, merge, sleep, say
        self.viewer = str(api.get("user")["login"])

    def pulls(self, slug: str) -> list[dict[str, Any]]:
        """The open pull requests, whole, the oldest first."""
        listed = self.api.get(f"repos/{slug}/pulls?state=open&per_page=100&direction=asc")
        return [self.api.get(f"repos/{slug}/pulls/{p['number']}") for p in listed]

    def judge(self, slug: str, pull: dict[str, Any]) -> str | None:
        """The guards that need no fresh run."""
        base = f"repos/{slug}/pulls/{pull['number']}"
        commits = self.api.get(f"{base}/commits?per_page=100")
        files = self.api.get(f"{base}/files?per_page=100")
        return refusal(pull, commits, files, self.viewer)

    def fresh(self, slug: str, number: int) -> tuple[str, str]:
        """Update a branch to today's main and wait for its run: (head, its check state)."""
        before = self.api.get(f"repos/{slug}/pulls/{number}")
        main = self.api.get(f"repos/{slug}/commits/{before['base']['ref']}")["sha"]
        compared = self.api.get(f"repos/{slug}/compare/{main}...{before['head']['sha']}")
        head = before["head"]["sha"]
        waited = 0
        if compared["behind_by"]:
            self.api.put(f"repos/{slug}/pulls/{number}/update-branch", {"expected_head_sha": head})
            while head == before["head"]["sha"] and waited < WAIT_SECONDS:
                self.sleep(POLL_SECONDS)
                waited += POLL_SECONDS
                head = self.api.get(f"repos/{slug}/pulls/{number}")["head"]["sha"]
        state = "pending"
        while waited < WAIT_SECONDS:
            runs = self.api.get(f"repos/{slug}/actions/runs?head_sha={head}&per_page=100")
            checks = self.api.get(f"repos/{slug}/commits/{head}/check-runs?per_page=100")
            state = check_state(runs["workflow_runs"], checks["check_runs"])
            if state != "pending":
                break
            self.sleep(POLL_SECONDS)
            waited += POLL_SECONDS
        return head, state

    def land(self, slug: str, pull: dict[str, Any]) -> bool:
        """Land one pull request, or say why not; whether it was merged."""
        label = f"{slug}#{pull['number']} {pull['title'][:70]}"
        why = self.judge(slug, pull)
        if why:
            self.say(f"left: {label}: {why}")
            return False
        if not self.merge:
            self.say(f"would land: {label}")
            return False
        head, state = self.fresh(slug, pull["number"])
        if state != "green":
            self.say(f"left: {label}: {state}")
            return False
        now = self.api.get(f"repos/{slug}/pulls/{pull['number']}")
        why = self.judge(slug, now) if now["head"]["sha"] == head else "its branch moved meanwhile"
        if why:
            self.say(f"left: {label}: {why}")
            return False
        self.api.put(
            f"repos/{slug}/pulls/{pull['number']}/merge", {"merge_method": "squash", "sha": head}
        )
        self.say(f"landed: {label}: {pull['html_url']}")
        return True


def land(declared: Declared, only: list[str], merge: bool, lander: Lander | None = None) -> int:
    """Walk the declared repositories; 0 unless GitHub refused something."""
    lander = lander or Lander(Api(), merge)
    status = 0
    for repo in declared.repositories:
        if only and repo.slug not in only:
            continue
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
            continue
        try:
            for pull in lander.pulls(repo.slug):
                lander.land(repo.slug, pull)
        except ApiError as exc:
            lander.say(f"stopped: {repo.slug}: {exc}")
            status = 1
    return status
