#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT

"""Check that a commit that says it is the owner's is the owner's.

What it judges: of the commits a pull request adds, wherever its branch is,
and of those a push adds to the default branch, the ones that are the owner's
by author or by committer. A field is the owner's when GitHub gives the
owner's login for it, or when it holds the owner's address (identity.json,
beside this file). What it holds of each (rule id):

  identity-author     the author, where it is the owner, uses the owner's
                      address
  identity-committer  the committer's address is the owner's: the owner's work
                      is committed by the owner, and so is what the owner
                      commits of somebody else's, whose author is untouched
  identity-signature  GitHub reports its signature valid, made with one of
                      the owner's keys; one GitHub made for a commit of its
                      web pages or of a merge button is none

Nobody else's commit is judged: neither a contributor's, with whatever
author, committer, key or none, nor a bot's. That what reaches main is signed
by somebody is GitHub's to hold (a ruleset), not this check's.

A commit of a pull request the owner opened from this repository, with an
address GitHub knows no account of, is warned about and never failed: it may
be the owner's other machine. The owner's other addresses are private, so
none is listed, and no address but the public one is ever printed.

What is not looked at: history (only what the change adds), a ref that
identity.json exempts, and a push made before its "since" (a run started again
judges what was pushed then).

Usage: commit_identity.py, in a GitHub Actions job, in a checkout with the
whole history. It reads GITHUB_EVENT_NAME, GITHUB_EVENT_PATH,
GITHUB_REPOSITORY, GITHUB_TOKEN (contents: read), GITHUB_API_URL and
GITHUB_STEP_SUMMARY. It runs nothing of the pull request.

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
RULES_HINT = 'kleidos-dev/.github docs/quality.md, "The identity of a commit"'

COMMITTER, SIGNATURE, AUTHOR = "identity-committer", "identity-signature", "identity-author"
WARNING = "identity-unknown"
HINT = (
    "If the commit is the owner's: set user.email and user.signingkey to the owner's, run"
    " `git rebase --force-rebase --gpg-sign origin/main` (and, for an author, `git commit"
    " --amend --no-edit --reset-author`), then `git push --force-with-lease`; a commit"
    " GitHub made (a merge button, its web editor) is made again locally. If it is not: the"
    " commit says it is the owner's, so drop it from the branch, or set your own name and"
    " address on what you wrote. Nobody else's commit is held to this."
)
UNKNOWN = (
    "GitHub knows no account of the address of its {}; if it was made on another machine of"
    " the owner's, set user.email there and make it again"
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
    """Who the owner is, and where nothing is judged (identity.json)."""

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

    def owns(self, email: str, login: str | None) -> bool:
        """Whether a commit's author or committer is the owner, by the login GitHub gives or by
        the address it claims."""
        return login == self.login or email.casefold() == self.email.casefold()


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
    none is; and whether the owner opened it from a branch of this repository."""

    head: str = ""
    known: tuple[str, ...] = ()
    note: str = ""
    own: bool = False


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


def of_owner(one: Fact, identity: Identity) -> bool:
    """Whether a commit is the owner's to answer for: by its author, or by its committer."""
    return identity.owns(one.author_email, one.author_login) or identity.owns(
        one.committer_email, one.committer_login
    )


def judge(one: Fact, identity: Identity) -> list[Problem]:
    """What a commit of the owner's breaks, and nothing of anybody else's; its e-mails stay out
    of what is said."""
    if not of_owner(one, identity):
        return []
    out = []
    author = identity.owns(one.author_email, one.author_login)
    if author and one.author_email != identity.email:
        out.append((AUTHOR, f"the author is {identity.login} with another address"))
    if one.committer_email != identity.email:
        who = "GitHub" if one.by_github else named(one.committer_login)
        of = "the owner's commit" if author else "a commit the owner made"
        out.append((COMMITTER, f"{of} is not committed as {identity.email} (it is by {who})"))
    if not one.signed:
        out.append((SIGNATURE, "it is not signed"))
    elif one.by_github:
        out.append((SIGNATURE, "GitHub signed it, not the owner's key"))
    elif not one.valid:
        out.append((SIGNATURE, f"GitHub reports its signature {one.state.lower()}"))
    elif one.key_id not in identity.key_ids():
        out.append((SIGNATURE, "it is signed with another key than the owner's"))
    return [Problem(one.sha, rule, text) for rule, text in out]


def unknown(one: Fact) -> str | None:
    """Which of a commit's fields holds an address GitHub knows no account of, if one does."""
    if one.author_login is None:
        return "author"
    # GitHub's own address has no account either, and its signature says it is GitHub.
    return "committer" if one.committer_login is None and not one.by_github else None


# --- the event ---------------------------------------------------------------
def pull_scope(event: dict[str, Any], repository: str, identity: Identity) -> Scope:
    """What a pull request's event adds."""
    pull = event["pull_request"]
    ref = f"refs/heads/{pull['base']['ref']}"
    exempt = identity.exemption(repository, ref)
    if exempt:
        return Scope(note=f"{ref} is exempt: {exempt.reason}")
    home = (pull["head"].get("repo") or {}).get("full_name")
    own = home == repository and pull["user"]["login"] == identity.login
    # What the base has by now is judged by the push that brought it there.
    known = (pull["base"]["sha"], f"refs/remotes/origin/{ref[11:]}")
    return Scope(pull["head"]["sha"], known, own=own)


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
def report(total: int, owners: int, problems: list[Problem], warnings: list[Problem]) -> str:
    """The job summary: a table of what is refused and of what is warned about."""
    commits = len({p.sha for p in problems})
    said = f"{commits} of the owner's {owners} refused" if commits else f"the owner's {owners} pass"
    out = f"### Identity of the commits: {said}\n\n"
    out += f"{total} added; {total - owners} are somebody else's or a bot's, and are not judged.\n"
    if problems or warnings:
        rows = "\n".join(f"| `{p.sha[:7]}` | `{p.rule}` | {p.text} |" for p in problems + warnings)
        out += f"\n| Commit | Rule | What |\n| --- | --- | --- |\n{rows}\n"
        out += f"\n{HINT} The rules: {RULES_HINT}.\n"
    return out


def warned(found: list[Fact], problems: list[Problem]) -> list[Problem]:
    """What to say of the commits of the owner's own branch that are refused for nothing and hold
    an address GitHub knows no account of."""
    refused = {p.sha for p in problems}
    out = []
    for one in found:
        field_of = unknown(one)
        if field_of and one.sha not in refused:
            out.append(Problem(one.sha, WARNING, UNKNOWN.format(field_of)))
    return out


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
    added_facts = facts(github_ask(api), repository, shas)
    owners = [one for one in added_facts if of_owner(one, identity)]
    problems = [p for one in owners for p in judge(one, identity)]
    warnings = warned(added_facts, problems) if what.own else []
    for level, found in (("error", problems), ("warning", warnings)):
        for p in found:
            print(f"::{level} title=Identity of a commit::{p.sha[:12]}: {p.rule}: {p.text}")
    tell(report(len(shas), len(owners), problems, warnings))
    print(
        f"{len(shas)} commit(s) added, {len(owners)} of the owner's, {len(problems)} problem(s);"
        f" {RULES_HINT}"
    )
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
