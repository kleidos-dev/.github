# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""commit_identity.py: the owner's commits are the owner's, nobody else's is judged, and no address
is ever said."""

from __future__ import annotations

import contextlib
import copy
import datetime as dt
import io
import json
import os
import re
import tempfile
import unittest
import urllib.error
from pathlib import Path
from typing import Any
from unittest import mock

import kit_fixtures as fx
from kit_fixtures import check_commit_msg as ccm
from kit_fixtures import commit_identity as ci

REPO = "kleidos-dev/boards"
EMAIL = "jmrplens@kleidos.dev"
OTHER = "somebody-private@example.invalid"
FINGERPRINT = "0A993B268654DBBA52B7E8D3FCF653391E2C91FC"
KEY_ID = "FCF653391E2C91FC"
A, B = "a" * 40, "b" * 40
ZERO = "0" * 40
THEIR_KEY = "E" * 16
SOUND: dict[str, Any] = json.loads(ci.IDENTITY.read_text(encoding="utf-8"))
IDENTITY = ci.load()


def node(sha: str = A, **more: Any) -> dict[str, Any]:
    """A commit as GraphQL gives it: the owner's, unless told."""
    return {
        "oid": sha,
        "parents": {"totalCount": 1},
        "author": {"email": EMAIL, "user": {"login": "jmrplens"}},
        "committer": {"email": EMAIL, "user": {"login": "jmrplens"}},
        "signature": {
            "isValid": True,
            "state": "VALID",
            "wasSignedByGitHub": False,
            "keyId": KEY_ID,
        },
        **more,
    }


def signature(**more: Any) -> dict[str, Any]:
    return {"signature": {**node()["signature"], **more}}


def who(email: str, login: str | None) -> dict[str, Any]:
    return {"email": email, "user": {"login": login} if login else None}


class FakeGitHub:
    """GraphQL over a table of nodes, as the query asks for them."""

    def __init__(self, *nodes: dict[str, Any]) -> None:
        self.nodes = {n["oid"]: n for n in nodes}
        self.asked: list[tuple[str, dict[str, Any]]] = []
        self.then: list[dict[str, Any]] = []

    def __call__(self, query: str, variables: dict[str, Any]) -> Any:
        self.asked.append((query, variables))
        oids = [part.split('"')[0] for part in query.split('object(oid:"')[1:]]
        found = {f"c{n}": self.nodes.get(oid) for n, oid in enumerate(oids)}
        for one in self.then[:1]:
            self.then.pop(0)
            self.nodes[one["oid"]] = one
        return {"repository": found}


