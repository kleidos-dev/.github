# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""No step that holds a secret, or a token that can write, follows a third party's code.

Code that ran earlier in a job reaches the steps after it: it can write the
files GitHub reads between steps (GITHUB_ENV, GITHUB_PATH), the workspace and
the tools' folders. So in a job with something to lose, every step is one of
those listed here: an action of GitHub's or Sonar's at a commit, or a script
of the kit's own, named with the reason it is safe.
"""

from __future__ import annotations

import copy
import json
import unittest
from typing import Any

import expressions as ex
import kit_fixtures as fx
import yaml

WORKFLOWS = fx.CENTRAL / ".github" / "workflows"
ACTIONS = {
    "actions/checkout": "GitHub's own, which leaves no credential behind",
    "actions/setup-python": "GitHub's own",
    "actions/download-artifact": "GitHub's own; what it brings is read as data",
    "SonarSource/sonarqube-auth-action": "exchanges the job's own OIDC token, the job's purpose",
    "SonarSource/sonarqube-scan-action": "the analysis the token is for",
}
# What each action may be told in such a job, and what it must be told. An
# input is code too: a checkout of another ref or repository, a token left
# behind, a cache that restores what another run saved.
WITH: dict[str, tuple[frozenset[str], dict[str, Any]]] = {
    "actions/checkout": (
        frozenset({"persist-credentials", "fetch-depth"}),
        {"persist-credentials": False},
    ),
    "actions/setup-python": (frozenset({"python-version"}), {}),
    "actions/download-artifact": (frozenset({"name", "path", "run-id", "github-token"}), {}),
    "SonarSource/sonarqube-auth-action": (frozenset(), {}),
    "SonarSource/sonarqube-scan-action": (frozenset(), {}),
}
# The environment an action step may set: the server it is sent to, fixed.
ACTION_ENV = {"SONAR_HOST_URL": "https://sonarcloud.io"}
# The one place the running kit's folder comes from: the step that fetched it.
KIT_DIR = "${{ steps.kit.outputs.dir }}"
SCRIPTS = {
    "The kit this workflow is part of": "git and the kit's own commit",
    "Install the kit's tools (hashed)": "pip checks every package against its SHA-256",
    "The hooks that read the deny-list": "the caller's own hooks, which install nothing",
    "Post, update or remove the comment": "the kit's checker; the artifact is data",
    "OIDC token available": "the event's own fields",
    "SonarCloud accepted the analysis": "curl and jq on Sonar's answer",
}
HASHED = 'python -I -m pip install --require-hashes -r "${KIT}/quality/requirements-tools.txt"'


def holds(thing: Any) -> bool:
    """Whether a step, or an env, names a secret."""
    return "secrets." in json.dumps(thing)


def to_lose(workflow: dict[Any, Any], job: dict[str, Any]) -> bool:
    """Whether a job holds a secret, or a token that can write or buy another."""
    granted = job.get("permissions", workflow.get("permissions"))
    writes = granted == "write-all" or (isinstance(granted, dict) and "write" in granted.values())
    steps = job.get("steps") or []
    return writes or any(holds(step) for step in steps) or holds(job.get("env"))


def leaks(workflow: dict[Any, Any]) -> list[str]:
    """The steps of a workflow that a secret, or a token that can write, is not safe beside."""
    out = []
    if holds(workflow.get("env")) or holds(workflow.get("defaults")):
        out.append("the workflow's env names a secret, for every step of every job")
    for job_id, job in workflow["jobs"].items():
        if "uses" in job:
            if job.get("secrets") == "inherit":
                out.append(f"{job_id}: inherits every secret")
            continue
        if not to_lose(workflow, job):
            continue
        for_all = [k for k in ("env", "defaults", "container", "services") if k in job]
        out += [f"{job_id}: sets {key} for every step" for key in for_all]
        steps = job["steps"]
        for index, step in enumerate(steps):
            name = str(step.get("name") or step.get("uses"))
            if holds(step) and index != len(steps) - 1:
                out.append(f"{job_id}: {name} holds a secret and is not the last step")
            if "uses" in step:
                action, _at, ref = str(step["uses"]).partition("@")
                if action not in ACTIONS or len(ref) != 40:
                    out.append(f"{job_id}: {name} is not an action listed here")
                else:
                    out += [f"{job_id}: {name} {why}" for why in told(action, step)]
            elif name not in SCRIPTS:
                out.append(f"{job_id}: {name} is not a script listed here")
            elif "hashed" in name and step["run"] != HASHED:
                out.append(f"{job_id}: {name} installs more than the kit's hashed tools")
            kit = (step.get("env") or {}).get("KIT")
            if kit is not None and kit != KIT_DIR:
                out.append(
                    f"{job_id}: {name} takes the kit from {kit}, not from the step that fetched it"
                )
    return out


def told(action: str, step: dict[str, Any]) -> list[str]:
    """What is wrong with what an action step is told (its with: and its env)."""
    allowed, required = WITH[action]
    given = step.get("with") or {}
    out = [f"is told {key}" for key in sorted(set(given) - allowed)]
    out += [
        f"is not told {key}: {value!r}"
        for key, value in required.items()
        if given.get(key) is not value
    ]
    out += [
        f"is given {key} in its environment"
        for key, value in (step.get("env") or {}).items()
        if ACTION_ENV.get(key) != value
    ]
    return out


class IsolationTest(unittest.TestCase):
    def test_no_workflow_leaks(self) -> None:
        found = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
            found += [f"{path.name}: {line}" for line in leaks(workflow)]
        self.assertEqual(found, [])

    def test_the_jobs_with_something_to_lose_are_three(self) -> None:
        found = set()
        for path in WORKFLOWS.glob("*.yml"):
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
            for job_id, job in workflow["jobs"].items():
                if "uses" not in job and to_lose(workflow, job):
                    found.add((path.name, job_id))
        self.assertEqual(
            found,
            {
                ("reusable-deny.yml", "deny"),
                ("reusable-sonarcloud.yml", "sonarcloud"),
                ("reusable-commit-check-comment.yml", "comment"),
            },
        )

    def test_every_listed_step_exists(self) -> None:
        text = "".join(p.read_text(encoding="utf-8") for p in WORKFLOWS.glob("reusable-*.yml"))
        for name in (*ACTIONS, *SCRIPTS):
            self.assertIn(name, text)


class PlantedTest(unittest.TestCase):
    """Each way a secret could come to follow a third party's code."""

    def setUp(self) -> None:
        text = (WORKFLOWS / "reusable-deny.yml").read_text(encoding="utf-8")
        self.deny = yaml.safe_load(text)

    def leak(self, index: int, step: dict[str, Any] | None = None, **job: Any) -> list[str]:
        planted = copy.deepcopy(self.deny)
        if step is not None:
            planted["jobs"]["deny"]["steps"].insert(index, step)
        planted["jobs"]["deny"].update(job)
        return leaks(planted)

    def test_the_real_one_is_clean(self) -> None:
        self.assertEqual(leaks(self.deny), [])

    def test_a_planted_step_is_found_wherever_it_is(self) -> None:
        sha = "a" * 40
        for step in (
            {"name": "Every hook", "run": "pre-commit run --all-files"},
            {"run": "npm ci"},
            {"name": "Install the kit's tools (hashed)", "run": "pip install pre-commit"},
            {"name": "Cache", "uses": f"actions/cache@{sha}"},
            {"uses": f"evil/action@{sha}"},
            {"uses": "actions/checkout@main"},
            {"uses": "./.github/actions/x"},
        ):
            last = len(self.deny["jobs"]["deny"]["steps"])
            for index in range(last + 1):
                with self.subTest(step=step, index=index):
                    # After the last step, the secret's step is not the last any more.
                    self.assertEqual(len(self.leak(index, step)), 1 + (index == last))

    def test_a_planted_environment_is_found(self) -> None:
        for job in (
            {"env": {"BASH_ENV": "planted"}},
            {"env": {"A": "${{ secrets.deny }}"}},
            {"defaults": {"run": {"shell": "x {0}"}}},
            {"container": "evil/image"},
            {"services": {"x": {"image": "evil"}}},
        ):
            self.assertEqual(len(self.leak(0, None, **job)), 1, job)
        planted = copy.deepcopy(self.deny)
        planted["env"] = {"A": "${{ secrets.deny }}"}
        self.assertEqual(len(leaks(planted)), 1)

    def test_a_secret_in_a_job_of_hooks_is_found(self) -> None:
        lint = yaml.safe_load((WORKFLOWS / "reusable-lint.yml").read_text(encoding="utf-8"))
        self.assertEqual(leaks(lint), [])
        lint["jobs"]["lint"]["steps"][-1]["env"]["DENY"] = "${{ secrets.deny }}"
        self.assertTrue(any("Every pre-commit hook" in line for line in leaks(lint)))

    def test_a_token_that_can_write_is_something_to_lose(self) -> None:
        lint = yaml.safe_load((WORKFLOWS / "reusable-lint.yml").read_text(encoding="utf-8"))
        for granted in ({"contents": "write"}, {"id-token": "write"}, "write-all"):
            lint["jobs"]["lint"]["permissions"] = granted
            self.assertTrue(leaks(lint), granted)
        del lint["jobs"]["lint"]["permissions"]
        lint["permissions"] = {"contents": "write"}
        self.assertTrue(leaks(lint))

    def test_inherited_secrets_are_found(self) -> None:
        quick = yaml.safe_load((WORKFLOWS / "quick.yml").read_text(encoding="utf-8"))
        self.assertEqual(leaks(quick), [])
        quick["jobs"]["deny"]["secrets"] = "inherit"
        self.assertEqual(leaks(quick), ["deny: inherits every secret"])

    def test_what_an_action_is_told_is_found(self) -> None:
        """An input is code too: each of these turns the deny job into another job."""
        for where, key, value in (
            (0, "persist-credentials", True),
            (0, "ref", "${{ github.event.pull_request.head.sha }}"),
            (0, "repository", "evil/fork"),
            (0, "token", "${{ github.token }}"),
            (2, "cache", "pip"),
            (2, "python-version-file", ".python-version"),
        ):
            with self.subTest(key=key):
                planted = copy.deepcopy(self.deny)
                planted["jobs"]["deny"]["steps"][where].setdefault("with", {})[key] = value
                self.assertEqual(len(leaks(planted)), 1, leaks(planted))
        planted = copy.deepcopy(self.deny)
        del planted["jobs"]["deny"]["steps"][0]["with"]["persist-credentials"]
        checkout = f"actions/checkout@{ACTION_REF[0]}"
        self.assertEqual(
            leaks(planted), [f"deny: {checkout} is not told persist-credentials: False"]
        )
        planted = copy.deepcopy(self.deny)
        planted["jobs"]["deny"]["steps"][2]["env"] = {"PIP_INDEX_URL": "https://evil.invalid"}
        self.assertEqual(len(leaks(planted)), 1)

    def test_a_secret_before_the_last_step_is_found(self) -> None:
        for index in range(len(self.deny["jobs"]["deny"]["steps"]) - 1):
            with self.subTest(index=index):
                planted = copy.deepcopy(self.deny)
                step = planted["jobs"]["deny"]["steps"][index]
                step.setdefault("env", {})["KLEIDOS_DENY_EXTRA"] = "${{ secrets.deny }}"
                self.assertTrue(any("not the last step" in line for line in leaks(planted)))

    def test_the_kit_comes_only_from_the_step_that_fetched_it(self) -> None:
        for kit in ("${{ github.workspace }}", ".", "${{ inputs.kit }}", ""):
            with self.subTest(kit=kit):
                planted = copy.deepcopy(self.deny)
                planted["jobs"]["deny"]["steps"][-1]["env"]["KIT"] = kit
                self.assertTrue(any("takes the kit from" in line for line in leaks(planted)))

    def test_the_job_reads_and_nothing_more(self) -> None:
        self.assertEqual(self.deny["jobs"]["deny"]["permissions"], {"contents": "read"})
        self.assertEqual(self.deny["permissions"], {})
        self.assertNotIn("continue-on-error", self.deny["jobs"]["deny"])
        self.assertNotIn("if", self.deny["jobs"]["deny"])


