# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""fast_forward.py: what lands is the commit that was judged, by a push that is never forced.

The git is real: a bare repository stands for GitHub's, and the clones, the
copies and the pushes of a landing run against it. The key is not: a program
in gpg's place writes down which key it was asked to sign with.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import kit_fixtures as fx
from kit_fixtures import commit_identity, fast_forward, landing, run_form

SLUG = "kleidos-dev/boards"
EMAIL = "jmrplens@kleidos.dev"
OWNER = {"login": "jmrplens", "type": "User"}
PERSON = {"login": "somebody", "type": "User"}
BOT = {"login": fast_forward.BOT, "type": "Bot"}
FINGERPRINT = "0A993B268654DBBA52B7E8D3FCF653391E2C91FC"
GATE = {
    "name": fast_forward.GATE,
    "status": "completed",
    "conclusion": "success",
    "app": {"id": fast_forward.ACTIONS_APP},
}
CI = {"name": "CI", "event": "pull_request", "status": "completed", "conclusion": "success"}
GPG = """#!/bin/sh
echo "$*" >> "{log}"
cat > /dev/null
printf '\\n[GNUPG:] SIG_CREATED \\n' >&2
printf -- '-----BEGIN PGP SIGNATURE-----\\n\\nx\\n-----END PGP SIGNATURE-----\\n'
"""