class IdentityFileTest(unittest.TestCase):
    def load(self, data: Any) -> ci.Identity:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "identity.json"
            text = data if isinstance(data, str) else json.dumps(data)
            path.write_text(text, encoding="utf-8")
            return ci.load(path)

    def test_the_organizations(self) -> None:
        self.assertEqual((IDENTITY.login, IDENTITY.email), ("jmrplens", EMAIL))
        self.assertEqual((IDENTITY.keys, IDENTITY.key_ids()), ((FINGERPRINT,), frozenset({KEY_ID})))
        self.assertEqual(
            [(e.repository, e.ref) for e in IDENTITY.exempt],
            [
                ("kleidos-dev/cla", "refs/heads/signatures"),
                ("kleidos-dev/meter", "refs/heads/main"),
            ],
        )
        self.assertEqual(IDENTITY.since.tzinfo, dt.UTC)

    def test_another_owner_takes_its_place(self) -> None:
        data = copy.deepcopy(SOUND)
        data["owner"] = {"login": "o", "email": "o@x.invalid", "keys": ["B" * 40, "C" * 40]}
        data["since"], data["exempt"] = "2030-01-02T03:04:05Z", []
        found = self.load(data)
        self.assertEqual((found.login, found.email), ("o", "o@x.invalid"))
        self.assertEqual(found.key_ids(), frozenset({"B" * 16, "C" * 16}))
        self.assertEqual(found.since, dt.datetime(2030, 1, 2, 3, 4, 5, tzinfo=dt.UTC))
        self.assertEqual(found.exempt, ())

    def test_one_that_is_not_sound_judges_nothing(self) -> None:
        entry = SOUND["exempt"][0]
        for change, needle in (
            ({"schema": "kleidos.commit-identity/2"}, "schema"),
            ({"more": 1}, "^identity.json: it does not hold exempt, owner, schema, since$"),
            ({"owner": []}, "owner does not hold"),
            ({"owner": ["login", "email", "keys"]}, "owner does not hold"),
            ({"owner": {"login": "a", "email": "a@b"}}, "owner does not hold email, keys, login"),
            ({"owner": {**SOUND["owner"], "keys": []}}, "fingerprints"),
            ({"owner": {**SOUND["owner"], "keys": FINGERPRINT}}, "fingerprints"),
            ({"owner": {**SOUND["owner"], "keys": {FINGERPRINT: 1}}}, "fingerprints"),
            ({"owner": {**SOUND["owner"], "keys": [FINGERPRINT, KEY_ID]}}, "fingerprints"),
            ({"owner": {**SOUND["owner"], "keys": [FINGERPRINT.lower()]}}, "fingerprints"),
            ({"owner": {**SOUND["owner"], "keys": [f"{FINGERPRINT}0"]}}, "fingerprints"),
            ({"owner": {**SOUND["owner"], "login": "a b"}}, "login is not"),
            ({"owner": {**SOUND["owner"], "login": 3}}, "login is not"),
            ({"owner": {**SOUND["owner"], "email": "a"}}, "email is not"),
            ({"owner": {**SOUND["owner"], "email": ""}}, "email is not"),
            ({"since": "2026-11-26"}, "since is not"),
            ({"since": None}, "since is not"),
            ({"exempt": {}}, "exempt is not a list"),
            ({"exempt": ["x"]}, "an exemption does not hold reason, ref, repository"),
            ({"exempt": [{**entry, "reason": ""}]}, "reason is not"),
            ({"exempt": [{**entry, "reason": "because"}]}, "reason is not"),
            ({"exempt": [{**entry, "ref": "signatures"}]}, "ref is not"),
            ({"exempt": [{**entry, "ref": "refs/heads/"}]}, "ref is not"),
            ({"exempt": [{**entry, "repository": "cla"}]}, "repository is not"),
            ({"exempt": [{**entry, "repository": "o/r/x"}]}, "repository is not"),
        ):
            with self.subTest(change=change), self.assertRaisesRegex(ci.Unreadable, needle):
                self.load({**SOUND, **change})
        for text in ("{", "[]"):
            with self.assertRaisesRegex(ci.Unreadable, "identity.json"):
                self.load(text)
        with self.assertRaisesRegex(ci.Unreadable, "identity.json"):
            ci.load(Path("/nowhere/identity.json"))

    def test_an_exemption_is_one_ref_of_one_repository(self) -> None:
        cla, ref = "kleidos-dev/cla", "refs/heads/signatures"
        entry = IDENTITY.exemption(cla, ref)
        assert entry is not None
        self.assertIn("CLA bot", entry.reason)
        for repository, other in (
            ("kleidos-dev/qa", ref),
            (cla, "refs/heads/main"),
            (cla, "refs/heads/signatures/x"),
            ("x/cla", ref),
        ):
            self.assertIsNone(IDENTITY.exemption(repository, other))


