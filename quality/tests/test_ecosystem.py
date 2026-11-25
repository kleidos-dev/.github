# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""ecosystem.py: each state, each planted defect, and a public run that names nothing private."""

from __future__ import annotations

import contextlib
import datetime as dt
import http.server
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import kit_fixtures as fx
from kit_fixtures import ecosystem as eco
from kit_fixtures import kit_preview, landing

NOW = dt.datetime(2026, 11, 24, 12, tzinfo=dt.UTC)
KIT, BOARDS, BRAND, CLA = (f"kleidos-dev/{n}" for n in (".github", "boards", "brand", "cla"))
SECRET, FIRMWARE = "kleidos-dev/hidden", "jmrplens/kleidos"
SHA = "a" * 40

RAW = """
[organization]
login = "kleidos-dev"
kit = "kleidos-dev/.github"
deploy_keys = false
bypass = ["OrganizationAdmin"]
[limits]
copy = 14
bot_pull = 14
public_run = 8
worker = 7
[limits.source]
"kleidos-dev/boards" = 30
[required_checks]
"gate" = 1
[rules]
main = ["deletion", "update"]
kit_branch = ["creation"]
kit_tags = ["deletion"]
[[worker]]
url = "https://cla.example/version"
repository = "kleidos-dev/cla"
path = "worker"
[[repository]]
slug = "kleidos-dev/.github"
public = true
cla = true
sonar = "k_github"
[[repository]]
slug = "kleidos-dev/boards"
public = true
[[repository]]
slug = "kleidos-dev/brand"
public = true
folds_into = "kleidos-dev/boards"
[[repository]]
slug = "kleidos-dev/cla"
public = true
[[repository]]
slug = "kleidos-dev/hidden"
public = false
[[repository]]
slug = "jmrplens/kleidos"
public = false
hold = true
"""


class FakeReader(eco.Reader):
    """The outside as tables; whatever is asked of it is kept."""

    def __init__(self) -> None:
        super().__init__(Path("/nowhere"), ssh=False)
        self.tree_of: dict[str, dict[str, bytes]] = {}
        self.answers: dict[str, Any] = {}
        self.statuses: dict[str, int] = {}
        self.pages: dict[str, bytes] = {}
        self.trees: dict[str, str] = {}
        self.asked: list[str] = []

    def put(self, slug: str, path: str, content: str | bytes) -> str:
        data = content.encode() if isinstance(content, str) else content
        self.tree_of.setdefault(slug, {})[path] = data
        return eco.sha256(data)

    def api(self, path: str, pages: bool = False) -> Any:
        self.asked.append(path)
        return self.answers.get(path)

    def fetch(self, slug: str) -> bool:
        self.asked.append(f"clone {slug}")
        return True

    def files(self, slug: str) -> list[str]:
        self.asked.append(f"files {slug}")
        return list(self.tree_of.get(slug, {}))

    def prefetch(self, slug: str, paths: Iterable[str]) -> None:
        self.asked.append(f"fetch {slug} {sorted(paths)}")

    def read(self, slug: str, path: str) -> bytes | None:
        self.asked.append(f"read {slug} {path}")
        return self.tree_of.get(slug, {}).get(path)

    def tree(self, slug: str, path: str) -> str:
        return self.trees.get(f"{slug}:{path}", "")

    def status(self, url: str) -> int:
        self.asked.append(url)
        return self.statuses.get(url, 200)

    def page(self, url: str) -> bytes | None:
        return self.pages.get(url)


class ReportCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "ecosystem.toml"
        self.path.write_text(RAW, encoding="utf-8")
        self.reader = FakeReader()
        self.report = self.fresh()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def fresh(self, everything: bool = False) -> eco.Report:
        local = self.path.with_name("local.toml")
        self.report = eco.Report(eco.load(self.path), self.reader, NOW, everything, local)
        return self.report

    def rows(self, state: str | None = None, kind: str | None = None) -> list[str]:
        return [
            r.text
            for r in self.report.rows
            if (state is None or r.state == state) and (kind is None or r.kind == kind)
        ]

    def record(self, consumer: str, rel: str, data: dict[str, Any]) -> None:
        self.reader.put(consumer, rel, json.dumps(data))

    def copies(self, everything: bool = False) -> eco.Report:
        report = self.fresh(everything)
        for copy in eco.find_copies(report):
            eco.judge_copy(report, copy)
        return report