class Hub(fast_forward.Api):
    """GitHub: a bare repository, the pull requests on it, and what ran on a commit."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.bare = root / "hub.git"
        self.work = fx.init(root / "work")
        self.env = {
            "GIT_COMMITTER_EMAIL": EMAIL,
            "GIT_COMMITTER_NAME": "The owner",
            "GIT_AUTHOR_NAME": "Who wrote it",
        }
        fx.write(self.work, "a.txt", "0\n")
        self.first = self.commit("Add a")
        fx.git(root, "clone", "-q", "--bare", str(self.work), str(self.bare))
        fx.git(self.work, "remote", "add", "origin", str(self.bare))
        self.pulls: dict[int, dict[str, Any]] = {}
        self.nodes: dict[str, dict[str, Any]] = {}
        self.runs, self.checks = [dict(CI)], [dict(GATE)]
        self.status = {"total_count": 0, "state": "pending"}
        self.more: dict[str, int] = {}
        self.posts: list[tuple[str, dict[str, str]]] = []
        self.logins = {EMAIL: "jmrplens", "p@example.invalid": "somebody"}
        self.viewer = "jmrplens"
        self.never_merged = False

    # the repository
    def git(self, *args: str) -> str:
        return fx.git(self.bare, *args).strip()

    def commit(self, message: str, email: str = EMAIL, text: str | None = None) -> str:
        if text is not None:
            fx.write(self.work, "a.txt", text)
        env = {**fx.GIT_ENV, **self.env, "GIT_AUTHOR_EMAIL": email}
        with mock.patch.dict(fx.GIT_ENV, env):
            fx.commit(self.work, message)
        return fx.git(self.work, "rev-parse", "HEAD").strip()

    def branch(self, name: str, *texts: str, email: str = EMAIL, rel: str = "a.txt") -> str:
        """A branch on main with a commit per text, pushed; its head."""
        fx.git(self.work, "fetch", "-q", "origin")
        fx.git(self.work, "checkout", "-q", "-B", name, "origin/main")
        head = ""
        for text in texts:
            fx.write(self.work, rel, text)
            head = self.commit(f"Write {text.strip()}", email)
        fx.git(self.work, "push", "-q", "-f", "origin", f"HEAD:refs/heads/{name}")
        return head

    def open(self, number: int, sha: str, ref: str = "topic", **more: Any) -> dict[str, Any]:
        self.git("update-ref", f"refs/pull/{number}/head", sha)
        repo = {"full_name": SLUG, "default_branch": "main"}
        self.pulls[number] = {
            "number": number,
            "title": f"Title of {number}",
            "state": "open",
            "draft": False,
            "html_url": f"https://x/{number}",
            "user": OWNER,
            "head": {"sha": sha, "ref": ref, "repo": dict(repo)},
            "base": {"ref": "main", "repo": dict(repo)},
            **more,
        }
        return self.pulls[number]

    def main(self) -> str:
        return self.git("rev-parse", "refs/heads/main")

    def range(self, number: int) -> list[str]:
        head = self.pulls[number]["head"]["sha"]
        return self.git("rev-list", "--reverse", head, "^refs/heads/main").split()

    # the API
    def get(self, path: str) -> Any:
        base = f"repos/{SLUG}"
        if path == "user":
            return {"login": self.viewer}
        if found := re.fullmatch(rf"{base}/pulls/(\d+)", path):
            pull = self.pulls[int(found[1])]
            merged = self.git("merge-base", pull["head"]["sha"], "refs/heads/main")
            done = merged == pull["head"]["sha"] and not self.never_merged
            return {**json.loads(json.dumps(pull)), "merged": done}
        if found := re.fullmatch(rf"{base}/pulls/(\d+)/(commits|files)\?per_page=100&page=1", path):
            return self.commits(int(found[1])) if found[2] == "commits" else self.files(found[1])
        if path == f"{base}/commits/main":
            return {"sha": self.main()}
        if found := re.fullmatch(rf"{base}/compare/([0-9a-f]+)\.\.\.([0-9a-f]+)", path):
            ahead = self.git("rev-list", "--count", f"{found[1]}..{found[2]}")
            behind = self.git("rev-list", "--count", f"{found[2]}..{found[1]}")
            return {"ahead_by": int(ahead), "behind_by": int(behind)}
        if re.fullmatch(rf"{base}/actions/runs\?head_sha=[0-9a-f]+&per_page=100", path):
            return {"workflow_runs": self.runs, "total_count": self.more.get("runs", 1)}
        if re.fullmatch(rf"{base}/commits/[0-9a-f]+/check-runs\?per_page=100", path):
            return {"check_runs": self.checks, "total_count": self.more.get("checks", 1)}
        if re.fullmatch(rf"{base}/commits/[0-9a-f]+/status\?per_page=100", path):
            return self.status
        raise AssertionError(f"not asked for: {path}")

    def commits(self, number: int) -> list[dict[str, Any]]:
        out = []
        for sha in self.range(number):
            email, parents, message = self.git("show", "-s", "--format=%ae%x00%P%x00%B", sha).split(
                "\0"
            )
            login = self.logins.get(email)
            out.append(
                {
                    "sha": sha,
                    "parents": [{"sha": p} for p in parents.split()],
                    "author": {"login": login} if login else None,
                    "commit": {"message": message, "author": {"email": email}},
                }
            )
        return out

    def files(self, number: str) -> list[dict[str, Any]]:
        head = self.pulls[int(number)]["head"]["sha"]
        names = self.git("diff", "--name-only", f"refs/heads/main...{head}").split()
        return [{"filename": n, "status": "modified", "patch": "@@"} for n in names]

    def post(self, path: str, fields: dict[str, str]) -> Any:
        self.posts.append((path, fields))
        head = self.git("rev-parse", f"refs/heads/{fields['head']}")
        return self.open(100 + len(self.posts), head, fields["head"], title=fields["title"])

    def ask(self, query: str, variables: dict[str, Any]) -> Any:
        found = {}
        for n, sha in enumerate(re.findall(r'oid:"([0-9a-f]+)"', query)):
            author, committer, parents = self.git(
                "show", "-s", "--format=%ae%x00%ce%x00%P", sha
            ).split("\0")
            found[f"c{n}"] = {
                "oid": sha,
                "parents": {"totalCount": len(parents.split())},
                "author": {"email": author, "user": {"login": self.logins.get(author)}},
                "committer": {"email": committer, "user": None},
                "signature": {
                    "isValid": True,
                    "state": "VALID",
                    "wasSignedByGitHub": False,
                    "keyId": FINGERPRINT[-16:],
                },
                **self.nodes.get(sha, {}),
            }
        return {"repository": found}


class LocalGit(fast_forward.Git):
    """Clones of the hub, with the owner's identity, and a pen that writes down the key."""

    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.email = EMAIL
        self.ran: list[tuple[str, ...]] = []
        self.before: dict[str, Any] = {}
        self.log = hub.root / "keys"
        self.gpg = fx.write(hub.root, "gpg", GPG.format(log=self.log))
        self.gpg.chmod(0o755)

    def clone(self, slug: str, folder: Path) -> None:
        assert slug == SLUG, slug
        self._run(["git", "clone", "-q", str(self.hub.bare), str(folder)])
        for name, value in (
            ("user.name", "The owner"),
            ("user.email", self.email),
            ("gpg.program", str(self.gpg)),
        ):
            self._run(["git", "-C", str(folder), "config", name, value])

    def run(self, folder: Path, *args: str) -> str:
        self.ran.append(args)
        if args[0] in self.before:
            self.before.pop(args[0])()
        return super().run(folder, *args)

    def pushes(self) -> list[tuple[str, ...]]:
        return [args for args in self.ran if args[0] == "push"]


class HubCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        outer = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env = {**outer, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
        patch = mock.patch.dict(os.environ, env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.hub = Hub(Path(self._tmp.name))
        self.git = LocalGit(self.hub)
        self.said: list[str] = []
        self.slept: list[float] = []
        self.later: list[Any] = []

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        if self.later:
            self.later.pop(0)()

    def lander(self, merge: bool = True) -> landing.Lander:
        return landing.Lander(self.hub, self.git, merge, self.sleep, self.said.append)

    def land(self, number: int = 7, merge: bool = True, read: str = "") -> bool:
        return self.lander(merge).land(SLUG, number, False, read)


class OwnTest(HubCase):
    def setUp(self) -> None:
        super().setUp()
        self.head = self.hub.branch("topic", "1\n", "2\n")
        self.pull = self.hub.open(7, self.head)

    def left(self, needle: str, read: str = "", **lander: Any) -> None:
        """It stays, for this reason, and main with it."""
        before = self.hub.main()
        self.assertFalse(self.land(read=read, **lander))
        self.assertEqual(len(self.said), 1, self.said)
        self.assertRegex(self.said[0], f"^left: {SLUG}#7 Title of 7: .*{re.escape(needle)}")
        self.assertEqual((self.hub.main(), self.git.pushes()), (before, []))

    def test_the_very_head_becomes_main(self) -> None:
        self.assertTrue(self.land())
        self.assertEqual(self.hub.main(), self.head)
        self.assertEqual(
            self.git.pushes(), [("push", "-q", "origin", f"{self.head}:refs/heads/main")]
        )
        self.assertEqual(self.said, [f"landed: {SLUG}#7 Title of 7: https://x/7"])
        self.assertEqual(self.slept, [])

    def test_a_dry_run_says_the_state_and_pushes_nothing(self) -> None:
        self.assertFalse(self.land(merge=False))
        self.assertEqual(self.said, [f"would land: {SLUG}#7 Title of 7: green"])
        self.assertEqual((self.hub.main(), self.git.ran), (self.hub.first, []))
        self.said.clear()
        self.hub.runs = []
        self.land(merge=False)
        self.assertEqual((self.said[0][-9:], self.slept), (": pending", []))
        self.said.clear()
        self.pull["draft"] = True
        self.left("a draft", merge=False)

    def test_who_lands_is_the_owner(self) -> None:
        self.hub.viewer = "someone"
        lander = self.lander()
        self.assertFalse(lander.own(SLUG, self.hub.get(f"repos/{SLUG}/pulls/7")))
        self.assertIn("someone is not jmrplens, whose commits these must be", self.said[0])

    def test_only_the_owners_pull_request_lands_as_it_is(self) -> None:
        for change in (
            {"user": PERSON},
            {"user": BOT},
            {"head": {**self.pull["head"], "repo": {"full_name": "jmrplens/boards"}}},
            {"head": {**self.pull["head"], "repo": None}},
        ):
            self.said.clear()
            pull = {**self.hub.get(f"repos/{SLUG}/pulls/7"), **change}
            self.assertFalse(self.lander().own(SLUG, pull))
            self.assertIn("opened by ", self.said[0])

    def test_a_pull_request_that_cannot_land(self) -> None:
        for change, needle in (
            ({"state": "closed"}, "it is not open"),
            ({"draft": True}, "a draft"),
            ({"base": {**self.pull["base"], "ref": "v2"}}, "against v2, not the default branch"),
        ):
            with self.subTest(needle=needle):
                self.said.clear()
                self.hub.open(7, self.head, **change)
                self.left(needle)

    def test_an_exempt_branch_is_left(self) -> None:
        with mock.patch.object(
            commit_identity.Identity, "exemption", return_value=object()
        ) as asked:
            self.left("main is exempt from the identity of its commits")
        self.assertEqual(asked.call_args.args, (SLUG, "refs/heads/main"))

    def test_a_branch_that_is_not_on_top_of_main(self) -> None:
        self.hub.git("update-ref", "refs/heads/main", self.hub.branch("other", "x\n"))
        self.left("it is not on top of main: rebase it here, signed")

    def test_a_branch_that_adds_nothing(self) -> None:
        self.hub.open(7, self.hub.first)
        self.left("it is not on top of main")

    def test_the_commits_are_the_ones_that_land(self) -> None:
        listed = self.hub.commits(7)
        for found in (listed[:1], [], listed[::-1], [*listed, listed[0]]):
            with (
                self.subTest(found=len(found)),
                mock.patch.object(self.hub, "commits", return_value=found),
            ):
                self.said.clear()
                self.left("its commits are not the ones that would land")

    def test_each_commit_is_the_owners(self) -> None:
        first = self.hub.range(7)[0]
        for of, change, needle in (
            (first, {"signature": None}, f"commit {first[:7]}: it is not signed"),
            (self.head, {"committer": {"email": "noreply@github.com"}}, "the committer is not"),
            (
                first,
                {"author": {"email": "x@example.invalid", "user": {"login": "jmrplens"}}},
                "the author is jmrplens with another address",
            ),
            (first, {"parents": {"totalCount": 2}}, f"commit {first[:7]} is a merge"),
            (first, {"parents": {"totalCount": 0}}, f"commit {first[:7]} is a merge"),
        ):
            with self.subTest(needle=needle):
                self.said.clear()
                self.hub.nodes = {of: change}
                self.left(needle)

    def test_a_persons_commit_taken_before_lands(self) -> None:
        self.hub.open(7, self.hub.branch("topic", "1\n", email="p@example.invalid"))
        self.assertTrue(self.land())

    def test_what_a_green_gate_says_nothing_of_is_read_first(self) -> None:
        for rel in (".github/workflows/x.yml", ".pre-commit-config.yaml"):
            with self.subTest(rel=rel):
                self.said.clear()
                head = self.hub.branch("topic", "1\n", rel=rel)
                self.hub.open(7, head)
                self.left(f"{rel}: a green ✅ Check proves nothing about it")
                self.assertIn(f"--read {head}", self.said[0])
                self.said.clear()
                self.left("proves nothing", read="f" * 40)
        self.assertTrue(self.land(read=head))

    def test_a_file_that_left_github_is_read_too(self) -> None:
        moved = [{"filename": "ci.yml", "previous_filename": ".github/workflows/ci.yml"}]
        with mock.patch.object(self.hub, "files", return_value=moved):
            self.left(".github/workflows/ci.yml: a green")
        same = [{"filename": "a", "previous_filename": None}, {"filename": "x/.github/y"}]
        with mock.patch.object(self.hub, "files", return_value=same):
            self.assertTrue(self.land())

    def test_red_checks_leave_it(self) -> None:
        self.hub.runs = [{**CI, "conclusion": "failure"}]
        self.left("failing: CI")
        self.assertEqual(self.slept, [])

    def test_the_gate_is_among_them(self) -> None:
        self.hub.checks = []
        self.left(f"no {fast_forward.GATE} of GitHub Actions")

    def test_a_commit_status_counts(self) -> None:
        for status, needle in (
            ({"total_count": 1, "state": "failure"}, "failing: a commit status"),
            ({"total_count": 1, "state": "error"}, "failing: a commit status"),
            ({"total_count": 1, "state": "pending"}, "pending"),
        ):
            with self.subTest(status=status):
                self.said.clear()
                self.hub.status = status
                self.left(needle)
        self.hub.status = {"total_count": 1, "state": "success"}
        self.assertTrue(self.land())

    def test_a_status_never_outweighs_a_red_run(self) -> None:
        self.hub.status = {"total_count": 1, "state": "pending"}
        self.hub.runs = [{**CI, "conclusion": "failure"}]
        self.left("failing: CI")

    def test_more_than_is_read_is_no_pass(self) -> None:
        for of in ("runs", "checks"):
            self.said.clear()
            self.hub.more = {of: fast_forward.PAGE + 1}
            self.left("failing: more ran on it than is read")
        self.hub.more = {"runs": fast_forward.PAGE, "checks": fast_forward.PAGE}
        self.assertTrue(self.land())

    def test_it_waits_for_the_checks_of_that_head(self) -> None:
        self.hub.runs = []
        self.later = [lambda: None, lambda: setattr(self.hub, "runs", [dict(CI)])]
        self.assertTrue(self.land())
        self.assertEqual(self.slept, [fast_forward.POLL_SECONDS] * 2)

    def test_it_does_not_wait_for_ever(self) -> None:
        self.hub.runs = []
        for bound, polls in ((20, 1), (21, 2), (40, 2), (41, 3)):
            self.slept.clear()
            self.said.clear()
            with mock.patch.object(fast_forward, "WAIT_SECONDS", bound):
                self.left("pending")
            self.assertEqual(self.slept, [fast_forward.POLL_SECONDS] * polls)

    def test_a_branch_that_moved_while_it_waited_is_left(self) -> None:
        self.hub.runs = []
        other = self.hub.branch("other", "9\n")

        def moved() -> None:
            self.hub.runs = [dict(CI)]
            self.hub.open(7, other)

        self.later = [moved]
        self.left("its branch moved meanwhile")

    def test_a_main_that_moved_while_it_waited_is_seen(self) -> None:
        self.hub.runs = []
        other = self.hub.branch("other", "9\n")

        def moved() -> None:
            self.hub.runs = [dict(CI)]
            self.hub.git("update-ref", "refs/heads/main", other)

        self.later = [moved]
        before = self.land()
        self.assertFalse(before)
        self.assertIn("it is not on top of main", self.said[0])
        self.assertEqual((self.hub.main(), self.git.pushes()), (other, []))

    def test_a_main_that_moved_at_the_last_moment_refuses_the_push(self) -> None:
        other = self.hub.branch("other", "9\n")
        self.git.before["push"] = lambda: self.hub.git("update-ref", "refs/heads/main", other)
        with self.assertRaisesRegex(fast_forward.GitError, "rejected|fetch first"):
            self.land()
        self.assertEqual((self.hub.main(), self.said), (other, []))

    def test_it_is_confirmed(self) -> None:
        self.hub.never_merged = True
        self.later = [lambda: None, lambda: setattr(self.hub, "never_merged", False)]
        self.assertTrue(self.land())
        self.assertEqual(self.slept, [fast_forward.POLL_SECONDS] * 2)

    def test_one_github_never_says_is_merged_is_an_error(self) -> None:
        self.hub.never_merged = True
        with self.assertRaisesRegex(fast_forward.ApiError, "pushed, and GitHub does not say"):
            self.land()
        self.assertEqual(len(self.slept), fast_forward.CONFIRM_TRIES)

    def test_one_that_was_taken_names_its_original(self) -> None:
        head = self.hub.branch("land/pr-12", "5\n")
        self.hub.open(7, head, "land/pr-12")
        self.assertTrue(self.land())
        self.assertEqual(
            self.said[1],
            f"now #12 of {SLUG} can be closed: it landed as {head[:7]} (Dependabot closes its own)",
        )


class PersonTest(HubCase):
    def setUp(self) -> None:
        super().setUp()
        self.head = self.hub.branch("theirs", "1\n", "2\n", email="p@example.invalid")
        fork = {"full_name": "somebody/boards", "default_branch": "main"}
        self.there = {"sha": self.head, "ref": "main", "repo": fork}
        self.pull = self.hub.open(7, self.head, user=PERSON, head=self.there)

    def left(self, needle: str, read: str = "") -> None:
        self.assertFalse(self.land(read=read))
        self.assertEqual(len(self.said), 1, self.said)
        self.assertRegex(self.said[0], f"^left: {SLUG}#7 Title of 7: .*{re.escape(needle)}")
        self.assertEqual((self.hub.posts, self.git.pushes()), ([], []))

    def test_it_is_taken_on_todays_main_with_its_authorship(self) -> None:
        # main moves meanwhile, in another file
        self.hub.git("update-ref", "refs/heads/main", self.hub.branch("o", "x\n", rel="b.txt"))
        self.assertTrue(self.land())
        self.assertEqual(self.said, [f"taken: {SLUG}#7 Title of 7: https://x/101"])
        ((path, fields),) = self.hub.posts
        self.assertEqual(path, f"repos/{SLUG}/pulls")
        self.assertEqual(
            (fields["title"], fields["head"], fields["base"]),
            ("Title of 7", "land/pr-7", "main"),
        )
        self.assertIn("Lands #7, opened by `somebody`, whose commits keep", fields["body"])
        self.assertNotIn("@", fields["body"])
        taken = self.hub.git(
            "log", "--format=%ae %an %ce %s", "refs/heads/main..refs/heads/land/pr-7"
        )
        self.assertEqual(
            taken.splitlines(),
            [
                f"p@example.invalid Who wrote it {EMAIL} Write 2",
                f"p@example.invalid Who wrote it {EMAIL} Write 1",
            ],
        )
        self.assertEqual(self.hub.git("rev-parse", "refs/heads/land/pr-7~2"), self.hub.main())
        signed = self.git.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(signed), 2)
        self.assertTrue(all(FINGERPRINT in line for line in signed), signed)