ACTION_REF = [
    str(step["uses"]).partition("@")[2]
    for step in yaml.safe_load((WORKFLOWS / "reusable-deny.yml").read_text(encoding="utf-8"))[
        "jobs"
    ]["deny"]["steps"]
    if "uses" in step
]


class EveryKitTest(unittest.TestCase):
    """Rules of every kit workflow, not only of the jobs with something to lose."""

    def test_every_step_takes_the_kit_from_the_step_that_fetched_it(self) -> None:
        # The 2.x drift job compares two kits and names them itself; it goes with kit 3.1.
        found = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            if path.name == "reusable-quality-drift.yml":
                continue
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
            for job_id, job in workflow["jobs"].items():
                for step in job.get("steps") or []:
                    kit = (step.get("env") or {}).get("KIT")
                    if kit is not None and kit != KIT_DIR:
                        found.append(f"{path.name} {job_id}: {step.get('name')}: {kit}")
        self.assertEqual(found, [])


def context(**given: Any) -> dict[str, Any]:
    """The contexts a condition reads, every one present and empty unless given."""
    return {"inputs": {}, "secrets": {}, "github": {}, "steps": {}, **given}


class ConditionTest(unittest.TestCase):
    """The conditions that decide what runs, run: by what they decide, not by their words."""

    def setUp(self) -> None:
        self.quick = yaml.safe_load((WORKFLOWS / "quick.yml").read_text(encoding="utf-8"))
        self.deny = yaml.safe_load((WORKFLOWS / "reusable-deny.yml").read_text(encoding="utf-8"))

    def test_the_deny_job_runs_exactly_where_there_are_hooks(self) -> None:
        condition = self.quick["jobs"]["deny"]["if"]
        for hooks, wanted in (("", False), ("my-hook", True), ("a,b", True), ("0", True)):
            with self.subTest(hooks=hooks):
                given = context(inputs={"deny-hooks": hooks, "skip": ""})
                self.assertIs(ex.runs(condition, given), wanted)

    def test_the_commits_job_runs_on_every_pull_request_and_only_there(self) -> None:
        condition = self.quick["jobs"]["commits"]["if"]
        for event, wanted in (
            ("pull_request", True),
            ("push", False),
            ("schedule", False),
            ("workflow_dispatch", False),
            ("pull_request_target", False),
            ("merge_group", False),
        ):
            with self.subTest(event=event):
                self.assertIs(ex.runs(condition, context(github={"event_name": event})), wanted)

    def test_the_other_quick_jobs_always_run(self) -> None:
        conditional = {job_id for job_id, job in self.quick["jobs"].items() if "if" in job}
        self.assertEqual(conditional, {"deny", "commits"})

    def test_the_deny_list_is_optional_only_when_no_secret_came(self) -> None:
        value = self.deny["jobs"]["deny"]["steps"][-1]["env"]["KLEIDOS_DENY_OPTIONAL"]
        for secret, wanted in (("", "1"), (None, "1"), ("a-pattern", "0"), ("0", "0")):
            with self.subTest(secret=secret):
                self.assertEqual(ex.evaluate(value, context(secrets={"deny": secret})), wanted)

    def test_the_comment_is_posted_only_for_a_pull_requests_finished_run(self) -> None:
        name = "reusable-commit-check-comment.yml"
        condition = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))["jobs"][
            "comment"
        ]["if"]
        for event, conclusion, wanted in (
            ("pull_request", "success", True),
            ("pull_request", "failure", True),
            ("pull_request", "cancelled", False),
            ("pull_request", "skipped", False),
            ("pull_request", "", False),
            ("push", "success", False),
            ("push", "failure", False),
            ("pull_request_target", "failure", False),
        ):
            with self.subTest(event=event, conclusion=conclusion):
                run = {"event": event, "conclusion": conclusion}
                given = context(github={"event": {"workflow_run": run}})
                self.assertIs(ex.runs(condition, given), wanted)


