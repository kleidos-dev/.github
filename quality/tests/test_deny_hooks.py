# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""deny_hooks.py: only a repository's own hook that installs nothing runs beside the deny-list."""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import kit_fixtures as fx
import yaml
from kit_fixtures import deny_hooks as dh


def hook(**more: Any) -> dict[str, Any]:
    return {"id": "own", "name": "own", "entry": "true", "language": "system", **more}


class RefusalTest(unittest.TestCase):
    def test_what_may_run(self) -> None:
        for one, needle in (
            (hook(), ""),
            (hook(language="script"), ""),
            (hook(language="unsupported"), ""),
            (hook(language="unsupported_script"), ""),
            (hook(stages=["pre-commit", "manual"]), ""),
            (hook(stages=None), ""),
            (hook(additional_dependencies=[]), ""),
            (hook(language="python"), "is language python: it may install something"),
            (hook(language="node"), "is language node"),
            (hook(language="docker_image"), "is language docker_image"),
            (hook(language=None), "is language None"),
            (hook(additional_dependencies=["evil"]), "installs ['evil']"),
            (hook(stages=["manual"]), "does not run at the pre-commit stage"),
            (hook(stages=["commit-msg"]), "does not run at the pre-commit stage"),
        ):
            with self.subTest(hook=one):
                why = dh.refusal("own", {"own": one})
                self.assertEqual(why is None, not needle, why)
                self.assertIn(needle, why or "")
        self.assertEqual(dh.refusal("x", {"own": hook()}), "x is not a local hook")

    def test_only_local_entries_are_hooks(self) -> None:
        for body, ids in (
            ("repos: [{repo: local, hooks: [{id: a}, {id: b}]}]", ["a", "b"]),
            ("repos: [{repo: https://x, hooks: [{id: a}]}]", []),
            ("repos: [{repo: meta, hooks: [{id: a}]}, {repo: local, hooks: [{id: c}]}]", ["c"]),
            ("repos: [{repo: local}, 3, {repo: local, hooks: [3, {name: x}]}]", []),
            ("repos: 3", []),
            ("[]", []),
            ("", []),
        ):
            self.assertEqual(list(dh.local_hooks(body)), ids, body)

    def test_the_chosen_are_the_named_in_order(self) -> None:
        hooks = {"a": hook(id="a"), "b": hook(id="b"), "c": hook(id="c", language="node")}
        self.assertEqual(dh.chosen("b, a", hooks), [hooks["b"], hooks["a"]])
        self.assertEqual(dh.chosen("a b", hooks), [hooks["a"], hooks["b"]])
        for names, why in (
            ("", "no hook is named"),
            (" , ", "no hook is named"),
            ("a,c", "c is language node"),
            ("a,x", "x is not a local hook"),
        ):
            with self.assertRaisesRegex(dh.RefusedError, why):
                dh.chosen(names, hooks)


class MainTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fx.init(Path(self._tmp.name) / "repo")
        self.enterContext(contextlib.chdir(self.root))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def config(self, *hooks: dict[str, Any], **more: Any) -> None:
        local = {"repo": "local", "hooks": list(hooks)}
        data = {"repos": [local], **more}
        fx.write(self.root, dh.CONFIG, yaml.safe_dump(data))

    def run_main(self, *argv: str) -> tuple[int, str]:
        with contextlib.redirect_stderr(io.StringIO()) as err:
            return dh.main(list(argv)), err.getvalue()

    def test_a_refused_hook_runs_nothing(self) -> None:
        self.config(hook(), hook(id="n", language="node"))
        with mock.patch.object(subprocess, "run", side_effect=AssertionError):
            for argv, needle in (
                (("n",), "n is language node"),
                (("own,n",), "n is language node"),
                (("",), "no hook is named"),
                ((), "usage"),
                (("own", "x"), "usage"),
            ):
                status, said = self.run_main(*argv)
                self.assertEqual(status, 2, argv)
                self.assertIn(needle, said)
            fx.write(self.root, dh.CONFIG, "repos: [")
            self.assertEqual(self.run_main("own")[0], 2)
            (self.root / dh.CONFIG).unlink()
            self.assertEqual(self.run_main("own")[0], 2)

    def test_the_status_is_the_hooks(self) -> None:
        self.config(hook())
        for code, status in ((0, 0), (1, 1), (3, 1)):
            done: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess([], code)
            with mock.patch.object(subprocess, "run", return_value=done) as run:
                self.assertEqual(self.run_main("own")[0], status)
            self.assertIn("--all-files", run.call_args.args[0])
            self.assertEqual(run.call_args.kwargs, {"check": False})

    @unittest.skipIf(shutil.which("pre-commit") is None, "pre-commit is not installed")
    def test_pre_commit_sees_the_named_hooks_and_no_other(self) -> None:
        seen = self.root.parent / "seen"
        script = f"import os; open({str(seen)!r}, 'a').write(os.environ['KLEIDOS_DENY_EXTRA'])"
        fx.write(self.root, "own.py", script + "\n")
        fx.write(self.root, "other.py", f"open({str(seen)!r}, 'a').write('OTHER')\n")
        python = sys.executable
        self.config(
            hook(entry=f"{python} own.py", pass_filenames=False, always_run=True),
            hook(id="other", entry=f"{python} other.py", pass_filenames=False, always_run=True),
        )
        # A hook repository that does not exist: pre-commit would fail on it.
        data = yaml.safe_load((self.root / dh.CONFIG).read_text(encoding="utf-8"))
        data["repos"].append({"repo": "/no/such/repo", "rev": "v1", "hooks": [{"id": "x"}]})
        fx.write(self.root, dh.CONFIG, yaml.safe_dump(data))
        fx.commit(self.root)
        env = {"KLEIDOS_DENY_EXTRA": "value", "PRE_COMMIT_HOME": str(self.root.parent / "pc")}
        with mock.patch.dict(os.environ, env):
            for name in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
                os.environ.pop(name, None)
            real = subprocess.run

            def quiet(cmd: list[str], check: bool) -> subprocess.CompletedProcess[bytes]:
                return real(cmd, check=check, capture_output=True)

            with mock.patch.object(subprocess, "run", side_effect=quiet):
                self.assertEqual(self.run_main("own")[0], 0)
        self.assertEqual(seen.read_text(encoding="utf-8"), "value")
        self.assertEqual(fx.git(self.root, "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
