# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""run_form.py: a repository that calls the kit by name, and each defect planted in one."""

from __future__ import annotations

import datetime as dt
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

import kit_fixtures as fx
import yaml
from kit_fixtures import check_quality as cq
from kit_fixtures import run_form as rf

TODAY = dt.datetime.now(tz=dt.UTC).date()
GATE = ".github/workflows/check.yml"
COMMENT = ".github/workflows/commit-check-comment.yml"
SHA = "a" * 40
KIT = cq.DirKit(fx.CENTRAL)


class CalledCase(unittest.TestCase):
    """A fresh copy of one run-form repository for each test."""

    _template: tempfile.TemporaryDirectory[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls._template = tempfile.TemporaryDirectory()
        fx.called(Path(cls._template.name) / "repo")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._template.cleanup()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        shutil.copytree(Path(self._template.name) / "repo", self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def report(self) -> cq.Report:
        return cq.run(self.root, kit=KIT, today=TODAY)

    def found(self) -> list[str]:
        return [f"{p.where}: [{p.rule}] {p.message}" for p in self.report().problems]

    def text(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8")

    def edit(self, rel: str, old: str, new: str, count: int = 1) -> None:
        text = self.text(rel)
        self.assertIn(old, text, rel)
        (self.root / rel).write_text(text.replace(old, new, count), encoding="utf-8")

    def record(self, change: dict[str, Any]) -> None:
        path = self.root / cq.SOURCE_JSON
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(change)
        path.write_text(json.dumps(data), encoding="utf-8")

    def assert_only(self, *needles: str) -> None:
        """The problems are these and no others, in any order."""
        found = self.found()
        self.assertEqual(len(found), len(needles), found)
        for needle in needles:
            self.assertTrue(any(needle in f for f in found), f"{needle!r} not in {found}")


class CleanTest(CalledCase):
    def test_a_switched_repository_keeps_every_rule(self) -> None:
        report = self.report()
        self.assertEqual(report.problems, [])
        self.assertTrue(report.behind_is_note)
        self.assertFalse(any("run on pull requests outside" in n for n in report.notes))
        self.assertIn("base configurations of 3.", report.notes[0])

    def test_it_holds_no_kit_code_and_no_marker(self) -> None:
        held = [p for p in cq.Repo(self.root).files if p.startswith(".github/quality/")]
        self.assertEqual(
            held,
            [
                ".github/quality/SOURCE.json",
                ".github/quality/markdownlint.jsonc",
                ".github/quality/ruff.toml",
                ".github/quality/waivers.toml",
            ],
        )
        for rel in rf.MARKED_FILES:
            self.assertNotIn("kleidos-quality", self.text(rel), rel)

    def test_the_agent_docs_are_clean(self) -> None:
        self.assertEqual(fx.agent_docs.check(fx.agent_docs.Repo(self.root)), [])

    def test_it_is_judged_by_the_kit_it_is_part_of_when_none_is_named(self) -> None:
        self.assertEqual(cq.run(self.root, today=TODAY).problems, [])

    def test_the_tree_still_decides_the_profiles(self) -> None:
        fx.write(self.root, "tools/run.sh", "#!/bin/sh\n" + fx.header() + "echo hi\n")
        self.assert_only("the tree holds shell files but the shell profile is not adopted")


class RecordTest(CalledCase):
    def test_an_edited_configuration_is_caught(self) -> None:
        self.edit(".github/quality/ruff.toml", "line-length = 100", "line-length = 200")
        self.assert_only(".github/quality/ruff.toml: [record] edited in place")

    def test_an_edited_configuration_recorded_again_is_caught(self) -> None:
        path = self.root / ".github/quality/ruff.toml"
        path.write_text(path.read_text(encoding="utf-8") + "# mine\n", encoding="utf-8")
        files = json.loads(self.text(cq.SOURCE_JSON))["files"]
        files[".github/quality/ruff.toml"] = cq.sha256(path.read_bytes())
        self.record({"files": files})
        self.assert_only("no release's quality/ruff/ruff.toml")

    def test_an_older_release_of_a_configuration_is_green(self) -> None:
        kit = fx.CENTRAL / "quality"
        released = json.loads((kit / "config-digests.json").read_text(encoding="utf-8"))
        old = b"# an older release\n"
        released["quality/zizmor/zizmor.yml"].insert(0, cq.sha256(old))

        class OlderKit(cq.DirKit):
            def read(self, path: str) -> bytes:
                return json.dumps(released).encode() if path == rf.DIGESTS else super().read(path)

        (self.root / ".github/zizmor.yml").write_bytes(old)
        files = json.loads(self.text(cq.SOURCE_JSON))["files"]
        files[".github/zizmor.yml"] = cq.sha256(old)
        self.record({"files": files, "taken": "2020-01-01"})
        problems = cq.run(self.root, kit=OlderKit(fx.CENTRAL), today=TODAY).problems
        self.assertEqual(problems, [])

    def test_a_missing_configuration_is_caught(self) -> None:
        (self.root / ".gitleaks-mac.toml").unlink()
        self.assert_only("names .gitleaks-mac.toml, which is not in the tree")

    def test_a_configuration_left_out_of_the_record_is_caught(self) -> None:
        files = json.loads(self.text(cq.SOURCE_JSON))["files"]
        del files[".github/zizmor.yml"]
        self.record({"files": files})
        self.assert_only("the profiles call for .github/zizmor.yml")

    def test_a_file_that_is_no_configuration_cannot_hide_in_the_record(self) -> None:
        fx.write(self.root, ".github/quality/own.toml", fx.header())
        files = json.loads(self.text(cq.SOURCE_JSON))["files"]
        files[".github/quality/own.toml"] = cq.sha256(fx.header().encode())
        self.record({"files": files})
        self.assert_only("records .github/quality/own.toml, not a base configuration")

    def test_any_other_file_beside_the_configurations_is_caught(self) -> None:
        fx.write(self.root, ".github/quality/notes.txt", "x\n")
        self.assert_only(".github/quality/notes.txt: [kit-dir]")

    def test_the_source_of_a_configuration_is_the_kits(self) -> None:
        sources = json.loads(self.text(cq.SOURCE_JSON))["sources"]
        sources[".github/zizmor.yml"] = "quality/ruff/ruff.toml"
        self.record({"sources": sources})
        self.assert_only("sources must say that .github/zizmor.yml")

    def test_sources_that_are_no_table_are_caught(self) -> None:
        self.record({"sources": []})
        self.assertEqual(len([f for f in self.found() if "sources must say" in f]), 4)

    def test_the_records_own_fields(self) -> None:
        upstream = json.loads(self.text(cq.SOURCE_JSON))["upstream"]
        tomorrow = TODAY + dt.timedelta(days=1)
        for change, needle in (
            ({"root": "/"}, 'root must be "."'),
            ({"mode": "frozen", "reason": "x"}, 'mode must be "follow"'),
            ({"mode": "frozen"}, "a frozen copy says why"),
            ({"mode": "sometimes"}, 'mode must be "follow" or "frozen"'),
            ({"taken": "yesterday"}, "taken must be the date"),
            ({"taken": (tomorrow + dt.timedelta(days=1)).isoformat()}, "in the future"),
            ({"max_age_days": 0}, "max_age_days must be a whole number"),
            ({"max_age_days": True}, "max_age_days must be a whole number"),
            ({"upstream": {**upstream, "repo": "other/kit"}}, "upstream.repo must be kleidos-dev"),
            ({"upstream": {**upstream, "repo": "nothing"}}, "must name the source repository"),
            ({"upstream": {**upstream, "commit": "main"}}, "must be a 40-hex commit"),
            ({"upstream": []}, "must name the source repository"),
            ({"kit": {"profiles": ["python"]}}, "must be a list of profiles that includes base"),
            ({"kit": "x"}, "must be a list of profiles that includes base"),
            ({"kit": {"profiles": ["base", "cobol"]}}, "unknown profile 'cobol'"),
            ({"files": {}}, "files must name every copied file"),
            ({"files": [".github/zizmor.yml"]}, "files must name every copied file"),
            ({"files": {".github/zizmor.yml": "x"}}, "must give each file's SHA-256"),
            ({"schema": "kleidos.vendored-copy/9"}, "is not kleidos.vendored-copy/1"),
        ):
            with self.subTest(change=change):
                original = self.text(cq.SOURCE_JSON)
                self.record(change)
                found = self.found()
                self.assertTrue(any(needle in f for f in found), (needle, found))
                (self.root / cq.SOURCE_JSON).write_text(original, encoding="utf-8")
        self.record({"taken": tomorrow.isoformat(), "max_age_days": 1})
        self.assertEqual(self.found(), [])

    def test_every_vendored_copy_of_the_tree_is_held(self) -> None:
        art = fx.write(self.root, "vendor/brand/mark.svg", "<svg/>\n")
        copy = {
            "schema": rf.SCHEMA,
            "upstream": {"repo": "kleidos-dev/brand", "path": "logo", "commit": SHA},
            "mode": "frozen",
            "reason": "until the next deploy",
            "taken": TODAY.isoformat(),
            "files": {"mark.svg": cq.sha256(art.read_bytes())},
        }
        fx.write(self.root, "vendor/brand/SOURCE.json", json.dumps(copy))
        fx.write(self.root, "vendor/other/SOURCE.json", json.dumps({"files": {"x": "y"}}))
        fx.write(self.root, "tests/fixtures/SOURCE.json", "not json")
        self.assertEqual(self.found(), [])
        art.write_text("<svg><g/></svg>\n", encoding="utf-8")
        self.assert_only("vendor/brand/mark.svg: [record] edited in place")
        copy["files"] = {"../../../etc/passwd": "0" * 64}
        fx.write(self.root, "vendor/brand/SOURCE.json", json.dumps(copy))
        self.assert_only("names ../../../etc/passwd, outside this repository")
        fx.write(self.root, "vendor/brand/SOURCE.json", "{")
        self.assert_only("vendor/brand/SOURCE.json: [record] cannot be read")

    def test_a_record_names_nothing_outside(self) -> None:
        data = {"files": dict.fromkeys(("/etc/hosts", "..", ".", "../..", "a/../../b", "a/b"), "")}
        self.assertEqual(
            rf.record_targets("vendor/SOURCE.json", data),
            {
                "/etc/hosts": None,
                "..": None,
                ".": "vendor",
                "../..": None,
                "a/../../b": "b",
                "a/b": "vendor/a/b",
            },
        )
        self.assertIsNone(rf.record_targets("SOURCE.json", {"files": {".": ""}})["."])
        self.assertEqual(rf.record_targets("a/SOURCE.json", {"files": []}), {})
        self.assertEqual(
            rf.record_targets("a/b/SOURCE.json", {"root": ".", "files": {"c": ""}}), {"c": "c"}
        )


class KitCodeTest(CalledCase):
    def test_what_is_left_of_the_copies_is_caught(self) -> None:
        for rel, needle in (
            (".github/quality/md_nowrap.py", "a kit script is run from the kit"),
            (".github/commit-check/check_commit_msg.py", "run, not held"),
            (".github/workflows/quality-drift.yml", "run, not held"),
            ("tests/test_quality_kit.py", "the drift test has nothing to compare"),
        ):
            with self.subTest(rel=rel):
                path = fx.write(self.root, rel, fx.header())
                found = self.found()
                self.assertTrue(
                    any(f.startswith(f"{rel}: [kit-code]") and needle in f for f in found), found
                )
                path.unlink()

    def test_a_marker_left_behind_is_caught(self) -> None:
        for line in ("# >>> kleidos-quality typos (x)", "# <<< kleidos-quality typos"):
            self.edit(".typos.toml", "[default]\n", f"[default]\n{line}\n")
            self.assert_only(".typos.toml:2: [kit-code] a managed-block marker")
            self.edit(".typos.toml", f"{line}\n", "")

    def test_a_kit_script_elsewhere_is_a_note(self) -> None:
        data = (fx.CENTRAL / "quality/md_nowrap.py").read_bytes()
        path = self.root / "pkg" / "wrap.py"
        path.write_bytes(data)
        report = self.report()
        self.assertEqual(report.problems, [])
        self.assertTrue(any("pkg/wrap.py holds the bytes" in n for n in report.notes))


class ReferenceTest(CalledCase):
    def test_only_the_branch_is_the_reference(self) -> None:
        for ref, needle in (
            ("main", "called at @v3 and nothing else"),
            ("v2", "called at @v3 and nothing else"),
            ("v33", "called at @v3 and nothing else"),
            ("V3", "called at @v3 and nothing else"),
            ("refs/heads/v3", "called at @v3 and nothing else"),
            (SHA, "called at a commit"),
            ("v3.0.0", "called at the tag v3.0.0"),
            ("v3.1", "called at the tag v3.1"),
        ):
            with self.subTest(ref=ref):
                original = self.text(GATE)
                self.edit(GATE, "quick.yml@v3", f"quick.yml@{ref}")
                found = self.found()
                self.assertTrue(any(needle in f for f in found), found)
                (self.root / GATE).write_text(original, encoding="utf-8")

    def test_no_spelling_hides_a_reference(self) -> None:
        for spelled, needle in (
            ("Kleidos-Dev/.GitHub/.github/workflows/quick.yml@v3", "in lower case"),
            (">-\n      kleidos-dev/.github/.github/workflows/quick.yml@main", "nothing else"),
            ('"kleidos-dev/.github/.github/workflows/quick.yml@main"', "nothing else"),
        ):
            with self.subTest(spelled=spelled):
                original = self.text(GATE)
                old = "uses: kleidos-dev/.github/.github/workflows/quick.yml@v3"
                self.edit(GATE, old, f"uses: {spelled}")
                found = self.found()
                self.assertTrue(any(needle in f for f in found), found)
                (self.root / GATE).write_text(original, encoding="utf-8")

    def test_a_step_is_read_too(self) -> None:
        self.edit(
            GATE,
            "  done:\n",
            '  own:\n    name: "🔧 Own"\n    needs: quick\n    runs-on: ubuntu-latest\n'
            "    timeout-minutes: 5\n    steps:\n      - run: 'true'\n"
            "      - uses: kleidos-dev/.github/actions/x@main\n  done:\n",
        )
        self.edit(GATE, "needs: [quick, check, sonar]", "needs: [quick, check, sonar, own]")
        self.assertTrue(any("jobs.own" in f and "nothing else" in f for f in self.found()))

    def test_what_the_kit_does_not_offer(self) -> None:
        for path, needle in (
            (".github/workflows/ci.yml", "is not a workflow the kit offers"),
            (".github/actions/x", "is not a workflow the kit offers"),
            (".github/workflows/reusable-nothing.yml", "the kit has no"),
        ):
            with self.subTest(path=path):
                reference = f"kleidos-dev/.github/{path}@v3"
                self.assertIn(needle, str(rf.reference_problem(reference, "v3", KIT)))
        for path in ("quick.yml", "check.yml", "sonar.yml", "reusable-python-tests.yml"):
            reference = f"kleidos-dev/.github/.github/workflows/{path}@v3"
            self.assertIsNone(rf.reference_problem(reference, "v3", KIT))
        self.assertIsNone(rf.reference_problem(f"actions/checkout@{SHA}", "v3", KIT))
        self.assertEqual(rf.branch_of("4.12.0"), "v4")

    def test_a_local_action_cannot_call_the_kit(self) -> None:
        body = fx.header() + "runs:\n  using: composite\n  steps:\n"
        call = "    - uses: kleidos-dev/.github/actions/x@v3\n"
        fx.write(self.root, "actions/a/action.yml", body + "    # kleidos-dev/.github/x@v3\n")
        self.assertEqual(self.found(), [])
        fx.write(self.root, "actions/a/action.yaml", body + call)
        self.assert_only("actions/a/action.yaml:6: [workflows] an action cannot call the kit")

    def test_the_kits_name_is_no_third_party_action(self) -> None:
        self.edit(GATE, "quick.yml@v3", "quick.yml@v3x")
        self.assertTrue(any("[ci]" in f and "not pinned by a full" in f for f in self.found()))


class CallerTest(CalledCase):
    def test_every_entry_workflow_is_called(self) -> None:
        fx.write(self.root, "sonar-project.properties", fx.header())
        self.assertEqual(self.found(), [])
        self.edit(GATE, "/sonar.yml@v3", "/reusable-sonarcloud.yml@v3")
        self.assert_only("no workflow calls the kit's sonar.yml")
        (self.root / COMMENT).unlink()
        self.assertTrue(
            any("the kit's reusable-commit-check-comment.yml" in f for f in self.found())
        )

    def test_a_caller_that_may_not_run_is_caught(self) -> None:
        needs = "    needs: quick\n"
        for old, new, needle in (
            (needs, needs + "    if: false\n", "calls check.yml but it carries the condition"),
            ("  push:\n    branches: [main]\n", "", "does not run on push"),
            (
                "    branches: [main]\n  push",
                "    paths: [x]\n  push",
                "its pull_request trigger has a paths filter",
            ),
        ):
            with self.subTest(new=new):
                original = self.text(GATE)
                self.edit(GATE, old, new)
                found = self.found()
                self.assertTrue(any(needle in f for f in found), found)
                (self.root / GATE).write_text(original, encoding="utf-8")

    def test_types_and_typescript_follow_the_tree(self) -> None:
        self.edit(GATE, "    with:\n", "    with:\n      types: false\n")
        self.assert_only("types: false, but the tree holds Python")
        self.edit(GATE, "types: false", 'types: "False"')
        self.assert_only("types: false, but the tree holds Python")
        self.edit(GATE, 'types: "False"', "types: true")
        self.assertEqual(self.found(), [])

    def test_the_typescript_folder_is_named(self) -> None:
        fx.write(self.root, "web/a.ts", fx.header(prefix="// ") + "export {};\n")
        self.assertTrue(any("node-directory is empty" in f for f in self.found_with_ts()))
        self.edit(GATE, "    with:\n", "    with:\n      node-directory: web\n")
        self.assertFalse(any("node-directory is empty" in f for f in self.found_with_ts()))

    def found_with_ts(self) -> list[str]:
        self.record({"kit": {"version": "3.0.0", "profiles": ["base", "python", "actions", "ts"]}})
        return self.found()

    def test_a_kit_hook_is_never_skipped(self) -> None:
        call = "quick.yml@v3\n"
        for hook in ("kleidos-kit", "own, kleidos-mypy"):
            with self.subTest(hook=hook):
                original = self.text(GATE)
                self.edit(GATE, call, f"{call}    with:\n      skip: {hook}\n")
                self.assert_only("skip names the kit hook kleidos-")
                (self.root / GATE).write_text(original, encoding="utf-8")
        self.edit(GATE, call, f"{call}    with:\n      skip: own\n")
        self.assertEqual(self.found(), [])

    def test_only_a_local_hook_reads_the_deny_list(self) -> None:
        call = "quick.yml@v3\n"
        self.edit(GATE, call, f"{call}    with:\n      deny-hooks: typos, own\n")
        self.assert_only(
            "deny-hooks names typos, which is not a local hook",
            "deny-hooks names own, which is not a local hook",
        )
        self.edit(
            ".pre-commit-config.yaml",
            "repos:\n",
            "repos:\n  - repo: local\n    hooks:\n      - id: own\n        name: own\n"
            "        entry: 'true'\n        language: system\n",
        )
        self.assert_only("deny-hooks names typos, which is not a local hook")

    def test_the_comment_follows_the_gate(self) -> None:
        self.edit(COMMENT, "workflows: [CI]", "workflows: [Commit check]")
        self.assert_only("follows Commit check, not CI")
        self.edit(COMMENT, "workflows: [Commit check]", "workflows: Not CI")
        self.assert_only("follows Not CI, not CI")
        self.edit(COMMENT, "workflows: Not CI", "workflows: CI")
        self.assertEqual(self.found(), [])

    def test_a_workflow_on_pull_requests_outside_the_gate_is_noted(self) -> None:
        fx.write(
            self.root,
            ".github/workflows/docs.yml",
            fx.header()
            + 'name: Docs\non: pull_request\njobs:\n  a:\n    name: "📚 A"\n'
            + "    runs-on: ubuntu-latest\n    timeout-minutes: 5\n    steps:\n"
            + "      - run: 'true'\n",
        )
        report = self.report()
        self.assertEqual(report.problems, [])
        self.assertTrue(
            any("outside ✅ Check: .github/workflows/docs.yml" in n for n in report.notes)
        )

    def test_files_that_are_no_workflow_are_left_to_the_other_checks(self) -> None:
        for body in ("[]\n", "a: [\n", "jobs: 3\n", "jobs:\n  x: 3\n"):
            fx.write(self.root, ".github/workflows/odd.yml", body)
            repo = cq.Repo(self.root)
            self.assertEqual(
                [w.jobs for w in rf.workflows(repo) if w.rel.endswith("odd.yml")],
                [{}] if body.startswith("jobs") else [],
            )

    def test_without_workflows_nothing_is_called(self) -> None:
        shutil.rmtree(self.root / ".github/workflows")
        found = self.found()
        self.assertEqual(len([f for f in found if "no workflow calls the kit's" in f]), 3)
        self.assertTrue(any('no job is named "✅ Check"' in f for f in found))


class GrantTest(CalledCase):
    def test_a_grant_beyond_what_the_kit_needs_is_caught(self) -> None:
        call = "quick.yml@v3\n    permissions:\n      contents: read\n"
        for grant, needle in (
            ("contents: write", "grants contents: write to the kit's quick.yml"),
            ("id-token: write", "grants id-token: write"),
            ("packages: read", "grants packages: read"),
        ):
            with self.subTest(grant=grant):
                original = self.text(GATE)
                self.edit(GATE, call, f"quick.yml@v3\n    permissions:\n      {grant}\n")
                self.assert_only(needle)
                (self.root / GATE).write_text(original, encoding="utf-8")
        self.edit(GATE, call, "quick.yml@v3\n    permissions:\n      issues: none\n")
        self.assertEqual(self.found(), [])

    def test_permissions_are_stated(self) -> None:
        for stated in ("read-all", "write-all"):
            with self.subTest(stated=stated):
                original = self.text(GATE)
                self.edit(
                    GATE,
                    "quick.yml@v3\n    permissions:\n      contents: read\n",
                    f"quick.yml@v3\n    permissions: {stated}\n",
                )
                self.assertTrue(any("must state permissions" in f for f in self.found()))
                (self.root / GATE).write_text(original, encoding="utf-8")

    def test_the_files_own_permissions_count(self) -> None:
        self.edit(GATE, "quick.yml@v3\n    permissions:\n      contents: read\n", "quick.yml@v3\n")
        self.assertEqual(self.found(), [])
        self.edit(GATE, "\npermissions:\n  contents: read\n", "\n")
        self.assertTrue(
            any("jobs.quick: [workflows] must state permissions" in f for f in self.found())
        )

    def test_secrets_are_passed_by_name_to_quick_alone(self) -> None:
        deny = f"    secrets:\n      deny: {rf.DENY_INPUT}\n"
        for where, handed, problems in (
            ("quick", deny, 0),
            ("quick", "    secrets: inherit\n", 1),
            ("quick", "    secrets:\n      deny: ${{ secrets.OTHER }}\n", 1),
            ("quick", deny + "      more: ${{ secrets.MORE }}\n", 1),
            ("check", deny, 1),
            ("check", "    secrets: inherit\n", 1),
        ):
            with self.subTest(where=where, handed=handed):
                original = self.text(GATE)
                self.edit(GATE, f"{where}.yml@v3\n", f"{where}.yml@v3\n{handed}")
                found = [f for f in self.found() if "passes secrets" in f]
                self.assertEqual(len(found), problems, found)
                (self.root / GATE).write_text(original, encoding="utf-8")


class ForgeryTest(CalledCase):
    """A token that can post a check, or a commit status, can post the gate's name."""

    def test_a_workflow_that_can_write_checks_is_caught(self) -> None:
        job = (
            'jobs:\n  a:\n    name: "🔧 A"\n    runs-on: ubuntu-latest\n    timeout-minutes: 5\n'
            "    steps:\n      - run: 'true'\n"
        )
        rel = ".github/workflows/other.yml"
        head = fx.header() + "name: Other\non: workflow_dispatch\n"
        for grant in ("checks: write", "statuses: write"):
            fx.write(self.root, rel, f"{head}permissions:\n  {grant}\n{job}")
            self.assert_only(f"{rel}: [permissions] {grant}")
            in_job = job.replace("    steps", f"    permissions:\n      {grant}\n    steps")
            fx.write(self.root, rel, f"{head}permissions: {{}}\n{in_job}")
            self.assert_only(f"{rel} jobs.a: [permissions] {grant}")
        fx.write(self.root, rel, f"{head}permissions: write-all\n{job}")
        self.assert_only(f"{rel}: [permissions] write-all")
        fx.write(self.root, rel, f"{head}permissions:\n  checks: read\n  contents: write\n{job}")
        self.assertEqual(self.found(), [])


class GateTest(CalledCase):
    def gate(self, change: dict[str, Any], drop: tuple[str, ...] = ()) -> list[str]:
        """The problems of a gate job changed so."""
        model = rf.model_gate(KIT)
        gate = {k: v for k, v in {**model, **change}.items() if k not in drop}
        return list(rf.gate_shape(gate, model))

    def step(self, change: dict[str, Any], drop: tuple[str, ...] = ()) -> list[str]:
        step = rf.model_gate(KIT)["steps"][0]
        changed = {k: v for k, v in {**step, **change}.items() if k not in drop}
        return self.gate({"steps": [changed]})

    def test_the_model_is_the_model(self) -> None:
        self.assertEqual(self.gate({}), [])
        self.assertEqual(self.gate({"if": "${{ always() }}"}), [])
        self.assertEqual(self.step({}, drop=("name",)), [])

    def test_each_way_to_neuter_it_is_caught(self) -> None:
        for problems, needle in (
            (self.gate({"if": "success()"}), "if: always()"),
            (self.gate({}, drop=("if",)), "if: always()"),
            (self.gate({"continue-on-error": True}), "sets continue-on-error"),
            (self.gate({"strategy": {"matrix": {"a": [1]}}}), "sets strategy"),
            (self.gate({"runs-on": "self-hosted"}), "runs-on must be ubuntu-latest"),
            (self.gate({"permissions": {"checks": "write"}}), "permissions must be {}"),
            (self.gate({}, drop=("permissions",)), "permissions must be {}"),
            (self.gate({"steps": []}), "has one step"),
            (self.gate({"steps": [{"run": "true"}, {"run": "true"}]}), "has one step"),
            (self.gate({"steps": ["x"]}), "has one step"),
            (self.gate({}, drop=("steps",)), "has one step"),
            (self.step({"run": "true"}), "must run the kit's script"),
            (self.step({}, drop=("run",)), "must run the kit's script"),
            (self.step({"continue-on-error": True}), "its step sets name, shell"),
            (self.step({"if": "false"}), "its step sets name, shell"),
            (self.step({"shell": "true {0}"}), "its step sets name, shell"),
            (self.step({}, drop=("shell",)), "its step sets name, shell"),
            (self.step({"env": {"NEEDS": "{}"}}), "reads NEEDS"),
            (self.step({}, drop=("env",)), "reads NEEDS"),
            (
                self.step({"env": {"NEEDS": "${{ toJSON(needs) }}", "BASH_ENV": "x"}}),
                "holds NEEDS and MAY_SKIP only",
            ),
        ):
            with self.subTest(needle=needle):
                self.assertTrue(any(needle in p for p in problems), problems)

    def needs(self, jobs: dict[str, Any], gate: dict[str, Any]) -> list[str]:
        whole = {**jobs, "done": gate}
        return list(rf.gate_needs(rf.Workflow("x", {}, whole, {}), "done"))

    def gated(self, needs: Any, may_skip: str = "") -> dict[str, Any]:
        return {"needs": needs, "steps": [{"env": {"MAY_SKIP": may_skip}}]}

    def test_it_needs_every_other_job(self) -> None:
        jobs: dict[str, Any] = {"a": {}, "b": {}}
        self.assertEqual(self.needs(jobs, self.gated(["a", "b"])), [])
        self.assertEqual(self.needs({"a": {}}, self.gated("a")), [])
        self.assertIn("does not need b", self.needs(jobs, self.gated(["a"]))[0])
        self.assertIn("does not need a, b", self.needs(jobs, {})[0])

    def test_a_skip_has_a_reason(self) -> None:
        some = {"if": "needs.a.outputs.x == 'true'"}
        kit = f"kleidos-dev/.github/.github/workflows/{rf.QUICK}@v3"
        for jobs, needle in (
            ({"b": some}, ""),
            ({"b": {"needs": "c"}, "c": some}, ""),
            ({"b": {"needs": ["c"]}, "c": {}}, "has no condition"),
            ({"b": {}}, "has no condition"),
            ({"b": {"if": False}}, "whose condition is false"),
            ({"b": {"if": "${{ false }}"}}, "whose condition is false"),
            ({"b": {**some, "uses": kit}}, "always run"),
            ({"b": {**some, "uses": kit.replace(rf.QUICK, rf.CHECK)}}, "always run"),
            ({"b": {**some, "uses": kit.replace(rf.QUICK, rf.SONAR)}}, ""),
            ({"a": {}}, "which is not a job"),
        ):
            with self.subTest(jobs=jobs):
                found = self.needs(
                    jobs, self.gated(list(jobs), " ".join(jobs if "c" in jobs else "b"))
                )
                if needle:
                    self.assertTrue(any(needle in f for f in found), found)
                else:
                    self.assertEqual([f for f in found if "MAY_SKIP names b" in f], [])

    def test_there_is_one_and_it_runs(self) -> None:
        self.edit(GATE, 'name: "✅ Check"', 'name: "🏁 Check"')
        self.assertTrue(any('no job is named "✅ Check"' in f for f in self.found()))
        self.edit(GATE, 'name: "🏁 Check"', 'name: "✅ Checks"')
        self.assertTrue(any("only the gate's name starts with ✅" in f for f in self.found()))

    def test_a_second_one_is_caught(self) -> None:
        fx.write(
            self.root,
            ".github/workflows/fake.yml",
            fx.header()
            + f'name: Fake\non: push\npermissions: {{}}\njobs:\n  x:\n    name: "{rf.GATE}"\n'
            + "    runs-on: ubuntu-latest\n    timeout-minutes: 5\n    steps:\n"
            + "      - run: 'true'\n",
        )
        found = self.found()
        self.assertTrue(
            any('fake.yml jobs.x: [gate] a second job named "✅ Check"' in f for f in found)
        )

    def test_its_workflow_runs_on_every_pull_request(self) -> None:
        self.edit(GATE, "  pull_request:\n    branches: [main]\n", "")
        self.assertTrue(
            any("[gate]" in f and "does not run on pull_request" in f for f in self.found())
        )

    def test_its_workflow_has_no_path_filter(self) -> None:
        self.edit(GATE, "  push:\n    branches: [main]\n", "  push:\n    paths: [src]\n")
        self.assertTrue(
            any("[gate] its push trigger has a paths filter" in f for f in self.found())
        )


class HookTest(CalledCase):
    CONFIG = ".pre-commit-config.yaml"

    def test_the_kits_hooks_are_there_at_a_release_tag(self) -> None:
        rev = f"rev: v{KIT.version()}"
        for bad in ("rev: v3", "rev: main", f"rev: {SHA}", "rev: v2.9.9", "rev: v3.0.0-rc1"):
            with self.subTest(bad=bad):
                original = self.text(self.CONFIG)
                self.edit(self.CONFIG, rev, bad)
                self.assert_only("name a release tag, v3.x.y")
                (self.root / self.CONFIG).write_text(original, encoding="utf-8")
        self.edit(self.CONFIG, rev, "rev: v3.12.4")
        self.assertEqual(self.found(), [])
        self.edit(self.CONFIG, "    rev: v3.12.4\n", "")
        self.assertTrue(any("at no rev" in f for f in self.found()))

    def test_each_of_the_kits_hooks_is_required(self) -> None:
        for hook in rf.KIT_HOOKS:
            with self.subTest(hook=hook):
                original = self.text(self.CONFIG)
                self.edit(self.CONFIG, f"      - id: {hook}\n", "")
                self.assert_only(f"no {hook} hook from {rf.KIT_HOOKS_URL}")
                (self.root / self.CONFIG).write_text(original, encoding="utf-8")

    def test_without_python_the_mypy_hook_is_not_asked(self) -> None:
        self.edit(self.CONFIG, "      - id: kleidos-mypy\n", "")
        report = cq.Report()
        rf.check_hooks(cq.Repo(self.root), ["base", "actions"], KIT, report)
        self.assertEqual(report.problems, [])
        rf.check_hooks(cq.Repo(self.root), ["base", "python", "actions"], KIT, report)
        self.assertEqual(len(report.problems), 1)

    def test_the_kits_hooks_are_taken_as_they_are(self) -> None:
        self.edit(
            self.CONFIG,
            "      - id: kleidos-kit\n",
            "      - id: kleidos-kit\n        exclude: x\n",
        )
        self.assert_only("kleidos-kit sets exclude")

    def test_a_canonical_hook_is_required(self) -> None:
        self.edit(self.CONFIG, "      - id: ruff-check\n", "")
        self.assert_only("no ruff-check hook from https://github.com/astral-sh/ruff-pre-commit")

    def test_an_alias_is_its_own_hook(self) -> None:
        self.edit(self.CONFIG, "        alias: gitleaks-mac\n", "")
        self.assert_only("no gitleaks-mac hook")

    def test_a_changed_hook_is_refused_or_needs_a_waiver(self) -> None:
        for old, new, needle in (
            (
                "      - id: gitleaks\n",
                "      - id: gitleaks\n        entry: 'true'\n",
                "sets entry",
            ),
            ("      - id: reuse\n", "      - id: reuse\n        stages: [manual]\n", "sets stages"),
            (
                '"--ignore-gitleaks-allow"]',
                "]",
                "gitleaks:args:['--config', '.gitleaks.toml'] weakens a kit rule",
            ),
            ("        types_or: [python, pyi]\n", "", "ruff-format:types_or:None weakens"),
            (
                "      - id: reuse\n",
                "      - id: reuse\n        files: x\n",
                "reuse:files:x weakens",
            ),
        ):
            with self.subTest(new=new):
                original = self.text(self.CONFIG)
                self.edit(self.CONFIG, old, new)
                self.assert_only(needle)
                (self.root / self.CONFIG).write_text(original, encoding="utf-8")

    def test_a_waiver_accepts_a_weakening(self) -> None:
        self.edit(self.CONFIG, "      - id: reuse\n", "      - id: reuse\n        files: x\n")
        path = self.root / cq.WAIVERS
        path.write_text(
            path.read_text(encoding="utf-8")
            + '\n[[waiver]]\ntool = "pre-commit"\nwhat = "reuse:files:x"\nreason = "r"\n'
            + 'decided = "d"\n',
            encoding="utf-8",
        )
        self.assertEqual(self.found(), [])

    def test_a_name_and_a_verbose_flag_change_nothing(self) -> None:
        self.edit(
            self.CONFIG,
            "      - id: reuse\n",
            "      - id: reuse\n        name: mine\n        verbose: true\n",
        )
        self.assertEqual(self.found(), [])

    def test_a_held_script_is_no_hook(self) -> None:
        self.edit(
            self.CONFIG,
            "repos:\n",
            "repos:\n  - repo: local\n    hooks:\n      - id: q\n        name: q\n"
            "        entry: python .github/quality/check_quality.py\n        language: system\n",
        )
        self.assert_only("a local hook runs a held kit script")

    def test_a_configuration_that_does_not_read(self) -> None:
        path = self.root / self.CONFIG
        path.write_text("repos: [\n", encoding="utf-8")
        self.assertTrue(any("[hooks] not valid YAML" in f for f in self.found()))
        path.write_text(
            "repos:\n  - 3\n  - repo: x\n    hooks: 3\n  - hooks: [3]\n", encoding="utf-8"
        )
        self.assertEqual(rf.hook_lists(path.read_text(encoding="utf-8")), [])
        self.assertEqual(rf.hook_lists("[]"), [])
        self.assertEqual(rf.hook_lists("repos: 3"), [])
        path.unlink()
        self.assert_only("[pre-commit] missing")

    def test_the_revision_and_the_exclude_are_read(self) -> None:
        repo = cq.Repo(self.root)
        self.assertEqual(rf.hook_rev(repo), f"v{KIT.version()}")
        self.assertEqual(rf.global_exclude(repo), "")
        self.edit(self.CONFIG, "repos:\n", "exclude: '^x$'\nrepos:\n")
        self.assertEqual(rf.global_exclude(repo), "^x$")
        for body in ("[]", "repos: [", None):
            path = self.root / self.CONFIG
            path.unlink(missing_ok=True)
            if body is not None:
                path.write_text(body, encoding="utf-8")
            self.assertEqual(rf.hook_rev(repo), "none")
            self.assertEqual(rf.global_exclude(repo), "")


class DependabotTest(CalledCase):
    REL = ".github/dependabot.yml"

    def test_the_hooks_are_moved_and_the_majors_are_not(self) -> None:
        text = self.text(self.REL)
        entry = text.index("  - package-ecosystem: pre-commit")
        comment = text.rindex("\n", 0, text.rindex("#", 0, entry)) + 1
        (self.root / self.REL).write_text(text[:comment], encoding="utf-8")
        self.assert_only("no pre-commit ecosystem")
        for old, new in (
            ('update-types: ["version-update:semver-major"]', "versions: ['x']"),
            ('["version-update:semver-major"]', '["version-update:semver-minor"]'),
            (f'dependency-name: "{rf.KIT_HOOKS_URL}"', 'dependency-name: "https://x"'),
        ):
            with self.subTest(old=old):
                (self.root / self.REL).write_text(text, encoding="utf-8")
                self.edit(self.REL, old, new)
                self.assert_only("pre-commit must ignore")
        (self.root / self.REL).write_text(text, encoding="utf-8")
        self.edit(self.REL, f'name: "{rf.KIT_HOOKS_URL}"', f'name: "{rf.KIT_HOOKS_URL}*"')
        self.assertEqual(self.found(), [])

    def test_the_kits_calls_are_still_ignored(self) -> None:
        self.edit(self.REL, '- dependency-name: "kleidos-dev/.github*"', '- dependency-name: "x"')
        self.assert_only('github-actions must ignore "kleidos-dev/.github*"')

    def test_a_file_that_is_missing_or_does_not_read(self) -> None:
        path = self.root / self.REL
        path.write_text("updates: [\n", encoding="utf-8")
        self.assert_only("[dependabot] not valid YAML")
        path.unlink()
        self.assert_only("[dependabot] missing")
        report = cq.Report()
        fx.write(self.root, self.REL, "[]\n")
        rf.check_dependabot(cq.Repo(self.root), report)
        self.assertEqual(
            [p.message for p in report.problems],
            ["no pre-commit ecosystem: it moves the hook revisions"],
        )


class BehindTest(CalledCase):
    """Being behind is never red."""

    def test_old_pins_are_notes(self) -> None:
        self.edit("pyproject.toml", 'target-version = "py315"', 'target-version = "py311"')
        self.edit(
            GATE,
            "  done:\n",
            '  own:\n    name: "🔧 Own"\n    needs: quick\n    runs-on: ubuntu-latest\n'
            "    timeout-minutes: 5\n    steps:\n"
            f"      - uses: actions/checkout@{SHA} # v4.0.0\n  done:\n",
        )
        self.edit(GATE, "needs: [quick, check, sonar]", "needs: [quick, check, sonar, own]")
        report = self.report()
        self.assertEqual(report.problems, [])
        notes = "\n".join(report.notes)
        self.assertIn("python:py311 is behind 3.15 (a note, never red)", notes)
        self.assertIn("action:actions/checkout@v4.0.0 is behind", notes)

    def test_a_written_reason_silences_the_note(self) -> None:
        self.edit(
            "pyproject.toml",
            'target-version = "py315"',
            'target-version = "py311" # below-latest: why',
        )
        report = self.report()
        self.assertEqual(report.problems, [])
        self.assertFalse(any("is behind" in n for n in report.notes))

    def test_what_a_pin_must_say_stays_a_problem(self) -> None:
        self.edit(
            GATE,
            "  done:\n",
            '  own:\n    name: "🔧 Own"\n    needs: quick\n    runs-on: ubuntu-latest\n'
            "    timeout-minutes: 5\n    container: kicad/kicad:9.0.0\n    steps:\n"
            "      - uses: actions/checkout@v7\n  done:\n",
        )
        self.edit(GATE, "needs: [quick, check, sonar]", "needs: [quick, check, sonar, own]")
        self.assert_only("is pinned by tag only", "actions/checkout@v7 is not pinned")


class FloorTest(CalledCase):
    """What the blocks used to hold, now the repository's own text."""

    def test_mypy_and_typos_keep_the_kits_settings(self) -> None:
        self.edit("pyproject.toml", 'enable_error_code = ["ignore-without-code"]\n', "")
        self.assert_only('enable_error_code must hold "ignore-without-code"')
        self.edit("pyproject.toml", "strict = true\n", "")
        self.assert_only('enable_error_code must hold "ignore-without-code"', "strict must be true")

    def test_typos_stays_us_english(self) -> None:
        self.edit(".typos.toml", 'locale = "en-us"', 'locale = "en-gb"')
        self.assert_only('[default] locale must be "en-us"')
        (self.root / ".typos.toml").write_text("default = 3\n", encoding="utf-8")
        self.assert_only('[default] locale must be "en-us"')
        (self.root / ".typos.toml").write_text("= 3\n", encoding="utf-8")
        self.assert_only(".typos.toml: [typos] not valid TOML")
        (self.root / ".typos.toml").unlink()
        self.assert_only('.typos.toml: [typos] missing: [default] locale = "en-us"')


class HomeTest(unittest.TestCase):
    """The kit's home calls its own entry workflows, by ./ path, behind the same gate."""

    def problems(self, change: dict[str, str]) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = fx.init(Path(tmp) / "kit")
            shutil.copytree(
                fx.CENTRAL / ".github", root / ".github", ignore=shutil.ignore_patterns("*.pyc")
            )
            shutil.copytree(
                fx.CENTRAL / "quality", root / "quality", ignore=shutil.ignore_patterns("*.pyc")
            )
            for rel in ("sonar-project.properties", ".pre-commit-config.yaml"):
                shutil.copy(fx.CENTRAL / rel, root)
            for rel, text in change.items():
                (root / rel).write_text(text, encoding="utf-8")
            report = cq.Report()
            rf.check_workflows(
                cq.Repo(root), ["base", "python", "actions"], KIT, report, self_ref=True
            )
            return [f"{p.where}: [{p.rule}] {p.message}" for p in report.problems]

    def test_the_home_passes(self) -> None:
        self.assertEqual(self.problems({}), [])

    def test_the_home_is_held_to_the_same_rules(self) -> None:
        rel = ".github/workflows/ci.yml"
        text = (fx.CENTRAL / rel).read_text(encoding="utf-8")
        for old, new, needle in (
            ("uses: ./.github/workflows/quick.yml", "uses: ./.github/workflows/x.yml", "quick.yml"),
            ("needs: [quick, check, release", "needs: [quick, release", "does not need check"),
            ("    if: always()\n", "", "needs `if: always()`"),
        ):
            with self.subTest(new=new):
                self.assertIn(old, text)
                found = self.problems({rel: text.replace(old, new, 1)})
                self.assertTrue(any(needle in f for f in found), found)


class ModelTest(unittest.TestCase):
    """The model CI and the released digests, which the check reads."""

    def test_the_model_is_a_gate_that_passes(self) -> None:
        model = yaml.safe_load(KIT.read(rf.MODEL_CI).decode("utf-8"))
        workflow = rf.Workflow("x", model, model["jobs"], cq.workflow_triggers(model))
        report = cq.Report()
        rf.check_gate([workflow], KIT, report)
        rf.check_grants([workflow], rf.callers([workflow], self_ref=False), report)
        self.assertEqual(report.problems, [])

    def test_every_base_configuration_is_listed_at_its_newest_bytes(self) -> None:
        released = json.loads(KIT.read(rf.DIGESTS).decode("utf-8"))
        configs = rf.base_configs(KIT, cq.KNOWN_PROFILES)
        self.assertEqual(set(released), set(configs.values()))
        for source, digests in released.items():
            self.assertEqual(digests[-1], cq.sha256(KIT.read(source)), source)
            self.assertEqual(len(set(digests)), len(digests), source)
        self.assertNotIn("{test_dir}/test_quality_kit.py", configs)
        self.assertFalse(any(s.endswith(".py") for s in configs.values()))


if __name__ == "__main__":
    unittest.main()
