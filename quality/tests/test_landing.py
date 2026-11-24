# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""landing.py: each guard refuses the pull request it is there for, and nothing lands past one."""

from __future__ import annotations

import copy
import json
import subprocess
import unittest
from typing import Any
from unittest import mock

from kit_fixtures import ecosystem, landing

SLUG = "kleidos-dev/boards"
HEAD, NEW_HEAD, MAIN = "a" * 40, "b" * 40, "c" * 40
OWNER = "someone"
MESSAGE = (
    "Bump x from 1.2.0 to 1.3.0\n\n---\nupdated-dependencies:\n- dependency-name: x\n"
    "  dependency-version: 1.3.0\n  update-type: version-update:semver-minor\n...\n"
)


def commit(message: str = MESSAGE, **more: Any) -> dict[str, Any]:
    return {
        "sha": HEAD,
        "author": {"login": landing.BOT},
        "committer": {"login": "web-flow"},
        "parents": [{"sha": MAIN}],
        "commit": {"message": message, "verification": {"verified": True, "reason": "valid"}},
        **more,
    }


def pull(**more: Any) -> dict[str, Any]:
    repo = {"full_name": SLUG, "default_branch": "main"}
    return {
        "number": 7,
        "title": "Bump x",
        "draft": False,
        "html_url": "https://x/7",
        "user": {"login": landing.BOT, "type": "Bot"},
        "head": {"sha": HEAD, "repo": dict(repo)},
        "base": {"ref": "main", "repo": dict(repo)},
        **more,
    }


def changed(
    name: str = "requirements.txt", patch: str = "@@\n-x==1\n+x==2", **more: Any
) -> dict[str, Any]:
    return {"filename": name, "status": "modified", "patch": patch, **more}