class ExpressionTest(unittest.TestCase):
    """The reader the conditions are run with, on GitHub's own rules."""

    def test_its_rules(self) -> None:
        given = context(inputs={"a": "X", "n": 0, "e": ""})
        for text, wanted in (
            ("inputs.a == 'x'", True),
            ("inputs.a != 'x'", False),
            ("inputs.e == ''", True),
            ("inputs.missing == ''", True),
            ("inputs.missing == 0", True),
            ("inputs.n == ''", True),
            ("inputs.a == 0", False),
            ("inputs.e && 'yes' || 'no'", "no"),
            ("inputs.a && 'yes' || 'no'", "yes"),
            ("!inputs.e", True),
            ("!(inputs.a == 'X') || false", False),
            ("${{ true && null }}", None),
            ("'it''s'", "it's"),
            ("1 == 1.0", True),
            ("true == 1", True),
        ):
            with self.subTest(text=text):
                self.assertEqual(ex.evaluate(text, given), wanted)

    def test_what_it_does_not_read_is_refused(self) -> None:
        for text in ("always()", "inputs.a[0]", "inputs.a < 'b'", "(inputs.a", "inputs.a ==", "@"):
            with self.subTest(text=text), self.assertRaises(ex.ExpressionError):
                ex.evaluate(text, context())


if __name__ == "__main__":
    unittest.main()
