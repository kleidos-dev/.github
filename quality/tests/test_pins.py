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
KICAD_TAG, KICAD_DIGEST = cq.LATEST_IMAGES["kicad/kicad"]
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

    def image(self, ref: str, above: str = "") -> None:
        self.workflow()
        self.edit(
            ".github/workflows/extra.yml",
            "    runs-on: ubuntu-latest\n",
            f"    runs-on: ubuntu-latest\n    container:\n{above}      image: {ref}\n",
        )

    def test_a_known_image_at_its_latest_digest_is_clean(self) -> None:
        self.image(f"kicad/kicad@{KICAD_DIGEST} # {KICAD_TAG}")
        self.assertEqual(self.found(), [])
        self.image(f"docker.io/kicad/kicad:{KICAD_TAG}@{KICAD_DIGEST}")
        self.assertEqual(self.found(), [])

    def test_a_known_image_by_tag_only_is_reported(self) -> None:
        self.image(f"kicad/kicad:{KICAD_TAG}")
        self.assertFound(
            "extra.yml:15: [pins] image:kicad/kicad is pinned by tag only",
            f"kicad/kicad@{KICAD_DIGEST} # {KICAD_TAG}",
        )

    def test_a_known_image_by_digest_with_no_tag_is_reported(self) -> None:
        self.image(f"kicad/kicad@{KICAD_DIGEST}")
        self.assertFound("image:kicad/kicad pins a digest and names no tag")

    def test_the_latest_tag_with_another_digest_is_reported(self) -> None:
        self.image(f"kicad/kicad@sha256:{'b' * 64} # {KICAD_TAG}")
        self.assertFound(f"image:kicad/kicad:{KICAD_TAG} pins sha256:{'b' * 64}, not the digest")

    def test_an_older_image_needs_a_reason_and_a_waiver(self) -> None:
        self.image(f"kicad/kicad@sha256:{'c' * 64} # 9.0.9")
        self.assertFound(
            "image:kicad/kicad:9.0.9 is below the latest stable release"
            f" the kit knows ({KICAD_TAG})"
        )
        self.image(
            f"kicad/kicad@sha256:{'c' * 64} # 9.0.9",
            above="      # below-latest: the boards were drawn in KiCad 9\n",
        )
        self.assertFound("image:kicad/kicad:9.0.9 weakens a kit rule and has no waiver")
        self.append(cq.WAIVERS, WAIVER.format(what="image:kicad/kicad:9.0.9"))
        self.assertEqual(self.found(), [])

    def test_a_flow_mapping_container_and_a_service_are_read(self) -> None:
        self.image(f"kicad/kicad@{KICAD_DIGEST} # {KICAD_TAG}")
        self.edit(
            ".github/workflows/extra.yml",
            f"    container:\n      image: kicad/kicad@{KICAD_DIGEST} # {KICAD_TAG}\n",
            f"    container: {{image: 'kicad/kicad:{KICAD_TAG}', options: --user root}}\n"
            "    services:\n      kicad:\n        image: kicad/kicad:10.0.7\n",
        )
        self.assertFound(
            "extra.yml:14: [pins] image:kicad/kicad is pinned by tag only",
            "extra.yml:17: [pins] image:kicad/kicad is pinned by tag only",
        )

    def test_an_image_named_in_a_script_is_not_a_pin(self) -> None:
        self.image(f"kicad/kicad@{KICAD_DIGEST} # {KICAD_TAG}")
        self.append(
            ".github/workflows/extra.yml",
            "      - run: |\n          echo 'image: kicad/kicad:9.0.9'\n",
        )
        self.assertEqual(self.found(), [])

    def test_an_image_the_kit_does_not_know_is_left_alone(self) -> None:
        self.image("example/tool:1.0")
        self.assertEqual(self.found(), [])
        self.image("${{ matrix.image }}")
        self.assertEqual(self.found(), [])


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
        for name, (known_tag, known_digest) in cq.LATEST_IMAGES.items():
            tag, digest = newer.get(name, known_tag), newer.get(f"{name}@", known_digest)
            second = f"https://hub.docker.com/v2/repositories/{name}/tags?page=2"
            data[lr.DOCKER_TAGS.format(name=name)] = {
                "next": second,
                "results": [
                    {"name": "latest", "digest": digest},
                    {"name": "9.0.9", "digest": f"sha256:{'9' * 64}"},
                    {"name": "nightly-1.2.3", "digest": f"sha256:{'8' * 64}"},
                ],
            }
            # The newest tag on the second page: every page is read.
            data[second] = {"next": None, "results": [{"name": tag, "digest": digest}]}
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
            "kicad/kicad": "10.1.0",
            "kicad/kicad@": f"sha256:{'d' * 64}",
        }
        lines = lr.outdated(self.fake(self.upstream(newer)), binaries=False)
        self.assertEqual(len(lines), 5, lines)
        self.assertIn("Python: the kit knows 3.15, latest 3.16", lines)
        self.assertIn("action actions/checkout: pinned v7.0.1, latest v8.0.0", lines)
        self.assertIn(
            f"image kicad/kicad: pinned {KICAD_TAG}, latest 10.1.0 (sha256:{'d' * 64})", lines
        )

    def test_an_image_tag_pushed_again_is_reported(self) -> None:
        newer = {"kicad/kicad@": f"sha256:{'e' * 64}"}
        lines = lr.outdated(self.fake(self.upstream(newer)), binaries=False)
        self.assertEqual(
            lines,
            [
                f"image kicad/kicad: {KICAD_TAG} now names sha256:{'e' * 64},"
                f" the kit knows {KICAD_DIGEST}"
            ],
        )

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