    def test_what_was_taken_lands_as_any_other(self) -> None:
        self.land()
        self.assertTrue(self.land(101))
        self.assertEqual(self.hub.main(), self.hub.git("rev-parse", "refs/heads/land/pr-7"))
        self.assertIn("now #7 of", self.said[-1])

    def test_a_dry_run_takes_nothing(self) -> None:
        self.assertFalse(self.land(merge=False))
        self.assertEqual(self.said, [f"would take: {SLUG}#7 Title of 7"])
        self.assertEqual((self.hub.posts, self.git.ran), ([], []))

    def test_a_branch_here_of_somebody_elses_is_taken_too(self) -> None:
        self.hub.open(7, self.head, user=PERSON)
        self.assertTrue(self.land())
        self.assertIn("taken:", self.said[0])

    def test_a_pull_request_that_cannot_land(self) -> None:
        self.hub.open(7, self.head, user=PERSON, head=self.there, draft=True)
        self.left("a draft")

    def test_the_owner_with_another_address_is_not_taken(self) -> None:
        self.hub.logins["p@example.invalid"] = "jmrplens"
        self.left("the author is jmrplens with another address")
        self.assertNotIn("p@example.invalid", self.said[0])

    def test_who_has_no_account_and_the_owner_himself_are_taken(self) -> None:
        for logins in ({}, {"p@example.invalid": "somebody"}):
            self.hub.logins = logins
            self.assertTrue(self.land())
            self.hub.git("update-ref", "-d", "refs/heads/land/pr-7")
        head = self.hub.branch("theirs", "1\n")
        self.hub.logins = {EMAIL: "jmrplens"}
        self.hub.open(7, head, user=PERSON, head={**self.there, "sha": head})
        self.assertTrue(self.land())