class CopyTest(ReportCase):
    """A record of copies, in each dialect, in each state."""

    def vendored(self, taken: str = "2026-11-20", **more: Any) -> dict[str, Any]:
        digest = self.reader.put(CLA, "art/mark.svg", "<svg/>")
        return {
            "schema": "kleidos.vendored-copy/1",
            "upstream": {"repo": BOARDS, "path": "svg", "commit": SHA},
            "mode": "follow",
            "taken": taken,
            "files": {"mark.svg": digest},
            **more,
        }

    def judge(self, data: dict[str, Any], source: str | None = "<svg/>") -> list[tuple[str, str]]:
        self.record(CLA, "art/SOURCE.json", data)
        if source is not None:
            self.reader.put(BOARDS, "svg/mark.svg", source)
        report = self.copies()
        return [(r.state, r.text) for r in report.rows]

    def test_equal_digests_are_green_however_old(self) -> None:
        found = self.judge(self.vendored(taken="2020-01-01"))
        self.assertEqual(found, [("green", f"{CLA} <- {BOARDS} art/SOURCE.json: 1 equal")])

    def test_behind_is_amber_until_its_limit_and_then_late(self) -> None:
        for taken, limit, state in (
            ("2026-11-24", None, "amber"),
            ("2026-10-25", None, "amber"),  # 30 days: boards' own limit
            ("2026-10-24", None, "late"),
            ("2026-11-20", 4, "amber"),
            ("2026-11-19", 4, "late"),
        ):
            with self.subTest(taken=taken, limit=limit):
                found = self.judge(self.vendored(taken, max_age_days=limit), "<svg>new</svg>")
                self.assertEqual([s for s, _t in found], [state], found)
                self.assertIn("1 of 1 differ", found[0][1])
                self.assertEqual("[limit" in found[0][1], state == "late")

    def test_a_frozen_copy_has_no_limit(self) -> None:
        data = self.vendored("2020-01-01", mode="frozen", reason="x")
        self.assertEqual([s for s, _t in self.judge(data, "<svg>new</svg>")], ["frozen"])

    def test_the_kits_own_record_is_never_more_than_amber(self) -> None:
        data = self.vendored("2020-01-01", upstream={"repo": KIT, "path": ".", "commit": SHA})
        data["root"], data["sources"] = ".", {"art/mark.svg": "quality/mark.svg"}
        data["files"] = {"art/mark.svg": data["files"]["mark.svg"]}
        self.reader.put(KIT, "quality/mark.svg", "<svg>new</svg>")
        found = self.judge(data)
        self.assertEqual([s for s, _t in found], ["amber"], found)
        del self.reader.tree_of[KIT]
        self.assertEqual(self.judge(data), [])

    def test_a_copy_edited_in_place_is_red(self) -> None:
        data = self.vendored()
        self.reader.put(CLA, "art/mark.svg", "<svg>mine</svg>")
        found = self.judge(data)
        self.assertEqual([s for s, _t in found], ["red", "green"], found)
        self.assertIn("edited in place, or gone: art/mark.svg", found[0][1])
        del self.reader.tree_of[CLA]["art/mark.svg"]
        self.assertEqual([s for s, _t in self.judge(data)], ["red", "green"])

    def test_a_source_that_is_gone_is_red(self) -> None:
        for mode in ({"mode": "follow"}, {"mode": "frozen", "reason": "x"}):
            found = self.judge(self.vendored(**mode), None)
            self.assertEqual([s for s, _t in found], ["red"], found)
            self.assertIn("no longer has svg/mark.svg", found[0][1])

    def test_the_date_of_a_record_stands_in_for_its_own(self) -> None:
        data = self.vendored(taken="")
        path = f"repos/{CLA}/commits?path=art/SOURCE.json&per_page=1"
        when = {"commit": {"committer": {"date": "2026-09-01T00:00:00Z"}}}
        self.reader.answers[path] = [when]
        self.assertEqual([s for s, _t in self.judge(data, "<svg>new</svg>")], ["late"])
        self.reader.answers[path] = []
        self.assertEqual([s for s, _t in self.judge(data, "<svg>new</svg>")], ["amber"])

    def test_the_older_dialects(self) -> None:
        digest = self.reader.put(BRAND, "x/a.svg", "a")
        other = self.reader.put(BRAND, "x/k.py", "k")
        self.record(
            BRAND,
            "x/boards.json",
            {
                "repository": f"https://github.com/{BOARDS}",
                "commit": SHA,
                "boards": {"a": {"from": "a/front.svg", "sha256": digest}},
            },
        )
        self.record(
            BOARDS,
            "x/KIT.json",
            {
                "kit": "kleidos-kicad/1",
                "source": f"https://github.com/{BRAND}.git",
                "files": {"k.py": other},
            },
        )
        self.reader.put(BOARDS, "x/k.py", "k")
        self.reader.put(BOARDS, "a/front.svg", "new")
        self.reader.put(BRAND, "kicad/k.py", "k")
        self.copies()
        self.assertEqual(
            self.rows("frozen"),
            [f"{BRAND} <- {BOARDS} x/boards.json: 1 of 1 differ, taken 0 d ago: a/front.svg"],
        )
        self.assertEqual(self.rows("green"), [f"{BOARDS} <- {BRAND} x/KIT.json: 1 equal"])

    def test_the_dialects_with_no_bytes(self) -> None:
        self.record(BRAND, "tokens/mirror.json", {"files": {"src/theme.h": "0" * 64}})
        self.record(
            FIRMWARE,
            "qa/meter-registry.lock.json",
            {
                "repo": BOARDS,
                "commit": SHA,
                "index_sha256": "0" * 64,
                "taken": "2026-11-01",
            },
        )
        self.reader.put(FIRMWARE, "src/theme.h", "x")
        self.reader.put(BOARDS, "calibration/index.json", "x")
        self.copies(everything=True)
        self.assertEqual(len(self.rows("frozen")), 1)
        self.assertEqual(len(self.rows("amber")), 1)

    def test_a_generators_output_is_not_comparable(self) -> None:
        data = self.vendored(upstream={"repo": BOARDS, "path": "make", "commit": None})
        self.record(CLA, "art/SOURCE.json", data)
        self.copies(everything=True)
        self.assertEqual(
            self.rows("note"),
            [f"{CLA} <- {BOARDS} art/SOURCE.json: 1 held, its source not comparable"],
        )
        self.copies()
        self.assertEqual(self.rows(), [])

    def test_files_that_are_no_record(self) -> None:
        for rel, body in (
            ("a/SOURCE.json", "[]"),
            ("a/KIT.json", '{"kit": "other"}'),
            ("a/boards.json", "{}"),
            ("a/mirror.json", "{}"),
            ("tests/fixtures/SOURCE.json", "{"),
        ):
            self.reader.put(CLA, rel, body)
        self.copies()
        self.assertEqual(self.rows(), [])

    def test_a_record_that_does_not_read_is_red(self) -> None:
        for n, body in enumerate(("{", '{"schema": "kleidos.vendored-copy/1"}')):
            self.reader.put(CLA, f"a{n}/SOURCE.json", body)
        self.copies()
        self.assertEqual(len(self.rows("red")), 2)

    def test_names_are_cut_after_three(self) -> None:
        self.assertEqual(eco.named(["b", "a", "c"]), "a, b, c")
        self.assertEqual(eco.named("edcba"), "a, b, c and 2 more")


