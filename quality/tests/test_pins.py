# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""check_quality.py's pin rule: every pin at the latest stable release the kit knows."""

from __future__ import annotations

import datetime as dt
import re
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path

import kit_fixtures as fx
from kit_fixtures import check_quality as cq
from kit_fixtures import latest_releases as lr
from kit_fixtures import sync

TODAY = dt.date(2026, 11, 23)
OLD_SHA = "a" * 40
WAIVER = (
    '\n[[waiver]]\ntool = "pins"\nwhat = "{what}"\n'
    'reason = "The image the job runs in ships no newer Python"\n'
    'decided = "owner 2026-11-23"\n'
)
WORKFLOW = """name: Extra
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  extra:
    name: "🧪 Extra"
    runs-on: ubuntu-latest
    timeout-minutes: 5
    strategy:
      matrix:
        python-version:
          - "3.15"
          - "{matrix}"
    steps:
      - uses: actions/checkout@{sha} # {checkout}
      - uses: actions/setup-python@{sha} # v7.1.0
        with:
          python-version: {python}
      - uses: actions/setup-python@{sha} # v7.1.0
        with:
          python-version: ${{{{ matrix.python-version }}}}
"""


class PinsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fx.consumer(Path(self._tmp.name) / "repo")
        sync.write(self.root, commit=fx.FAKE_COMMIT)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def found(self) -> list[str]:
        report = cq.run(self.root, kit=cq.DirKit(fx.CENTRAL), today=TODAY)
        return [f"{p.where}: [{p.rule}] {p.message}" for p in report.problems]

    def pins_found(self) -> list[str]:
        return [f for f in self.found() if "[pins]" in f or "pins:" in f or "python:" in f]

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

    def workflow(
        self, checkout: str = "v7.0.1", python: str = '"3.15"', matrix: str = "3.15"
    ) -> None:
        text = WORKFLOW.format(sha=OLD_SHA, checkout=checkout, python=python, matrix=matrix)
        fx.write(self.root, ".github/workflows/extra.yml", fx.header() + text)

    def test_the_fixture_at_the_latest_python_is_clean(self) -> None:
        self.workflow()
        self.assertEqual(self.found(), [])

    def test_an_older_python_version_file_is_reported(self) -> None:
        (self.root / ".python-version").write_text("3.13.5\n", encoding="utf-8")
        self.assertFound(".python-version:1: [pins] python:3.13.5 is below", "(3.15)")

    def test_a_reason_beside_it_makes_it_a_weakening_that_needs_a_waiver(self) -> None:
        (self.root / ".python-version").write_text(
            "# below-latest: the KiCad image ships 3.13\n3.13\n", encoding="utf-8"
        )
        self.assertFound("python:3.13 weakens a kit rule and has no waiver")
        self.append(cq.WAIVERS, WAIVER.format(what="python:3.13"))
        self.assertEqual(self.found(), [])
        (self.root / ".python-version").write_text("3.15\n", encoding="utf-8")
        self.assertFound("matches nothing any more")

    def test_a_reason_without_the_marker_does_not_count(self) -> None:
        (self.root / ".python-version").write_text(
            "# the KiCad image ships 3.13\n3.13\n", encoding="utf-8"
        )
        self.assertFound(".python-version:2: [pins] python:3.13 is below")

    def test_ruff_mypy_and_requires_python_are_read(self) -> None:
        self.edit("pyproject.toml", 'target-version = "py315"', 'target-version = "py311"')
        self.edit("pyproject.toml", 'python_version = "3.15"', 'python_version = "3.12"')
        self.append(
            "pyproject.toml",
            '\n[project]\nname = "demo"\nversion = "1"\nrequires-python = ">=3.11"\n',
        )
        self.assertFound("python:py311 is below", "python:3.12 is below", "python:3.11 is below")

    def test_requires_python_pins_only_its_lower_bound(self) -> None:
        self.append(
            "pyproject.toml",
            '\n[project]\nname = "demo"\nversion = "1"\nrequires-python = ">=3.15,!=3.13.0"\n',
        )
        self.assertEqual(self.found(), [])

    def test_a_folded_python_version_is_read(self) -> None:
        self.workflow(python=">-\n            3.13")
        self.assertFound("extra.yml:25: [pins] python:3.13 is below")
        self.edit(
            ".github/workflows/extra.yml",
            "          python-version: >-",
            "          # below-latest: the image ships 3.13\n          python-version: >-",
        )
        self.append(cq.WAIVERS, WAIVER.format(what="python:3.13"))
        self.assertEqual(self.found(), [])

    def test_a_folded_matrix_entry_ends_at_its_neighbor_key(self) -> None:
        self.workflow()
        self.edit(
            ".github/workflows/extra.yml",
            "      matrix:\n",
            "      matrix:\n        include:\n          - python: >-\n              3.15\n"
            '            library: "1.0"\n',
        )
        self.edit(
            ".github/workflows/extra.yml", "${{ matrix.python-version }}", "${{ matrix.python }}"
        )
        self.assertEqual(self.found(), [])

    def test_an_inline_reason_on_a_toml_line_counts(self) -> None:
        self.edit(
            "pyproject.toml",
            'target-version = "py315"',
            'target-version = "py313"  # below-latest: KiCad 10.0.8 runs 3.13',
        )
        self.assertFound("python:py313 weakens a kit rule and has no waiver")
        self.assertFalse(any("[pins] python:py313 is below" in f for f in self.found()))

    def test_ci_python_versions_inline_and_in_a_matrix(self) -> None:
        self.workflow(python='"3.13"', matrix="3.14")
        found = self.found()
        self.assertTrue(any("extra.yml:24: [pins] python:3.13" in f for f in found), found)
        self.assertTrue(any("extra.yml:19: [pins] python:3.14" in f for f in found), found)
        self.assertFalse(any("matrix" in f for f in found), found)

    def test_a_matrix_key_python_version_reads_is_a_pin(self) -> None:
        self.workflow()
        self.edit(
            ".github/workflows/extra.yml",
            "      matrix:\n",
            '      matrix:\n        python: ["3.15", "3.13"]\n'
            '        include:\n          - python: "3.12"\n',
        )
        self.edit(
            ".github/workflows/extra.yml",
            "${{ matrix.python-version }}",
            "${{ matrix.python }}",
        )
        self.assertFound("[pins] python:3.13 is below", "[pins] python:3.12 is below")

    def test_a_matrix_key_counts_only_in_the_job_that_reads_it(self) -> None:
        self.workflow()
        self.edit(
            ".github/workflows/extra.yml",
            "      matrix:\n",
            '      matrix:\n        version: ["3.15"]\n',
        )
        self.edit(
            ".github/workflows/extra.yml",
            "${{ matrix.python-version }}",
            "${{ matrix.version }}",
        )
        self.append(
            ".github/workflows/extra.yml",
            "  other:\n"
            '    name: "🧪 Other tool"\n'
            "    runs-on: ubuntu-latest\n"
            "    timeout-minutes: 5\n"
            "    strategy:\n"
            "      matrix:\n"
            '        version: ["1.0", "2.0"]\n'
            "    steps:\n"
            "      - run: echo ${{ matrix.version }}\n",
        )
        self.assertEqual(self.found(), [])
        self.edit(".github/workflows/extra.yml", 'version: ["3.15"]', 'version: ["3.13"]')
        self.assertFound("[pins] python:3.13 is below")
        self.edit(".github/workflows/extra.yml", "\njobs:\n", '\n"jobs":\n')
        self.assertFound("[pins] python:3.13 is below")

    def test_the_documented_reason_inside_with_counts(self) -> None:
        self.workflow(python='"3.9"')
        self.edit(
            ".github/workflows/extra.yml",
            '          python-version: "3.9"',
            "          # below-latest: the skills' scripts run on the python3 macOS ships (3.9)\n"
            '          python-version: "3.9"',
        )
        self.assertFound("python:3.9 weakens a kit rule and has no waiver")
        self.append(cq.WAIVERS, WAIVER.format(what="python:3.9"))
        self.assertEqual(self.found(), [])

    def test_an_action_below_its_latest_release_is_reported(self) -> None:
        self.workflow(checkout="v6.0.2")
        self.assertFound("extra.yml:21: [pins] action:actions/checkout@v6.0.2 is below", "(v7.0.1)")

    def test_an_action_reason_on_the_line_above(self) -> None:
        self.workflow(checkout="v6.0.2")
        self.edit(
            ".github/workflows/extra.yml",
            "      - uses: actions/checkout",
            "      # below-latest: v7 drops the node runtime this runner has\n"
            "      - uses: actions/checkout",
        )
        self.assertFound("action:actions/checkout@v6.0.2 weakens a kit rule and has no waiver")
        self.append(cq.WAIVERS, WAIVER.format(what="action:actions/checkout@v6.0.2"))
        self.assertEqual(self.found(), [])

    def test_an_action_the_kit_does_not_know_is_left_alone(self) -> None:
        self.workflow()
        self.edit(
            ".github/workflows/extra.yml",
            f"actions/checkout@{OLD_SHA} # v7.0.1",
            f"example/tool@{OLD_SHA} # v0.0.1",
        )
        self.assertEqual(self.found(), [])

    def test_a_hook_below_its_latest_release_is_reported(self) -> None:
        self.append(
            ".pre-commit-config.yaml",
            "  - repo: https://github.com/crate-ci/typos\n"
            f"    rev: {OLD_SHA}  # frozen: v1.40.0\n"
            "    hooks:\n      - id: typos\n",
        )
        self.assertFound("hook:https://github.com/crate-ci/typos@v1.40.0 is below", "(v1.52.2)")

    def test_a_known_hook_pinned_by_a_bare_commit_is_reported(self) -> None:
        self.append(
            ".pre-commit-config.yaml",
            "  - repo: https://github.com/crate-ci/typos\n"
            f"    rev: {OLD_SHA}\n"
            "    hooks:\n      - id: typos\n",
        )
        self.assertFound(
            "hook:https://github.com/crate-ci/typos pins a commit and names no release"
        )

    def test_a_hook_reason_above_its_repo_line(self) -> None:
        self.append(
            ".pre-commit-config.yaml",
            "  # below-latest: typos 1.52 misreads the generated tables\n"
            "  - repo: https://github.com/crate-ci/typos\n"
            "    rev: v1.40.0\n"
            "    hooks:\n      - id: typos\n",
        )
        what = "hook:https://github.com/crate-ci/typos@v1.40.0"
        self.assertFound(f"{what} weakens a kit rule and has no waiver")
        self.append(cq.WAIVERS, WAIVER.format(what=what))
        self.assertEqual(self.found(), [])

    def test_the_synced_hook_block_is_at_the_latest(self) -> None:
        self.assertFalse(any("[pins] hook:" in f for f in self.found()))