    def test_a_merge_is_not_taken(self) -> None:
        merge = [{**self.hub.commits(7)[0], "parents": [{}, {}]}]
        with mock.patch.object(self.hub, "commits", return_value=merge):
            self.left(f"commit {merge[0]['sha'][:7]} is a merge")

    def test_a_message_that_breaks_the_rules_is_not_taken(self) -> None:
        one = self.hub.commits(7)[0]
        for message, taken in (("Added x", False), ("Add " + "x" * 60, True)):
            commits = [{**one, "commit": {**one["commit"], "message": message}}]
            with mock.patch.object(self.hub, "commits", return_value=commits):
                if taken:
                    self.assertTrue(self.land())
                else:
                    self.left("the subject starts with 'Added'")
                    self.said.clear()

    def test_what_a_green_gate_says_nothing_of_is_read_first(self) -> None:
        files = [{"filename": ".github/x"}]
        with mock.patch.object(self.hub, "files", return_value=files):
            self.left(f"--read {self.head}")
            self.assertTrue(self.land(read=self.head))

    def test_its_checks_are_green(self) -> None:
        for runs, needle in (
            ([{**CI, "conclusion": "action_required"}], "failing: CI"),
            ([], "pending"),
        ):
            self.said.clear()
            self.hub.runs = runs
            self.left(needle)
        self.assertEqual(self.slept, [])