class PublicTest(ReportCase):
    """A public run asks nothing about a private repository and prints none of their names."""

    def plant(self) -> None:
        """Private names in every place the report reads."""
        digest = self.reader.put(CLA, "art/mark.svg", "mine")
        for rel, source in (("art", SECRET), ("fw", FIRMWARE)):
            self.record(
                CLA,
                f"{rel}/SOURCE.json",
                {
                    "schema": "kleidos.vendored-copy/1",
                    "upstream": {"repo": source, "path": ".", "commit": SHA},
                    "mode": "follow",
                    "taken": "2020-01-01",
                    "files": {"mark.svg": digest + "0"},
                },
            )
        self.record(BRAND, "tokens/mirror.json", {"files": {"src/x.h": digest}})
        self.reader.put(SECRET, "README.md", "[x](https://secret.example/)")
        self.reader.put(
            CLA,
            "README.md",
            (
                f"[a](https://github.com/{SECRET}) [b](https://github.com/{FIRMWARE}/issues)"
                f" [c](https://raw.githubusercontent.com/{SECRET.upper()}/x) [d](https://fine.example/)"
            ),
        )
        for url in (
            f"https://github.com/{SECRET}",
            f"https://github.com/{FIRMWARE}/issues",
            f"https://raw.githubusercontent.com/{SECRET.upper()}/x",
        ):
            self.reader.statuses[url] = 404
        self.pull(CLA, f"Bump {SECRET}")
        self.reader.answers[f"repos/{KIT}/tags?per_page=100"] = [{"name": "v3.0.0"}]
        self.reader.answers[f"repos/{KIT}/branches?per_page=100"] = [{"name": "v3"}]
        self.reader.unread = [f"{SECRET}: cannot be cloned"]

    def pull(self, slug: str, title: str) -> None:
        self.reader.answers[f"repos/{slug}/pulls?state=open&per_page=100"] = [
            {
                "user": {"type": "Bot"},
                "number": 3,
                "title": title,
                "created_at": "2026-11-23T00:00:00Z",
                "head": {"sha": SHA},
            }
        ]

    def build(self, everything: bool) -> str:
        report = self.fresh(everything)
        head = eco.build(report, lambda: [f"hook {SECRET}: old"])
        return eco.render(report, head)

    def test_nothing_private_is_asked_or_printed(self) -> None:
        self.plant()
        text = self.build(everything=False)
        for name in (SECRET, FIRMWARE, "hidden", "jmrplens"):
            self.assertNotIn(name, text.lower(), name)
        asked = "\n".join(a for a in self.reader.asked if not a.startswith("https://"))
        self.assertNotIn(SECRET, asked)
        self.assertNotIn(FIRMWARE, asked)
        self.assertEqual(self.report.withheld, 8)
        self.assertIn("Only the local run (report --all) reads:", text)
        self.assertNotIn("installations", asked)

    def test_the_local_run_sees_what_the_public_one_withholds(self) -> None:
        self.plant()
        text = self.build(everything=True)
        for name in (SECRET, FIRMWARE):
            self.assertIn(name, text)
        self.assertEqual(self.report.withheld, 0)
        self.assertNotIn("Only the local run", text)

    def test_what_each_half_reads(self) -> None:
        both = {"copy", "kit", "pin", "pull", "link", "leaving", "sonar", "unread"}
        local = {"setting", "worker", "schedule"}
        head = "Kleidos ecosystem, 2026-11-24 12:00 UTC"
        for everything, kinds, said in (
            (False, both, f"# {head}, the public repositories\n"),
            (True, both | local, f"# {head}, every repository; no public run yet\n"),
        ):
            self.plant()
            self.reader.unread = ["x: y"]
            own = self.reader.put(BOARDS, "x/k.py", "k")
            self.reader.put(BRAND, "kicad/k.py", "k")
            kit = {"kit": "kleidos-kicad/1", "source": BRAND, "files": {"k.py": own}}
            self.record(BOARDS, "x/KIT.json", kit)
            self.pull(BOARDS, "Bump x")
            app = {"app_slug": "odd", "permissions": {"contents": "write"}}
            path = "orgs/kleidos-dev/installations?per_page=100"
            self.reader.answers[path] = {"installations": [app]}
            report = self.fresh(everything)
            report.local.write_text("[apps]\n", encoding="utf-8")
            text = eco.render(report, eco.build(report, lambda: ["a pin"]))
            self.assertEqual({r.kind for r in report.rows}, kinds)
            self.assertEqual("the App odd can write contents" in text, everything)
            self.assertTrue(text.startswith(said), text[:120])
            self.assertEqual(
                "clone kleidos-dev/hidden" in self.reader.asked, everything, self.reader.asked
            )

    def test_the_contents_of_what_is_read_are_fetched_at_once(self) -> None:
        for rel in (".github/x.yml", "README.md", "a/SOURCE.json", "a/b.txt", "pic.png", "i.svg"):
            self.reader.put(CLA, rel, "{}")
        list(eco.find_copies(self.fresh()))
        fetched = next(a for a in self.reader.asked if a.startswith(f"fetch {CLA}"))
        self.assertEqual(fetched, f"fetch {CLA} ['.github/x.yml', 'README.md', 'a/SOURCE.json']")

    def test_what_names_a_private_repository(self) -> None:
        declared = eco.load(self.path)
        for text, names in (
            ("kleidos-dev/hidden", True),
            ("see KLEIDOS-DEV/Hidden.", True),
            ("github.com/kleidos-dev/hidden/issues", True),
            ("git@github.com:jmrplens/kleidos.git", True),
            ("kleidos-dev/hidden-not", False),
            ("kleidos-dev/hiddenly", False),
            ("kleidos-dev/hidden.tools", False),
            ("kleidos-dev/boards", False),
            ("jmrplens/kleidoscope", False),
            ("hidden", False),
        ):
            with self.subTest(text=text):
                self.assertIs(eco.names_private(declared, text), names)

    def test_the_shipped_list_says_what_is_private_and_nothing_of_it(self) -> None:
        declared = eco.load()
        public = {r.slug for r in declared.repositories if r.public}
        self.assertEqual(
            public, {f"kleidos-dev/{n}" for n in (".github", "boards", "brand", "cla")}
        )
        for repo in declared.repositories:
            if not repo.public:
                self.assertFalse(repo.cla or repo.sonar, repo.slug)
        for worker in declared.raw["worker"]:
            self.assertIn(worker["repository"], public)

    def test_the_command_prints_the_public_half(self) -> None:
        self.plant()
        with (
            mock.patch.object(eco, "Reader", return_value=self.reader) as made,
            mock.patch.object(eco, "kit_pins_behind", return_value=[]),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            status = eco.main(["--declared", str(self.path), "report"])
        self.assertEqual(made.call_args.kwargs, {"ssh": False})
        self.assertEqual(status, 0, out.getvalue())
        self.assertNotIn(SECRET, out.getvalue())

    def test_a_report_that_would_name_one_is_not_printed(self) -> None:
        with (
            mock.patch.object(eco, "Reader", return_value=self.reader),
            mock.patch.object(eco, "build", return_value=f"head {SECRET}"),
            contextlib.redirect_stdout(io.StringIO()) as out,
            contextlib.redirect_stderr(io.StringIO()) as err,
        ):
            status = eco.main(["--declared", str(self.path), "report"])
        self.assertEqual((status, out.getvalue()), (2, ""))
        self.assertIn("would name a private repository", err.getvalue())
        self.assertNotIn(SECRET, err.getvalue())

    def test_the_local_run_is_refused_in_ci(self) -> None:
        for verb in ("report", "preview"):
            with (
                mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}),
                mock.patch.object(eco, "Reader", side_effect=AssertionError),
                contextlib.redirect_stderr(io.StringIO()) as err,
            ):
                self.assertEqual(eco.main([verb, "--all"]), 2)
            self.assertIn("never for CI", err.getvalue())


class KitTest(ReportCase):
    def setUp(self) -> None:
        super().setUp()
        self.names(["v3.0.0", "v3.1.0", "quality-v2.3.0"], ["main", "v3"])
        self.reader.answers[f"repos/{KIT}/compare/v3...main"] = {"behind_by": 0}

    def names(self, tags: list[str], branches: list[str]) -> None:
        for kind, names in (("tags", tags), ("branches", branches)):
            path = f"repos/{KIT}/{kind}?per_page=100"
            self.reader.answers[path] = [{"name": n} for n in names]

    def check(self) -> list[tuple[str, str]]:
        report = self.fresh()
        eco.check_kit(report)
        return [(r.state, r.text) for r in report.rows]

    def call(self, slug: str, ref: str, rev: str = "v3.1.0") -> None:
        uses = f"    uses: kleidos-dev/.github/.github/workflows/quick.yml@{ref}\n"
        self.reader.put(slug, ".github/workflows/ci.yml", uses)
        self.reader.put(
            slug,
            ".pre-commit-config.yaml",
            f"repos:\n  - repo: https://github.com/kleidos-dev/.github\n    # x\n    rev: {rev}\n",
        )

    def test_sound_names_are_green(self) -> None:
        self.assertIn(("green", f"{KIT}: v3 is on main, newest release v3.1.0"), self.check())

    def test_the_newest_is_by_number(self) -> None:
        self.names(["v3.9.0", "v3.10.0"], ["v3"])
        self.assertIn("newest release v3.10.0", self.check()[0][1])

    def test_each_unsound_name_is_red(self) -> None:
        self.reader.answers[f"repos/{KIT}/compare/v3...main"] = {"behind_by": 2}
        self.assertIn(("red", f"{KIT}: v3 is not on main"), self.check())
        self.names(["v3.0.0", "v3"], ["main", "v3"])
        self.assertIn("a tag and a branch are both named v3", self.check()[0][1])
        self.names(["v3.0.0"], ["main"])
        self.assertIn(("red", f"{KIT}: no branch v3, which every repository calls"), self.check())
        self.names([], ["main"])
        self.assertEqual([s for s, _t in self.check()], ["note"])

    def test_how_each_repository_calls_it(self) -> None:
        for ref, rev, state, needle in (
            ("v3", "v3.1.0", "green", "at v3, hooks at v3.1.0"),
            ("v3", "v3.0.0", "amber", "hooks at v3.0.0, newest v3.1.0"),
            (SHA, "v3.1.0", "amber", "kit 2.x copies, not v3"),
            ("v2", "v3.1.0", "amber", "v2, not v3"),
            ("main", "v3.1.0", "amber", "main, not v3"),
        ):
            with self.subTest(ref=ref, rev=rev):
                self.call(BOARDS, ref, rev)
                found = [(s, t) for s, t in self.check() if t.startswith(BOARDS)]
                self.assertEqual([s for s, _t in found], [state])
                self.assertIn(needle, found[0][1])
        del self.reader.tree_of[BOARDS][".pre-commit-config.yaml"]
        self.call(BOARDS, "v3")
        del self.reader.tree_of[BOARDS][".pre-commit-config.yaml"]
        self.assertIn(("amber", f"{BOARDS}: at v3, hooks at none, newest v3.1.0"), self.check())

    def test_a_repository_that_leaves_is_not_judged(self) -> None:
        found = self.check()
        self.assertFalse(any(t.startswith(BRAND) for _s, t in found))
        self.assertIn(("amber", f"{CLA}: does not call the kit yet"), found)

    def test_the_kits_own_pins(self) -> None:
        for outdated, state, text in (
            (lambda: ["a is behind"], "amber", "a is behind"),
            (list, "green", "every kit pin is at its latest release"),
        ):
            report = self.fresh()
            eco.check_pins(report, outdated)
            self.assertEqual([(r.state, r.text) for r in report.rows], [(state, text)])
        report = self.fresh()
        eco.check_pins(report, mock.Mock(side_effect=OSError("down")))
        self.assertEqual([r.state for r in report.rows], ["note"])


