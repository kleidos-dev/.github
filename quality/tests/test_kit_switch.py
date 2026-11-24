# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""kit_switch.py: a 2.x repository becomes a run-form one, and nothing of its own is lost."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path

import kit_fixtures as fx
import yaml
from kit_fixtures import agent_docs, own_files, sync
from kit_fixtures import check_quality as cq
from kit_fixtures import kit_switch as ks
from kit_fixtures import run_form as rf

TODAY = dt.date(2026, 11, 24)
KIT = cq.DirKit(fx.CENTRAL)
OLD = (
    "kleidos-dev/.github/.github/workflows/reusable-{}.yml@" + fx.FAKE_COMMIT + " # quality-v2.3.0"
)


class SwitchTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fx.consumer(Path(self._tmp.name) / "repo")
        sync.write(self.root, commit=fx.FAKE_COMMIT, test_dir="tests")
        fx.write(self.root, ".github/commit-check/check_commit_msg.py", fx.header())
        fx.write(self.root, ".github/commit-check/SOURCE.json", "{}")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def switch(self) -> list[str]:
        return ks.switch(self.root, KIT, fx.FAKE_COMMIT, TODAY)

    def text(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8")

    def problems(self) -> list[str]:
        return [p.message for p in cq.run(self.root, kit=KIT).problems]

    def test_the_whole_switch(self) -> None:
        log = self.switch()
        self.assertEqual(self.problems(), [])
        for rel in (
            ".github/quality/check_quality.py",
            ".github/commit-check",
            ".github/workflows/quality-drift.yml",
            ".github/workflows/commit-check.yml",
            "tests/test_quality_kit.py",
        ):
            self.assertFalse((self.root / rel).exists(), rel)
        record = json.loads(self.text(cq.SOURCE_JSON))
        self.assertEqual(record["taken"], "2026-11-24")
        self.assertEqual(record["upstream"]["commit"], fx.FAKE_COMMIT)
        self.assertEqual(record["kit"]["profiles"], ["base", "python", "actions"])
        self.assertEqual(rf.record_problems(record, TODAY), [])
        self.assertIn("dependabot.yml moves the hook revisions", log)
        self.assertTrue(any("check.yml calls the entry workflows" in line for line in log), log)
        self.assertIn(agent_docs.RULES_URL, self.text("AGENTS.md"))
        self.assertNotIn("Never `--no-verify`", self.text("AGENTS.md"))
        self.assertIn(f"{ks.RULES_SECTION}\n## Other repositories", self.text("AGENTS.md"))
        self.assertIn("removed .github/commit-check/", log)
        self.assertIn(f".pre-commit-config.yaml takes the kit's hooks at v{KIT.version()}", log)

    def test_a_second_switch_changes_nothing(self) -> None:
        self.switch()
        fx.commit(self.root)
        self.assertEqual(
            self.switch(), ["nothing to switch: this repository holds no kit 2.x copies"]
        )
        self.assertEqual(fx.git(self.root, "status", "--porcelain"), "")

    def test_a_repository_with_no_record_is_left_alone(self) -> None:
        (self.root / cq.SOURCE_JSON).unlink()
        self.assertEqual(len(self.switch()), 1)

    def test_own_hooks_and_their_comments_stay(self) -> None:
        path = self.root / ".pre-commit-config.yaml"
        own = (
            "  # Mine.\n  - repo: local\n    hooks:\n      - id: kleidos-commit-msg\n"
            "        name: old\n        entry: x\n        language: system\n"
            "      # Why mine.\n      - id: mine\n        name: mine\n        entry: 'true'\n"
            "        language: system\n"
            "  - repo: https://example.org/other\n    rev: v1\n    hooks:\n      - id: other\n"
        )
        path.write_text(path.read_text(encoding="utf-8") + own, encoding="utf-8")
        self.switch()
        text = self.text(".pre-commit-config.yaml")
        ids = [rf.hook_key(h["hook"]) for h in rf.hook_lists(text)]
        self.assertEqual(ids[:3], list(rf.KIT_HOOKS))
        self.assertEqual(ids[-2:], ["mine", "other"])
        self.assertEqual(ids.count("kleidos-commit-msg"), 1)
        self.assertIn("      # Why mine.\n      - id: mine\n", text)

    def test_every_hook_of_the_copies_goes(self) -> None:
        held = ["kleidos-quality", "kleidos-md-nowrap", "kleidos-spdx-headers"]
        held += ["kleidos-agent-docs", "kleidos-commit-msg", "mypy"]
        for name in held:
            own = f"  - repo: local\n    hooks:\n      - id: {name}\n        name: x\n"
            text = ks.hook_list(f"# x\nrepos:\n{own}", KIT, ["base"])
            ids = [rf.hook_key(h["hook"]) for h in rf.hook_lists(text)]
            self.assertEqual(ids, ["kleidos-kit", "kleidos-commit-msg"], name)

    def test_the_first_entry_and_a_third_partys_hooks_stay_whole(self) -> None:
        own = "  - repo: local\n    hooks:\n      - id: own\n        name: own\n"
        theirs = "  - repo: https://x\n    rev: v1\n    hooks:\n      - id: mypy\n      - id: b\n"
        text = ks.hook_list(f"repos:\n{own}{theirs}".join(("# x\n", "")), KIT, ["base"])
        self.assertTrue(text.endswith(own + theirs), text)
        self.assertEqual(
            [rf.hook_key(h["hook"]) for h in rf.hook_lists(text)],
            ["kleidos-kit", "kleidos-commit-msg", "own", "mypy", "b"],
        )

    def test_without_python_there_is_no_mypy_hook(self) -> None:
        text = ks.hook_list("# x\nrepos:\n  - repo: local\n    hooks: []\n", KIT, ["base"])
        self.assertNotIn("kleidos-mypy", text)
        self.assertIn("- id: kleidos-kit\n      - id: kleidos-commit-msg\n", text)

    def test_dependabot_keeps_an_entry_it_has(self) -> None:
        path = self.root / ".github/dependabot.yml"
        path.write_text(path.read_text(encoding="utf-8") + ks.DEPENDABOT_ENTRY, encoding="utf-8")
        before = path.read_bytes()
        self.assertNotIn("dependabot.yml moves the hook revisions", self.switch())
        self.assertEqual(path.read_bytes(), before)

    def test_what_is_missing_is_left_missing(self) -> None:
        for rel in (".github/dependabot.yml", "AGENTS.md", ".typos.toml"):
            (self.root / rel).unlink()
        self.switch()
        for rel in (".github/dependabot.yml", "AGENTS.md", ".typos.toml"):
            self.assertFalse((self.root / rel).exists(), rel)

    def test_an_agents_file_without_the_block_is_left_as_it_is(self) -> None:
        self.assertEqual(ks.rules_link("# A\n\nText.\n"), "# A\n\nText.\n")

    def test_without_a_gate_workflow_it_says_so(self) -> None:
        (self.root / ".github/workflows/check.yml").unlink()
        fx.write(self.root, ".github/workflows/odd.yml", "[]\n")
        fx.write(self.root, ".github/workflows/jobless.yml", "on: push\n")
        self.assertTrue(any(line.startswith("left: no gate workflow") for line in self.switch()))

    def test_a_record_never_reaches_outside(self) -> None:
        outside = self.root.parent / "victim.py"
        outside.write_text("keep\n", encoding="utf-8")
        path = self.root / cq.SOURCE_JSON
        record = json.loads(path.read_text(encoding="utf-8"))
        record["files"] += [{"path": "../victim.py"}, "odd"]
        path.write_text(json.dumps(record), encoding="utf-8")
        self.switch()
        self.assertTrue(outside.is_file())

    def test_a_dirty_tree_is_refused(self) -> None:
        fx.commit(self.root, "Hold the kit")
        for rel in ("AGENTS.md", "new.txt"):
            fx.git(self.root, "reset", "-q", "--hard")
            with (self.root / rel).open("a", encoding="utf-8") as fh:
                fh.write("mine\n")
            before = fx.git(self.root, "status", "--porcelain")
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(ks.main(["--write", str(self.root)]), 2)
            self.assertIn("has uncommitted changes: commit them first", err.getvalue())
            self.assertEqual(fx.git(self.root, "status", "--porcelain"), before)


class ConfigsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fx.called(Path(self._tmp.name) / "repo")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_nothing_to_take_changes_nothing(self) -> None:
        before = (self.root / cq.SOURCE_JSON).read_bytes()
        self.assertEqual(ks.write_configs(self.root, KIT, "f" * 40, TODAY), [])
        self.assertEqual((self.root / cq.SOURCE_JSON).read_bytes(), before)

    def test_a_new_language_brings_its_configuration(self) -> None:
        fx.write(self.root, "run.sh", "#!/bin/sh\n" + fx.header())
        log = ks.write_configs(self.root, KIT, "f" * 40, TODAY)
        self.assertEqual(
            log,
            [
                "wrote .shellcheckrc",
                "recorded 5 base configurations in .github/quality/SOURCE.json",
            ],
        )
        record = json.loads((self.root / cq.SOURCE_JSON).read_text(encoding="utf-8"))
        self.assertEqual(record["upstream"]["commit"], "f" * 40)
        self.assertIn("shell", record["kit"]["profiles"])

    def test_nothing_is_written_through_a_link_or_in_gits_folder(self) -> None:
        outside = self.root.parent / "outside"
        outside.mkdir()
        (outside / "zizmor.yml").write_text("keep\n", encoding="utf-8")
        target = self.root / ".github/zizmor.yml"
        target.unlink()
        target.symlink_to(outside / "zizmor.yml")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(ks.main(["--configs", str(self.root)]), 2)
        self.assertIn(".github/zizmor.yml is a symbolic link", err.getvalue())
        self.assertEqual((outside / "zizmor.yml").read_text(encoding="utf-8"), "keep\n")
        linked = self.root / "linked"
        linked.symlink_to(outside)
        for rel, why in (
            (".git/config", "is in git's own folder"),
            ("sub/.GIT/hooks/x", "is in git's own folder"),
            ("linked/zizmor.yml", "linked is a symbolic link"),
            ("linked/new/x", "linked is a symbolic link"),
            ("linked", "linked is a symbolic link"),
            ("../outside/zizmor.yml", "is not in the repository"),
            ("/etc/x", "is not in the repository"),
            (".", "is not in the repository"),
        ):
            with self.assertRaisesRegex(own_files.RefusedError, why):
                own_files.own_file(self.root, rel)
        self.assertEqual(own_files.own_file(self.root, "new/x"), self.root / "new/x")

    def test_an_old_configuration_is_written_again(self) -> None:
        (self.root / ".github/zizmor.yml").write_text("old\n", encoding="utf-8")
        (self.root / cq.SOURCE_JSON).unlink()
        log = ks.write_configs(self.root, KIT, "f" * 40, TODAY)
        self.assertEqual(len(log), 2)
        self.assertEqual([p.message for p in cq.run(self.root, kit=KIT).problems], [])


class ConvertTest(unittest.TestCase):
    """The gate workflow, job by job."""

    HEAD = "name: CI\n\non:\n  pull_request:\n  push:\n\njobs:\n"

    def convert(self, body: str, profiles: list[str] | None = None) -> dict[str, dict[str, object]]:
        text = ks.convert_ci(self.HEAD + body, KIT, profiles or ["base", "python", "actions"])
        jobs: dict[str, dict[str, object]] = yaml.safe_load(text)["jobs"]
        return jobs

    def old(self, job_id: str, name: str, more: str = "") -> str:
        return f'  {job_id}:\n    name: "x"\n{more}    uses: {OLD.format(name)}\n'

    def test_what_the_old_callers_said_reaches_the_new_one(self) -> None:
        jobs = self.convert(
            self.old("lint", "lint")
            + "    with:\n      skip: mine,other\n"
            + self.old("tests", "python-tests")
            + "    with:\n      install: pip install -r a.txt\n"
            + '      run: >-\n        A=1\n        python -m pytest -m "not x"\n'
            + "      coverage-artifact: cov\n      timeout-minutes: 20\n"
            + self.old("types", "mypy")
            + "    with:\n      install: pip install -r b.txt\n"
        )
        self.assertEqual(jobs["quick"]["with"], {"skip": "mine,other"})
        self.assertEqual(
            jobs["check"]["with"],
            {
                "install": "pip install -r a.txt",
                "tests": 'A=1 python -m pytest -m "not x"',
                "coverage-artifact": "cov",
                "timeout-minutes": 20,
                "types-install": "pip install -r b.txt",
            },
        )
        self.assertEqual(list(jobs), ["quick", "check", "done"])
        self.assertEqual(jobs["done"]["needs"], ["quick", "check"])

    def test_the_defaults_of_the_old_workflow_are_kept(self) -> None:
        jobs = self.convert(self.old("tests", "python-tests") + "    with:\n      run: t\n")
        self.assertEqual(jobs["check"]["with"], {"python": "-r requirements.txt", "tests": "t"})

    def test_types_alone_install_for_themselves(self) -> None:
        jobs = self.convert(self.old("types", "mypy") + "    with:\n      install: i\n")
        self.assertEqual(jobs["check"]["with"], {"install": "i"})

    def test_a_tree_without_python_or_tests(self) -> None:
        jobs = self.convert(self.old("lint", "lint"), ["base", "actions"])
        self.assertEqual(jobs["check"]["with"], {"types": False})
        self.assertNotIn("with", jobs["quick"])
        # Nothing may skip, and the gate says so: nothing outside its step can.
        step = jobs["done"]["steps"]
        assert isinstance(step, list)
        self.assertEqual(step[0]["env"]["MAY_SKIP"], "")

    def test_typescript(self) -> None:
        jobs = self.convert(
            self.old("eslint", "eslint")
            + "    with:\n      working-directory: w\n      projects: a.json b.json\n",
            ["base", "python", "actions", "ts"],
        )
        self.assertEqual(
            jobs["check"]["with"], {"node-directory": "w", "node-projects": "a.json b.json"}
        )
        jobs = self.convert(self.old("eslint", "eslint"), ["base", "actions", "ts"])
        self.assertEqual(jobs["check"]["with"], {"types": False, "node-directory": "."})

    def test_own_jobs_stay_and_need_the_new_ones(self) -> None:
        jobs = self.convert(
            self.old("lint", "lint")
            + self.old("reuse", "reuse")
            + self.old("osv", "osv")
            + '  # Mine.\n  own:\n    name: "🔧 Own"\n    needs: [lint, reuse]\n'
            + "    runs-on: ubuntu-latest\n    steps:\n      - run: 'true'\n"
            + '\n  last:\n    name: "🔧 Last"\n    needs: [own, osv]\n    if: github.x\n'
            + "    runs-on: ubuntu-latest\n    steps: []\n"
            + self.old("sonarcloud", "sonarcloud", "    needs: [osv, own]\n")
            + "    with:\n      coverage-artifact: cov\n"
        )
        self.assertEqual(list(jobs), ["quick", "check", "sonar", "own", "last", "done"])
        self.assertEqual(jobs["own"]["needs"], ["quick"])
        self.assertEqual(jobs["last"]["needs"], ["own", "check"])
        self.assertEqual(jobs["sonar"]["needs"], ["check", "own"])
        self.assertEqual(jobs["sonar"]["with"], {"coverage-artifact": "cov"})
        self.assertEqual(jobs["done"]["needs"], ["quick", "check", "own", "last", "sonar"])
        step = jobs["done"]["steps"]
        assert isinstance(step, list)
        self.assertEqual(step[0]["env"]["MAY_SKIP"], "last sonar")

    def test_a_second_test_job_is_called_itself_at_the_branch(self) -> None:
        jobs = self.convert(
            self.old("tests", "python-tests")
            + "    with:\n      run: a\n"
            + self.old("more", "python-tests", "    needs: lint\n")
            + "    with:\n      run: b\n"
            + self.old("lint", "lint")
        )
        self.assertEqual(list(jobs), ["quick", "check", "more", "done"])
        self.assertEqual(
            jobs["more"]["uses"],
            "kleidos-dev/.github/.github/workflows/reusable-python-tests.yml@v3",
        )
        self.assertEqual(jobs["more"]["needs"], ["quick"])

    def test_the_comment_above_a_job_goes_with_it(self) -> None:
        text = ks.convert_ci(
            self.HEAD
            + "  # About lint.\n"
            + self.old("lint", "lint")
            + '\n  # About own.\n  own:\n    name: "x"\n    steps: []\n',
            KIT,
            ["base"],
        )
        self.assertNotIn("About lint", text)
        self.assertIn("  # About own.\n  own:\n", text)
        self.assertEqual(text.count("\njobs:\n"), 1)
        self.assertNotIn("\n\n\n", text)
        bare = ks.convert_ci(self.HEAD + self.old("lint", "lint"), KIT, ["base"])
        self.assertNotIn("\n\n\n", bare)

    def test_lines_that_are_no_needs_are_left(self) -> None:
        for line in ("    needs:\n", "      needs: [lint]\n", "    needs: ${{ x }}\n"):
            self.assertEqual(ks.rewrite_needs(line, {"lint": "quick"}), line)
        self.assertEqual(
            ks.rewrite_needs("    needs: lint\n", {"lint": "quick"}), "    needs: [quick]\n"
        )
        self.assertEqual(ks.point_at("    uses: a/b@c\n", {"uses": "a/b@c"}), "    uses: a/b@c\n")


class CommandTest(unittest.TestCase):
    def run_main(self, *argv: str) -> tuple[int, str]:
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(out):
            status = ks.main(list(argv))
        return status, out.getvalue()

    def test_the_command_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = fx.consumer(Path(tmp) / "repo")
            sync.write(root, commit=fx.FAKE_COMMIT)
            fx.commit(root, "Hold the kit")
            status, said = self.run_main("--write", str(root))
            self.assertEqual(status, 0)
            self.assertIn("calls the entry workflows", said)
            head = sync.git("rev-parse", "HEAD")
            record = json.loads((root / cq.SOURCE_JSON).read_text(encoding="utf-8"))
            self.assertEqual(record["upstream"]["commit"], head)
            self.assertEqual(self.run_main("--configs", str(root), "--commit", "x"), (0, ""))
            status, said = self.run_main("--write", tmp)
            self.assertEqual(status, 2)
            self.assertIn("not the top of a git work tree", said)


if __name__ == "__main__":
    unittest.main()
