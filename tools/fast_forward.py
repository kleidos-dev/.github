#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Land a pull request by a signed fast forward of main (ecosystem.py land).

A commit a merge button makes is GitHub's, with GitHub's signature, so a pull
request lands by pushing its head to main as it is (docs/quality.md,
"Merging"): the head is on top of main, every commit is signed and GitHub
verified it, each commit that is the owner's is the owner's (docs/quality.md,
"The identity of a commit"), every check on that very commit is green, main
has not moved, and GitHub then marks the pull request merged.

What is judged is what is pushed: the commits are asked for by their SHAs, not
as what the pull request holds at that instant, the files by git, in the clone
they are pushed from, and the checks of that commit once more right there.

  own     a branch of the repository, opened by the owner: judged, waited
          for, pushed to main and confirmed
  person  a pull request of somebody else (a fork's, or a branch here). On
          top of main and signed, it lands the same way, as it is: author,
          committer and signature are theirs. Otherwise its commits are
          rebased on today's main by the owner, who then is their committer
          and signs them, with their authors kept, on a branch land/pr-<n>
          with a pull request of its own, which lands as the owner's
  bot     Dependabot's: one signed commit of the owner's on land/pr-<n>

Nothing of the pull request runs here: git copies commits, and the checks run
on GitHub. No push is forced and no ref is deleted.

Python 3.14 or newer, gh, git.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import textwrap
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
import check_commit_msg
import commit_identity

if TYPE_CHECKING:
    from commit_identity import Fact, Identity

BOT = "dependabot[bot]"
GATE, ACTIONS_APP = "✅ Check", 15368  # the job every repository requires; GitHub Actions
PASSED = ("success", "skipped", "neutral")
POLL_SECONDS = 20
WAIT_SECONDS = 3600
CONFIRM_TRIES = 15
PAGE = 100
MAX_PAGES = 30  # GitHub lists no more than 3,000 files of a pull request
BRANCH = re.compile(r"land/pr-(\d+)")
# What a green gate proves nothing about, since the pull request brings its own.
OWN_GATE = (".github", ".pre-commit-config.yaml")


class ApiError(Exception):
    """A request GitHub refused."""


class GitError(Exception):
    """A git command that failed."""


# What stops a landing, and not the walk it is part of.
REFUSED = (ApiError, GitError, commit_identity.Unreadable)


class Api:
    """GitHub's API through gh."""

    def get(self, path: str) -> Any:
        """One GET."""
        return self._run(["--method", "GET", path])

    def post(self, path: str, fields: dict[str, str]) -> Any:
        """One POST."""
        return self._run(["--method", "POST", path, *self._fields(fields)])

    def ask(self, query: str, variables: dict[str, Any]) -> Any:
        """One GraphQL query, to its data."""
        return self._run(["graphql", *self._fields({"query": query, **variables})])["data"]

    @staticmethod
    def _fields(fields: dict[str, str]) -> list[str]:
        return [arg for name, value in fields.items() for arg in ("-f", f"{name}={value}")]

    @staticmethod
    def _run(args: list[str]) -> Any:
        done = subprocess.run(["gh", "api", *args], capture_output=True, text=True, check=False)
        if done.returncode != 0:
            raise ApiError(f"{' '.join(args[:3])}: {done.stderr.strip()[:200]}")
        return json.loads(done.stdout) if done.stdout.strip() else {}


class Git:
    """The git of a landing, in a clone of its own that holds no work tree of anybody's."""

    def clone(self, slug: str, folder: Path) -> None:
        """A fresh clone, of every branch and the commits whole."""
        self._run(["gh", "repo", "clone", slug, str(folder), "--", "-q", "--filter=blob:none"])

    def run(self, folder: Path, *args: str) -> str:
        """One git command in the clone."""
        return self._run(["git", "-C", str(folder), *args])

    @staticmethod
    def _run(cmd: list[str]) -> str:
        done = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            raise GitError(f"{' '.join(cmd[:5])}: {done.stderr.strip()[-300:]}")
        return done.stdout.strip()


# --- what a pull request is --------------------------------------------------
def kind(pull: dict[str, Any], owner: str) -> str:
    """ "bot" (Dependabot), "own" (the owner's, in this repository), "person", or ""."""
    user = pull["user"]
    if user["type"] == "Bot":
        return "bot" if user["login"] == BOT else ""
    return "own" if user["login"] == owner and at_home(pull) else "person"


def at_home(pull: dict[str, Any]) -> bool:
    """Whether its branch is in the repository it is for."""
    head = pull["head"]["repo"]
    return head is not None and head["full_name"] == pull["base"]["repo"]["full_name"]


def open_refusal(pull: dict[str, Any], slug: str, identity: Identity) -> str | None:
    """Why a pull request cannot land as it stands, whoever opened it, or None."""
    base = pull["base"]
    if pull["state"] != "open":
        return "it is not open"
    if pull["draft"]:
        return "a draft"
    if base["ref"] != base["repo"]["default_branch"]:
        return f"against {base['ref']}, not the default branch"
    if identity.exemption(slug, f"refs/heads/{base['ref']}"):
        return f"{base['ref']} is exempt from the identity of its commits (hooks/identity.json)"
    return None


def listed_names(files: list[dict[str, Any]]) -> list[str]:
    """The paths of files GitHub lists that a green gate proves nothing about."""
    names = {str(f.get(key) or "") for f in files for key in ("filename", "previous_filename")}
    return sorted(name for name in names if name.split("/")[0] in OWN_GATE)


def read_refusal(found: list[str], head: str, read: str) -> str | None:
    """Why the part a green gate proves nothing about still has to be read, or None."""
    if found and read != head:
        return (
            f"{found[0]}: a green {GATE} proves nothing about it; read that part of the diff"
            f" line by line, then land it with --read {head}"
        )
    return None


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
    gates = [
        c for c in checks if c["name"] == GATE and (c.get("app") or {}).get("id") == ACTIONS_APP
    ]
    if not gates or any(c["conclusion"] != "success" for c in gates):
        return f"no {GATE} of GitHub Actions succeeded on it"
    return "green"


def update_message(pull: dict[str, Any]) -> str:
    """The message of the owner's commit that takes an update of Dependabot's."""
    number, title = pull["number"], str(pull["title"])
    subject = title
    if any(p["severity"] == check_commit_msg.ERROR for p in check_commit_msg.check_message(title)):
        subject = f"Take Dependabot's update of #{number}"
    body = textwrap.fill(f"Pull request #{number} of Dependabot: {title}", 72)
    return f"{subject}\n\n{body}\n"


class Lander:
    """The landing of one pull request, with what it needs of the outside."""

    def __init__(
        self,
        api: Api,
        git: Git,
        merge: bool,
        sleep: Callable[[float], object] = time.sleep,
        say: Callable[[str], object] = print,
    ) -> None:
        self.api, self.git, self.merge = api, git, merge
        self.sleep, self.say = sleep, say
        self.identity = commit_identity.load()
        self.viewer = str(api.get("user")["login"])

    # what is read
    def pull(self, slug: str, number: int) -> dict[str, Any]:
        """One pull request, whole."""
        found: dict[str, Any] = self.api.get(f"repos/{slug}/pulls/{number}")
        return found

    def pages(self, path: str, key: str = "") -> list[dict[str, Any]]:
        """Every entry of a list GitHub gives by pages, or of the one its answers hold at key."""
        out: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            got = self.api.get(f"{path}?per_page={PAGE}&page={page}")
            got = got[key] if key else got
            out += got
            if len(got) < PAGE:
                return out
        raise ApiError(f"{path}: too large to read whole")

    def main(self, slug: str, pull: dict[str, Any]) -> str:
        """Today's head of the branch it is against."""
        return str(self.api.get(f"repos/{slug}/commits/{pull['base']['ref']}")["sha"])

    def state(self, slug: str, head: str) -> str:
        """check_state of a commit, its commit statuses among it."""
        runs = self.api.get(f"repos/{slug}/actions/runs?head_sha={head}&per_page={PAGE}")
        checks = self.api.get(f"repos/{slug}/commits/{head}/check-runs?per_page={PAGE}")
        status = self.api.get(f"repos/{slug}/commits/{head}/status?per_page={PAGE}")
        if max(runs["total_count"], checks["total_count"]) > PAGE:
            return "failing: more ran on it than is read"
        state = check_state(runs["workflow_runs"], checks["check_runs"])
        if state == "green" and status["total_count"] and status["state"] != "success":
            return "pending" if status["state"] == "pending" else "failing: a commit status"
        return state

    def wait(self, slug: str, head: str) -> str:
        """The state of a commit once nothing on it runs any more."""
        waited = 0
        state = self.state(slug, head)
        while state == "pending" and waited < WAIT_SECONDS:
            self.sleep(POLL_SECONDS)
            waited += POLL_SECONDS
            state = self.state(slug, head)
        return state

    # what lands as it is
    def own_refusal(self, slug: str, pull: dict[str, Any], read: str) -> str | None:
        """Why the owner's pull request does not land, its checks apart, or None."""
        if kind(pull, self.identity.login) != "own":
            return f"opened by {pull['user']['login']}"
        why = self.refusal(slug, pull, read)
        if why:
            return why
        why = self.remake_reason(slug, pull)
        return (
            f"{why}: rebase it here, signed, and push it with --force-with-lease" if why else None
        )

    def person_refusal(self, slug: str, pull: dict[str, Any], read: str) -> str | None:
        """Why a person's pull request neither lands nor is taken, its checks apart, or None."""
        why = self.refusal(slug, pull, read)
        if why:
            return why
        for commit, one in self.commits(slug, pull):
            for problem in check_commit_msg.check_message(commit["commit"]["message"]):
                if problem["severity"] == check_commit_msg.ERROR:
                    return f"commit {one.sha[:7]}: {problem['message']}"
        return None

    def refusal(self, slug: str, pull: dict[str, Any], read: str) -> str | None:
        """Why a pull request does not land, whoever opened it and however it would, or None: how
        it stands, a commit that is a merge or says it is the owner's and is not, a part nobody
        read."""
        why = open_refusal(pull, slug, self.identity)
        if why:
            return why
        head, listed = pull["head"]["sha"], self.commits(slug, pull)
        ahead = self.compared(slug, pull)["ahead_by"]
        if not listed or len(listed) != ahead or listed[-1][1].sha != head:
            return "its commits are not the ones that would land"
        for _commit, one in listed:
            if one.parents != 1:
                return f"commit {one.sha[:7]} is a merge"
            for problem in commit_identity.judge(one, self.identity):
                return f"commit {one.sha[:7]}: {problem.text}"
            if one.state in commit_identity.UNDECIDED:
                return (
                    f"commit {one.sha[:7]}: GitHub has not decided on its signature"
                    f" ({one.state.lower()}); land it again later"
                )
        files = self.pages(f"repos/{slug}/pulls/{pull['number']}/files")
        return read_refusal(listed_names(files), head, read)

    def remake_reason(self, slug: str, pull: dict[str, Any]) -> str | None:
        """Why the commits of a pull request have to be made again to land, or None: they land as
        they are."""
        for _commit, one in self.commits(slug, pull):
            if not one.valid:
                return f"commit {one.sha[:7]}: GitHub does not report it signed and verified"
        if self.compared(slug, pull)["behind_by"]:
            return f"it is not on top of {pull['base']['ref']}"
        return None

    def commits(self, slug: str, pull: dict[str, Any]) -> list[tuple[dict[str, Any], Fact]]:
        """The commits that would land, each with what GitHub says of whose it is."""
        listed = self.pages(self.comparison(slug, pull), "commits")
        shas = [commit["sha"] for commit in listed]
        facts = commit_identity.facts(self.api.ask, slug, shas, self.identity, self.sleep)
        return list(zip(listed, facts, strict=True))

    def comparison(self, slug: str, pull: dict[str, Any]) -> str:
        """Where GitHub compares a pull request's head with today's main, by the SHAs of both: the
        pull request's own lists are those of whatever its head is at that instant."""
        return f"repos/{slug}/compare/{self.main(slug, pull)}...{pull['head']['sha']}"

    def compared(self, slug: str, pull: dict[str, Any]) -> dict[str, Any]:
        """How far a pull request's head is from today's main, with the first commits and files
        of what it adds."""
        path = self.comparison(slug, pull)
        found: dict[str, Any] = self.api.get(f"{path}?per_page={PAGE}&page=1")
        return found

    def own(self, slug: str, pull: dict[str, Any], read: str = "") -> bool:
        """Land the owner's pull request, or say why not; whether it landed."""
        return self.forward(slug, pull, read, lambda now: self.own_refusal(slug, now, read))

    def person(self, slug: str, pull: dict[str, Any], read: str = "") -> bool:
        """Land a person's pull request as it is, or take it, or say why not; whether it did."""
        label = self.label(slug, pull)
        why = self.person_refusal(slug, pull, read)
        if why:
            return self.left(label, why)
        # Nothing of a person's is waited for: what is not green yet is landed later.
        state = self.state(slug, pull["head"]["sha"])
        if state != "green":
            return self.left(label, state)
        why = self.remake_reason(slug, pull)
        if why:
            self.say(f"to be rebased: {label}: {why}")
            return self.take(slug, pull, read) is not None
        return self.forward(
            slug,
            pull,
            read,
            lambda now: self.person_refusal(slug, now, read) or self.remake_reason(slug, now),
        )

    def forward(
        self,
        slug: str,
        pull: dict[str, Any],
        read: str,
        refusal: Callable[[dict[str, Any]], str | None],
    ) -> bool:
        """Push a pull request's head to main once it is green, or say why not; whether it
        landed."""
        head, label = pull["head"]["sha"], self.label(slug, pull)
        why = None
        if self.viewer != self.identity.login:
            why = f"{self.viewer} is not {self.identity.login}, who lands"
        why = why or refusal(pull)
        if why:
            return self.left(label, why)
        if not self.merge:
            self.say(f"would land: {label}: {self.state(slug, head)}")
            return False
        state = self.wait(slug, head)
        if state != "green":
            return self.left(label, state)
        now = self.pull(slug, pull["number"])
        why = "its branch moved meanwhile" if now["head"]["sha"] != head else refusal(now)
        why = why or self.push(slug, pull, read)
        if why:
            return self.left(label, why)
        self.confirm(slug, pull)
        self.say(f"landed: {label}: {pull['html_url']}")
        taken = BRANCH.fullmatch(pull["head"]["ref"])
        if taken and kind(pull, self.identity.login) == "own":
            self.say(
                f"now #{taken[1]} of {slug} can be closed: it landed as {head[:7]}"
                " (Dependabot closes its own)"
            )
        return True

    def push(self, slug: str, pull: dict[str, Any], read: str) -> str | None:
        """Move main to a pull request's head, as a plain push, which the server refuses unless
        it is a fast forward; or why not: the last look is at the clone, and at the checks."""
        head = pull["head"]["sha"]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "clone"
            self.git.clone(slug, folder)
            self.fetch(folder, pull)
            why = self.unread(folder, pull, head, read)
            if why:
                return why
            state = self.state(slug, head)
            if state != "green":
                return state
            main = f"refs/heads/{pull['base']['ref']}"
            self.git.run(folder, "push", "-q", "origin", f"{head}:{main}")
        return None

    def unread(self, folder: Path, pull: dict[str, Any], rev: str, read: str) -> str | None:
        """read_refusal of what a clone is about to push, as its own git tells it."""
        changed = self.git.run(
            folder,
            *("-c", "core.quotePath=true", "diff", "--name-only"),
            *(f"origin/{pull['base']['ref']}...{rev}", "--", *OWN_GATE),
        )
        return read_refusal(changed.splitlines(), pull["head"]["sha"], read)

    def fetch(self, folder: Path, pull: dict[str, Any]) -> None:
        """Bring the head of a pull request, a fork's too, into a clone."""
        self.git.run(folder, "fetch", "-q", "origin", f"refs/pull/{pull['number']}/head")
        if self.git.run(folder, "rev-parse", "FETCH_HEAD") != pull["head"]["sha"]:
            raise GitError(f"#{pull['number']} moved meanwhile")

    def confirm(self, slug: str, pull: dict[str, Any]) -> None:
        """Wait until GitHub says the pull request is merged."""
        for _try in range(CONFIRM_TRIES):
            if self.pull(slug, pull["number"])["merged"]:
                return
            self.sleep(POLL_SECONDS)
        raise ApiError(f"{self.label(slug, pull)}: pushed, and GitHub does not say it is merged")

    # what is made again
    def take(self, slug: str, pull: dict[str, Any], read: str = "") -> dict[str, Any] | None:
        """Put a pull request's commits on today's main as the owner's, with a pull request of
        their own; None in a dry run, or where a part nobody read would run with the
        repository's own token."""
        label, number = self.label(slug, pull), pull["number"]
        if not self.merge:
            self.say(f"would take: {label}")
            return None
        branch, login = f"land/pr-{number}", pull["user"]["login"]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "clone"
            self.git.clone(slug, folder)
            self.copy(folder, pull, branch)
            why = self.unread(folder, pull, "HEAD", read)
            if why:
                self.left(label, why)
                return None
            self.git.run(folder, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
        bot = login == BOT
        title = update_message(pull).splitlines()[0] if bot else pull["title"]
        who = "Dependabot" if bot else f"`{login}`, whose commits keep their authorship"
        opened: dict[str, Any] = self.api.post(
            f"repos/{slug}/pulls",
            {
                "title": title,
                "head": branch,
                "base": pull["base"]["ref"],
                "body": f"Lands #{number}, opened by {who}, on today's"
                f" `{pull['base']['ref']}`, committed and signed by the owner"
                ' (kleidos-dev/.github, docs/quality.md, "Merging").',
            },
        )
        self.say(f"taken: {label}: {opened['html_url']}")
        return self.pull(slug, opened["number"])

    def copy(self, folder: Path, pull: dict[str, Any], branch: str) -> None:
        """The commits of a pull request on main, in a clone, on a branch that did not exist."""
        git, head = self.git, pull["head"]["sha"]
        for who in ("AUTHOR", "COMMITTER"):
            # The committer of what is made here, and the author of what a bot's becomes.
            if f" <{self.identity.email}> " not in git.run(folder, "var", f"GIT_{who}_IDENT"):
                raise GitError(f"git's {who.lower()} here is not {self.identity.email}")
        if git.run(folder, "ls-remote", "--heads", "origin", f"refs/heads/{branch}"):
            raise GitError(f"{branch} exists: land its pull request, or delete it first")
        main = f"origin/{pull['base']['ref']}"
        self.fetch(folder, pull)
        git.run(folder, "checkout", "-q", "-b", branch, main)
        sign = f"--gpg-sign={self.identity.keys[0]}"
        if pull["user"]["login"] == BOT:
            git.run(folder, "merge", "-q", "--squash", head)
            git.run(folder, "commit", "-q", sign, "-m", update_message(pull))
        else:
            git.run(folder, "cherry-pick", sign, f"{main}..{head}")

    # what is said
    @staticmethod
    def label(slug: str, pull: dict[str, Any]) -> str:
        """How a pull request is named in what is said."""
        return f"{slug}#{pull['number']} {pull['title'][:70]}"

    def left(self, label: str, why: str) -> bool:
        """Say why a pull request stays."""
        self.say(f"left: {label}: {why}")
        return False
