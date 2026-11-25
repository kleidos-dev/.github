#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT

"""Check that every commit a change adds is the owner's: committer, key, author.

What it holds of each commit a pull request from the same repository adds,
and of each commit a push adds to the default branch (rule id):

  identity-committer  its committer's e-mail is the owner's, as identity.json
                      beside this file says
  identity-signature  GitHub reports its signature valid, made with one of
                      the owner's keys; one GitHub made for a commit of its
                      web pages or of a merge button is none
  identity-author     an author GitHub knows as the owner uses that e-mail;
                      another author is a person whose work was landed, and
                      keeps the authorship

GitHub is asked (GraphQL: the e-mails, the logins behind them, the key id of
the signature), so no key is needed here. No e-mail but the owner's public
one is ever printed: another address of the owner is private.

What is not judged: history (only what the change adds), a ref that
identity.json exempts, a push made before its "since" (a run started again
judges what was pushed then), and a pull request from a fork or opened by
Dependabot: the maintainer lands those as commits of the owner, and this says
so. Nothing is asked of GitHub, and no token is read, in that case.

Usage: commit_identity.py, in a GitHub Actions job, in a checkout with the
whole history. It reads GITHUB_EVENT_NAME, GITHUB_EVENT_PATH,
GITHUB_REPOSITORY, GITHUB_TOKEN (contents: read), GITHUB_API_URL and
GITHUB_STEP_SUMMARY.

Exit status: 0 nothing to refuse, 1 a commit is refused, 2 git, the event,
identity.json or GitHub could not be read.

Python 3.9 or newer, standard library only, as check_commit_msg.py beside it.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import check_commit_msg

IDENTITY = Path(__file__).resolve().parent / "identity.json"
SCHEMA = "kleidos.commit-identity/1"
BOT = "dependabot[bot]"
RULES_HINT = 'kleidos-dev/.github docs/quality.md, "The identity of a commit"'
LANDED = (
    "its commits keep their author, and the maintainer lands them rebased on main,"
    " committed and signed with the owner's key"
)

COMMITTER, SIGNATURE, AUTHOR = "identity-committer", "identity-signature", "identity-author"
HINT = (
    "To repair your own branch: set user.email and user.signingkey to the owner's, run"
    " `git rebase --force-rebase --gpg-sign origin/main` (and, for an author, `git commit"
    " --amend --no-edit --reset-author`), then `git push --force-with-lease`. A commit"
    " GitHub made (a merge button, its web editor) is made again locally."
)

BATCH = 50
TRIES, PAUSE_SECONDS = 3, 10.0
# States in which GitHub has not verified a signature yet, or could not.
UNDECIDED = frozenset({"GPGVERIFY_ERROR", "GPGVERIFY_UNAVAILABLE"})
FIELDS = (
    "oid parents{totalCount} author{email user{login}} committer{email user{login}}"
    " signature{isValid state wasSignedByGitHub ... on GpgSignature{keyId}}"
)
SHA = re.compile(r"[0-9a-f]{40}")
KEY = re.compile(r"[0-9A-F]{40}")
LOGIN = re.compile(r"[A-Za-z0-9-]{1,40}(?:\[bot\])?")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+")

# One GraphQL request: the query and its variables, to its "data".
Ask = Callable[[str, "dict[str, Any]"], Any]


class Unreadable(Exception):
    """What has to be read to judge could not be."""


@dataclass(frozen=True)
class Exempt:
    """A ref whose commits are not judged, and why."""

    repository: str
    ref: str
    reason: str


@dataclass(frozen=True)
class Identity:
    """Whose commits these are (identity.json)."""

    login: str
    email: str
    keys: tuple[str, ...]
    since: dt.datetime
    exempt: tuple[Exempt, ...]

    def exemption(self, repository: str, ref: str) -> Exempt | None:
        """The entry that exempts a ref, or None."""
        for entry in self.exempt:
            if (entry.repository, entry.ref) == (repository, ref):
                return entry
        return None

    def key_ids(self) -> frozenset[str]:
        """The owner's keys as GitHub names them: the last 16 digits of each fingerprint."""
        return frozenset(key[-16:] for key in self.keys)