    def stopped(self, needle: str) -> None:
        with self.assertRaisesRegex(fast_forward.GitError, needle):
            self.land()
        self.assertEqual((self.hub.posts, self.git.pushes()), ([], []))

    def test_the_identity_here_is_the_owners(self) -> None:
        self.git.email = "x@example.invalid"
        self.stopped(f"git's author here is not {EMAIL}")
        self.git.email = EMAIL
        with mock.patch.dict(os.environ, {"GIT_COMMITTER_EMAIL": "x@example.invalid"}):
            self.stopped("git's committer here is not")

    def test_it_is_taken_once(self) -> None:
        self.land()
        self.git.ran.clear()
        self.hub.posts.clear()
        self.stopped("land/pr-7 exists: land its pull request, or delete it first")

    def test_one_that_moved_is_not_taken(self) -> None:
        other = self.hub.branch("theirs", "9\n")
        self.git.before["fetch"] = lambda: self.hub.git("update-ref", "refs/pull/7/head", other)
        self.stopped("#7 moved meanwhile")

    def test_one_that_does_not_apply_is_not_taken(self) -> None:
        self.hub.git("update-ref", "refs/heads/main", self.hub.branch("o", "x\n"))
        self.stopped("cherry-pick")


class UpdateTest(HubCase):
    """What is taken of Dependabot's is one commit of the owner's."""

    def setUp(self) -> None:
        super().setUp()
        self.head = self.hub.branch("dependabot/x", "1\n", "2\n", email="bot@example.invalid")

    def take(self, title: str) -> list[str]:
        pull = self.hub.open(7, self.head, "dependabot/x", user=BOT, title=title)
        self.assertIsNotNone(self.lander().take(SLUG, {**pull, "merged": False}))
        text = self.hub.git("log", "--format=%ae %ce%n%B", "refs/heads/main..refs/heads/land/pr-7")
        return text.splitlines()

