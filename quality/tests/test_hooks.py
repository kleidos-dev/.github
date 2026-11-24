# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""The kit's hooks: they start on an old Python, find a new one, or say what is missing."""

from __future__ import annotations

import ast
import contextlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import kit_fixtures as fx
import yaml
from kit_fixtures import launch, policy
from kit_fixtures import run_form as rf

HOOKS = fx.CENTRAL / "hooks"
OLDEST = (3, 9)
PYTHONS = ("/usr/bin/python3", *(f"python3.{m}" for m in range(9, 20)))


def interpreters() -> list[str]:
    """Every Python of this machine that runs, once per version."""
    found: dict[tuple[int, int], str] = {}
    for name in PYTHONS:
        path = shutil.which(name)
        python = launch.probe(path, "") if path else None
        if python and python.version >= OLDEST:
            found.setdefault(python.version, python.path)
    return list(found.values())


class ManifestTest(unittest.TestCase):
    def hooks(self) -> list[dict[str, object]]:
        text = (fx.CENTRAL / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
        hooks: list[dict[str, object]] = yaml.safe_load(text)
        return hooks

    def test_the_hooks_are_the_ones_the_check_requires(self) -> None:
        self.assertEqual([h["id"] for h in self.hooks()], list(rf.KIT_HOOKS))

    def test_each_is_a_script_that_names_its_stage(self) -> None:
        stages = {"kleidos-commit-msg": ["commit-msg"]}
        for hook in self.hooks():
            with self.subTest(hook=hook["id"]):
                self.assertEqual(hook["language"], "script")
                self.assertEqual(hook["stages"], stages.get(str(hook["id"]), ["pre-commit"]))
                script, name = str(hook["entry"]).split()
                self.assertTrue(os.access(fx.CENTRAL / script, os.X_OK), script)
                self.assertTrue((fx.CENTRAL / launch.HOOKS[name].script).is_file(), name)

    def test_the_policy_hook_runs_whatever_changed(self) -> None:
        hook = next(h for h in self.hooks() if h["id"] == "kleidos-kit")
        self.assertIs(hook["always_run"], True)
        self.assertIs(hook["pass_filenames"], False)

    def test_the_requirement_is_the_kits_pin(self) -> None:
        pins = (fx.QUALITY / "requirements-tools.in").read_text(encoding="utf-8").splitlines()
        self.assertIn(launch.HOOKS["policy"].requirement, pins)


class OldPythonTest(unittest.TestCase):
    def test_every_file_of_the_hooks_reads_on_the_oldest(self) -> None:
        files = sorted(HOOKS.glob("*.py"))
        self.assertEqual([f.name for f in files], ["check_commit_msg.py", "launch.py"])
        for path in files:
            ast.parse(path.read_text(encoding="utf-8"), str(path), feature_version=OLDEST)

    def test_what_the_other_hooks_run_needs_the_floor_they_declare(self) -> None:
        source = (fx.QUALITY / "check_quality.py").read_text(encoding="utf-8")
        for name in ("policy", "mypy"):
            floor = launch.HOOKS[name].floor
            ast.parse(source, feature_version=floor)
            with self.assertRaises(SyntaxError):
                ast.parse(source, feature_version=(floor[0], floor[1] - 1))

    def test_the_starter_runs_on_every_python_of_this_machine(self) -> None:
        for path in interpreters():
            with self.subTest(python=path):
                done = subprocess.run(
                    [path, str(HOOKS / "launch.py")], capture_output=True, text=True, check=False
                )
                self.assertEqual(done.returncode, 2)
                self.assertIn("usage: launch.py policy|mypy|commit-msg", done.stderr)

    def test_the_commit_hook_runs_on_every_python_of_this_machine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            message = Path(tmp) / "message"
            for text, status in (("Add a thing\n", 0), ("Added a thing.\n", 1)):
                message.write_text(text, encoding="utf-8")
                for path in interpreters():
                    with self.subTest(python=path, text=text):
                        done = subprocess.run(
                            [path, str(HOOKS / "launch.py"), "commit-msg", str(message)],
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        self.assertEqual(done.returncode, status, done.stderr)


class ChooseTest(unittest.TestCase):
    """Which Python a hook gets, from the ones there are."""

    HOOK = launch.Hook("x.py", (3, 14), "yaml", "pyyaml==1")

    def choose(self, *pythons: launch.Python) -> tuple[launch.Python | None, str]:
        known = {p.path: p for p in pythons}
        with mock.patch.object(launch, "probe", side_effect=lambda path, _m: known.get(path)):
            return launch.choose(self.HOOK, [*known, "/broken"])

    def test_the_first_that_fits_is_taken(self) -> None:
        old = launch.Python("/old", (3, 9), True)
        bare = launch.Python("/bare", (3, 14), False)
        good = launch.Python("/good", (3, 15), True)
        best = launch.Python("/best", (3, 16), True)
        self.assertEqual(self.choose(old, bare, good, best), (good, ""))
        self.assertEqual(self.choose(launch.Python("/edge", (3, 14), True))[1], "")

    def test_a_missing_module_names_its_install_line(self) -> None:
        bare = launch.Python("/bare", (3, 14), False)
        also = launch.Python("/also", (3, 15), False)
        python, why = self.choose(launch.Python("/old", (3, 13), True), bare, also)
        self.assertIsNone(python)
        own = launch.environment()
        self.assertEqual(
            why,
            "/bare has no yaml module; this makes an environment that has:"
            f" /bare -m venv --clear '{own}' && '{own}/bin/python' -m pip install 'pyyaml==1'",
        )

    def test_the_kits_own_environment_is_outside_every_repository(self) -> None:
        home = {"HOME": "/h"}
        for env, where in (
            ({}, "/h/.local/share/kleidos-kit"),
            ({"XDG_DATA_HOME": ""}, "/h/.local/share/kleidos-kit"),
            ({"XDG_DATA_HOME": "."}, "/h/.local/share/kleidos-kit"),
            ({"XDG_DATA_HOME": "/d"}, "/d/kleidos-kit"),
        ):
            with mock.patch.dict(os.environ, {**home, **env}, clear=True):
                self.assertEqual(launch.environment(), Path(where))

    def test_the_line_it_prints_works(self) -> None:
        """The advice itself, run in a shell: the environment it makes is the next one chosen."""
        with tempfile.TemporaryDirectory() as tmp:
            local = {**os.environ, "XDG_DATA_HOME": str(Path(tmp) / "with space")}
            with mock.patch.dict(os.environ, local, clear=True):
                base = launch.Python(sys.executable, sys.version_info[:2], False)
                known = {base.path: base}
                hook = launch.Hook("x.py", (3, 14), "yaml", "pyyaml==1")
                with mock.patch.object(launch, "probe", side_effect=lambda p, _m: known.get(p)):
                    _python, why = launch.choose(hook, [base.path])
                line = why.split("has: ", 1)[1].replace("-m pip install 'pyyaml==1'", "-m pip -V")
                done = subprocess.run(
                    ["/bin/sh", "-c", line], capture_output=True, text=True, check=False
                )
                self.assertEqual(done.returncode, 0, done.stderr)
                own = launch.candidates((3, 14))[-1]
                self.assertEqual(
                    launch.probe(own, "json"), launch.Python(own, sys.version_info[:2], True)
                )

    def test_an_old_python_is_refused_by_name(self) -> None:
        python, why = self.choose(
            launch.Python("/a", (3, 13), True), launch.Python("/b", (3, 9), True)
        )
        self.assertIsNone(python)
        self.assertIn("needs Python 3.14 or newer and the PATH has 3.13, 3.9:", why)
        self.assertIn("has none", self.choose()[1])

    def test_the_candidates_are_this_python_and_the_paths(self) -> None:
        there = {"python3": "/p/python3", "python3.15": "/p/python3.15", "python3.13": "/p/13"}
        own = str(launch.environment() / "bin" / "python")
        with mock.patch.object(shutil, "which", side_effect=there.get):
            self.assertEqual(
                launch.candidates((3, 14)), [sys.executable, "/p/python3", "/p/python3.15", own]
            )
        with mock.patch.object(shutil, "which", return_value=sys.executable):
            self.assertEqual(launch.candidates((3, 14)), [sys.executable, own])
        with mock.patch.object(shutil, "which", return_value=None) as which:
            launch.candidates((3, 14))
        asked = [c.args[0] for c in which.call_args_list]
        self.assertEqual(asked[:2], ["python3", f"python3.{launch.NEWEST_MINOR}"])
        self.assertEqual(asked[-1], "python3.14")

    def test_a_probe_says_what_an_interpreter_is(self) -> None:
        python = launch.probe(sys.executable, "json")
        self.assertEqual(python, launch.Python(sys.executable, sys.version_info[:2], True))
        python = launch.probe(sys.executable, "no_such_module_here")
        assert python is not None
        self.assertFalse(python.has_module)
        self.assertIsNone(launch.probe("/no/such/python", ""))

    def test_a_program_that_is_no_python_is_not_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for body in ("exit 127", "echo 3 15", "echo 3 15 1; exit 1"):
                path = Path(tmp) / "python3.15"
                path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
                path.chmod(path.stat().st_mode | stat.S_IXUSR)
                self.assertIsNone(launch.probe(str(path), ""), body)

    def test_a_probe_that_hangs_is_given_up(self) -> None:
        late = subprocess.TimeoutExpired("python3", 30)
        with mock.patch.object(subprocess, "run", side_effect=late) as run:
            self.assertIsNone(launch.probe(sys.executable, ""))
        self.assertEqual(run.call_args.kwargs["timeout"], 30)

    def test_the_repository_cannot_plant_a_module_for_the_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            planted = Path(tmp) / "importlib"
            planted.mkdir()
            (planted / "__init__.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
            (Path(tmp) / "planted_module.py").write_text("", encoding="utf-8")
            with contextlib.chdir(tmp):
                python = launch.probe(sys.executable, "planted_module")
        self.assertEqual(python, launch.Python(sys.executable, sys.version_info[:2], False))


class LaunchTest(unittest.TestCase):
    def launch(self, *argv: str) -> tuple[int, str]:
        with contextlib.redirect_stderr(io.StringIO()) as err:
            return launch.main(list(argv)), err.getvalue()

    def test_a_hook_gets_its_arguments_and_gives_its_status(self) -> None:
        chosen = (launch.Python("/py", (3, 15), True), "")
        with (
            mock.patch.object(subprocess, "call", return_value=7) as call,
            mock.patch.object(launch, "choose", return_value=chosen),
        ):
            status, said = self.launch("commit-msg", "--MSG")
            self.assertEqual((status, said), (7, ""))
            call.assert_called_once_with(["/py", str(HOOKS / "check_commit_msg.py"), "--", "--MSG"])
            for name in ("policy", "mypy"):
                self.assertEqual(self.launch(name)[0], 7)
                script = fx.CENTRAL / launch.HOOKS[name].script
                self.assertEqual(call.call_args.args[0], ["/py", str(script)])

    def test_without_a_python_it_says_why_and_fails(self) -> None:
        with mock.patch.object(launch, "choose", return_value=(None, "needs X")):
            status, said = self.launch("policy")
        self.assertEqual(status, 2)
        self.assertIn("hook policy: needs X", said)
        self.assertIn("the CI runs the same check", said)

    def test_an_unknown_hook_is_refused(self) -> None:
        self.assertEqual(self.launch("nothing")[0], 2)
        self.assertEqual(self.launch()[0], 2)

    def test_each_gets_the_arguments_it_takes(self) -> None:
        for argv in (("policy", "x"), ("mypy", "x"), ("commit-msg",), ("commit-msg", "a", "b")):
            with mock.patch.object(launch, "choose") as choose:
                status, said = self.launch(*argv)
            self.assertEqual(status, 2)
            self.assertIn("usage: launch.py", said)
            choose.assert_not_called()


class PreCommitTest(unittest.TestCase):
    """pre-commit itself, with the hooks of this working tree and an empty cache."""

    @unittest.skipIf(shutil.which("pre-commit") is None, "pre-commit is not installed")
    def test_the_hooks_install_and_run_from_an_empty_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kit = Path(tmp) / "kit"
            fx.init(kit)
            listed = fx.sync.git("ls-files", "--cached", "--others", "--exclude-standard")
            for rel in listed.splitlines():
                if (fx.CENTRAL / rel).is_file():
                    (kit / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(fx.CENTRAL / rel, kit / rel)
            fx.commit(kit, "Kit")
            fx.git(kit, "tag", "v3.0.0")
            root = fx.init(Path(tmp) / "repo")
            fx.write(root, "a.md", "One\nwrapped.\n")
            fx.write(
                root,
                ".pre-commit-config.yaml",
                f"repos:\n  - repo: {kit}\n    rev: v3.0.0\n    hooks:\n"
                "      - id: kleidos-kit\n      - id: kleidos-commit-msg\n",
            )
            fx.commit(root)
            # The Python of this test comes first, whatever else the machine has.
            first = Path(tmp) / "bin"
            first.mkdir()
            (first / "python3").write_text(
                f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8"
            )
            (first / "python3").chmod(0o755)
            env = {
                **os.environ,
                **fx.GIT_ENV,
                "PATH": f"{first}:{os.environ['PATH']}",
                "PRE_COMMIT_HOME": str(Path(tmp) / "cache"),
                "XDG_DATA_HOME": str(Path(tmp) / "data"),
            }
            for name in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
                env.pop(name, None)
            run = ["pre-commit", "run", "--all-files", "--verbose"]
            done = subprocess.run(
                run, cwd=root, env=env, capture_output=True, text=True, check=False
            )
            self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
            self.assertIn("a.md:2: hard-wrapped prose", done.stdout)
            self.assertIn(f"problem(s) found by {policy.kit_line()[:8]}", done.stdout)
            self.assertNotIn("commit message", done.stdout)  # not at this stage
            message = Path(tmp) / "message"
            message.write_text("Added a thing.\n", encoding="utf-8")
            done = subprocess.run(
                [*run[:2], "--hook-stage", "commit-msg", "--commit-msg-filename", str(message)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
            self.assertIn("subject-imperative", done.stdout)
            self.assertNotIn("hard-wrapped", done.stdout)


if __name__ == "__main__":
    unittest.main()