class KitKnowsItsOwnPinsTest(unittest.TestCase):
    """LATEST_* are the kit's own pins, so a bump of one is a bump of both."""

    def test_python(self) -> None:
        text = (fx.CENTRAL / ".python-version").read_text(encoding="utf-8").strip()
        self.assertEqual(tuple(int(x) for x in text.split(".")[:2]), cq.LATEST_PYTHON)

    def test_actions(self) -> None:
        pinned: dict[str, set[str]] = {}
        roots = [fx.CENTRAL / ".github/workflows", fx.QUALITY / "templates/workflows"]
        for path in sorted(p for root in roots for p in root.glob("*.yml")):
            for line in path.read_text(encoding="utf-8").splitlines():
                m = cq.USES_LINE.match(line)
                if not m or cq.KIT_USES.search(line) or m.group("ref").startswith("./"):
                    continue
                action = "/".join(m.group("ref").split("@")[0].split("/")[:2]).lower()
                pinned.setdefault(action, set()).add((m.group("comment") or "").strip("# "))
        self.assertEqual({a: {v} for a, v in cq.LATEST_ACTIONS.items()}, pinned)

    def test_hooks(self) -> None:
        text = (fx.CENTRAL / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        pairs = re.findall(r"- repo: (https://\S+)\n\s+rev: [0-9a-f]{40}  # frozen: (v\S+)", text)
        self.assertEqual({url.lower(): tag for url, tag in pairs}, cq.LATEST_HOOKS)


class LatestReleasesTest(unittest.TestCase):
    """The weekly report, against a fake upstream (no network)."""

    def upstream(self, newer: dict[str, str]) -> dict[str, object]:
        data: dict[str, object] = {
            lr.PYTHON_MANIFEST: [
                {"version": "3.99.0-alpha.1", "stable": False},
                {"version": newer.get("python", "3.15.2"), "stable": True},
            ]
        }
        for action, tag in cq.LATEST_ACTIONS.items():
            data[f"https://api.github.com/repos/{action}/releases/latest"] = {
                "tag_name": newer.get(action, tag)
            }
        for url, tag in cq.LATEST_HOOKS.items():
            repo = url.removeprefix("https://github.com/")
            data[f"https://api.github.com/repos/{repo}/releases/latest"] = {
                "tag_name": newer.get(url, tag)
            }
        for name, version in lr.tool_pins().items():
            data[f"https://pypi.org/pypi/{name}/json"] = {
                "info": {"version": newer.get(name, version)}
            }
        return data

    def fake(self, data: dict[str, object]) -> lr.GetJson:
        def get(url: str) -> object:
            if url not in data:
                missing = urllib.error.HTTPError(url, 404, "Not Found", Message(), None)
                missing.close()  # its empty body is never read
                raise missing
            return data[url]

        return get

    def test_nothing_newer_reports_nothing(self) -> None:
        self.assertEqual(lr.outdated(self.fake(self.upstream({})), binaries=False), [])

    def test_each_kind_of_newer_release_is_reported(self) -> None:
        newer = {
            "python": "3.16.0",
            "actions/checkout": "v8.0.0",
            "https://github.com/crate-ci/typos": "v1.60.0",
            "ruff": "9.9.9",
        }
        lines = lr.outdated(self.fake(self.upstream(newer)), binaries=False)
        self.assertEqual(len(lines), 4, lines)
        self.assertIn("Python: the kit knows 3.15, latest 3.16", lines)
        self.assertIn("action actions/checkout: pinned v7.0.1, latest v8.0.0", lines)

    def test_a_repository_without_releases_falls_back_to_its_version_tags(self) -> None:
        data = self.upstream({})
        url = "https://github.com/davidanson/markdownlint-cli2"
        del data["https://api.github.com/repos/davidanson/markdownlint-cli2/releases/latest"]
        data["https://api.github.com/repos/davidanson/markdownlint-cli2/tags?per_page=100"] = [
            {"name": "next"},
            {"name": "v0.30.0"},
            {"name": "v0.24.2"},
        ]
        lines = lr.outdated(self.fake(data), binaries=False)
        self.assertEqual(lines, [f"hook {url}: pinned v0.24.2, latest v0.30.0"])


class HelpersTest(unittest.TestCase):
    def test_versions_compare_by_number(self) -> None:
        self.assertTrue(cq.is_below((1, 9), (1, 10)))
        self.assertFalse(cq.is_below((1, 2), (1, 2, 0)))
        self.assertTrue(cq.is_below((0, 11, 0), (0, 11, 0, 1)))
        self.assertEqual(cq.version_tuple("# v7.0.1"), (7, 0, 1))

    def test_python_versions_in_every_spelling(self) -> None:
        names = [t for t, _ in cq.python_versions('">=3.11,<4"')]
        self.assertEqual(names, ["3.11"])
        self.assertEqual(cq.python_versions('"py313"'), [("py313", (3, 13))])
        self.assertEqual(cq.python_versions("3.13.5"), [("3.13.5", (3, 13))])
        self.assertEqual(cq.python_versions('"3.x"'), [])


if __name__ == "__main__":
    unittest.main()