    def test_one_signed_commit(self) -> None:
        self.assertEqual(
            self.take("Bump x from 1.2.0 to 1.3.0"),
            [
                f"{EMAIL} {EMAIL}",
                "Bump x from 1.2.0 to 1.3.0",
                "",
                "Pull request #7 of Dependabot: Bump x from 1.2.0 to 1.3.0",
            ],
        )
        self.assertIn(FINGERPRINT, self.git.log.read_text(encoding="utf-8"))
        self.assertEqual(self.hub.git("show", "refs/heads/land/pr-7:a.txt"), "2")
        fields = self.hub.posts[0][1]
        self.assertEqual(fields["title"], "Bump x from 1.2.0 to 1.3.0")
        self.assertIn("Lands #7, opened by Dependabot, on", fields["body"])

    def test_a_title_too_long_for_a_subject(self) -> None:
        title = "Bump https://example.invalid/some/where from v3.0.0 to 3.1.2 in the hooks group"
        lines = self.take(title)
        self.assertEqual(lines[1:3], ["Take Dependabot's update of #7", ""])
        self.assertEqual(" ".join(lines[3:]), f"Pull request #7 of Dependabot: {title}")
        self.assertTrue(all(len(line) <= 72 for line in lines))
        self.assertEqual(self.hub.posts[0][1]["title"], "Take Dependabot's update of #7")

    def test_one_that_does_not_apply_is_not_taken(self) -> None:
        self.hub.git("update-ref", "refs/heads/main", self.hub.branch("o", "x\n"))
        with self.assertRaisesRegex(fast_forward.GitError, "merge|commit"):
            self.take("Bump x")
        self.assertEqual((self.hub.posts, self.git.pushes()), ([], []))


class KindTest(unittest.TestCase):
    def test_who_opened_it_and_where(self) -> None:
        here = {"full_name": SLUG}
        for user, repo, wanted in (
            (OWNER, here, "own"),
            (OWNER, {"full_name": "jmrplens/boards"}, "person"),
            (OWNER, None, "person"),
            (PERSON, here, "person"),
            (PERSON, {"full_name": "x/boards"}, "person"),
            (BOT, here, "bot"),
            ({"login": "dependabot[bot]", "type": "User"}, here, "person"),
            ({"login": "renovate[bot]", "type": "Bot"}, here, ""),
            ({"login": "jmrplens", "type": "Bot"}, here, ""),
        ):
            pull = {"user": user, "head": {"repo": repo}, "base": {"repo": here}}
            with self.subTest(user=user, repo=repo):
                self.assertEqual(fast_forward.kind(pull, "jmrplens"), wanted)


class CheckStateTest(unittest.TestCase):
    def run_of(self, name: str = "CI", event: str = "pull_request", **more: Any) -> dict[str, Any]:
        return {**CI, "name": name, "event": event, **more}

    def test_the_states(self) -> None:
        ci = self.run_of()
        bot = self.run_of("App", "")
        gate = dict(GATE)
        none = f"no {fast_forward.GATE} of GitHub Actions succeeded on it"
        for workflows, checks, state in (
            ([ci], [gate], "green"),
            ([ci], [bot, gate], "green"),
            ([ci, self.run_of("Docs", conclusion="skipped")], [gate], "green"),
            ([], [bot, gate], "pending"),
            ([self.run_of("CI", "push")], [bot, gate], "pending"),
            ([self.run_of(status="in_progress", conclusion=None)], [gate], "pending"),
            ([ci, self.run_of("B", status="queued", conclusion=None)], [gate], "pending"),
            ([ci], [gate, {**bot, "status": "in_progress", "conclusion": None}], "pending"),
            ([self.run_of(conclusion="failure")], [gate], "failing: CI"),
            ([self.run_of(conclusion="cancelled")], [gate], "failing: CI"),
            ([ci], [gate, {**bot, "conclusion": "timed_out"}], "failing: App"),
            ([self.run_of(conclusion="action_required")], [gate], "failing: CI"),
            ([self.run_of(conclusion="skipped")], [bot], none),
            ([ci], [], none),
            ([ci], [bot], none),
            ([ci], [{**gate, "conclusion": "skipped"}], none),
            ([ci], [{**gate, "conclusion": "neutral"}, gate], none),
            ([ci], [{**gate, "conclusion": "failure"}], f"failing: {fast_forward.GATE}"),
            ([ci], [{**gate, "name": "✅ Check "}], none),
            ([ci], [{**gate, "app": {"id": 1}}], none),
            ([ci], [{**gate, "app": None}], none),
            ([ci], [gate, {**gate, "app": {"id": 1}, "conclusion": "skipped"}], "green"),
            ([ci, self.run_of("D", "push", conclusion="neutral")], [gate], "green"),
        ):
            with self.subTest(state=state, workflows=workflows, checks=checks):
                self.assertEqual(fast_forward.check_state(workflows, checks), state)