class RefusalTest(unittest.TestCase):
    def why(
        self,
        of: dict[str, Any] | None = None,
        commits: list[dict[str, Any]] | None = None,
        files: list[dict[str, Any]] | None = None,
    ) -> str:
        return str(
            landing.refusal(
                of or pull(),
                [commit()] if commits is None else commits,
                [changed()] if files is None else files,
                OWNER,
            )
        )

    def test_a_bots_minor_update_is_accepted(self) -> None:
        self.assertEqual(self.why(), "None")

    def test_who_opened_it_and_where_it_is(self) -> None:
        fork = {"full_name": "x/boards", "default_branch": "main"}
        here = {"full_name": SLUG, "default_branch": "main"}
        for of, needle in (
            (pull(user={"login": OWNER, "type": "User"}), "opened by someone"),
            (pull(user={"login": "dependabot", "type": "User"}), "opened by dependabot"),
            (pull(user={"login": landing.BOT, "type": "User"}), "opened by dependabot[bot]"),
            (pull(user={"login": "renovate[bot]", "type": "Bot"}), "opened by renovate"),
            (pull(draft=True), "a draft"),
            (pull(head={"sha": HEAD, "repo": fork}), "not in this repository"),
            (pull(head={"sha": HEAD, "repo": None}), "not in this repository"),
            (pull(base={"ref": "v2", "repo": here}), "against v2, not the default branch"),
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.why(of))

    def test_who_wrote_the_commits(self) -> None:
        unsigned = commit()
        unsigned["commit"]["verification"] = {"verified": False, "reason": "unsigned"}
        for one, needle in (
            (unsigned, "is not signed by GitHub (unsigned)"),
            (commit(author={"login": OWNER}), "is someone's"),
            (commit(author={"login": "coderabbitai[bot]"}), "is coderabbitai[bot]'s"),
            (commit(author=None), "is None's"),
            (commit(committer={"login": OWNER}), "was not made on GitHub (someone)"),
            (commit(committer=None), "was not made on GitHub (None)"),
            (
                commit(author={"login": "app[bot]"}, parents=[{}, {}]),
                "is app[bot]'s",
            ),
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.why(commits=[commit(), one]))
        self.assertIn(f"commit {HEAD[:7]} ", self.why(commits=[unsigned]))

    def test_the_merge_of_its_own_update_is_accepted(self) -> None:
        merge = commit("Merge main", author={"login": OWNER}, parents=[{}, {}])
        self.assertEqual(self.why(commits=[commit(), merge]), "None")
        self.assertIn("is someone's", self.why(commits=[commit("x", author={"login": OWNER})]))

    def test_what_the_files_change(self) -> None:
        sha = "d" * 40
        new = f"+      - uses: a/b@{sha} # v2"
        uses = f"@@ -1 +1 @@\n context: x\n-      - uses: a/b@{HEAD} # v1\n{new}"
        rev = "@@\n-    rev: v3.0.0\n+    rev: v3.1.0"
        uses_line, other_line = (f"  - uses: {name}@{sha} # uses: a/b@x" for name in ("a/b", "c/d"))
        for one, needle in (
            (changed(), "None"),
            (changed("a/package-lock.json", patch=""), "None"),
            (changed("pnpm-lock.yaml"), "None"),
            (changed("quality/requirements-tools.in"), "None"),
            (changed(".github/workflows/ci.yml", uses), "None"),
            (changed(".github/workflows/ci.yaml", uses), "None"),
            (changed(".pre-commit-config.yaml", rev), "None"),
            (
                changed(".github/workflows/ci.yml", uses + "\n+      run: evil"),
                "more than a version",
            ),
            (changed(".github/workflows/ci.yml", "@@\n+  uses: a/b@main"), "more than a version"),
            (changed(".github/workflows/ci.yml", rev), "more than a version"),
            (changed(".pre-commit-config.yaml", rev + "\n+    entry: x"), "more than a version"),
            (changed(".pre-commit-config.yaml", uses), "more than a version"),
            (
                changed(".github/workflows/ci.yml", uses.replace(new, new.replace("a/b", "c/d"))),
                "calls another action",
            ),
            (changed(".github/workflows/ci.yml", f"{uses}\n{new}"), "calls another action"),
            (changed(".github/workflows/ci.yml", f"@@\n+{uses_line}\n-{other_line}"), "another"),
            (changed(".github/workflows/ci.yml", ""), "shows no diff"),
            (changed(".github/workflows/run.sh", uses), "neither a manifest"),
            (changed("src/main.py"), "neither a manifest"),
            (changed("README.md"), "neither a manifest"),
            (changed(".github/workflows/x/action.yml/../../y.py"), "neither a manifest"),
            (changed("sub/.pre-commit-config.yaml", rev), "neither a manifest"),
            (changed("requirements.txt", status="added"), "is added"),
            (changed("requirements.txt", status="renamed"), "is renamed"),
        ):
            with self.subTest(file=one["filename"], patch=one["patch"]):
                self.assertIn(needle, self.why(files=[changed(), one]))

    def test_what_the_versions_are(self) -> None:
        def update(*levels: str) -> str:
            return "".join(
                f"- dependency-name: {n}\n  update-type: version-update:semver-{level}\n"
                for n, level in enumerate(levels)
            )

        for message, needle in (
            (update("minor"), "None"),
            (update("patch", "minor", "patch"), "None"),
            (update("major"), "holds a major"),
            (update("patch", "major"), "holds a major"),
            ("Bump x", "does not say"),
            (update("minor") + "- dependency-name: y\n", "does not say"),
            (update("minor") + "  update-type: version-update:semver-minor\n", "does not say"),
            ("", "does not say"),
        ):
            with self.subTest(message=message):
                self.assertIn(needle, self.why(commits=[commit(message)]))

    def test_a_merge_commit_says_nothing_of_the_versions(self) -> None:
        merge = commit(MESSAGE, author={"login": OWNER}, parents=[{}, {}])
        self.assertIn("does not say", self.why(commits=[commit("Bump x"), merge]))

    def test_what_is_too_large_or_empty(self) -> None:
        self.assertIn("too large", self.why(commits=[commit()] * 100))
        self.assertIn("too large", self.why(files=[changed()] * 100))
        self.assertEqual(self.why(commits=[commit()] * 99, files=[changed()] * 99), "None")
        self.assertIn("changes nothing", self.why(files=[]))
        self.assertIn("changes nothing", self.why(commits=[]))


class CheckStateTest(unittest.TestCase):
    def run_of(self, name: str = "CI", event: str = "pull_request", **more: Any) -> dict[str, Any]:
        done = {"status": "completed", "conclusion": "success"}
        return {"name": name, "event": event, **done, **more}

    def test_the_states(self) -> None:
        ci = self.run_of()
        bot = self.run_of("App", "")
        for workflows, checks, state in (
            ([ci], [], "green"),
            ([ci], [bot], "green"),
            ([ci, self.run_of("Docs", conclusion="skipped")], [], "green"),
            ([], [bot], "pending"),
            ([self.run_of("CI", "push")], [], "pending"),
            ([self.run_of(status="in_progress", conclusion=None)], [], "pending"),
            ([ci, self.run_of("B", status="queued", conclusion=None)], [], "pending"),
            ([ci], [{**bot, "status": "in_progress", "conclusion": None}], "pending"),
            ([self.run_of(conclusion="failure")], [], "failing: CI"),
            ([self.run_of(conclusion="cancelled")], [], "failing: CI"),
            ([ci], [{**bot, "conclusion": "timed_out"}], "failing: App"),
            ([self.run_of(conclusion="action_required")], [bot], "failing: CI"),
            ([self.run_of(conclusion="skipped")], [bot], "nothing ran on it"),
            ([ci, self.run_of("D", "push", conclusion="neutral")], [], "green"),
        ):
            with self.subTest(state=state, workflows=workflows, checks=checks):
                self.assertEqual(landing.check_state(workflows, checks), state)