@dataclass(frozen=True)
class Fact:
    """What GitHub says of one commit. Its e-mails never reach a repr."""

    sha: str
    parents: int
    author_email: str = field(repr=False)
    author_login: str | None
    committer_email: str = field(repr=False)
    committer_login: str | None
    signed: bool
    valid: bool
    state: str
    by_github: bool
    key_id: str | None


@dataclass(frozen=True)
class Problem:
    """What one commit breaks."""

    sha: str
    rule: str
    text: str


@dataclass(frozen=True)
class Scope:
    """What of an event is judged: the commits of `head` not in `known`, or, with no head, why
    none is."""

    head: str = ""
    known: tuple[str, ...] = ()
    note: str = ""


# --- identity.json -----------------------------------------------------------
def text_of(table: dict[str, Any], key: str, pattern: str = r".+") -> str:
    """A text of identity.json that its pattern fits."""
    value = table.get(key)
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise Unreadable(f"identity.json: {key} is not as it must be")
    return value


def when(text: str) -> dt.datetime:
    """A moment of identity.json, in UTC."""
    try:
        return dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError as exc:
        raise Unreadable("identity.json: since is not as it must be") from exc


def table_of(value: Any, name: str, keys: frozenset[str]) -> dict[str, Any]:
    """A table of identity.json that holds these keys and no other."""
    if not isinstance(value, dict) or set(value) != keys:
        raise Unreadable(f"identity.json: {name} does not hold {', '.join(sorted(keys))}")
    return value


def load(path: Path = IDENTITY) -> Identity:
    """identity.json, whole and sound."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Unreadable(f"identity.json: {exc}") from exc
    top = table_of(data, "it", frozenset({"schema", "owner", "since", "exempt"}))
    text_of(top, "schema", re.escape(SCHEMA))
    owner = table_of(top["owner"], "owner", frozenset({"login", "email", "keys"}))
    keys = owner["keys"]
    if not isinstance(keys, list) or not keys or not all(KEY.fullmatch(str(k)) for k in keys):
        raise Unreadable("identity.json: keys are not fingerprints in capitals")
    if not isinstance(top["exempt"], list):
        raise Unreadable("identity.json: exempt is not a list")
    exempt = []
    for entry in top["exempt"]:
        one = table_of(entry, "an exemption", frozenset({"repository", "ref", "reason"}))
        exempt.append(
            Exempt(
                text_of(one, "repository", r"[\w.-]+/[\w.-]+"),
                text_of(one, "ref", r"refs/heads/\S+"),
                text_of(one, "reason", r".+ .+"),
            )
        )
    return Identity(
        text_of(owner, "login", LOGIN.pattern),
        text_of(owner, "email", EMAIL.pattern),
        tuple(keys),
        when(text_of(top, "since")),
        tuple(exempt),
    )


# --- what GitHub says --------------------------------------------------------
def person(node: dict[str, Any], role: str) -> tuple[str, str | None]:
    """The e-mail and the login of a commit's author or committer."""
    found = node.get(role) or {}
    return str(found.get("email") or ""), (found.get("user") or {}).get("login")


def fact(node: dict[str, Any]) -> Fact:
    """One commit as GraphQL gave it."""
    signature = node.get("signature")
    made = signature or {}
    author_email, author_login = person(node, "author")
    committer_email, committer_login = person(node, "committer")
    return Fact(
        str(node["oid"]),
        int(node["parents"]["totalCount"]),
        author_email,
        author_login,
        committer_email,
        committer_login,
        signed=signature is not None,
        valid=made.get("isValid") is True and made.get("state") == "VALID",
        state=str(made.get("state") or "UNSIGNED"),
        by_github=signature is not None and made.get("wasSignedByGitHub") is not False,
        key_id=made.get("keyId"),
    )