class PullTest(ReportCase):
    def pulls(self, slug: str = BOARDS, **more: Any) -> list[tuple[str, str]]:
        self.reader.answers[f"repos/{slug}/pulls?state=open&per_page=100"] = [
            {
                "user": {"type": "Bot"},
                "number": 3,
                "title": "Bump x",
                "head": {"sha": SHA},
                "created_at": "2026-11-20T00:00:00Z",
                **more,
            }
        ]
        report = self.fresh()
        eco.check_pulls(report)
        return [(r.state, r.text) for r in report.rows]

    def test_waiting_and_failing(self) -> None:
        self.assertEqual(self.pulls(), [("amber", f"{BOARDS}#3 open 4 d: Bump x")])
        for created, state in (("2026-11-10T00:00:00Z", "amber"), ("2026-11-09T00:00:00Z", "late")):
            self.assertEqual([s for s, _t in self.pulls(created_at=created)], [state], created)
        runs = f"repos/{BOARDS}/commits/{SHA}/check-runs?per_page=100"
        for conclusion in ("failure", "timed_out", "startup_failure"):
            self.reader.answers[runs] = {"check_runs": [{"name": "CI", "conclusion": conclusion}]}
            self.assertEqual(self.pulls(), [("red", f"{BOARDS}#3 open 4 d: Bump x [failing: CI]")])
        for other in ("cancelled", "skipped", "neutral", "success", None):
            self.reader.answers[runs] = {"check_runs": [{"name": "CI", "conclusion": other}]}
            self.assertEqual([s for s, _t in self.pulls()], ["amber"])

    def test_a_persons_pull_request_is_theirs(self) -> None:
        self.assertEqual(self.pulls(user={"type": "User"}), [])


class PatternTest(unittest.TestCase):
    """What the report reads in other repositories' text, character by character."""

    def test_a_call_of_the_kit(self) -> None:
        call = "uses: kleidos-dev/.github/.github/workflows/quick.yml@v3"
        for line, ref in (
            (call, "v3"),
            (f"    {call} # why", "v3"),
            (f"      - {call}", "v3"),
            (call.replace("kleidos", "'kleidos") + "'", "v3"),
            (call.replace("kleidos", '"kleidos') + '"', "v3"),
            (call.replace("v3", "a" * 40), "a" * 40),
            (call.replace("@v3", "@"), None),
            (call.replace("@v3", ""), None),
            (f"# {call}", None),
            (f"x{call}", None),
            (call.replace("/.github/.github", "/xgithub/.github"), None),
            (call.replace("/.github/.github", "/.github/xgithub"), None),
            (call.replace("kleidos-dev", "other"), None),
            (call.replace("quick.yml", "x/quick.yml"), None),
        ):
            found = eco.KIT_CALL.search(f"jobs:\n{line}\n")
            self.assertEqual(found["ref"] if found else None, ref, line)

    def test_the_rev_of_the_hooks(self) -> None:
        url = "https://github.com/kleidos-dev/.github"
        for text, rev in (
            (f"  - repo: {url}\n    rev: v3.0.0\n", "v3.0.0"),
            (f"  - repo: '{url}.git'\n    # why\n    # more\n    rev: 'v3.0.0' # x\n", "v3.0.0"),
            (f'  - repo: "{url}"\n    rev: "v3"\n', "v3"),
            (f"  - repo: {url}\n    hooks: []\n    rev: v3\n", None),
            (f"  - repo: {url.replace('/.github', '/xgithub')}\n    rev: v3\n", None),
            (f"  - repo: {url}xgit\n    rev: v3\n", None),
            (f"  - repo: {url.replace('github.com', 'githubxcom')}\n    rev: v3\n", None),
            (f"  - repo: {url}/x\n    rev: v3\n", None),
        ):
            found = eco.KIT_REV.search(text)
            self.assertEqual(found["rev"] if found else None, rev, text)

    def test_a_release_tag(self) -> None:
        for tag, parts in (
            ("v3.0.0", ("3", "0", "0")),
            ("v10.21.32", ("10", "21", "32")),
            ("v3.0", None),
            ("v3x0.0", None),
            ("v3.0x0", None),
            ("v3.0.0-rc", None),
            ("xv3.0.0", None),
            ("quality-v2.0.0", None),
        ):
            found = eco.RELEASE_TAG.match(tag)
            self.assertEqual(found.groups() if found else None, parts, tag)

    def test_no_link_is_empty(self) -> None:
        for text in ("[a](https://)", "<https://>", '<a href="https://">', 'src="https:// x"'):
            self.assertEqual(eco.links_in(text), [], text)

    def test_the_titles_say_what_each_state_is(self) -> None:
        self.assertEqual(
            eco.TITLES,
            {
                "red": "Red: broken, or not what is declared",
                "late": "Late: behind for longer than its limit (fails nothing)",
                "amber": "Amber: behind",
                "frozen": "Frozen inputs that differ from their source (no limit)",
                "note": "Notes",
                "green": "Green",
            },
        )