class FakeApi(landing.Api):
    """GitHub as one pull request, its branch a commit behind main."""

    def __init__(self, behind: int = 1) -> None:
        self.behind = behind
        self.pull = pull()
        self.commits = [commit()]
        self.files = [changed()]
        self.runs: list[dict[str, Any]] = [
            {"name": "CI", "event": "pull_request", "status": "completed", "conclusion": "success"}
        ]
        self.puts: list[tuple[str, dict[str, str]]] = []
        self.gets: list[str] = []
        self.later: list[dict[str, Any]] = []
        self.refuse = ""

    def get(self, path: str) -> Any:
        self.gets.append(path)
        if self.refuse and self.refuse in path:
            raise landing.ApiError("refused")
        base = f"repos/{SLUG}"
        if path == "user":
            return {"login": OWNER}
        if path.startswith(f"{base}/pulls?"):
            return [{"number": 7}]
        if path == f"{base}/pulls/7":
            return copy.deepcopy(self.pull)
        if path.startswith(f"{base}/pulls/7/commits"):
            return copy.deepcopy(self.commits)
        if path.startswith(f"{base}/pulls/7/files"):
            return copy.deepcopy(self.files)
        if path == f"{base}/commits/main":
            return {"sha": MAIN}
        if path.startswith(f"{base}/compare/{MAIN}..."):
            return {"behind_by": self.behind}
        if path.startswith(f"{base}/actions/runs?head_sha={self.pull['head']['sha']}"):
            return {"workflow_runs": self.runs}
        if path.startswith(f"{base}/commits/{self.pull['head']['sha']}/check-runs"):
            return {"check_runs": []}
        raise AssertionError(f"not asked for: {path}")

    def put(self, path: str, fields: dict[str, str]) -> Any:
        self.puts.append((path, fields))
        return {}


class LanderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeApi()
        self.said: list[str] = []
        self.slept: list[float] = []

    def sleep(self, seconds: float) -> None:
        """Time passes: GitHub makes the merge commit of an updated branch."""
        self.slept.append(seconds)
        if any("update-branch" in p for p, _f in self.api.puts):
            self.api.pull["head"]["sha"] = NEW_HEAD
        for change in self.api.later[:1]:
            self.api.later.pop(0)
            for name, value in change.items():
                setattr(self.api, name, value)

    def lander(self, merge: bool = True) -> landing.Lander:
        return landing.Lander(self.api, merge, self.sleep, self.said.append)

    def land(self, merge: bool = True, only: list[str] | None = None) -> int:
        declared = ecosystem.load()
        chosen = [SLUG] if only is None else only
        return landing.land(declared, chosen, merge, self.lander(merge))

    def merged(self) -> list[dict[str, str]]:
        return [fields for path, fields in self.api.puts if path.endswith("/merge")]

    def test_it_updates_waits_and_merges_that_head(self) -> None:
        self.assertEqual(self.land(), 0)
        self.assertEqual(
            self.api.puts,
            [
                (f"repos/{SLUG}/pulls/7/update-branch", {"expected_head_sha": HEAD}),
                (f"repos/{SLUG}/pulls/7/merge", {"merge_method": "squash", "sha": NEW_HEAD}),
            ],
        )
        self.assertEqual(self.said, [f"landed: {SLUG}#7 Bump x: https://x/7"])

    def test_a_branch_on_todays_main_is_not_updated(self) -> None:
        self.api.behind = 0
        self.land()
        self.assertEqual(self.merged(), [{"merge_method": "squash", "sha": HEAD}])
        self.assertEqual(len(self.api.puts), 1)

    def test_without_merge_it_only_says(self) -> None:
        self.assertEqual(self.land(merge=False), 0)
        self.assertEqual(self.api.puts, [])
        self.assertEqual(self.said, [f"would land: {SLUG}#7 Bump x"])

    def test_a_guard_that_fails_leaves_it(self) -> None:
        self.api.files = [changed("src/x.py")]
        self.land()
        self.assertEqual(self.api.puts, [])
        self.assertIn("neither a manifest", self.said[0])

    def test_a_red_run_leaves_it(self) -> None:
        self.api.runs[0]["conclusion"] = "failure"
        self.land()
        self.assertEqual(self.merged(), [])
        self.assertEqual(self.said, [f"left: {SLUG}#7 Bump x: failing: CI"])

    def test_it_waits_for_the_run_to_end(self) -> None:
        running: list[dict[str, Any]] = [
            {**self.api.runs[0], "status": "in_progress", "conclusion": None}
        ]
        done = self.api.runs
        self.api.runs = running
        self.api.later = [{}, {}, {"runs": done}]
        self.land()
        self.assertEqual(len(self.merged()), 1)
        self.assertEqual(self.slept, [landing.POLL_SECONDS] * 3)

    def test_it_does_not_wait_for_ever(self) -> None:
        self.api.runs = []
        self.land()
        self.assertEqual(self.merged(), [])
        self.assertEqual(self.said, [f"left: {SLUG}#7 Bump x: pending"])
        self.assertEqual(sum(self.slept), landing.WAIT_SECONDS)

    def test_a_branch_that_never_updates_is_left(self) -> None:
        with mock.patch.object(self, "sleep", self.slept.append):
            self.land()
        self.assertEqual(self.merged(), [])
        self.assertIn("pending", self.said[0])

    def test_what_changed_while_it_waited_is_judged_again(self) -> None:
        self.api.later = [{"commits": [commit(), commit("x", author={"login": "app[bot]"})]}]
        self.land()
        self.assertEqual(self.merged(), [])
        self.assertIn("is app[bot]'s", self.said[0])

    def test_a_branch_that_moves_after_its_run_is_left(self) -> None:
        lander = self.lander()
        with mock.patch.object(lander, "fresh", return_value=("f" * 40, "green")):
            self.assertFalse(lander.land(SLUG, self.api.pull))
        self.assertEqual(self.api.puts, [])
        self.assertIn("moved meanwhile", self.said[0])

    def test_the_kit_the_held_and_the_leaving_are_never_walked(self) -> None:
        declared = ecosystem.load()
        self.land(
            only=[r.slug for r in declared.repositories if r.hold or r.folds_into] + [declared.kit]
        )
        self.assertEqual(self.api.gets, ["user"])
        self.assertEqual(self.api.puts, [])
        said = "\n".join(self.said)
        self.assertIn(f"skipped: {declared.kit}: the kit's releases are made by hand", said)
        self.assertIn("skipped: jmrplens/kleidos: on hold", said)
        self.assertIn("skipped: kleidos-dev/social: it moves into kleidos-dev/brand", said)

    def test_what_it_says_it_merged(self) -> None:
        for change, merge, landed in (
            ({}, True, True),
            ({}, False, False),
            ({"files": [changed("src/x.py")]}, True, False),
            ({"runs": [{**self.api.runs[0], "conclusion": "failure"}]}, True, False),
        ):
            self.api = FakeApi()
            for name, value in change.items():
                setattr(self.api, name, value)
            self.assertIs(self.lander(merge).land(SLUG, self.api.pull), landed, change)

    def test_a_refused_request_stops_that_repository(self) -> None:
        self.api.refuse = "/pulls?"
        self.assertEqual(self.land(), 1)
        self.assertEqual(self.said, [f"stopped: {SLUG}: refused"])


class ApiTest(unittest.TestCase):
    def call(self, done: subprocess.CompletedProcess[str]) -> tuple[Any, list[str]]:
        with mock.patch.object(subprocess, "run", return_value=done) as run:
            return landing.Api().put("repos/x", {"a": "b"}), list(run.call_args.args[0])

    def test_gh_is_called_with_the_method_and_the_fields(self) -> None:
        answer, cmd = self.call(subprocess.CompletedProcess([], 0, json.dumps({"x": 1}), ""))
        self.assertEqual(answer, {"x": 1})
        self.assertEqual(cmd, ["gh", "api", "--method", "PUT", "repos/x", "-f", "a=b"])
        self.assertEqual(self.call(subprocess.CompletedProcess([], 0, " ", ""))[0], {})
        done = subprocess.CompletedProcess([], 0, "[]", "")
        with mock.patch.object(subprocess, "run", return_value=done) as run:
            self.assertEqual(landing.Api().get("repos/x"), [])
        self.assertEqual(run.call_args.args[0], ["gh", "api", "--method", "GET", "repos/x"])
        flags = {"capture_output": True, "text": True, "check": False}
        self.assertEqual(run.call_args.kwargs, flags)

    def test_a_refusal_is_an_error(self) -> None:
        with self.assertRaisesRegex(landing.ApiError, "PUT repos/x: no"):
            self.call(subprocess.CompletedProcess([], 1, "", "no\n"))


if __name__ == "__main__":
    unittest.main()