def batch(ask: Ask, slug: str, shas: list[str]) -> list[Fact]:
    """What GitHub says of up to BATCH commits, in their order."""
    owner, _slash, name = slug.partition("/")
    wanted = " ".join(
        f'c{n}:object(oid:"{sha}"){{... on Commit{{{FIELDS}}}}}' for n, sha in enumerate(shas)
    )
    query = (
        f"query($owner:String!,$name:String!){{repository(owner:$owner,name:$name){{{wanted}}}}}"
    )
    found = (ask(query, {"owner": owner, "name": name}) or {}).get("repository") or {}
    out = []
    for n, sha in enumerate(shas):
        node = found.get(f"c{n}")
        if not node or node.get("oid") != sha:
            raise Unreadable(f"GitHub knows no commit {sha[:12]} of {slug}")
        out.append(fact(node))
    return out


def facts(
    ask: Ask, slug: str, shas: list[str], sleep: Callable[[float], object] = time.sleep
) -> list[Fact]:
    """What GitHub says of each commit, asked again while a signature is undecided."""
    for sha in shas:
        if not SHA.fullmatch(sha):
            raise Unreadable(f"{sha[:12]!r} is no commit")
    out: list[Fact] = []
    for start in range(0, len(shas), BATCH):
        part = shas[start : start + BATCH]
        found = batch(ask, slug, part)
        for _again in range(TRIES - 1):
            if not any(one.state in UNDECIDED for one in found):
                break
            sleep(PAUSE_SECONDS)
            found = batch(ask, slug, part)
        if any(one.state in UNDECIDED for one in found):
            raise Unreadable("GitHub could not verify a signature; run the job again")
        out += found
    return out


# --- the rules ---------------------------------------------------------------
def named(login: str | None) -> str:
    """A login for a log, or what stands for none."""
    return login if login and LOGIN.fullmatch(login) else "an address GitHub knows no account of"


def judge(one: Fact, identity: Identity) -> list[Problem]:
    """What a commit breaks; its e-mails stay out of what is said."""
    out = []
    if one.committer_email != identity.email:
        who = "GitHub" if one.by_github else named(one.committer_login)
        out.append((COMMITTER, f"the committer is not {identity.email} (it is {who})"))
    if not one.signed:
        out.append((SIGNATURE, "it is not signed"))
    elif one.by_github:
        out.append((SIGNATURE, "GitHub signed it, not the owner's key"))
    elif not one.valid:
        out.append((SIGNATURE, f"GitHub reports its signature {one.state.lower()}"))
    elif one.key_id not in identity.key_ids():
        out.append((SIGNATURE, "it is signed with another key than the owner's"))
    if one.author_login == identity.login and one.author_email != identity.email:
        out.append((AUTHOR, f"the author is {identity.login} with another address"))
    return [Problem(one.sha, rule, text) for rule, text in out]


# --- the event ---------------------------------------------------------------
def pull_scope(event: dict[str, Any], repository: str, identity: Identity) -> Scope:
    """What a pull request's event adds."""
    pull = event["pull_request"]
    home = (pull["head"].get("repo") or {}).get("full_name")
    if home != repository:
        return Scope(note=f"a pull request from a fork: {LANDED}")
    if pull["user"]["login"] == BOT and pull["user"].get("type") == "Bot":
        return Scope(note=f"a pull request of Dependabot's: {LANDED}")
    ref = f"refs/heads/{pull['base']['ref']}"
    exempt = identity.exemption(repository, ref)
    if exempt:
        return Scope(note=f"{ref} is exempt: {exempt.reason}")
    # What the base has by now is judged by the push that brought it there.
    return Scope(pull["head"]["sha"], (pull["base"]["sha"], f"refs/remotes/origin/{ref[11:]}"))


def push_scope(event: dict[str, Any], repository: str, identity: Identity) -> Scope:
    """What a push's event adds to the default branch."""
    ref = event["ref"]
    if ref != f"refs/heads/{event['repository']['default_branch']}":
        return Scope(note=f"{ref} is not the default branch")
    exempt = identity.exemption(repository, ref)
    if exempt:
        return Scope(note=f"{ref} is exempt: {exempt.reason}")
    if event.get("deleted"):
        return Scope(note=f"{ref} was deleted")
    # GitHub's own record of when the push came: a committer date is the committer's to write.
    pushed = event["repository"].get("pushed_at")
    if isinstance(pushed, int) and pushed < identity.since.timestamp():
        return Scope(note="the push is older than the rule")
    return Scope(event["after"], (event["before"],))