class JudgeTest(unittest.TestCase):
    def test_the_names_the_documentation_gives_the_rules(self) -> None:
        names = (ci.COMMITTER, ci.SIGNATURE, ci.AUTHOR, ci.WARNING)
        self.assertEqual(
            names,
            ("identity-committer", "identity-signature", "identity-author", "identity-unknown"),
        )
        text = (fx.CENTRAL / "docs/quality.md").read_text(encoding="utf-8")
        for name in names:
            self.assertIn(f"| `{name}` |", text)
        document, _comma, heading = ci.RULES_HINT.partition(", ")
        self.assertEqual(document, "kleidos-dev/.github docs/quality.md")
        self.assertIn(f"\n### {heading.strip(chr(34))}\n", text)

    def broken(self, **more: Any) -> list[tuple[str, str]]:
        one = ci.fact(node(**more))
        return [(p.rule, p.text) for p in ci.judge(one, IDENTITY)]

    def rules(self, **more: Any) -> list[str]:
        return [rule for rule, _text in self.broken(**more)]

    # (a) the author is the owner
    def test_a_the_owners_own_commit_passes(self) -> None:
        self.assertEqual(self.broken(), [])

    def test_a_the_owner_with_another_address_is_refused(self) -> None:
        for email in (OTHER, "1+jmrplens@users.noreply.github.com", EMAIL.upper(), ""):
            with self.subTest(email=email):
                self.assertEqual(
                    self.broken(author=who(email, "jmrplens")),
                    [(ci.AUTHOR, "the author is jmrplens with another address")],
                )

    def test_a_the_owners_address_claimed_by_somebody_is_refused(self) -> None:
        """Whatever login GitHub gives the address, or none."""
        for login in ("jmrplens", "somebody", None):
            for committer in (who(OTHER, "somebody"), who(OTHER, None)):
                with self.subTest(login=login):
                    self.assertEqual(
                        self.rules(
                            author=who(EMAIL, login),
                            committer=committer,
                            **signature(keyId=THEIR_KEY),
                        ),
                        [ci.COMMITTER, ci.SIGNATURE],
                    )
        found = self.rules(author=who(EMAIL.title(), None), **signature(keyId=THEIR_KEY))
        self.assertEqual(found, [ci.AUTHOR, ci.SIGNATURE])
        self.assertEqual(
            self.broken(author=who(EMAIL, None), committer=who(EMAIL, None), signature=None),
            [(ci.SIGNATURE, "it is not signed")],
        )

    def test_a_the_owners_work_is_committed_by_the_owner(self) -> None:
        needle = f"the owner's commit is not committed as {EMAIL} (it is by "
        for email, login, said in (
            (OTHER, "jmrplens", "jmrplens)"),
            (OTHER, "somebody", "somebody)"),
            (OTHER, "x[bot]", "x[bot])"),
            (OTHER, None, "an address GitHub knows no account of)"),
            (OTHER, "::error::", "an address GitHub knows no account of)"),
            (EMAIL.title(), "jmrplens", "jmrplens)"),
            ("", None, "an address GitHub knows no account of)"),
        ):
            with self.subTest(login=login):
                found = self.broken(committer=who(email, login))
                self.assertEqual(found, [(ci.COMMITTER, needle + said)])

    def test_a_what_a_merge_button_or_the_web_editor_makes_is_refused(self) -> None:
        made = {
            "committer": who("noreply@github.com", None),
            **signature(wasSignedByGitHub=True, keyId="B5690EEEBB952194"),
        }
        self.assertEqual(
            self.broken(**made),
            [
                (
                    ci.COMMITTER,
                    f"the owner's commit is not committed as {EMAIL} (it is by GitHub)",
                ),
                (ci.SIGNATURE, "GitHub signed it, not the owner's key"),
            ],
        )

    def test_a_the_signature_is_valid_and_the_owners(self) -> None:
        another = "it is signed with another key than the owner's"
        for change, said in (
            ({"signature": None}, "it is not signed"),
            (signature(isValid=False, state="UNKNOWN_KEY"), "signature unknown_key"),
            (signature(isValid=False), "signature valid"),
            (signature(isValid=None), "signature valid"),
            (signature(state="BAD_EMAIL"), "signature bad_email"),
            (signature(state=None), "signature unsigned"),
            (signature(wasSignedByGitHub=True), "GitHub signed it"),
            (signature(wasSignedByGitHub=None), "GitHub signed it"),
            (signature(keyId=THEIR_KEY), another),
            (signature(keyId=None), another),
            (signature(keyId=KEY_ID.lower()), another),
            (signature(keyId=FINGERPRINT), another),
        ):
            # of the owner's own commit, and of one of somebody's the owner landed
            for author in ({}, {"author": who(OTHER, "somebody")}):
                with self.subTest(change=change, author=author):
                    found = self.broken(**change, **author)
                    self.assertEqual([rule for rule, _text in found], [ci.SIGNATURE])
                    self.assertIn(said, found[0][1])

    # (b) the committer is the owner, the author somebody else
    def test_b_what_the_owner_landed_keeps_its_author(self) -> None:
        for login in ("somebody", None, "jmrplens2", "Jmrplens", "dependabot[bot]"):
            self.assertEqual(self.broken(author=who(OTHER, login)), [])

    def test_b_the_owner_lands_it_with_the_owners_address_and_key(self) -> None:
        theirs = who(OTHER, "somebody")
        self.assertEqual(
            self.broken(author=theirs, committer=who(OTHER, "jmrplens")),
            [
                (
                    ci.COMMITTER,
                    f"a commit the owner made is not committed as {EMAIL} (it is by jmrplens)",
                )
            ],
        )
        # The owner's address claimed as committer by somebody, with their key or with none.
        for login in ("jmrplens", "somebody", None):
            for made in (signature(keyId=THEIR_KEY), {"signature": None}):
                found = self.rules(author=theirs, committer=who(EMAIL, login), **made)
                self.assertEqual(found, [ci.SIGNATURE])
        found = self.rules(author=theirs, committer=who(EMAIL.upper(), None))
        self.assertEqual(found, [ci.COMMITTER])

    # (c) neither is the owner
    def test_c_a_contributors_commit_is_not_judged(self) -> None:
        theirs = who(OTHER, "somebody")
        github = who("noreply@github.com", None)
        for committer in (theirs, who(OTHER, "another"), github):
            for made in (
                signature(keyId=THEIR_KEY),
                signature(keyId=None),
                signature(wasSignedByGitHub=True, keyId="B5690EEEBB952194"),
                signature(isValid=False, state="UNKNOWN_KEY"),
                signature(isValid=False, state="BAD_EMAIL", keyId=None),
                {"signature": None},
            ):
                with self.subTest(committer=committer, made=made):
                    one = ci.fact(node(author=theirs, committer=committer, **made))
                    self.assertFalse(ci.of_owner(one, IDENTITY))
                    self.assertEqual(ci.judge(one, IDENTITY), [])

    # (d) GitHub knows no account of either
    def test_d_a_commit_of_no_account_is_not_judged(self) -> None:
        nobody = who(OTHER, None)
        for made in (signature(keyId=THEIR_KEY), {"signature": None}):
            self.assertEqual(self.broken(author=nobody, committer=nobody, **made), [])
        self.assertEqual(self.broken(author=None, committer=None, signature=None), [])

    def test_d_which_address_is_unknown(self) -> None:
        known, nobody = who(OTHER, "somebody"), who(OTHER, None)
        github = who("noreply@github.com", None)
        made = signature(wasSignedByGitHub=True)
        for change, wanted in (
            ({}, None),
            ({"author": known, "committer": known}, None),
            ({"author": nobody, "committer": nobody}, "author"),
            ({"author": nobody}, "author"),
            ({"committer": nobody}, "committer"),
            ({"committer": nobody, "signature": None}, "committer"),
            ({"committer": github, **made}, None),
            ({"committer": github}, "committer"),
            ({"author": nobody, "committer": github, **made}, "author"),
        ):
            with self.subTest(change=change):
                self.assertEqual(ci.unknown(ci.fact(node(**change))), wanted)

    # (e) a bot
    def test_e_a_bots_commit_is_not_judged(self) -> None:
        for bot in ("dependabot[bot]", "github-actions[bot]", "release[bot]"):
            made = {
                "author": who(f"1+{bot}@users.noreply.github.com", bot),
                "committer": who("noreply@github.com", None),
                **signature(wasSignedByGitHub=True, keyId="B5690EEEBB952194"),
            }
            self.assertEqual(self.broken(**made), [])
            self.assertIsNone(ci.unknown(ci.fact(node(**made))))

    def test_everything_wrong_is_said_at_once(self) -> None:
        self.assertEqual(
            self.rules(
                author=who(OTHER, "jmrplens"), committer=who(OTHER, "jmrplens"), signature=None
            ),
            [ci.AUTHOR, ci.COMMITTER, ci.SIGNATURE],
        )

    def test_another_owner_is_judged_by_the_same_rules(self) -> None:
        data = copy.deepcopy(SOUND)
        data["owner"] = {"login": "o", "email": "o@x.invalid", "keys": ["B" * 40]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "identity.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            identity = ci.load(path)
        self.assertEqual(ci.judge(ci.fact(node(signature=None)), identity), [])
        theirs = ci.fact(node(author=who("o@x.invalid", "o")))
        rules = [p.rule for p in ci.judge(theirs, identity)]
        self.assertEqual(rules, [ci.COMMITTER, ci.SIGNATURE])

    def test_no_address_is_ever_said(self) -> None:
        one = ci.fact(node(author=who(OTHER, "jmrplens"), committer=who(OTHER, None)))
        problems = ci.judge(one, IDENTITY)
        warnings = ci.warned([ci.fact(node(author=who(OTHER, None)))], [])
        self.assertEqual((len(problems), len(warnings)), (2, 1))
        said = [repr(one), repr(problems), repr(warnings), ci.report(2, 1, problems, warnings)]
        self.assertNotIn(OTHER, "\n".join(said))

    def test_what_is_not_there_is_nobodys(self) -> None:
        one = ci.fact(node(author=None, committer={}))
        self.assertEqual((one.author_email, one.author_login, one.committer_email), ("", None, ""))
        self.assertFalse(ci.of_owner(one, IDENTITY))


class FactsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.slept: list[float] = []

    def facts(self, hub: FakeGitHub, *shas: str) -> list[ci.Fact]:
        return ci.facts(hub, REPO, list(shas), self.slept.append)

    def test_what_is_asked_and_in_which_order(self) -> None:
        hub = FakeGitHub(node(A), node(B, parents={"totalCount": 2}))
        found = self.facts(hub, B, A)
        self.assertEqual([(f.sha, f.parents) for f in found], [(B, 2), (A, 1)])
        ((query, variables),) = hub.asked
        self.assertEqual(variables, {"owner": "kleidos-dev", "name": "boards"})
        self.assertIn(f'}} c1:object(oid:"{A}")', query)
        for wanted in ("isValid", "state", "wasSignedByGitHub", "keyId", "user{login}"):
            self.assertIn(wanted, query)
        self.assertEqual(self.slept, [])

    def test_it_asks_by_batches(self) -> None:
        self.assertEqual(ci.BATCH, 50)
        shas = [f"{n:040x}" for n in range(ci.BATCH + 1)]
        hub = FakeGitHub(*(node(sha) for sha in shas))
        self.assertEqual([f.sha for f in self.facts(hub, *shas)], shas)
        self.assertEqual([q.count("object(oid") for q, _v in hub.asked], [ci.BATCH, 1])
        hub.asked.clear()
        self.assertEqual(self.facts(hub), [])
        self.assertEqual(hub.asked, [])

    def test_a_commit_github_does_not_know_is_no_pass(self) -> None:
        answers: tuple[Any, ...] = (
            None,
            {},
            {"repository": None},
            {"repository": {"c0": None}},
            {"repository": {"c0": {}}},
            {"repository": {"c0": node(B)}},
        )
        for answer in answers:

            def ask(_query: str, _variables: dict[str, Any], answer: Any = answer) -> Any:
                return answer

            with (
                self.subTest(answer=answer),
                self.assertRaisesRegex(ci.Unreadable, f"no commit {A[:12]} of {REPO}"),
            ):
                ci.facts(ask, REPO, [A])

    def test_what_is_no_commit_is_never_asked(self) -> None:
        hub = FakeGitHub()
        for text in ("", "main", A[:39], A + "a", A.upper(), f'{A}"', f"{A}\n"):
            said = f"^{re.escape(repr(text[:12]))} is no commit$"
            with self.subTest(text=text), self.assertRaisesRegex(ci.Unreadable, said):
                self.facts(hub, A, text)
        self.assertEqual(hub.asked, [])

    def test_an_undecided_signature_is_asked_again(self) -> None:
        for state in ("GPGVERIFY_ERROR", "GPGVERIFY_UNAVAILABLE"):
            undecided = node(**signature(isValid=False, state=state))
            hub = FakeGitHub(undecided)
            hub.then = [undecided, node()]
            self.slept.clear()
            (one,) = self.facts(hub, A)
            self.assertTrue(one.valid)
            self.assertEqual((len(hub.asked), self.slept), (3, [ci.PAUSE_SECONDS] * 2))

    def test_one_that_stays_undecided_is_no_pass(self) -> None:
        hub = FakeGitHub(node(B), node(**signature(isValid=False, state="GPGVERIFY_ERROR")))
        with self.assertRaisesRegex(ci.Unreadable, "run the job again"):
            self.facts(hub, A, B)
        self.assertEqual((len(hub.asked), self.slept), (3, [10.0, 10.0]))


def pull_event(**more: Any) -> dict[str, Any]:
    return {
        "pull_request": {
            "user": {"login": "jmrplens", "type": "User"},
            "head": {"sha": A, "repo": {"full_name": REPO}},
            "base": {"sha": B, "ref": "main"},
            **more,
        }
    }


def push_event(**more: Any) -> dict[str, Any]:
    return {
        "ref": "refs/heads/main",
        "before": B,
        "after": A,
        "deleted": False,
        "repository": {
            "default_branch": "main",
            "pushed_at": int(IDENTITY.since.timestamp()),
        },
        **more,
    }


class ScopeTest(unittest.TestCase):
    def scope(self, name: str, event: dict[str, Any], repository: str = REPO) -> ci.Scope:
        return ci.scope(name, event, repository, IDENTITY)

    def test_what_a_pull_request_adds(self) -> None:
        self.assertEqual(
            self.scope("pull_request", pull_event()),
            ci.Scope(A, (B, "refs/remotes/origin/main"), own=True),
        )
        event = pull_event(base={"sha": B, "ref": "a/b"})
        self.assertEqual(self.scope("pull_request", event).known, (B, "refs/remotes/origin/a/b"))

    def test_every_pull_request_is_looked_at_wherever_its_branch_is(self) -> None:
        here, fork = {"full_name": REPO}, {"full_name": "x/boards"}
        bot = {"login": "dependabot[bot]", "type": "Bot"}
        for user, repo, own in (
            ("jmrplens", here, True),
            ("jmrplens", fork, False),
            ("jmrplens", None, False),
            ("somebody", here, False),
            ("somebody", fork, False),
            ("Jmrplens", here, False),
        ):
            event = pull_event(user={"login": user, "type": "User"}, head={"sha": A, "repo": repo})
            found = self.scope("pull_request", event)
            self.assertEqual((found.head, found.note, found.own), (A, "", own))
        found = self.scope("pull_request", pull_event(user=bot))
        self.assertEqual((found.head, found.note, found.own), (A, "", False))
        found = self.scope("pull_request", pull_event(head={"sha": A}))
        self.assertEqual((found.head, found.own), (A, False))

    def test_what_a_push_adds(self) -> None:
        self.assertEqual(self.scope("push", push_event()), ci.Scope(A, (B,)))

    def test_only_the_default_branch_is_judged(self) -> None:
        for ref in ("refs/heads/x", "refs/tags/main", "refs/heads/main2", "main"):
            found = self.scope("push", push_event(ref=ref))
            self.assertEqual(found, ci.Scope(note=f"{ref} is not the default branch"))
        repository = {**push_event()["repository"], "default_branch": "trunk"}
        event = push_event(ref="refs/heads/trunk", repository=repository)
        self.assertEqual(self.scope("push", event).head, A)

    def test_an_exempt_ref(self) -> None:
        meter = "kleidos-dev/meter"
        reason = "refs/heads/main is exempt: Work in flight"
        self.assertIn(reason, self.scope("push", push_event(), meter).note)
        event = pull_event(head={"sha": A, "repo": {"full_name": meter}})
        self.assertIn(reason, self.scope("pull_request", event, meter).note)
        event = pull_event(
            head={"sha": A, "repo": {"full_name": meter}}, base={"sha": B, "ref": "v2"}
        )
        self.assertEqual(self.scope("pull_request", event, meter).head, A)

    def test_a_deleted_branch_adds_nothing(self) -> None:
        found = self.scope("push", push_event(deleted=True, after=ZERO))
        self.assertEqual(found, ci.Scope(note="refs/heads/main was deleted"))

    def test_a_run_started_again_judges_what_was_pushed_then(self) -> None:
        since = int(IDENTITY.since.timestamp())
        for pushed, judged in (
            (since - 1, False),
            (since, True),
            (since + 1, True),
            (None, True),
            (str(since - 1), True),
        ):
            repository = {"default_branch": "main", "pushed_at": pushed}
            found = self.scope("push", push_event(repository=repository))
            self.assertEqual(bool(found.head), judged, pushed)
            self.assertEqual(found.note, "" if judged else "the push is older than the rule")

    def test_another_event_adds_nothing(self) -> None:
        for name in ("schedule", "workflow_dispatch", "pull_request_target", "merge_group", ""):
            found = self.scope(name, pull_event())
            self.assertEqual(found, ci.Scope(note=f"a {name} run adds no commit"))

    def test_an_event_that_is_not_whole_is_no_pass(self) -> None:
        for name, event in (
            ("pull_request", {}),
            ("pull_request", {"pull_request": None}),
            ("pull_request", pull_event(base=None)),
            ("pull_request", pull_event(user=None)),
            ("pull_request", pull_event(head=None)),
            ("pull_request", pull_event(head={"sha": A, "repo": "x"})),
            ("push", {}),
            ("push", push_event(repository=None)),
        ):
            with self.subTest(name=name), self.assertRaisesRegex(ci.Unreadable, name):
                self.scope(name, event)


class AddedTest(unittest.TestCase):
    """What a change adds, over a real history."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = fx.init(Path(self._tmp.name) / "r")
        self.shas = [self.commit(str(n)) for n in range(4)]

    def commit(self, text: str) -> str:
        fx.write(self.root, "a.txt", text)
        fx.commit(self.root, f"Add {text}")
        return fx.git(self.root, "rev-parse", "HEAD").strip()

    def added(self, head: str, *known: str) -> list[str]:
        return ci.added(ci.Scope(head, known), str(self.root))

    def test_the_commits_between_the_oldest_first(self) -> None:
        self.assertEqual(self.added(self.shas[3], self.shas[1]), self.shas[2:])
        self.assertEqual(self.added(self.shas[1], self.shas[3]), [])

    def test_what_the_base_has_by_now_is_not_added(self) -> None:
        fx.git(self.root, "update-ref", "refs/remotes/origin/main", self.shas[2])
        ref = "refs/remotes/origin/main"
        self.assertEqual(self.added(self.shas[3], self.shas[0], ref), self.shas[3:])
        self.assertEqual(self.added(self.shas[3], self.shas[0], ref + "x"), self.shas[1:])

    def test_a_main_written_anew_or_new_is_judged_whole(self) -> None:
        for before in (ZERO, "e" * 40):
            self.assertEqual(self.added(self.shas[2], before), self.shas[:3])

    def test_what_is_no_commit_is_no_pass(self) -> None:
        for head, before in (("x", self.shas[0]), (self.shas[0], "--all"), ("", ""), (A, B)):
            with self.subTest(head=head), self.assertRaises(ci.Unreadable):
                self.added(head, before)
        with self.assertRaisesRegex(ci.Unreadable, "names no commit"):
            ci.added(ci.Scope(self.shas[1], (None,)), str(self.root))  # type: ignore[arg-type]  # what a broken event holds

    def test_where_it_is_run_is_the_repository(self) -> None:
        with mock.patch.object(ccm, "git", return_value="") as git:
            ci.added(ci.Scope(A, (B,)))
        self.assertEqual([call.args[1] for call in git.call_args_list], [None, None])


class RunTest(unittest.TestCase):
    """The job, over a real history and a GitHub that answers as told."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.root = fx.init(self.tmp / "r")
        self.shas = []
        for n in range(3):
            fx.write(self.root, "a.txt", str(n))
            fx.commit(self.root, f"Add {n}")
            self.shas.append(fx.git(self.root, "rev-parse", "HEAD").strip())
        self.hub = FakeGitHub(*(node(sha) for sha in self.shas))
        self.requests: list[tuple[str, str]] = []
        self.answer: Any = None

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        self.requests.append((method, path))
        if self.answer is not None:
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer
        assert body is not None
        return {"data": self.hub(body["query"], body["variables"])}

    def run_it(self, name: str, event: dict[str, Any], **env: str) -> tuple[int, str, str]:
        path, summary = self.tmp / "event.json", self.tmp / "summary"
        path.write_text(json.dumps(event), encoding="utf-8")
        summary.write_text("", encoding="utf-8")
        outer = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "GITHUB_"))}
        given = {
            **outer,
            "GITHUB_EVENT_NAME": name,
            "GITHUB_EVENT_PATH": str(path),
            "GITHUB_REPOSITORY": REPO,
            "GITHUB_STEP_SUMMARY": str(summary),
            "GITHUB_TOKEN": "t",
            **env,
        }
        given = {k: v for k, v in given.items() if v != "-"}
        out = io.StringIO()
        with (
            mock.patch.dict(os.environ, given, clear=True),
            mock.patch.object(ccm.GitHub, "request", lambda _s, *args: self.request(*args)),
            contextlib.chdir(self.root),
            contextlib.redirect_stdout(out),
        ):
            status = ci.main()
        return status, out.getvalue(), summary.read_text(encoding="utf-8")

    def push(self, **more: Any) -> dict[str, Any]:
        return push_event(before=self.shas[0], after=self.shas[2], **more)

    def pull(self, user: str = "jmrplens", repo: str = REPO) -> dict[str, Any]:
        return pull_event(
            user={"login": user, "type": "User"},
            head={"sha": self.shas[2], "repo": {"full_name": repo}},
            base={"sha": self.shas[0], "ref": "main"},
        )

    def test_the_owners_commits_pass(self) -> None:
        status, said, summary = self.run_it("push", self.push())
        self.assertEqual(status, 0, said)
        self.assertIn("2 commit(s) added, 2 of the owner's, 0 problem(s)", said)
        self.assertEqual(
            summary,
            "### Identity of the commits: the owner's 2 pass\n\n"
            "2 added; 0 are somebody else's or a bot's, and are not judged.\n",
        )
        self.assertEqual(self.requests, [("POST", "/graphql")])

    def test_one_that_is_not_the_owners_fails(self) -> None:
        self.hub.nodes[self.shas[1]] = node(self.shas[1], committer=who(OTHER, "jmrplens"))
        for user, repo in (("jmrplens", REPO), ("somebody", REPO), ("somebody", "x/boards")):
            status, said, summary = self.run_it("pull_request", self.pull(user, repo))
            self.assertEqual(status, 1)
            error = f"::error title=Identity of a commit::{self.shas[1][:12]}: identity-committer:"
            self.assertIn(error, said)
            self.assertIn("### Identity of the commits: 1 of the owner's 2 refused", summary)
            row = f"| `{self.shas[1][:7]}` | `identity-committer` | the owner's commit"
            self.assertIn(row, summary)
            self.assertIn("git rebase --force-rebase", summary)
            self.assertNotIn(OTHER, said + summary)

    def test_a_contributors_branch_passes_here_and_in_a_fork(self) -> None:
        """Author, committer and key are theirs, or there is no signature."""
        theirs = who(OTHER, "somebody")
        for made in (signature(keyId=THEIR_KEY), {"signature": None}):
            for sha in self.shas[1:]:
                self.hub.nodes[sha] = node(sha, author=theirs, committer=theirs, **made)
            for repo in (REPO, "x/boards"):
                status, said, summary = self.run_it("pull_request", self.pull("somebody", repo))
                self.assertEqual(status, 0, said)
                self.assertNotIn("::", said)
                self.assertIn("2 commit(s) added, 0 of the owner's, 0 problem(s)", said)
                self.assertIn("2 added; 2 are somebody else's", summary)
            self.assertEqual(self.run_it("push", self.push())[0], 0)

    def test_the_owners_commit_beside_a_contributors_is_judged_alone(self) -> None:
        theirs = who(OTHER, "somebody")
        self.hub.nodes[self.shas[1]] = node(
            self.shas[1], author=theirs, committer=theirs, signature=None
        )
        self.hub.nodes[self.shas[2]] = node(self.shas[2], signature=None)
        status, said, summary = self.run_it("pull_request", self.pull("somebody"))
        self.assertEqual((status, said.count("::error")), (1, 1))
        self.assertIn("1 of the owner's 1 refused", summary)
        self.assertNotIn(self.shas[1][:7], said + summary)

    def test_an_unknown_address_on_the_owners_own_branch_is_warned_about(self) -> None:
        nobody = who(OTHER, None)
        self.hub.nodes[self.shas[1]] = node(
            self.shas[1], author=nobody, committer=nobody, signature=None
        )
        status, said, summary = self.run_it("pull_request", self.pull())
        self.assertEqual(status, 0)
        warning = f"::warning title=Identity of a commit::{self.shas[1][:12]}: identity-unknown: "
        self.assertIn(f"{warning}GitHub knows no account of the address of its author", said)
        self.assertEqual(said.count("::warning"), 1)
        self.assertIn(f"| `{self.shas[1][:7]}` | `identity-unknown` | GitHub knows", summary)
        self.assertIn("the owner's 1 pass", summary)
        self.assertNotIn(OTHER, said + summary)
        # Each has its row, what is refused first.
        self.hub.nodes[self.shas[2]] = node(self.shas[2], signature=None)
        _status, _said, summary = self.run_it("pull_request", self.pull())
        rows = [row.split(" | ")[:2] for row in summary.splitlines() if row.startswith("| `")]
        self.assertEqual(
            rows,
            [
                [f"| `{self.shas[2][:7]}`", "`identity-signature`"],
                [f"| `{self.shas[1][:7]}`", "`identity-unknown`"],
            ],
        )
        self.hub.nodes[self.shas[2]] = node(self.shas[2])
        # Nobody else is, and neither is a push, nor what is refused already.
        for name, event in (
            ("pull_request", self.pull("somebody")),
            ("pull_request", self.pull("jmrplens", "x/boards")),
            ("push", self.push()),
        ):
            status, said, summary = self.run_it(name, event)
            self.assertEqual((status, "identity-unknown" in said + summary), (0, False))
        self.hub.nodes[self.shas[1]] = node(self.shas[1], committer=nobody)
        status, said, _summary = self.run_it("pull_request", self.pull())
        self.assertEqual((status, "::warning" in said), (1, False))

    def test_history_is_not_judged(self) -> None:
        self.hub.nodes[self.shas[0]] = node(self.shas[0], signature=None)
        self.assertEqual(self.run_it("push", self.push())[0], 0)

    def test_where_nothing_is_judged_it_says_so_and_asks_nothing(self) -> None:
        status, said, summary = self.run_it("push", self.push(ref="refs/heads/x"), GITHUB_TOKEN="-")
        self.assertEqual((status, self.requests), (0, []))
        note = "refs/heads/x is not the default branch"
        self.assertIn(f"::notice title=Identity of the commits::not judged: {note}", said)
        self.assertIn(f"Not judged: {note}.", summary)

    def test_what_cannot_be_read_is_no_pass(self) -> None:
        broken = fx.write(self.tmp, "broken.json", "{")
        for change, needle in (
            ({"GITHUB_EVENT_PATH": str(broken)}, "the event: JSONDecodeError"),
            ({"GITHUB_TOKEN": ""}, "GITHUB_TOKEN is empty"),
            ({"GITHUB_TOKEN": "-"}, "GITHUB_TOKEN is empty"),
            ({"GITHUB_EVENT_PATH": "-"}, "the event"),
            ({"GITHUB_EVENT_PATH": "/nowhere"}, "the event"),
            ({"GITHUB_EVENT_PATH": str(self.root / "a.txt")}, "the push event is not as"),
            ({"GITHUB_API_URL": "http://api.github.com"}, "is not https"),
        ):
            with self.subTest(needle=needle):
                status, said, _summary = self.run_it("push", self.push(), **change)
                self.assertEqual(status, 2)
                self.assertTrue(said.startswith("::error title=Identity of the commits::"), said)
                self.assertIn(needle, said)

    def test_a_refusal_of_githubs_is_no_pass(self) -> None:
        for answer, needle in (
            (urllib.error.URLError("down"), "GitHub: <urlopen error down>"),
            (ValueError("no JSON"), "GitHub: no JSON"),
            ({"errors": [{"message": "rate limited"}]}, "GitHub: rate limited"),
            ({"errors": [{"message": "x" * 300}]}, f"GitHub: {'x' * 200}\n"),
            ({"errors": [{}]}, "GitHub: None"),
            ({}, "GitHub knows no commit"),
            (False, "GitHub knows no commit"),
        ):
            with self.subTest(needle=needle):
                self.answer = answer
                status, said, _summary = self.run_it("push", self.push())
                self.assertEqual(status, 2)
                self.assertIn(needle, said)

    def test_without_a_summary_it_still_says(self) -> None:
        status, said, summary = self.run_it("push", self.push(), GITHUB_STEP_SUMMARY="-")
        self.assertEqual((status, summary), (0, ""))
        self.assertIn("2 commit(s) added", said)

    def test_where_the_server_is(self) -> None:
        seen: list[tuple[str, str]] = []

        def init(self: Any, token: str, api_url: str) -> None:
            seen.append((token, api_url))

        with mock.patch.object(ccm.GitHub, "__init__", init):
            self.run_it("push", self.push())
            self.run_it("push", self.push(), GITHUB_API_URL="https://x.invalid")
        self.assertEqual(seen, [("t", "https://api.github.com"), ("t", "https://x.invalid")])


if __name__ == "__main__":
    unittest.main()
