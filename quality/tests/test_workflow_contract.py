# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""The workflows every repository runs: each line pinned with its reason, and each script run.

The first half compares every workflow, parsed, with workflow_contract.yaml,
where each job and each step says why it is as it is. The second half runs
the scripts as GitHub starts them, with the tools they call replaced, and
holds each reason: what must fail the job does.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

import kit_fixtures as fx
import yaml

WORKFLOWS = fx.CENTRAL / ".github" / "workflows"
MODELS = fx.QUALITY / "templates" / "run"
CONTRACT = Path(__file__).resolve().parent / "workflow_contract.yaml"


def workflow(name: str) -> dict[Any, Any]:
    """A workflow, its `on` key as text."""
    folder = fx.CENTRAL if "/" in name else WORKFLOWS
    data = yaml.safe_load((folder / name).read_text(encoding="utf-8"))
    return {("on" if key is True else key): value for key, value in data.items()}


def contract() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return data


def without_reasons(entry: dict[str, Any]) -> dict[str, Any]:
    """A workflow of the contract as the workflow it describes."""
    bare = copy.deepcopy(entry)
    for job in bare["jobs"].values():
        job.pop("why", None)
        for step in job.get("steps") or []:
            step.pop("why", None)
    return bare


class ContractTest(unittest.TestCase):
    maxDiff = None

    def test_every_workflow_is_in_it(self) -> None:
        names = [path.name for path in WORKFLOWS.iterdir()]
        names += [path.relative_to(fx.CENTRAL).as_posix() for path in MODELS.iterdir()]
        self.assertEqual(sorted(contract()), sorted(names))

    def test_every_workflow_is_what_it_says(self) -> None:
        for name, entry in contract().items():
            with self.subTest(workflow=name):
                self.assertEqual(workflow(name), without_reasons(entry))

    def test_every_job_and_step_has_its_reason(self) -> None:
        for name, entry in contract().items():
            for job_id, job in entry["jobs"].items():
                for where, what in [(job_id, job), *enumerate(job.get("steps") or [])]:
                    with self.subTest(workflow=name, job=job_id, where=where):
                        self.assertGreater(len(str(what.get("why", "")).split()), 3)

    def test_nothing_fails_softly(self) -> None:
        """No job forgives itself, and one step does: a result that is not there to post."""
        soft = [
            (name, job_id, step.get("name"))
            for name in contract()
            for job_id, job in workflow(name)["jobs"].items()
            for step in [job, *(job.get("steps") or [])]
            if step.get("continue-on-error")
        ]
        wanted = ("reusable-commit-check-comment.yml", "comment", "Fetch the check's result")
        self.assertEqual(soft, [wanted])

    def test_every_workflow_starts_with_no_permission_or_reads(self) -> None:
        for name in contract():
            self.assertIn(workflow(name)["permissions"], ({}, {"contents": "read"}), name)

    def test_every_third_party_action_is_a_commit(self) -> None:
        for name in contract():
            for job in workflow(name)["jobs"].values():
                for step in job.get("steps") or []:
                    if "uses" in step:
                        self.assertRegex(step["uses"], r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")


class Ran:
    """What a step did: its status, what it said, its outputs, and the calls of the fakes."""

    def __init__(self, status: int, said: str, output: str, summary: str, calls: list[str]) -> None:
        self.status, self.said, self.output = status, said, output
        self.summary, self.calls = summary, calls


class ScriptCase(unittest.TestCase):
    """A step's script, as GitHub starts it, with the tools it calls replaced."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.cwd = self.tmp / "work"
        self.cwd.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def fake(self, name: str, status: int = 0, out: str = "", body: str = "") -> None:
        """A command that logs its arguments, says something and exits so."""
        path = self.bin / name
        path.write_text(
            f'#!/bin/bash\necho "{name} $*" >> "{self.tmp}/calls"\n{body}\n'
            f"cat <<'OUT'\n{out}\nOUT\nexit {status}\n",
            encoding="utf-8",
        )
        path.chmod(0o755)

    def step(self, name: str, title: str) -> dict[str, Any]:
        found = [
            step
            for job in workflow(name)["jobs"].values()
            for step in job.get("steps") or []
            if step.get("name") == title
        ]
        self.assertEqual(len(found), 1, (name, title))
        return dict(found[0])

    def run_step(self, name: str, title: str, **env: str) -> Ran:
        step = self.step(name, title)
        script = self.tmp / "script.sh"
        script.write_text(step["run"], encoding="utf-8")
        for rel in ("calls", "output", "summary"):
            (self.tmp / rel).write_text("", encoding="utf-8")
        done = subprocess.run(
            ["bash", "-e", str(script)],
            cwd=self.cwd,
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "HOME": str(self.tmp),
                "RUNNER_TEMP": str(self.tmp),
                "GITHUB_OUTPUT": str(self.tmp / "output"),
                "GITHUB_STEP_SUMMARY": str(self.tmp / "summary"),
                "GITHUB_PATH": str(self.tmp / "path"),
                "KIT": "/kit",
                **env,
            },
        )
        output, summary, calls = (
            (self.tmp / rel).read_text(encoding="utf-8") for rel in ("output", "summary", "calls")
        )
        said = done.stdout + done.stderr
        return Ran(done.returncode, said, output, summary, calls.splitlines())


class VerdictTest(ScriptCase):
    """A tool's verdict is the step's, whatever the tool exits with."""

    def test_each_tool_decides(self) -> None:
        gitleaks = "--no-banner --redact --ignore-gitleaks-allow --verbose"
        policy = "/kit/quality/policy.py"
        for name, title, tool, env, call in (
            (
                "reusable-lint.yml",
                "The kit's policy checks",
                "python",
                {"OWN_HOOKS": "a,b", "KIT_SHA": "s", "GITHUB_STEP_SUMMARY": "S", "BASE": "b"},
                f"python {policy} --without spdx-headers --lint-skip a,b --github --summary S"
                " --kit-sha s --base b",
            ),
            (
                "reusable-lint.yml",
                "zizmor, online audits included",
                "zizmor",
                {},
                "zizmor --no-progress .",
            ),
            (
                "reusable-reuse.yml",
                "Every file states its copyright and license (reuse lint)",
                "reuse",
                {},
                "reuse lint",
            ),
            (
                "reusable-reuse.yml",
                "Every file that can carry a comment carries both lines",
                "python",
                {"KIT_SHA": "s"},
                f"python {policy} --only spdx-headers --kit-sha s",
            ),
            (
                "reusable-mypy.yml",
                "mypy, once per group",
                "python",
                {},
                "python /kit/quality/mypy_groups.py --github",
            ),
            (
                "reusable-deny.yml",
                "The hooks that read the deny-list",
                "python",
                {"HOOKS": "a,b"},
                "python /kit/quality/deny_hooks.py a,b",
            ),
            (
                "reusable-secrets.yml",
                "History, default rules",
                "gitleaks",
                {},
                f"gitleaks git . --config .gitleaks.toml {gitleaks}",
            ),
            (
                "reusable-secrets.yml",
                "History, MAC rules",
                "gitleaks",
                {},
                f"gitleaks git . --config .gitleaks-mac.toml {gitleaks}",
            ),
            (
                "reusable-secrets.yml",
                "Tree, default rules",
                "gitleaks",
                {},
                f"gitleaks dir . --config .gitleaks.toml {gitleaks}",
            ),
            (
                "reusable-secrets.yml",
                "Tree, MAC rules",
                "gitleaks",
                {},
                f"gitleaks dir . --config .gitleaks-mac.toml {gitleaks}",
            ),
            (
                "reusable-secrets.yml",
                "The MAC rules fire on planted real shapes and spare the fakes",
                "python",
                {},
                "python /kit/quality/check_quality.py --plant-mac",
            ),
            (
                "reusable-eslint.yml",
                "Install the repository's pinned tools",
                "npm",
                {},
                "npm ci",
            ),
            (
                "reusable-eslint.yml",
                "ESLint (a warning fails too)",
                "npx",
                {},
                "npx --no-install eslint --max-warnings 0 .",
            ),
        ):
            for status in (0, 1, 2, 137):
                with self.subTest(workflow=name, title=title, status=status):
                    self.fake(tool, status)
                    ran = self.run_step(name, title, **env)
                    if "GITHUB_STEP_SUMMARY" in env:
                        ran.calls = [c.replace(str(self.tmp / "summary"), "S") for c in ran.calls]
                    self.assertEqual(ran.status, status, ran.said)
                    self.assertEqual(ran.calls, [call])

    def test_the_hooks_run_on_every_file_and_skip_what_other_jobs_run(self) -> None:
        for status in (0, 1, 3):
            self.fake("pre-commit", status, body=f'echo "SKIP=$SKIP" >> "{self.tmp}/calls"')
            ran = self.run_step(
                "reusable-lint.yml", "Every pre-commit hook on every file", OWN_HOOKS="own,"
            )
            self.assertEqual(ran.status, status)
            self.assertEqual(
                ran.calls,
                [
                    "pre-commit run --all-files --show-diff-on-failure --color always",
                    "SKIP=kleidos-quality,kleidos-md-nowrap,kleidos-agent-docs,"
                    "kleidos-spdx-headers,mypy,kleidos-kit,kleidos-mypy,reuse,own,",
                ],
            )

    def test_what_is_installed_is_hashed_or_the_callers(self) -> None:
        hashed = "Install the kit's tools (hashed)"
        for name in ("reusable-lint.yml", "reusable-reuse.yml", "reusable-mypy.yml"):
            for status in (0, 1):
                self.fake("python", status)
                ran = self.run_step(name, hashed)
                self.assertEqual(ran.status, status)
                self.assertEqual(
                    ran.calls,
                    [
                        "python -I -m pip install --require-hashes"
                        " -r /kit/quality/requirements-tools.txt"
                    ],
                )
        for name, title, variable in (
            ("reusable-mypy.yml", "Install the repository's dependencies", "INSTALL"),
            ("reusable-python-tests.yml", "Install the repository's dependencies", "INSTALL"),
            ("reusable-python-tests.yml", "Tests", "RUN"),
        ):
            for command, status in (
                ("true", 0),
                ("false; true", 1),
                ("false | true", 1),
                ("echo $unset_variable", 1),
                ("exit 7", 7),
                ("echo $(echo '`') > made", 0),
            ):
                with self.subTest(title=title, command=command):
                    ran = self.run_step(name, title, **{variable: command})
                    self.assertEqual(ran.status, status, ran.said)

    def test_the_binaries_come_through_the_lock(self) -> None:
        osv, secrets = "reusable-osv.yml", "reusable-secrets.yml"
        for status in (0, 1):
            self.fake("python3", status)
            self.fake("python")
            ran = self.run_step(osv, "Install OSV-Scanner (pinned, SHA-256 checked)")
            self.assertEqual(ran.status, status)
            fetch = f"python3 /kit/quality/fetch_tool.py osv-scanner {self.tmp}/bin"
            self.assertEqual(ran.calls, [fetch])
            title = "Install gitleaks (pinned, SHA-256 checked) and the kit's tools"
            ran = self.run_step(secrets, title)
            self.assertEqual(ran.status, status)
            self.assertEqual(
                ran.calls[0], f"python3 /kit/quality/fetch_tool.py gitleaks {self.tmp}/bin"
            )
        self.assertEqual((self.tmp / "path").read_text(encoding="utf-8"), f"{self.tmp}/bin\n")
        self.fake("python3")
        ran = self.run_step(secrets, title)
        self.assertIn("--require-hashes", ran.calls[1])


class OsvTest(ScriptCase):
    def test_only_a_clean_scan_or_nothing_to_scan_passes(self) -> None:
        for status, passes in ((0, True), (128, True), (1, False), (2, False), (127, False)):
            with self.subTest(status=status):
                self.fake("osv-scanner", status, out="the table")
                ran = self.run_step("reusable-osv.yml", "Scan every manifest and lockfile")
                self.assertEqual(ran.status, 0 if passes else status, ran.said)
                self.assertIn("the table", ran.summary)
                call = "osv-scanner scan source --recursive --format markdown ."
                self.assertEqual(ran.calls, [call])


class TypeScriptTest(ScriptCase):
    def tsc(self, projects: str) -> Ran:
        return self.run_step("reusable-eslint.yml", "tsc on every project", PROJECTS=projects)

    def test_every_project_is_checked_and_there_is_one(self) -> None:
        self.fake("npx")
        self.assertEqual(
            self.tsc("a.json ../b.json").calls,
            [
                "npx --no-install tsc --noEmit -p a.json",
                "npx --no-install tsc --noEmit -p ../b.json",
            ],
        )
        for projects in ("", "  "):
            ran = self.tsc(projects)
            self.assertEqual((ran.status, ran.calls), (1, []))
        self.fake("npx", body='[ "$5" = bad.json ] && exit 2')
        self.assertEqual(self.tsc("bad.json good.json").status, 2)
        self.assertEqual(self.tsc("good.json bad.json").status, 2)
        self.assertEqual(self.tsc("good.json").status, 0)


class CommitTest(ScriptCase):
    """The commit-message gate over a real history, in the kit's home and elsewhere."""

    def setUp(self) -> None:
        super().setUp()
        fx.init(self.cwd)
        fx.write(self.cwd, "a.txt", "1\n")
        fx.commit(self.cwd, "Add a")
        self.base = fx.git(self.cwd, "rev-parse", "HEAD").strip()

    def head(self, *messages: str) -> str:
        for n, message in enumerate(messages):
            fx.write(self.cwd, "a.txt", f"{n} {message}\n")
            fx.commit(self.cwd, message)
        return fx.git(self.cwd, "rev-parse", "HEAD").strip()

    def check(self, author: str = "someone", repository: str = "o/r", **env: str) -> Ran:
        return self.run_step(
            "reusable-commit-check.yml",
            "Check the pull request's commits",
            BASE_SHA=self.base,
            HEAD_SHA=fx.git(self.cwd, "rev-parse", "HEAD").strip(),
            PR_NUMBER="7",
            PR_AUTHOR=author,
            GITHUB_REPOSITORY=repository,
            **{"KIT": str(fx.CENTRAL), **env},
        )

    def test_every_commit_is_judged(self) -> None:
        self.head("Add b", "Add c")
        ran = self.check()
        self.assertEqual((ran.status, ran.output), (0, "status=0\n"), ran.said)
        result = json.loads((self.tmp / "commit-check/result.json").read_text(encoding="utf-8"))
        self.assertEqual((result["checked"], result["pr"]), (2, 7))
        self.head("Added d", "Add e")  # the bad one is not the last
        ran = self.check()
        self.assertEqual((ran.status, ran.output), (0, "status=1\n"), ran.said)
        self.assertIn("subject-imperative", ran.summary)

    def test_only_the_two_bots_are_excused(self) -> None:
        self.head("Added d")
        for author, status in (
            ("dependabot[bot]", "0"),
            ("renovate[bot]", "0"),
            ("dependabot", "1"),
            ("renovate", "1"),
            ("dependabotx[bot]", "1"),
            ("dependabotb", "1"),
            ("xdependabot[bot]", "1"),
            ("someone", "1"),
            ("", "1"),
            ("*", "1"),
        ):
            with self.subTest(author=author):
                self.assertEqual(self.check(author).output, f"status={status}\n")

    def test_the_kits_own_checker_judges_elsewhere(self) -> None:
        self.head("Added d")
        rel = "hooks/check_commit_msg.py"
        fx.write(self.cwd, rel, "raise SystemExit(0)\n")
        self.head("Plant a checker")
        self.assertEqual(self.check().output, "status=1\n")

    def test_the_checker_of_the_base_judges_in_the_kits_home(self) -> None:
        home = "kleidos-dev/.github"
        checker = (fx.CENTRAL / "hooks/check_commit_msg.py").read_text(encoding="utf-8")
        for rel in (".github/commit-check/check_commit_msg.py", "hooks/check_commit_msg.py"):
            with self.subTest(rel=rel):
                fx.git(self.cwd, "reset", "-q", "--hard", self.base)
                fx.write(self.cwd, rel, checker)
                fx.commit(self.cwd, "Add the checker")
                self.base = fx.git(self.cwd, "rev-parse", "HEAD").strip()
                fx.write(self.cwd, "hooks/check_commit_msg.py", "raise SystemExit(0)\n")
                self.head("Added d")
                self.assertEqual(self.check(repository=home).output, "status=1\n")
        fx.git(self.cwd, "rm", "-q", "-r", "hooks", ".github")
        self.base = self.head("Remove it")
        self.head("Add d")
        self.assertNotEqual(self.check(repository=home).status, 0)

    def test_the_last_step_fails_the_job(self) -> None:
        title = "Fail on a rule the commits break"
        step = self.step("reusable-commit-check.yml", title)
        self.assertEqual(step["if"], "steps.check.outputs.status != '0'")
        self.assertEqual(self.run_step("reusable-commit-check.yml", title, STATUS="1").status, 1)

    def test_the_comment_is_the_kits(self) -> None:
        self.fake("python3")
        ran = self.run_step(
            "reusable-commit-check-comment.yml",
            "Post, update or remove the comment",
            GITHUB_REPOSITORY="o/r",
            HEAD_SHA="abc",
        )
        self.assertEqual(
            ran.calls,
            [
                "python3 /kit/hooks/check_commit_msg.py"
                f" --comment {self.tmp}/commit-check/result.json --repo o/r --head-sha abc"
            ],
        )


class SonarTest(ScriptCase):
    NAME = "reusable-sonarcloud.yml"

    def oidc(self, event: str, head: str, token: bool) -> str:
        env = {"ACTIONS_ID_TOKEN_REQUEST_URL": "https://x"} if token else {}
        ran = self.run_step(
            self.NAME, "OIDC token available", EVENT=event, HEAD_REPO=head, REPO="o/r", **env
        )
        self.assertEqual(ran.status, 0, ran.said)
        self.assertEqual("notice" in ran.said, ran.output == "run=false\n")
        return ran.output.strip()

    def test_only_a_pull_request_without_a_token_is_let_go(self) -> None:
        for event, head, token, run in (
            ("push", "", True, "run=true"),
            ("push", "", False, "run=true"),
            ("pull_request", "o/r", True, "run=true"),
            ("pull_request", "o/r", False, "run=false"),
            ("pull_request", "fork/r", True, "run=false"),
            ("pull_request", "fork/r", False, "run=false"),
        ):
            with self.subTest(event=event, head=head, token=token):
                self.assertEqual(self.oidc(event, head, token), run)

    def accepted(self, *answers: str) -> Ran:
        """The wait, with Sonar's answers one after another."""
        folder = self.cwd / ".scannerwork"
        folder.mkdir(exist_ok=True)
        (folder / "report-task.txt").write_text("ceTaskId=T1\n", encoding="utf-8")
        for n, answer in enumerate(answers):
            (self.tmp / f"answer{n}").write_text(answer, encoding="utf-8")
        counter = self.tmp / "counter"
        counter.write_text("0", encoding="utf-8")
        body = (
            f'n=$(cat "{counter}"); echo $((n + 1)) > "{counter}"\n'
            f'cat "{self.tmp}/answer$n" 2>/dev/null || exit 22\nexit 0'
        )
        self.fake("curl", body=body)
        self.fake("sleep")
        return self.run_step(
            self.NAME,
            "SonarCloud accepted the analysis",
            SONAR_HOST_URL="https://s",
            SONAR_TOKEN="t",
        )

    @staticmethod
    def task(status: str) -> str:
        return json.dumps({"task": {"status": status, "analysisId": "A1"}})

    def test_the_servers_verdict_is_the_jobs(self) -> None:
        for answers, passes in (
            ([self.task("SUCCESS")], True),
            ([self.task("PENDING"), self.task("IN_PROGRESS"), self.task("SUCCESS")], True),
            ([self.task("FAILED")], False),
            ([self.task("CANCELED")], False),
            ([self.task("PENDING"), self.task("FAILED")], False),
            (["{}"], False),
            (["not json"], False),
            ([], False),
        ):
            with self.subTest(answers=answers):
                self.assertEqual(self.accepted(*answers).status == 0, passes)
        ran = self.accepted(self.task("SUCCESS"))
        call = next(c for c in ran.calls if c.startswith("curl"))
        for flag in ("--fail", "--proto =https", "--max-redirs 0", "https://s/api/ce/task?id=T1"):
            self.assertIn(flag, call)

    def test_a_scan_that_left_no_task_fails(self) -> None:
        self.accepted(self.task("SUCCESS"))
        (self.cwd / ".scannerwork/report-task.txt").write_text("x=y\n", encoding="utf-8")
        self.fake("curl", out=self.task("SUCCESS"))
        ran = self.run_step(
            self.NAME,
            "SonarCloud accepted the analysis",
            SONAR_HOST_URL="https://s",
            SONAR_TOKEN="t",
        )
        self.assertEqual(ran.status, 1)


class HomeTest(ScriptCase):
    def test_the_release_check_is_strict_on_main(self) -> None:
        title = "The kit at this commit is a release, or a new version"
        for event, flag in (
            ("pull_request", ""),
            ("push", " --on-main"),
            ("schedule", " --on-main"),
        ):
            for status in (0, 1):
                self.fake("git")
                self.fake("python", status)
                ran = self.run_step("ci.yml", title, EVENT=event)
                self.assertEqual(ran.status, status)
                self.assertEqual(
                    ran.calls,
                    [
                        "git fetch -q --tags --force origin",
                        f"python quality/sync.py --release-check --online{flag}",
                    ],
                )

    def test_the_public_report_is_public_and_red_fails_it(self) -> None:
        title = "Read the public repositories"
        for event, status, result in (
            ("schedule", 0, 0),
            ("schedule", 1, 1),
            ("workflow_dispatch", 1, 1),
            ("pull_request", 0, 0),
            ("pull_request", 1, 0),
            ("pull_request", 2, 2),
            ("schedule", 2, 2),
        ):
            with self.subTest(event=event, status=status):
                self.fake("python", status)
                ran = self.run_step("ecosystem.yml", title, EVENT=event)
                self.assertEqual(ran.status, result, ran.said)
                call = f"python tools/ecosystem.py report --summary {self.tmp}/summary"
                self.assertEqual(ran.calls, [call])


if __name__ == "__main__":
    unittest.main()
