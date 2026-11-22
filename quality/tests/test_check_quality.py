# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""check_quality.py: each conformance rule fires on the weakening it names."""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import kit_fixtures as fx
from kit_fixtures import check_quality as cq
from kit_fixtures import sync

TODAY = dt.date(2026, 11, 22)


class ConformanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fx.consumer(Path(self._tmp.name) / "repo")
        sync.write(self.root, commit=fx.FAKE_COMMIT)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def found(self) -> list[str]:
        report = cq.run(self.root, kit=cq.DirKit(fx.CENTRAL), today=TODAY)
        return [f"{p.where}: [{p.rule}] {p.message}" for p in report.problems]

    def edit(self, rel: str, old: str, new: str) -> None:
        path = self.root / rel
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text, rel)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def append(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")

    def assertFound(self, *needles: str) -> None:
        found = self.found()
        for needle in needles:
            self.assertTrue(any(needle in f for f in found), f"{needle!r} not in {found}")

    def test_the_fixture_starts_clean(self) -> None:
        self.assertEqual(self.found(), [])

    # --- mypy: owner, 2026-11-22: every error fixed, no baseline ---------

    def test_mypy_error_silencing_keys_are_refused(self) -> None:
        pyproject = self.root / "pyproject.toml"
        original = pyproject.read_text(encoding="utf-8")
        for key, value in (
            ("ignore_errors", "true"),
            ("disable_error_code", '["arg-type"]'),
            ("warn_return_any", "false"),
            ("follow_imports", '"skip"'),
            ("allow_untyped_defs", "true"),
        ):
            with self.subTest(key=key):
                pyproject.write_text(original + f"{key} = {value}\n", encoding="utf-8")
                self.assertFound(f"{key}")

    def test_a_mypy_override_may_only_declare_missing_types(self) -> None:
        self.append(
            "pyproject.toml",
            '\n# pcbnew ships no types\n[[tool.mypy.overrides]]\nmodule = ["pcbnew"]\n'
            "ignore_missing_imports = true\n",
        )
        self.assertEqual(self.found(), [])
        self.append(
            "pyproject.toml",
            '\n[[tool.mypy.overrides]]\nmodule = ["pkg.mod"]\ndisallow_untyped_defs = false\n',
        )
        self.assertFound(
            "an override may only set ignore_missing_imports", "needs a comment above it"
        )

    def test_a_python_file_outside_mypy_files_is_reported(self) -> None:
        fx.write(self.root, "tools/extra.py", fx.header() + "X = 1\n")
        self.assertFound("tools/extra.py: [mypy] not checked by mypy")

    def test_a_type_ignore_names_its_code_and_reason(self) -> None:
        fx.write(
            self.root,
            "pkg/bad.py",
            fx.header() + "A = 1  # type: ignore\nB = 2  # type: ignore[assignment]\n",
        )
        self.assertFound("names its error code", "carries its reason")

    # --- ruff ----------------------------------------------------------------

    def test_a_local_ruff_select_is_refused(self) -> None:
        self.append("pyproject.toml", '\n[tool.ruff.lint]\nselect = ["E"]\n')
        self.assertFound("a local select replaces the kit's rule list")

    def test_a_ruff_ignore_needs_a_waiver_and_a_waiver_needs_its_weakening(self) -> None:
        self.append("pyproject.toml", '\n[tool.ruff.lint]\nignore = ["E501"]\n')
        self.assertFound("ignore:E501 weakens a kit rule and has no waiver")
        waiver = (
            '\n[[waiver]]\ntool = "ruff"\nwhat = "ignore:E501"\n'
            'reason = "Generated tables keep their width"\ndecided = "owner 2026-11-22"\n'
        )
        self.append(cq.WAIVERS, waiver)
        self.assertEqual(self.found(), [])
        self.edit("pyproject.toml", 'ignore = ["E501"]', "")
        self.assertFound("matches nothing any more")

    def test_an_expired_or_unreasoned_waiver_fails(self) -> None:
        self.append("pyproject.toml", '\n[tool.ruff.lint]\nignore = ["E501"]\n')
        self.append(
            cq.WAIVERS,
            '\n[[waiver]]\ntool = "ruff"\nwhat = "ignore:E501"\nreason = ""\n'
            'decided = "owner 2026-01-01"\nexpires = 2026-06-01\n',
        )
        self.assertFound("needs reason", "expired on 2026-06-01")

    def test_mypy_cannot_be_waived(self) -> None:
        self.append(
            cq.WAIVERS,
            '\n[[waiver]]\ntool = "mypy"\nwhat = "ignore_errors"\nreason = "no"\ndecided = "x"\n',
        )
        self.assertFound("'mypy' cannot be waived")

    # --- gitleaks, OSV, Dependabot -------------------------------------------

    def test_gitleaks_keeps_every_default_rule_and_targets_its_allowlists(self) -> None:
        fx.write(
            self.root,
            ".gitleaks.toml",
            fx.header()
            + '[extend]\nuseDefault = true\ndisabledRules = ["generic-api-key"]\n'
            + "[allowlist]\npaths = ['x']\n"
            + "[[allowlists]]\npaths = ['y']\n",
        )
        self.assertFound(
            "disabledRules turns default rules off",
            "a global [allowlist] reaches every rule",
            "needs a description",
            "needs targetRules",
        )

    def test_a_gitleaksignore_fingerprint_says_why(self) -> None:
        fx.write(self.root, ".gitleaksignore", "abc:file:rule:1\n")
        self.assertFound("every fingerprint has a comment line above it")

    def test_an_osv_ignore_has_a_reason_and_a_near_end(self) -> None:
        fx.write(
            self.root,
            "osv-scanner.toml",
            '[[IgnoredVulns]]\nid = "GHSA-1"\nignoreUntil = 2027-12-01\nreason = "x"\n'
            '[[IgnoredVulns]]\nid = "GHSA-2"\nignoreUntil = 2026-12-01\n',
        )
        self.assertFound("more than 90 days ahead", "GHSA-2: [osv] needs a reason")

    def test_dependabot_ignores_the_kit_and_covers_every_manifest(self) -> None:
        self.edit(".github/dependabot.yml", '      - dependency-name: "kleidos-dev/.github*"\n', "")
        fx.write(self.root, "site/package.json", "{}\n")
        self.assertFound('github-actions must ignore "kleidos-dev/.github*"', "npm:/site weakens")

    # --- CI conventions and the kit workflows --------------------------------

    def test_ci_jobs_follow_the_conventions(self) -> None:
        fx.write(
            self.root,
            ".github/workflows/extra.yml",
            fx.header()
            + "name: Extra\non: push\njobs:\n  build:\n    name: Build\n"
            + "    runs-on: ubuntu-latest\n"
            + "    continue-on-error: true\n    steps:\n      - uses: actions/checkout@v7\n",
        )
        self.assertFound(
            "starts with an emoji",
            "needs a timeout-minutes",
            "actions/checkout@v7 is not pinned by a full commit SHA",
            "continue-on-error:.github/workflows/extra.yml:build weakens",
        )

    def test_every_kit_workflow_is_called(self) -> None:
        self.edit(".github/workflows/check.yml", "reusable-mypy.yml", "reusable-nothing.yml")
        self.assertFound("no workflow calls the kit's reusable-mypy.yml")
        fx.write(self.root, "sonar-project.properties", "# x\n")
        self.edit(".github/workflows/check.yml", "reusable-sonarcloud.yml", "reusable-none.yml")
        self.assertFound("no workflow calls the kit's reusable-sonarcloud.yml")

    def test_a_missing_profile_is_reported(self) -> None:
        fx.write(self.root, "web/app.ts", "// x\nexport const a = 1;\n")
        self.assertFound("the tree holds ts files but the ts profile is not adopted")

    # --- suppressions in other languages -------------------------------------

    def test_nolint_and_eslint_disable_name_their_rule_and_reason(self) -> None:
        fx.write(self.root, "src/a.cpp", "int a; // NOLINT\nint b; // NOLINT(misc-x)\n")
        fx.write(self.root, "web/a.js", "// eslint-disable-next-line\nlet a;\n")
        self.assertFound(
            "a NOLINT names the check",
            "a NOLINT carries its reason",
            "an eslint-disable names its rule",
        )


class HelpersTest(unittest.TestCase):
    def test_jsonc_reads_comments_and_trailing_commas(self) -> None:
        text = '{\n  // a comment\n  "a": "http://x", /* block */\n  "b": [1, 2,],\n}\n'
        self.assertEqual(cq.load_jsonc(text), {"a": "http://x", "b": [1, 2]})

    def test_a_block_that_opens_twice_is_an_error(self) -> None:
        text = "# >>> kleidos-quality x\n# >>> kleidos-quality x\n# <<< kleidos-quality x\n"
        with self.assertRaises(ValueError):
            cq.find_block(text, "x")

    def test_the_emoji_test_reads_the_first_character(self) -> None:
        self.assertTrue(cq.first_is_emoji("🧹 Lint"))
        self.assertFalse(cq.first_is_emoji("Lint"))


if __name__ == "__main__":
    unittest.main()