class LinkTest(ReportCase):
    def test_the_links_of_a_readme(self) -> None:
        text = (
            '[a](https://a.example/x#y) ![b](https://b.example/ "t")\n<https://c.example>'
            '<img src="https://d.example/i.svg"><source srcset="https://e.example/1.png 2x">'
            '<a href="https://f.example">f</a> [a](https://a.example/x) [g](http://g.example)'
            " [h](docs/h.md)"
        )
        self.assertEqual(
            eco.links_in(text),
            [
                "https://a.example/x",
                "https://c.example",
                "https://d.example/i.svg",
                "https://e.example/1.png",
                "https://f.example",
            ],
        )

    def test_dead_and_silent(self) -> None:
        self.reader.put(
            BOARDS,
            "README.md",
            "".join(
                f"[x](https://{n}.example/)"
                for n in ("fine", "gone", "left", "down", "late", "shy", "odd", "bad")
            ),
        )
        self.reader.put(KIT, "profile/README.md", "[x](https://fine.example/)")
        self.reader.put(SECRET, "README.md", "[x](https://secret.example/)")
        for name, status in (
            ("gone", 404),
            ("left", 410),
            ("down", 503),
            ("late", 0),
            ("odd", 499),
            ("bad", 500),
            ("shy", 403),
        ):
            self.reader.statuses[f"https://{name}.example/"] = status
        self.fresh(everything=True)
        eco.check_links(self.report)
        self.assertEqual(len(self.rows("red")), 2)
        self.assertIn(f"{BOARDS} README.md: https://gone.example/ answers 404", self.rows("red"))
        self.assertEqual(len(self.rows("note")), 3)
        self.assertEqual(self.rows("green"), ["3 of 8 links and banners answer"])
        self.assertNotIn("https://secret.example/", self.reader.asked)

    def test_a_reader_of_a_repository_that_leaves_is_red(self) -> None:
        """brand folds into boards here: no other README may link to it or show a banner of it."""
        self.reader.put(
            KIT,
            "README.md",
            f'<img src="https://raw.githubusercontent.com/{BRAND}/main/svg/b.svg">'
            f" [p](https://github.com/{BRAND.upper()}) [q](https://github.com/{BRAND}.git)"
            f" [r](https://github.com/{BRAND}?tab=readme) [s](https://github.com/{BRAND}#top)",
        )
        self.reader.put(
            KIT,
            "profile/README.md",
            f"[a](https://github.com/{BRAND}-old) [b](https://github.com/{BOARDS})"
            f" [c](https://example.org/{BRAND}) [d](https://github.com/{BRAND}/blob/main/x.md)",
        )
        # A repository that leaves is not read for it, whatever it links to.
        self.reader.put(
            BRAND,
            "README.md",
            f"[self](https://github.com/{BRAND}) [l](https://github.com/{BRAND}/x)",
        )
        self.reader.put(SECRET, "README.md", f"[x](https://github.com/{BRAND}/tree/main)")
        eco.check_links(self.report)
        leaving = self.rows("red", "leaving")
        self.assertEqual(
            leaving,
            [
                f"{KIT} README.md: https://raw.githubusercontent.com/{BRAND}/main/svg/b.svg"
                f" reads {BRAND}, which moves into {BOARDS} and is deleted",
                f"{KIT} README.md: https://github.com/{BRAND.upper()} reads {BRAND},"
                f" which moves into {BOARDS} and is deleted",
                f"{KIT} README.md: https://github.com/{BRAND}.git reads {BRAND},"
                f" which moves into {BOARDS} and is deleted",
                f"{KIT} README.md: https://github.com/{BRAND}?tab=readme reads {BRAND},"
                f" which moves into {BOARDS} and is deleted",
                f"{KIT} README.md: https://github.com/{BRAND} reads {BRAND},"
                f" which moves into {BOARDS} and is deleted",
                f"{KIT} profile/README.md: https://github.com/{BRAND}/blob/main/x.md reads"
                f" {BRAND}, which moves into {BOARDS} and is deleted",
            ],
        )
        self.assertNotIn(f"read {SECRET} README.md", self.reader.asked)
        # The local run reads the private READMEs too, and checks no link of theirs.
        self.fresh(everything=True)
        eco.check_links(self.report)
        self.assertIn(
            f"{SECRET} README.md: https://github.com/{BRAND}/tree/main reads {BRAND},"
            f" which moves into {BOARDS} and is deleted",
            self.rows("red", "leaving"),
        )
        self.assertNotIn(f"https://github.com/{BRAND}/tree/main", self.reader.asked)
        self.assertEqual(eco.leaving_slug("https://github.com/", {BRAND: BOARDS}), "")
        self.assertEqual(eco.leaving_slug("not a url", {BRAND: BOARDS}), "")


class SonarTest(ReportCase):
    """The quality gate on main, read from SonarCloud whatever the analysis job said."""

    URL = "https://sonarcloud.io/api/qualitygates/project_status?projectKey=k_github&branch=main"

    def gate(self, answer: Any) -> eco.Report:
        self.reader.pages = {} if answer is None else {self.URL: json.dumps(answer).encode()}
        report = self.fresh()
        eco.check_sonar(report)
        return report

    def test_a_passing_gate_is_green(self) -> None:
        self.gate({"projectStatus": {"status": "OK", "conditions": []}})
        self.assertEqual(self.rows(kind="sonar"), ["1 quality gates on main pass"])

    def test_a_failing_gate_is_red_with_its_conditions(self) -> None:
        conditions = [
            {"status": "ERROR", "metricKey": "new_security_rating"},
            {"status": "OK", "metricKey": "new_coverage"},
            {"status": "ERROR", "metricKey": "new_reliability_issue_severity"},
            "not a condition",
        ]
        self.gate({"projectStatus": {"status": "ERROR", "conditions": conditions}})
        self.assertEqual(
            self.rows("red", "sonar"),
            [
                f"{KIT}: SonarCloud's quality gate on main is ERROR"
                " (new_reliability_issue_severity, new_security_rating)"
            ],
        )
        self.assertEqual(self.rows("green", "sonar"), ["0 quality gates on main pass"])
        odd: tuple[Any, ...] = (None, 5, "ERROR", {"status": "ERROR", "metricKey": "x"})
        for listed in odd:
            with self.subTest(conditions=listed):
                self.gate({"projectStatus": {"status": "WARN", "conditions": listed}})
                self.assertEqual(
                    self.rows("red", "sonar"),
                    [f"{KIT}: SonarCloud's quality gate on main is WARN"],
                )
        self.gate({"projectStatus": {"status": "WARN"}})
        self.assertEqual(
            self.rows("red", "sonar"), [f"{KIT}: SonarCloud's quality gate on main is WARN"]
        )

    def test_no_gate_is_a_note(self) -> None:
        answers: tuple[Any, ...] = (
            None,
            {},
            {"projectStatus": {}},
            [],
            "x",
            {"projectStatus": None},
        )
        for answer in answers:
            with self.subTest(answer=answer):
                self.gate(answer)
                self.assertEqual(
                    self.rows("note", "sonar"), [f"{KIT}: SonarCloud gave no quality gate"]
                )
                self.assertEqual(self.rows("red"), [])

    def test_only_public_projects_that_stay_are_read(self) -> None:
        self.path.write_text(
            RAW.replace(
                'folds_into = "kleidos-dev/boards"', 'sonar = "k_brand"\nfolds_into = "x/y"'
            ),
            encoding="utf-8",
        )
        self.gate({"projectStatus": {"status": "OK"}})
        self.assertEqual(self.rows(kind="sonar"), ["1 quality gates on main pass"])

    def test_a_private_project_is_not_read(self) -> None:
        """Even in a run that reads everything, a private repository's gate is not asked for."""
        self.path.write_text(
            RAW.replace(
                'slug = "kleidos-dev/hidden"\n', 'slug = "kleidos-dev/hidden"\nsonar = "k_hidden"\n'
            ),
            encoding="utf-8",
        )
        hidden = self.URL.replace("k_github", "k_hidden")
        ok = json.dumps({"projectStatus": {"status": "OK"}}).encode()
        self.reader.pages = {self.URL: ok, hidden: ok}
        report = self.fresh(everything=True)
        self.assertIn(SECRET, [r.slug for r in report.repositories])
        with mock.patch.object(self.reader, "page", wraps=self.reader.page) as page:
            eco.check_sonar(report)
        page.assert_called_once_with(self.URL)
        self.assertEqual(
            [r.text for r in report.rows if r.kind == "sonar"], ["1 quality gates on main pass"]
        )