def scope(name: str, event: dict[str, Any], repository: str, identity: Identity) -> Scope:
    """What of an event is judged."""
    try:
        if name == "pull_request":
            return pull_scope(event, repository, identity)
        if name == "push":
            return push_scope(event, repository, identity)
    except (KeyError, TypeError, AttributeError) as exc:
        raise Unreadable(f"the {name} event is not as GitHub sends it: {exc!r}") from exc
    return Scope(note=f"a {name} run adds no commit")


def added(what: Scope, cwd: str | None = None) -> list[str]:
    """The commits of a scope, the oldest first.

    A commit that is not in the clone excludes nothing: a main written anew
    is judged whole, and so is a new one, whose push names no commit before.
    """
    for name in (what.head, what.known[0]):
        if not SHA.fullmatch(str(name)):
            raise Unreadable("the event names no commit")
    known = []
    for name in what.known:
        try:
            check_commit_msg.git(["rev-parse", "-q", "--verify", f"{name}^{{commit}}"], cwd)
        except RuntimeError:
            continue
        known.append(f"^{name}")
    try:
        listed = check_commit_msg.git(["rev-list", "--reverse", what.head, *known, "--"], cwd)
    except RuntimeError as exc:
        raise Unreadable(f"git: {exc}") from exc
    return listed.split()


# --- what is said ------------------------------------------------------------
def report(checked: int, problems: list[Problem]) -> str:
    """The table of the job summary."""
    if not problems:
        return f"### Identity of the commits: all {checked} pass\n"
    commits = len({p.sha for p in problems})
    rows = "\n".join(f"| `{p.sha[:7]}` | `{p.rule}` | {p.text} |" for p in problems)
    return (
        f"### Identity of the commits: {commits} of {checked} refused\n\n"
        f"| Commit | Rule | What |\n| --- | --- | --- |\n{rows}\n\n"
        f"{HINT} The rules: {RULES_HINT}.\n"
    )


def tell(text: str) -> None:
    """Into the job summary, where there is one."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)


def github_ask(api: check_commit_msg.Api) -> Ask:
    """GraphQL through the REST client of check_commit_msg.py."""

    def ask(query: str, variables: dict[str, Any]) -> Any:
        try:
            got = api.request("POST", "/graphql", {"query": query, "variables": variables}) or {}
        except (OSError, ValueError) as exc:
            raise Unreadable(f"GitHub: {exc}") from exc
        if got.get("errors"):
            raise Unreadable(f"GitHub: {str(got['errors'][0].get('message'))[:200]}")
        return got.get("data")

    return ask


def run(cwd: str | None = None) -> int:
    """Judge the event of the job."""
    identity = load()
    name = os.environ.get("GITHUB_EVENT_NAME", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    except (KeyError, OSError, ValueError) as exc:
        raise Unreadable(f"the event: {exc!r}") from exc
    what = scope(name, event, repository, identity)
    if what.note:
        print(f"::notice title=Identity of the commits::not judged: {what.note}")
        tell(f"### Identity of the commits\n\nNot judged: {what.note}.\n")
        return 0
    shas = added(what, cwd)
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise Unreadable("GITHUB_TOKEN is empty")
    url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    api = check_commit_msg.GitHub(token, url)
    problems = [p for one in facts(github_ask(api), repository, shas) for p in judge(one, identity)]
    for p in problems:
        print(f"::error title=Identity of a commit::{p.sha[:12]}: {p.rule}: {p.text}")
    tell(report(len(shas), problems))
    print(f"{len(shas)} commit(s) judged, {len(problems)} problem(s); {RULES_HINT}")
    return 1 if problems else 0


def main() -> int:
    """Judge, or say what could not be read."""
    try:
        return run()
    except (Unreadable, ValueError) as exc:
        print(f"::error title=Identity of the commits::{exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