SUB_REQS = "# The drawing stack.\n-r more.txt\nplaywright==1.65.1\n"
SUB_MORE = "charset-normalizer=={charset}\n"
SUB_WAIVER = (
    '\n[[waiver]]\ntool = "pins"\nwhat = "{what}"\n'
    'reason = "The pictures are redrawn with the next commit first"\n'
    'decided = "owner 2026-11-23"\n'
)


class SubmodulePinsTest(unittest.TestCase):
    """Pins a requirements file takes from a submodule (-r brand/requirements.txt)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.upstream = fx.init(tmp / "brand")
        fx.write(self.upstream, "requirements.txt", SUB_REQS)
        fx.write(self.upstream, "more.txt", SUB_MORE.format(charset="3.5.2"))
        fx.commit(self.upstream, "Pin the stack")
        self.old = fx.git(self.upstream, "rev-parse", "HEAD").strip()
        self.root = fx.consumer(tmp / "repo")
        sync.write(self.root, commit=fx.FAKE_COMMIT)
        fx.write(
            self.root,
            ".gitmodules",
            f'[submodule "brand"]\n\tpath = brand\n\turl = {self.upstream}\n',
        )
        fx.write(
            self.root,
            "requirements.txt",
            fx.header() + "-r brand/requirements.txt\npyyaml==6.0.4\n",
        )
        self.point_at(self.old)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def point_at(self, commit: str) -> None:
        fx.git(self.root, "update-index", "--add", "--cacheinfo", f"160000,{commit},brand")

    def upstream_commit(self, rel: str, text: str) -> str:
        fx.write(self.upstream, rel, text)
        fx.commit(self.upstream, f"Change {rel}")
        return fx.git(self.upstream, "rev-parse", "HEAD").strip()

    def found(self, online: bool = True) -> list[str]:
        kit = cq.DirKit(fx.CENTRAL) if online else None
        report = cq.run(self.root, kit=kit, today=TODAY)
        self.notes = report.notes
        return [f"{p.where}: [{p.rule}] {p.message}" for p in report.problems]

    def test_a_submodule_at_its_tip_is_clean(self) -> None:
        self.assertEqual(self.found(), [])

    def test_a_pin_the_tip_moved_is_reported_through_a_nested_include(self) -> None:
        tip = self.upstream_commit("more.txt", SUB_MORE.format(charset="3.5.3"))
        found = self.found()
        self.assertEqual(len(found), 1, found)
        self.assertIn(f"requirements.txt:3: [pins] submodule:brand@{self.old[:7]}", found[0])
        self.assertIn("charset-normalizer==3.5.3 (here 3.5.2)", found[0])
        self.assertIn(f"move the submodule to {tip[:7]}", found[0])
        self.point_at(tip)
        self.assertEqual(self.found(), [])

    def test_a_tip_that_changes_no_pin_is_clean(self) -> None:
        self.upstream_commit("README.md", "The brand.\n")
        self.assertEqual(self.found(), [])

    def test_added_and_dropped_pins_are_reported(self) -> None:
        self.upstream_commit("requirements.txt", "-r more.txt\nfonttools==4.60.0\n")
        found = "\n".join(self.found())
        self.assertIn("fonttools==4.60.0 (here none)", found)
        self.assertIn("no playwright (here playwright==1.65.1)", found)

    def test_an_included_file_the_tip_removed_is_reported(self) -> None:
        fx.git(self.upstream, "mv", "requirements.txt", "stack.txt")
        fx.commit(self.upstream, "Rename the stack")
        self.assertTrue(any("no requirements.txt any more" in f for f in self.found()))

    def test_a_named_branch_is_followed(self) -> None:
        fx.git(self.upstream, "checkout", "-q", "-b", "stable")
        self.upstream_commit("more.txt", SUB_MORE.format(charset="3.5.3"))
        fx.git(self.upstream, "checkout", "-q", "main")
        self.assertEqual(self.found(), [])
        self.append_gitmodules("\tbranch = stable\n")
        self.assertTrue(any("tip of its stable" in f for f in self.found()))

    def append_gitmodules(self, text: str) -> None:
        path = self.root / ".gitmodules"
        path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")

    def test_branch_dot_follows_the_parent_branch(self) -> None:
        fx.git(self.upstream, "checkout", "-q", "-b", "release")
        self.upstream_commit("more.txt", SUB_MORE.format(charset="3.5.3"))
        fx.git(self.upstream, "checkout", "-q", "main")
        self.append_gitmodules("\tbranch = .\n")
        self.assertEqual(self.found(), [])
        fx.git(self.root, "checkout", "-q", "-b", "release")
        self.assertTrue(any("tip of its release" in f for f in self.found()))

    def test_a_reason_beside_the_include_needs_a_waiver(self) -> None:
        self.upstream_commit("more.txt", SUB_MORE.format(charset="3.5.3"))
        what = f"submodule:brand@{self.old[:7]}"
        fx.write(
            self.root,
            "requirements.txt",
            fx.header()
            + "# below-latest: the pictures are redrawn with the next commit first\n"
            + "-r brand/requirements.txt\npyyaml==6.0.4\n",
        )
        self.assertTrue(any(f"{what} weakens a kit rule" in f for f in self.found()))
        path = self.root / cq.WAIVERS
        path.write_text(
            path.read_text(encoding="utf-8") + SUB_WAIVER.format(what=what), encoding="utf-8"
        )
        self.assertEqual(self.found(), [])
        # Offline nothing is compared, and the waiver is not called unused.
        self.assertEqual(self.found(online=False), [])

    def test_offline_it_compares_nothing_and_says_so(self) -> None:
        self.upstream_commit("more.txt", SUB_MORE.format(charset="3.5.3"))
        self.assertFalse(any("submodule:" in f for f in self.found(online=False)))
        self.assertIn("offline: the pins a submodule supplies are not compared", self.notes)

    def test_a_branch_that_reads_as_an_option_is_refused(self) -> None:
        marker = self.root / "ran"
        self.append_gitmodules(f"\tbranch = --upload-pack=touch {marker}\n")
        self.upstream_commit("more.txt", SUB_MORE.format(charset="3.5.3"))
        found = self.found()
        self.assertTrue(any("is not a plain branch name" in f for f in found), found)
        self.assertFalse(marker.exists())

    def test_a_pin_per_platform_is_compared_per_platform(self) -> None:
        win = "charset-normalizer==3.5.1 ; sys_platform == 'win32'\n"
        self.upstream_commit("more.txt", win + SUB_MORE.format(charset="3.5.2"))
        self.point_at(fx.git(self.upstream, "rev-parse", "HEAD").strip())
        self.upstream_commit(
            "more.txt", win.replace("3.5.1", "3.5.3") + SUB_MORE.format(charset="3.5.2")
        )
        found = "\n".join(self.found())
        self.assertIn("charset-normalizer==3.5.3 ; sys_platform == 'win32' (here 3.5.1)", found)

    def test_an_unreachable_upstream_is_reported(self) -> None:
        fx.write(
            self.root,
            ".gitmodules",
            f'[submodule "brand"]\n\tpath = brand\n\turl = {self.upstream}-gone\n',
        )
        self.assertTrue(any("could not be fetched" in f for f in self.found()))

    def test_a_requirements_file_without_a_submodule_include_fetches_nothing(self) -> None:
        fx.write(self.root, "requirements.txt", fx.header() + "pyyaml==6.0.4\n")
        fx.write(
            self.root, ".gitmodules", '[submodule "brand"]\n\tpath = brand\n\turl = /nowhere\n'
        )
        self.assertEqual(self.found(), [])


class SubmoduleHelpersTest(unittest.TestCase):
    def test_requirement_pins_normalizes_names_and_stays_inside_the_tree(self) -> None:
        files = {
            "requirements.txt": "-r sub/more.txt\n-c ../outside.txt\nFoo_Bar[x]==1.2  # why\n",
            "sub/more.txt": "--requirement=../extra.txt\nbaz===2.0 ; python_version > '3'\n",
            "extra.txt": "qux==3\nloose>=1\n",
        }
        pins = cq.requirement_pins(files.get, "requirements.txt")
        self.assertEqual(pins, {"foo-bar": "1.2", "baz ; python_version > '3'": "2.0", "qux": "3"})
        self.assertIsNone(cq.requirement_pins(files.get, "missing.txt"))

    def test_requirements_files_by_name_or_folder(self) -> None:
        for rel in (
            "requirements.txt",
            "requirements-dev.in",
            "deps.in",
            "ci/constraints.txt",
            "requirements/base.txt",
        ):
            self.assertTrue(cq.is_requirements_file(rel), rel)
        for rel in ("README.txt", "requirements.toml", "notes/list.txt"):
            self.assertFalse(cq.is_requirements_file(rel), rel)


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