class SettingTest(ReportCase):
    def setUp(self) -> None:
        super().setUp()
        self.answers = self.reader.answers
        self.answers["orgs/kleidos-dev"] = {"deploy_keys_enabled_for_repositories": False}
        self.reader.put(CLA, "registry/config.json", json.dumps({"served_repositories": {KIT: {}}}))
        for slug in (KIT, BOARDS, CLA, SECRET, FIRMWARE):
            self.reader.put(slug, ".github/dependabot.yml", "- package-ecosystem: pre-commit")
        for n, slug in enumerate((KIT, BOARDS, CLA)):
            self.answers[f"repos/{slug}/rulesets"] = [{"id": n}, {"id": n + 4}]
            self.answers[f"repos/{slug}/rulesets/{n}"] = self.rules(
                "branch", "~DEFAULT_BRANCH", ["deletion", "update"]
            )
            # The required checks are a ruleset of their own, which nobody may bypass.
            self.answers[f"repos/{slug}/rulesets/{n + 4}"] = self.rules(
                "branch", "~DEFAULT_BRANCH", []
            )
        self.answers[f"repos/{KIT}/rulesets"] += [{"id": 8}, {"id": 9}]
        self.answers[f"repos/{KIT}/rulesets/8"] = self.rules(
            "branch", "refs/heads/v[0-9]*", ["creation"]
        )
        self.answers[f"repos/{KIT}/rulesets/9"] = self.rules("tag", "~ALL", ["deletion"])
        self.answers[f"repos/{KIT}/immutable-releases"] = {"enabled": True}

    def rules(self, target: str, include: str, types: list[str], **more: Any) -> dict[str, Any]:
        checks = [{"context": "gate", "integration_id": 1}]
        required = {
            "type": "required_status_checks",
            "parameters": {"required_status_checks": checks},
        }
        return {
            "target": target,
            "enforcement": "active",
            "conditions": {"ref_name": {"include": [include]}},
            "bypass_actors": [{"actor_type": "OrganizationAdmin"}] if types else [],
            "rules": [{"type": t} for t in types] + ([] if types else [required]),
            **more,
        }

    def check(self) -> list[tuple[str, str]]:
        report = self.fresh(everything=True)
        eco.check_settings(report)
        return [(r.state, r.text) for r in report.rows]

    def test_what_is_declared_is_quiet(self) -> None:
        self.assertEqual(self.check(), [])

    def assert_red(self, text: str) -> None:
        self.assertIn(("red", text), self.check())

    def test_each_rule_that_lacks(self) -> None:
        for n, slug in ((0, KIT), (1, BOARDS), (2, CLA)):
            path = f"repos/{slug}/rulesets/{n}"
            whole = self.answers[path]
            self.answers[path] = self.rules("branch", "~DEFAULT_BRANCH", ["deletion"])
            self.assert_red(f"{slug} main: no rule update")
            self.answers[path] = whole
        self.answers[f"repos/{KIT}/rulesets/8"]["enforcement"] = "evaluate"
        self.assert_red(f"{KIT} v[0-9]*: no rule creation")
        self.answers[f"repos/{KIT}/rulesets/9"]["target"] = "branch"
        self.assert_red(f"{KIT} tags: no rule deletion")
        self.answers[f"repos/{BOARDS}/rulesets"] = None
        self.assert_red(f"{BOARDS} main: no rule deletion, update")
        self.assert_red(f"{BOARDS} main: gate of App 1 is not required")

    def test_who_may_bypass(self) -> None:
        self.answers[f"repos/{BOARDS}/rulesets/1"]["bypass_actors"].append(
            {"actor_type": "Integration"}
        )
        self.assert_red(f"{BOARDS} main: Integration may bypass the rules")

    def test_a_check_from_another_app_is_not_the_check(self) -> None:
        rules = self.answers[f"repos/{BOARDS}/rulesets/5"]["rules"]
        for app in (2, None):
            rules[-1]["parameters"]["required_status_checks"][0]["integration_id"] = app
            self.assert_red(f"{BOARDS} main: gate of App 1 is not required")
        rules.pop()
        self.assert_red(f"{BOARDS} main: gate of App 1 is not required")

    def test_a_required_check_nobody_may_bypass(self) -> None:
        checks = self.answers[f"repos/{BOARDS}/rulesets/5"]
        main = self.answers[f"repos/{BOARDS}/rulesets/1"]
        for who in ("OrganizationAdmin", "Integration"):
            checks["bypass_actors"] = [{"actor_type": who}]
            self.assert_red(f"{BOARDS} main: gate may be bypassed")
        checks["bypass_actors"] = None
        self.assertEqual(self.check(), [])
        main["rules"] += checks["rules"]
        self.assertEqual(self.check(), [])  # the one that can be bypassed adds nothing
        checks["enforcement"] = "disabled"
        self.assert_red(f"{BOARDS} main: gate may be bypassed")

    def test_the_rest(self) -> None:
        self.reader.put(CLA, "registry/config.json", "{}")
        self.assert_red(f"{KIT}: the CLA does not serve it")
        self.answers[f"repos/{SECRET}/keys"] = [{"title": "ci"}]
        self.assert_red(f"{SECRET}: a deploy key, 'ci'")
        self.answers["orgs/kleidos-dev"]["deploy_keys_enabled_for_repositories"] = True
        self.assert_red("kleidos-dev: deploy keys are not as declared")
        self.reader.statuses["https://sonarcloud.io/api/components/show?component=k_github"] = 404
        self.assert_red(f"{KIT}: no SonarQube Cloud project k_github")
        self.answers["orgs/kleidos-dev/repos?per_page=100"] = [
            {"full_name": "Kleidos-Dev/Boards"},
            {"full_name": "kleidos-dev/new"},
        ]
        self.assert_red("kleidos-dev/new is not in the declared list")
        self.assertEqual(len([t for _s, t in self.check() if "declared list" in t]), 1)
        self.answers[f"repos/{KIT}/immutable-releases"] = None
        self.assertIn(("note", f"{KIT}: immutable releases are off"), self.check())
        del self.reader.tree_of[BOARDS][".github/dependabot.yml"]
        self.assertIn(("amber", f"{BOARDS}: Dependabot moves no hook revision"), self.check())
        self.assertFalse(any(t.startswith(BRAND) for _s, t in self.check()))

    def test_the_apps(self) -> None:
        path = "orgs/kleidos-dev/installations?per_page=100"
        self.answers[path] = {
            "installations": [
                {"app_slug": "known", "permissions": {"checks": "write", "contents": "read"}},
                {"app_slug": "known2", "permissions": {"contents": "read", "issues": "write"}},
            ]
        }
        report = self.fresh(everything=True)
        eco.check_apps(report)
        self.assertEqual(
            self.rows("note"), [f"no list of the Apps that may write at {report.local}"]
        )
        report.rows.clear()
        report.local.write_text('[apps]\nknown = ["checks"]\n', encoding="utf-8")
        eco.check_apps(report)
        self.assertEqual(self.rows(), [])
        self.answers[path]["installations"] += [
            {"app_slug": "known", "permissions": {"checks": "write", "workflows": "write"}},
            {"app_slug": "new", "permissions": {"contents": "write", "statuses": "write"}},
        ]
        eco.check_apps(report)
        self.assertEqual(
            self.rows("red"),
            [
                "the App known can write workflows",
                "the App new can write contents, statuses",
            ],
        )

    def test_the_published_list_says_nothing_of_the_apps(self) -> None:
        raw = eco.load().raw
        self.assertNotIn("apps", raw)
        self.assertNotIn("workflows", eco.DECLARED.read_text(encoding="utf-8"))
        self.assertEqual(eco.LOCAL, Path.home() / ".config/kleidos/ecosystem.local.toml")

    def test_the_workers(self) -> None:
        url = "https://cla.example/version"
        self.reader.trees[f"{CLA}:worker"] = "t1"
        for body, state in (
            ({"tree": "t1", "built": "2020-01-01"}, "green"),
            ({"tree": "t0", "built": "2026-11-17"}, "amber"),
            ({"tree": "t0", "built": "2026-11-16"}, "red"),
            ({"tree": "t0"}, "note"),
            ({"tree": "t0", "built": "?"}, "note"),
            (None, "note"),
        ):
            self.reader.pages = {url: json.dumps(body).encode()}
            eco.check_workers(self.fresh(everything=True))
            self.assertEqual([r.state for r in self.report.rows], [state], body)
        self.reader.pages = {}
        eco.check_workers(self.fresh(everything=True))
        self.assertEqual([r.state for r in self.report.rows], ["note"])

    def test_the_public_schedule(self) -> None:
        runs = "actions/workflows/ecosystem.yml/runs?branch=main&status=completed&per_page=1"
        path = f"repos/{KIT}/{runs}"
        for created, rows in (("2026-11-16T12:00:00Z", []), ("2026-11-15T12:00:00Z", ["red"])):
            run = {"created_at": created, "conclusion": "success"}
            self.answers[path] = {"workflow_runs": [run]}
            report = self.fresh(everything=True)
            self.assertIn("(success)", eco.last_public_run(report))
            self.assertEqual([r.state for r in report.rows], rows, created)
        self.answers[path] = None
        report = self.fresh(everything=True)
        self.assertEqual(eco.last_public_run(report), "no public run yet")
        self.assertEqual([r.state for r in report.rows], ["note"])


