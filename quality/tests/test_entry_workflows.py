# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""The kit's own workflows: what they may do, the kit they fetch, and the gate's script."""

from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

import kit_fixtures as fx
import yaml
from kit_fixtures import check_quality as cq
from kit_fixtures import run_form as rf

WORKFLOWS = fx.CENTRAL / ".github" / "workflows"
KIT = cq.DirKit(fx.CENTRAL)


def load(name: str) -> dict[Any, Any]:
    data: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return data


def kit_steps() -> dict[str, dict[str, Any]]:
    """The step that finds the running kit, in each workflow that has one."""
    found = {}
    for path in sorted(WORKFLOWS.glob("reusable-*.yml")):
        for job in load(path.name)["jobs"].values():
            for step in job.get("steps") or []:
                if step.get("id") == "kit":
                    found[path.name] = step
    return found


class EntryTest(unittest.TestCase):
    def test_each_calls_the_workflows_beside_it_and_grants_what_they_take(self) -> None:
        for name in rf.ENTRY:
            data = load(name)
            self.assertEqual(data["permissions"], {}, name)
            self.assertEqual(list(cq.workflow_triggers(data)), ["workflow_call"], name)
            allowed = rf.ALLOWED_PERMISSIONS.get(name, rf.READ_CODE)
            for job_id, job in data["jobs"].items():
                with self.subTest(workflow=name, job=job_id):
                    self.assertRegex(job["uses"], r"^\./\.github/workflows/reusable-[\w-]+\.yml$")
                    self.assertTrue((fx.CENTRAL / job["uses"]).is_file(), job["uses"])
                    self.assertEqual(job["permissions"], allowed)
                    called = load(Path(job["uses"]).name)
                    for inner in called["jobs"].values():
                        self.assertEqual(set(inner["permissions"]) - set(allowed), set())
                    inputs = cq.workflow_triggers(called)["workflow_call"] or {}
                    self.assertEqual(
                        set(job.get("with") or {}) - set(inputs.get("inputs") or {}), set()
                    )

    def test_only_quick_takes_a_secret_and_hands_it_to_the_lint_job_alone(self) -> None:
        for name in rf.ENTRY:
            data = load(name)
            call = cq.workflow_triggers(data)["workflow_call"] or {}
            self.assertEqual(list(call.get("secrets") or {}), ["deny"] if name == rf.QUICK else [])
            handed = {j: job["secrets"] for j, job in data["jobs"].items() if "secrets" in job}
            expected = {"lint": {"deny": "${{ secrets.deny }}"}} if name == rf.QUICK else {}
            self.assertEqual(handed, expected)

    def test_the_secret_reaches_a_hook_of_the_caller_and_no_other_step(self) -> None:
        steps = load("reusable-lint.yml")["jobs"]["lint"]["steps"]
        readers = [s["name"] for s in steps if "secrets." in json.dumps(s)]
        self.assertEqual(readers, ["The repository's hooks that read the deny-list"])
        every = next(s for s in steps if s.get("name") == "Every pre-commit hook on every file")
        self.assertIn("${OWN_HOOKS}", every["run"])
        self.assertIn("inputs.deny-hooks", every["env"]["OWN_HOOKS"])

    def test_the_lint_job_skips_the_hooks_the_policy_checks_replace(self) -> None:
        steps = load("reusable-lint.yml")["jobs"]["lint"]["steps"]
        run = next(s["run"] for s in steps if "SKIP=" in s.get("run", ""))
        skipped = set(re.search(r'SKIP="([^"$]*)', run)[1].split(","))  # type: ignore[index]  # asserted by the next line
        kit_only = {"kleidos-kit", "kleidos-mypy", "reuse", "mypy"}
        self.assertLessEqual(kit_only, skipped)
        third_party = {
            rf.hook_key(h["hook"]) for h in rf.canonical_hooks(KIT, list(cq.KNOWN_PROFILES))
        }
        self.assertEqual(skipped & third_party, {"reuse"})

    def test_no_kit_workflow_can_write_a_check(self) -> None:
        repo = cq.Repo(fx.CENTRAL)
        report = cq.Report()
        rf.check_forgery(rf.workflows(repo), report)
        self.assertEqual(report.problems, [])

    def test_the_weekly_report_reads_and_nothing_else(self) -> None:
        data = load("ecosystem.yml")
        self.assertEqual(data["permissions"], {"contents": "read"})
        self.assertNotIn("secrets.", (WORKFLOWS / "ecosystem.yml").read_text(encoding="utf-8"))
        self.assertNotIn("--all", (WORKFLOWS / "ecosystem.yml").read_text(encoding="utf-8"))


