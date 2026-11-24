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
SCRIPTS = {
    "The kit this workflow is part of": "git and the kit's own commit",
    "Install the kit's tools (hashed)": "pip checks every package against its SHA-256",
    "The hooks that read the deny-list": "the caller's own hooks, which install nothing",
    "Post, update or remove the comment": "the kit's checker; the artifact is data",
    "OIDC token available": "the event's own fields",
    "SonarCloud accepted the analysis": "curl and jq on Sonar's answer",
}
HASHED = 'python -m pip install --require-hashes -r "${KIT}/quality/requirements-tools.txt"'


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
        for step in job["steps"]:
            name = str(step.get("name") or step.get("uses"))
            if "uses" in step:
                action, _at, ref = str(step["uses"]).partition("@")
                if action not in ACTIONS or len(ref) != 40:
                    out.append(f"{job_id}: {name} is not an action listed here")
            elif name not in SCRIPTS:
                out.append(f"{job_id}: {name} is not a script listed here")
            elif "hashed" in name and step["run"] != HASHED:
                out.append(f"{job_id}: {name} installs more than the kit's hashed tools")
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
            for index in range(len(self.deny["jobs"]["deny"]["steps"]) + 1):
                with self.subTest(step=step, index=index):
                    self.assertEqual(len(self.leak(index, step)), 1)

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


if __name__ == "__main__":
    unittest.main()