class CommandTest(ReportCase):
    def run_report(self, *argv: str, rows: tuple[str, ...] = ()) -> tuple[int, str]:
        def build(report: eco.Report, _outdated: object) -> str:
            for state in rows:
                report.add(state, "x", f"a {state} line")
            return "The head"

        with (
            mock.patch.object(eco, "Reader", return_value=self.reader),
            mock.patch.object(eco, "build", side_effect=build),
            mock.patch.object(eco, "notify") as notify,
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            os.environ.pop("GITHUB_ACTIONS", None)
            status = eco.main(["--declared", str(self.path), "report", *argv])
        self.notified = [c.args for c in notify.call_args_list]
        return status, out.getvalue()

    def setUp(self) -> None:
        super().setUp()
        patched = mock.patch.dict(os.environ)
        patched.start()
        self.addCleanup(patched.stop)

    def test_the_local_list_is_the_one_named(self) -> None:
        for argv, local in (([], eco.LOCAL), (["--local", "/x.toml"], Path("/x.toml"))):
            with mock.patch.object(eco, "render", return_value="") as render:
                self.run_report("--all", *argv)
            self.assertEqual(render.call_args.args[0].local, local)

    def test_only_red_fails(self) -> None:
        for rows, status in (
            ((), 0),
            (("late", "amber", "frozen", "note", "green"), 0),
            (("red",), 1),
            (("green", "red"), 1),
        ):
            self.assertEqual(self.run_report(rows=rows)[0], status, rows)

    def test_the_worst_is_first(self) -> None:
        _status, text = self.run_report(rows=tuple(reversed(eco.STATES)))
        places = [text.index(f"a {state} line") for state in eco.STATES]
        self.assertEqual(places, sorted(places))
        self.assertTrue(text.startswith("# The head\n"))
        for title in eco.TITLES.values():
            self.assertIn(f"## {title} (1)\n", text)

    def test_the_file_the_summary_and_the_notification(self) -> None:
        out = Path(self._tmp.name) / "out" / "deep"
        summary = Path(self._tmp.name) / "summary"
        _status, text = self.run_report(
            "--all",
            "--out",
            str(out),
            "--summary",
            str(summary),
            "--notify",
            rows=("red", "late", "late"),
        )
        written = list(out.glob("ecosystem-*.md"))
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].read_text(encoding="utf-8") + "\n", text)
        self.assertEqual(summary.read_text(encoding="utf-8") + "\n", text)
        self.assertEqual(self.notified, [("Kleidos ecosystem", "1 red, 2 late")])
        self.run_report("--out", str(out))
        self.run_report(rows=())
        self.assertEqual(self.notified, [])

    def test_a_notification_where_there_is_a_way(self) -> None:
        for tool, count in (("osascript", 1), ("notify-send", 1), ("", 0)):
            with (
                mock.patch.object(shutil, "which", side_effect=lambda n, t=tool: n == t or None),
                mock.patch.object(subprocess, "run") as run,
            ):
                eco.notify("Title", "Text")
            self.assertEqual(run.call_count, count, tool)
            if count:
                self.assertEqual(run.call_args.kwargs, {"check": False})
                self.assertEqual(run.call_args.args[0][0], tool)
                self.assertEqual(run.call_args.args[0][-2:], ["Title", "Text"])

    def test_preview(self) -> None:
        summary = Path(self._tmp.name) / "summary"
        for argv, chosen in (
            ([], [BOARDS, BRAND, CLA]),
            (["--all"], [BOARDS, BRAND, CLA, SECRET, FIRMWARE]),
            (["x/y"], ["x/y"]),
        ):
            os.environ.pop("GITHUB_ACTIONS", None)
            with (
                mock.patch.object(kit_preview, "table", return_value=("T\n", 0)) as table,
                contextlib.redirect_stdout(io.StringIO()) as out,
            ):
                base = ["--declared", str(self.path), "preview", "--summary", str(summary)]
                self.assertEqual(eco.main([*base, *argv]), 0)
            self.assertEqual(table.call_args.args[0], chosen)
            self.assertEqual(out.getvalue(), "T\n\n")
        self.assertEqual(summary.read_text(encoding="utf-8"), "T\n" * 3)
        with (
            mock.patch.object(kit_preview, "table", return_value=("T\n", 1)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(eco.main(["--declared", str(self.path), "preview"]), 1)

    def test_refresh(self) -> None:
        with (
            mock.patch.object(kit_preview, "refresh", return_value=["a"]) as refresh,
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(eco.main(["refresh", "x/SOURCE.json", "--from", "src"]), 0)
        self.assertEqual(refresh.call_args.args, (Path("x/SOURCE.json"), Path("src")))
        self.assertEqual(out.getvalue(), "a\n")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(eco.main(["refresh", "/no/such/SOURCE.json"]), 2)
        self.assertIn("cannot be read", err.getvalue())

    def test_land(self) -> None:
        for argv, merge, read in (
            ([], False, ""),
            (["--merge"], True, ""),
            (["--merge", "--read", "abc"], True, "abc"),
        ):
            with mock.patch.object(landing, "land", return_value=3) as land:
                self.assertEqual(eco.main(["land", *argv, BOARDS, f"{BOARDS}#7"]), 3)
            self.assertEqual(land.call_args.args[1], [BOARDS, f"{BOARDS}#7"])
            self.assertEqual(land.call_args.kwargs, {"merge": merge, "read": read})

    def test_the_kits_pins_are_asked_with_ghs_session(self) -> None:
        with mock.patch.object(fx.latest_releases, "outdated", return_value=["x"]):
            for env, token, expected in (
                ({"GH_TOKEN": "t"}, "other", "t"),
                ({"GITHUB_TOKEN": "t"}, "other", None),
                ({}, "session\n", "session"),
                ({}, "", None),
            ):
                done = subprocess.CompletedProcess([], 0, token, "")
                with (
                    mock.patch.dict(os.environ, env, clear=True),
                    mock.patch.object(subprocess, "run", return_value=done) as run,
                ):
                    self.assertEqual(eco.kit_pins_behind(), ["x"])
                    for call in run.call_args_list:  # no session is no error
                        self.assertEqual(call.args[0], ["gh", "auth", "token"])
                        self.assertIs(call.kwargs["check"], False)
                    self.assertEqual(os.environ.get("GH_TOKEN"), expected)


class ReaderTest(unittest.TestCase):
    """The real reader: gh mocked, git on a local remote, a local web server."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.reader = eco.Reader(Path(self._tmp.name), ssh=False)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @contextlib.contextmanager
    def gh(self, status: int, out: str, err: str = "") -> Iterator[mock.Mock]:
        done = subprocess.CompletedProcess([], status, out, err)
        with mock.patch.object(subprocess, "run", return_value=done) as run:
            yield run

    def test_the_api(self) -> None:
        with self.gh(0, '{"a": 1}') as run:
            self.assertEqual(self.reader.api("x"), {"a": 1})
        self.assertEqual(run.call_args.args[0], ["gh", "api", "--method", "GET", "x"])
        self.assertIs(run.call_args.kwargs["check"], False)  # a refusal is listed, not raised
        with self.gh(0, "[[1], [2, 3]]") as run:
            self.assertEqual(self.reader.api("x", pages=True), [1, 2, 3])
        self.assertEqual(run.call_args.args[0][-2:], ["--paginate", "--slurp"])
        with self.gh(0, '{"a": 1}'):
            self.assertEqual(self.reader.api("x", pages=True), {"a": 1})
        with self.gh(0, " "):
            self.assertIsNone(self.reader.api("x"))
        for err, unread in (("HTTP 404", 0), ("Upgrade to GitHub Pro", 0), ("HTTP 500: no", 1)):
            with self.gh(1, "", err):
                self.assertIsNone(self.reader.api("x"))
            self.assertEqual(len(self.reader.unread), unread)
        self.assertEqual(self.reader.unread, ["x: HTTP 500: no"])

    def test_the_lists(self) -> None:
        with self.gh(0, '{"k": [1]}') as run:
            self.assertEqual(self.reader.items("x", key="k"), [1])
        self.assertNotIn("--paginate", run.call_args.args[0])
        with self.gh(0, "[[1]]") as run:
            self.assertEqual(self.reader.items("x"), [1])
        self.assertIn("--paginate", run.call_args.args[0])
        for out in ("{}", '{"k": 3}', "3"):
            with self.gh(0, out):
                self.assertEqual(self.reader.items("x", key="k"), [])
        with self.gh(1, "", "HTTP 404"):
            self.assertEqual(self.reader.items("x"), [])

    def test_a_repository_is_read_without_a_checkout(self) -> None:
        remote = fx.init(Path(self._tmp.name) / "remote" / "o" / "r.git")
        fx.git(remote, "config", "uploadpack.allowFilter", "true")
        fx.git(remote, "config", "uploadpack.allowAnySHA1InWant", "true")
        fx.write(remote, "a/é.txt", "one\n")
        fx.write(remote, "b.txt", "two\n")
        fx.commit(remote)
        real = subprocess.run

        def local(cmd: list[str], **more: Any) -> subprocess.CompletedProcess[Any]:
            base = "https://github.com/"
            moved = [c.replace(base, f"file://{remote.parents[1]}/") for c in cmd]
            return real(moved, **more)

        with mock.patch.object(subprocess, "run", side_effect=local) as run:
            self.assertTrue(self.reader.fetch("o/r"))
            self.assertIn("--no-checkout", run.call_args.args[0])
            self.assertEqual(sorted(self.reader.files("o/r")), ["a/é.txt", "b.txt"])
            calls = run.call_count
            self.reader.files("o/r")
            self.assertEqual(run.call_count, calls)
            self.reader.prefetch("o/r", ["a/é.txt", "b.txt", "none"])
            fetched = run.call_args
            self.assertEqual(len(fetched.kwargs["input"].split(b"\n")), 2)
            self.reader.prefetch("o/r", ["none"])
            self.assertEqual(run.call_args, fetched)
            self.assertEqual(self.reader.read("o/r", "a/é.txt"), b"one\n")
            self.assertIsNone(self.reader.read("o/r", "none"))
            tree = fx.git(remote, "rev-parse", "HEAD:a").strip()
            self.assertEqual(self.reader.tree("o/r", "a"), tree)
            self.assertEqual(self.reader.tree("o/r", "none"), "")
            self.assertFalse(self.reader.fetch("o/none"))
        self.assertEqual(self.reader.unread, ["o/none: cannot be cloned"])
        self.assertEqual(self.reader.files("o/none"), [])

    def test_the_remote_of_each_half(self) -> None:
        for ssh, base in ((True, "git@github.com:o/r.git"), (False, "https://github.com/o/r.git")):
            with self.gh(0, "") as run:
                eco.Reader(Path(self._tmp.name), ssh).fetch("o/r")
            self.assertIn(base, run.call_args.args[0])
            self.assertIs(run.call_args.kwargs["check"], False)
            self.assertEqual(run.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")

    def test_the_web(self) -> None:
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(404 if self.path == "/gone" else 200)
                self.end_headers()
                self.wfile.write(b"body")

            def log_message(self, *_args: object) -> None:
                pass

        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{server.server_port}"
            self.assertEqual(self.reader.status(f"{base}/"), 200)
            self.assertEqual(self.reader.status(f"{base}/gone"), 404)
            self.assertEqual(self.reader.page(f"{base}/"), b"body")
            self.assertIsNone(self.reader.page(f"{base}/gone"))
            server.shutdown()
        with mock.patch.object(time, "sleep") as sleep:
            self.assertEqual(self.reader.status(f"{base}/"), 0)
        self.assertEqual(sleep.call_count, 2)
        self.assertIsNone(self.reader.page(f"{base}/"))


class AgeTest(ReportCase):
    def test_dates_and_times(self) -> None:
        for stamp, days in (
            ("2026-11-24", 0),
            ("2026-11-23", 1),
            ("2026-11-23T12:00:00Z", 1),
            ("2026-11-23T12:00:01Z", 0),
            ("2026-11-24T14:00:00+02:00", 0),
        ):
            self.assertEqual(self.report.age(stamp), days, stamp)

    def test_a_slug_of_a_url(self) -> None:
        for url in (
            "https://github.com/o/r",
            "https://github.com/o/r.git",
            "https://github.com/o/r/",
            "o/r",
        ):
            self.assertEqual(eco.slug_of(url), "o/r")


if __name__ == "__main__":
    unittest.main()