    def test_the_gate_is_the_kits(self) -> None:
        self.assertEqual(fast_forward.GATE, run_form.GATE)
        self.assertEqual(fast_forward.ACTIONS_APP, 15368)


class PagesTest(unittest.TestCase):
    def pages(self, *sizes: int) -> tuple[list[dict[str, Any]], list[str]]:
        asked: list[str] = []

        class Paged(fast_forward.Api):
            def get(self, path: str) -> Any:
                if path == "user":
                    return {"login": "x"}
                asked.append(path)
                return [{"n": len(asked)}] * sizes[len(asked) - 1]

        lander = fast_forward.Lander(Paged(), fast_forward.Git(), False)
        return lander.pages("p"), asked

    def test_every_page_is_read(self) -> None:
        found, asked = self.pages(100, 100, 3)
        self.assertEqual((len(found), found[-1]), (203, {"n": 3}))
        self.assertEqual(asked, [f"p?per_page=100&page={n}" for n in (1, 2, 3)])
        self.assertEqual(len(self.pages(100, 0)[0]), 100)
        self.assertEqual(self.pages(99)[1], ["p?per_page=100&page=1"])

    def test_one_too_large_is_an_error(self) -> None:
        with self.assertRaisesRegex(fast_forward.ApiError, "p: too large to read whole"):
            self.pages(*[100] * fast_forward.MAX_PAGES)
        sizes = [100] * (fast_forward.MAX_PAGES - 1) + [99]
        self.assertEqual(len(self.pages(*sizes)[0]), sum(sizes))


class OutsideTest(unittest.TestCase):
    """The commands that reach GitHub."""

    def ran(
        self, call: Any, out: str = "", status: int = 0, err: str = ""
    ) -> tuple[Any, list[str]]:
        done = subprocess.CompletedProcess([], status, out, err)
        with mock.patch.object(subprocess, "run", return_value=done) as run:
            answer = call()
        self.assertEqual(
            run.call_args.kwargs, {"capture_output": True, "text": True, "check": False}
        )
        return answer, list(run.call_args.args[0])

    def test_gh_is_called_with_the_method_and_the_fields(self) -> None:
        api = fast_forward.Api()
        self.assertEqual(
            self.ran(lambda: api.get("repos/x"), '{"x": 1}'),
            ({"x": 1}, ["gh", "api", "--method", "GET", "repos/x"]),
        )
        self.assertEqual(self.ran(lambda: api.get("repos/x"), "[]")[0], [])
        self.assertEqual(self.ran(lambda: api.get("repos/x"), " ")[0], {})
        self.assertEqual(
            self.ran(lambda: api.post("repos/x", {"a": "b", "c": "d"}), "{}")[1],
            ["gh", "api", "--method", "POST", "repos/x", "-f", "a=b", "-f", "c=d"],
        )
        self.assertEqual(
            self.ran(lambda: api.ask("query", {"owner": "o"}), '{"data": {"r": 1}}'),
            ({"r": 1}, ["gh", "api", "graphql", "-f", "query=query", "-f", "owner=o"]),
        )

    def test_a_refusal_is_an_error(self) -> None:
        with self.assertRaisesRegex(fast_forward.ApiError, "^--method POST repos/x: no$"):
            self.ran(lambda: fast_forward.Api().post("repos/x", {"a": "b"}), "", 1, "no\n")

    def test_git_runs_in_the_clone(self) -> None:
        git = fast_forward.Git()
        self.assertEqual(
            self.ran(lambda: git.run(Path("/c"), "push", "origin"), " out\n"),
            ("out", ["git", "-C", "/c", "push", "origin"]),
        )
        clone = ["gh", "repo", "clone", SLUG, "/c", "--", "-q", "--filter=blob:none"]
        self.assertEqual(self.ran(lambda: git.clone(SLUG, Path("/c"))), (None, clone))
        with self.assertRaisesRegex(fast_forward.GitError, "^git -C /c push origin: refused$"):
            self.ran(lambda: git.run(Path("/c"), "push", "origin", "x"), "", 1, "refused\n")

    def test_nothing_here_forces_or_deletes(self) -> None:
        text = (fx.CENTRAL / "tools/fast_forward.py").read_text(encoding="utf-8")
        for word in ('"--force', '"-f", "origin', '"--delete', '"+', '":refs', "--no-verify"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