class OwnKitTest(unittest.TestCase):
    """Every job fetches the kit at the commit of the workflow it is in."""

    def test_the_steps_that_find_the_kit_are_one(self) -> None:
        found = kit_steps()
        self.assertEqual(
            sorted(found),
            [
                "reusable-commit-check-comment.yml",
                "reusable-commit-check.yml",
                "reusable-lint.yml",
                "reusable-mypy.yml",
                "reusable-osv.yml",
                "reusable-reuse.yml",
                "reusable-secrets.yml",
            ],
        )
        comment = found.pop("reusable-commit-check-comment.yml")
        first = next(iter(found.values()))
        for name, step in found.items():
            self.assertEqual(step, first, name)
        self.assertEqual(comment["env"], first["env"])

    def run_step(self, env: dict[str, str]) -> tuple[int, str, str]:
        """The step's script with these variables: (status, what it printed, its outputs)."""
        step = kit_steps()["reusable-lint.yml"]
        with tempfile.TemporaryDirectory() as tmp:
            output, summary = Path(tmp) / "output", Path(tmp) / "summary"
            done = subprocess.run(
                ["bash", "-e", "-c", step["run"]],
                capture_output=True,
                text=True,
                check=False,
                env={
                    "PATH": os.environ["PATH"],
                    "GITHUB_OUTPUT": str(output),
                    "GITHUB_STEP_SUMMARY": str(summary),
                    "GITHUB_WORKSPACE": str(fx.CENTRAL),
                    "RUNNER_TEMP": tmp,
                    **env,
                },
            )
            outputs = output.read_text(encoding="utf-8") if output.is_file() else ""
            return done.returncode, done.stdout + done.stderr, outputs

    def test_the_home_is_its_own_kit(self) -> None:
        sha = "c" * 40
        status, said, outputs = self.run_step(
            {
                "KIT_REPO": cq.KIT_REPO,
                "KIT_SHA": sha,
                "GITHUB_REPOSITORY": cq.KIT_REPO,
            }
        )
        self.assertEqual(status, 0, said)
        self.assertIn(f"kit v{KIT.version()} ({sha})", said)
        self.assertEqual(outputs, f"dir={fx.CENTRAL}\nsha={sha}\n")

    def test_a_workflow_of_another_repository_stops(self) -> None:
        for home in ("", "someone/.github"):
            status, said, outputs = self.run_step(
                {"KIT_REPO": home, "KIT_SHA": "", "GITHUB_REPOSITORY": cq.KIT_REPO}
            )
            self.assertEqual((status, outputs), (1, ""), said)
            self.assertIn("not kleidos-dev/.github", said)

    def test_the_two_keys_are_read_in_the_way_actionlint_accepts(self) -> None:
        for name, step in kit_steps().items():
            self.assertEqual(
                step["env"],
                {
                    "KIT_REPO": "${{ fromJSON(toJSON(job)).workflow_repository }}",
                    "KIT_SHA": "${{ fromJSON(toJSON(job)).workflow_sha }}",
                },
                name,
            )


@unittest.skipIf(shutil.which("jq") is None, "jq is not installed")
class GateScriptTest(unittest.TestCase):
    """The gate's own script, run: what passes, and everything that must not."""

    def gate(self, results: dict[str, str], may_skip: str | None = None) -> tuple[int, str]:
        script = rf.model_gate(KIT)["steps"][0]["run"]
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "PATH": os.environ["PATH"],
                "GITHUB_STEP_SUMMARY": str(Path(tmp) / "summary"),
                "NEEDS": json.dumps({k: {"result": v, "outputs": {}} for k, v in results.items()}),
            }
            if may_skip is not None:
                env["MAY_SKIP"] = may_skip
            done = subprocess.run(
                ["bash", "-c", script], capture_output=True, text=True, check=False, env=env
            )
            return done.returncode, done.stdout + done.stderr

    def test_every_combination_of_two_results(self) -> None:
        kinds = ("success", "failure", "cancelled", "skipped")
        for one, two in itertools.product(kinds, kinds):
            for may in (None, "", "b", "a b", "ab", "c"):
                with self.subTest(a=one, b=two, may=may):
                    allowed = (may or "").split()
                    fine = all(
                        r == "success" or (r == "skipped" and job in allowed)
                        for job, r in (("a", one), ("b", two))
                    )
                    status, said = self.gate({"a": one, "b": two}, may)
                    self.assertEqual(status == 0, fine, said)
                    self.assertIn(f"a: {one}", said)

    def test_a_gate_with_nothing_to_need_fails(self) -> None:
        self.assertNotEqual(self.gate({})[0], 0)

    def test_a_word_that_is_part_of_a_job_id_gives_no_leave(self) -> None:
        self.assertNotEqual(self.gate({"models": "skipped"}, "model models2")[0], 0)
        self.assertEqual(self.gate({"models": "skipped"}, "a models b")[0], 0)

    def test_a_result_it_does_not_know_fails(self) -> None:
        self.assertNotEqual(self.gate({"a": ""})[0], 0)
        self.assertNotEqual(self.gate({"a": "neutral"}, "a")[0], 0)


if __name__ == "__main__":
    unittest.main()
