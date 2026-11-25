# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""supplier_fields.py: no e-mail address in the fields that say who a thing comes from."""

from __future__ import annotations

import datetime as dt
import json
import tempfile
import time
import unicodedata
import unittest
import unittest.mock
from pathlib import Path

import kit_fixtures as fx
from kit_fixtures import check_quality as cq
from kit_fixtures import supplier_fields as sf

H = fx.HOLDER
OWN = sf.ALLOWED
MAIL = "owner@example.org"  # any address but the allowed one
TODAY = dt.date(2026, 11, 25)


def reuse(body: str) -> str:
    """A REUSE.toml whose one annotation says everything is the owner's."""
    return (
        f'version = 1\n{body}\n[[annotations]]\npath = ["**"]\nprecedence = "aggregate"\n'
        f'SPDX-FileCopyrightText = "2026 {H}"\nSPDX-License-Identifier = "MIT"\n'
    )


def cff(body: str) -> str:
    return f"cff-version: 1.2.0\nmessage: Write to {MAIL}.\n{body}"


# Every row of sf.METADATA: a file, its text with {} in a field, and the field
# as a finding names it.
PLANTED: tuple[tuple[str, str, str], ...] = (
    ("REUSE.toml", reuse('SPDX-PackageSupplier = "{}"'), "SPDX-PackageSupplier"),
    ("REUSE.toml", reuse('SPDX-PackageOriginator = "{}"'), "SPDX-PackageOriginator"),
    ("REUSE.toml", reuse('spdx-packagesupplier = "{}"'), "spdx-packagesupplier"),
    (
        "REUSE.toml",
        reuse('[[annotations]]\npath = "x"\nSPDX-FileContributor = ["A", "{}"]'),
        "annotations.SPDX-FileContributor",
    ),
    ("package.json", '{"author": "{}"}', "author"),
    ("a/b/package.json", '{"author": {"name": "A", "email": "{}"}}', "author.email"),
    ("package.json", '{"contributors": ["A", {"email": "{}"}]}', "contributors.email"),
    ("package.json", '{"maintainers": ["{}"]}', "maintainers"),
    ("package.json", '{"bugs": {"email": "{}"}}', "bugs.email"),
    ("package.json", '{"author": "{}", "author": "A"}', "author"),
    ("package.json", '{"maintainers": {"{}": true}}', "maintainers.{}"),
    ("composer.json", '{"support": {"email": "{}"}}', "support.email"),
    ("composer.json", '{"authors": [{"email": "{}"}]}', "authors.email"),
    (
        "pyproject.toml",
        '[project]\nauthors = [{name = "A", email = "{}"}]',
        "project.authors.email",
    ),
    ("pyproject.toml", '[project]\nmaintainers = [{email = "{}"}]', "project.maintainers.email"),
    ("pyproject.toml", '[tool.poetry]\nauthors = ["A <{}>"]', "tool.poetry.authors"),
    ("pyproject.toml", '[tool.x]\nauthor_email = "{}"', "tool.x.author_email"),
    ("Cargo.toml", '[workspace.package]\nauthors = ["A <{}>"]', "workspace.package.authors"),
    ("CITATION.cff", cff("authors:\n  - email: {}\n"), "authors.email"),
    ("CITATION.cff", cff("contact:\n  - name: A\n    email: '{}'\n"), "contact.email"),
    ("CITATION.cff", cff("x: {y: {email: '{}'}}\n"), "x.y.email"),
    ("CITATION.cff", cff("authors: [{name: '{}', name: A}]\n"), "authors.name"),
    ("codemeta.json", '{"maintainer": {"email": "{}"}}', "maintainer.email"),
    (".zenodo.json", '{"creators": [{"name": "{}"}]}', "creators.name"),
    ("idf_component.yml", "maintainers:\n  - A <{}>\n", "maintainers"),
    ("library.json", '{"authors": {"email": "{}"}}', "authors.email"),
    ("x/.claude-plugin/plugin.json", '{"author": {"email": "{}"}}', "author.email"),
    (".claude-plugin/marketplace.json", '{"plugins": [{"author": "{}"}]}', "plugins.author"),
    ("action.yml", "author: {}\nname: x\n", "author"),
    ("x/action.yaml", "author: {}\nname: x\n", "author"),
    ("manifest.json", '{"author": {"email": "{}"}}', "author.email"),
    (
        "bom.json",
        '{"metadata": {"supplier": {"contact": [{"email": "{}"}]}}}',
        "metadata.supplier.contact.email",
    ),
    ("x.cdx.json", '{"components": [{"publisher": "{}"}]}', "components.publisher"),
    ("x.spdx.json", '{"packages": [{"supplier": "Person: A ({})"}]}', "packages.supplier"),
    ("x.spdx.yaml", "creationInfo: {creators: ['Person: A ({})']}\n", "creationInfo.creators"),
    ("x.spdx", "PackageSupplier: Person: A ({})\n", ""),
    ("bom.xml", "<bom><supplier><email>{}</email></supplier></bom>\n", ""),
    ("setup.cfg", "[metadata]\nauthor_email = {}\n", ""),
    ("setup.py", 'setup(author_email="{}")\n', ""),
    ("library.properties", "maintainer=A <{}>\n", ""),
    ("x.gemspec", 'spec.email = ["{}"]\n', ""),
    ("debian/control", "Maintainer: A <{}>\n", ""),
    (".reuse/dep5", "Upstream-Contact: A <{}>\n", ""),
    ("AUTHORS", "A <{}>\n", ""),
    ("Contributors.md", "- A <{}>\n", ""),
    ("MAINTAINERS.txt", "A <{}>\n", ""),
    (".github/CODEOWNERS", "* {}\n", ""),
    (".mailmap", "A <{}>\n", ""),
)

# The whole list, as it is meant to be: its files, each with every field
# ("" for a file that is searched whole).
PEOPLE = "AUTHORS AUTHORS.md AUTHORS.txt CONTRIBUTORS CONTRIBUTORS.md CONTRIBUTORS.txt"
LISTED: dict[str, str] = {
    "REUSE.toml": "SPDX-PackageSupplier SPDX-PackageOriginator annotations.SPDX-FileContributor",
    "package.json composer.json": (
        "author authors bugs contributors funding maintainers publisher support"
    ),
    "pyproject.toml Cargo.toml": (
        "x.author x.author_email x.authors x.maintainer x.maintainer-email x.maintainers"
    ),
    "CITATION.cff": "authors contact preferred-citation references x.email",
    "codemeta.json .zenodo.json": (
        "author contributor contributors copyrightHolder creator creators editor funder"
        " maintainer producer provider publisher sponsor"
    ),
    "idf_component.yml idf_component.yaml library.json": "authors maintainers",
    ".claude-plugin/x.json": "author owner plugins.author",
    "action.yml action.yaml": "author",
    "manifest.json": "author developer",
    "bom.json sbom.json x.cdx.json x.spdx.json x.spdx.yaml x.spdx.yml": (
        "x.annotator x.author x.authors x.contact x.creators x.email x.manufacture"
        " x.manufacturer x.originator x.publisher x.reviewer x.supplier"
    ),
    "bom.xml sbom.xml x.cdx.xml x.spdx .reuse/dep5": "",
    "setup.py setup.cfg library.properties x.gemspec debian/control": "",
    f"{PEOPLE} MAINTAINERS MAINTAINERS.md MAINTAINERS.txt CODEOWNERS .mailmap": "",
}


def document(rel: str, field: str, value: str) -> str:
    """A file of that format with the value in that field."""
    if not field:
        return value
    if rel.endswith(".toml"):
        table, dot, name = field.rpartition(".")
        head = f"[[{table}]]\n" if dot else ""
        return f'{head}{name} = "{value}"\n'
    doc: object = value
    for name in reversed(field.split(".")):
        doc = {name: doc}
    return json.dumps(doc)  # which is YAML too


class SupplierFieldsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fx.init(Path(self._tmp.name) / "repo")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def report(self, rel: str, text: str) -> cq.Report:
        """What is found in a repository that holds this one file more."""
        fx.write(self.root, rel, text)
        report = cq.Report()
        sf.check(cq.Repo(self.root), report)
        (self.root / rel).unlink()
        return report

    def found(self, rel: str, text: str) -> list[str]:
        """The fields with an address that is not allowed."""
        return [field for _rel, field in self.named(self.report(rel, text))]

    def named(self, report: cq.Report) -> list[tuple[str, str]]:
        """The (file, field) of each problem."""
        out = []
        for p in report.problems:
            self.assertEqual(p.rule, "supplier")
            field, sep, _why = p.message.partition(" holds an e-mail address")
            self.assertTrue(sep, p.message)
            out.append((p.where, field))
        return out

    def planted(self, value: str) -> tuple[cq.Report, list[tuple[str, str]]]:
        """PLANTED with this value, each in a folder of its own: what is found, and the fields."""
        where = []
        for n, (rel, text, field) in enumerate(PLANTED):
            fx.write(self.root, f"{n}/{rel}", text.replace("{}", value))
            where.append((f"{n}/{rel}", field.replace("{}", value) or sf.WHOLE))
        report = cq.Report()
        sf.check(cq.Repo(self.root), report)
        return report, sorted(where)

    # ----------------------------------------------------------------- fields

    def test_an_address_in_every_field_is_found(self) -> None:
        report, where = self.planted(MAIL)
        self.assertEqual(sorted(self.named(report)), where)
        self.assertEqual(report.weakenings, [])

    def test_a_name_in_every_field_is_not(self) -> None:
        report, _where = self.planted(H)
        self.assertEqual((report.problems, report.weakenings), ([], []))

    def test_the_one_address_needs_a_waiver_in_every_field(self) -> None:
        for address in (OWN, OWN.upper()):
            report, where = self.planted(address)
            self.assertEqual(report.problems, [])
            self.assertEqual({w.tool for w in report.weakenings}, {"supplier"})
            self.assertEqual(
                sorted((w.where, w.what) for w in report.weakenings),
                [(rel, f"address:{field}") for rel, field in where],
            )

    def test_every_file_and_field_of_the_list(self) -> None:
        listed = {
            tuple(name.casefold() for name in files.split()): tuple(
                field.casefold().replace("_", "-") for field in fields.split()
            )
            for files, fields in LISTED.items()
        }
        self.assertEqual(
            {
                tuple(name.replace("*", "x") for name in row.files): tuple(
                    field.replace("**", "x") for field in row.fields
                )
                for row in sf.METADATA
            },
            listed,
        )
        where = [
            fx.write(self.root, f"{n}/{i}/{j}/{rel}", document(rel, field, MAIL))
            for n, (files, fields) in enumerate(LISTED.items())
            for i, rel in enumerate(files.split())
            for j, field in enumerate(fields.split() or [""])
        ]
        report = cq.Report()
        sf.check(cq.Repo(self.root), report)
        self.assertEqual(
            sorted(p.where for p in report.problems),
            sorted(path.relative_to(self.root).as_posix() for path in where),
        )

    def test_one_finding_for_one_field(self) -> None:
        text = f'{{"contributors": ["A <{MAIL}>", "B <b@example.org>", "C <{OWN}>"]}}'
        report = self.report("package.json", text)
        self.assertEqual(len(report.problems), 1)
        self.assertEqual(report.weakenings, [])

    def test_an_address_elsewhere_in_the_file_is_not_a_suppliers(self) -> None:
        for rel, text in (
            ("package.json", f'{{"description": "{MAIL}", "scripts": {{"author": "{MAIL}"}}}}'),
            ("package.json", '{"dependencies": {"author": "x@1.2.3"}}'),
            ("package.json", f'["{MAIL}"]'),
            ("package.json", '{"author": null, "contributors": [1, true, {}], "bugs": {}}'),
            ("pyproject.toml", f'[project]\ndescription = "{MAIL}"\n'),
            ("CITATION.cff", cff("title: x\n")),
            ("action.yml", f"name: x\ninputs: {{author: {{default: {MAIL}}}}}\n"),
            ("library.json", f'{{"dependencies": [{{"authors": "{MAIL}"}}]}}'),
            ("REUSE.toml", reuse("")),
            ("authors.json", f'{{"author": "{MAIL}"}}'),
            ("tests/authors.py", f"AUTHOR = '{MAIL}'\n"),
            ("facts.json", f'{{"creator": {{"email": "{MAIL}"}}}}'),
            ("README.md", f"Write to {MAIL}.\n"),
            ("node_modules/x/package.json", f'{{"author": "{MAIL}"}}'),
        ):
            with self.subTest(rel=rel, text=text):
                report = self.report(rel, text)
                self.assertEqual((report.problems, report.weakenings), ([], []))

    # -------------------------------------------------------------- addresses

    def test_however_it_is_written(self) -> None:
        for value, found in (
            (f"{H} <{MAIL}>", True),
            (f"{H} ({MAIL})", True),
            (f"{MAIL}", True),
            (MAIL.upper(), True),
            (f"mailto:{MAIL}", True),
            (f"mailto:{MAIL}?subject=x", True),
            (unicodedata.lookup("FULLWIDTH COMMERCIAL AT").join(MAIL.split("@")), True),
            ("owner+kleidos@example.org", True),
            ("1+x@users.noreply.github.com", True),
            ("o'brien@example.org", True),
            ("owner@exämple.org", True),
            ("owner@example.xn--p1ai", True),
            ("Owner <owner@host>", True),
            ("Owner <mailto:owner@host>", True),
            ("owner at example dot org", True),
            ("owner [at] example [dot] org", True),
            ("owner (AT) example.org", True),
            ("owner{at}example.org", True),
            ("owner@example dot org", True),
            (f"x{OWN}", True),
            (f"{OWN}.example.org", True),
            ("mail@sub.kleidos.dev", True),
            (f"{OWN} and {MAIL}", True),
            (H, False),
            (f"{H} (https://kleidos.dev)", False),
            (f"{H} (https://example.org/@owner)", False),
            (f"{H} <https://example.org/@owner>", False),
            ("@owner@example.org, on the fediverse", False),
            ("@owner", False),
            ("Works at kleidos.dev", False),
            ("Looked at the dot", False),
            ("left-pad@1.2.3", False),
            ("left-pad@1.x", False),
            ("git+ssh://git@example.org/x", False),
            ("", False),
        ):
            with self.subTest(value=value):
                text = f'{{"author": "{value}"}}'
                self.assertEqual(bool(self.found("package.json", text)), found)

    def test_a_long_value_is_read_once(self) -> None:
        for value in (
            "a" * 200_000,
            "a." * 100_000,
            "a@" * 100_000,
            "a@b." * 50_000 + "1",
            "a at " * 40_000,
            "<" * 200_000,
            "<a@" * 60_000,
            "a@b dot " * 20_000,
        ):
            start = time.monotonic()
            list(sf.ADDRESS.finditer(value))
            self.assertLess(time.monotonic() - start, 5, value[:12])

    # ------------------------------------------------------------ the readers

    def test_a_file_that_cannot_be_read_is_searched_whole(self) -> None:
        for rel, text in (
            ("package.json", f'{{"description": "{MAIL}"'),
            ("package.json", "[" * 100_000 + MAIL),
            ("pyproject.toml", f'x = "{MAIL}"\nx = 1\n'),
            ("CITATION.cff", f"a: 1\n---\nb: {MAIL}\n"),
            ("CITATION.cff", f"\tauthors: {MAIL}\n"),
            ("action.yml", f"a: &a\n  - *a\n  - {MAIL}\n"),
        ):
            with self.subTest(rel=rel, text=text[:40]):
                self.assertEqual(self.found(rel, text), ["the file"])
                clean = text.replace(MAIL, "x")
                self.assertEqual(self.found(rel, clean), [])

    def test_the_one_address_in_a_mailto_link(self) -> None:
        for value in (f"mailto:{OWN}", f"<mailto:{OWN}>", f"{H} <MAILTO:{OWN.upper()}>"):
            with self.subTest(value=value):
                report = self.report("package.json", f'{{"author": "{value}"}}')
                self.assertEqual((len(report.problems), len(report.weakenings)), (0, 1))

    def test_a_suffix_in_capitals_and_bytes_that_are_no_text(self) -> None:
        self.assertEqual(self.found("CITATION.CFF", f"authors: {MAIL}\n"), ["authors"])
        (self.root / "AUTHORS").write_bytes(b"A\xff " + MAIL.encode() + b"\n")
        report = cq.Report()
        sf.check(cq.Repo(self.root), report)
        self.assertEqual(len(report.problems), 1)

    def test_an_empty_file_and_a_byte_order_mark(self) -> None:
        self.assertEqual(self.found("CITATION.cff", ""), [])
        text = f'﻿{{"author": "{MAIL}", "description": "{OWN}"}}'
        report = self.report("package.json", text)
        self.assertEqual([p.message.split()[0] for p in report.problems], ["author"])
        self.assertEqual(report.weakenings, [])

    # ------------------------------------------------------------ whose it is

    def test_what_reuse_toml_says_is_a_third_partys(self) -> None:
        fx.write(self.root, "vendor/package.json", f'{{"author": "{MAIL}"}}')
        for holder, found in (("2020 Someone", 0), (f"2020 {H}", 1), (None, 1)):
            line = f'SPDX-FileCopyrightText = "{holder}"\n' if holder else ""
            body = reuse("") + f'\n[[annotations]]\npath = "vendor/**"\n{line}'
            with self.subTest(holder=holder):
                self.assertEqual(len(self.report("REUSE.toml", body).problems), found)
        both = f'SPDX-FileCopyrightText = ["2020 Someone", "2026 {H}"]\n'
        body = reuse("") + f'\n[[annotations]]\npath = "vendor/**"\n{both}'
        self.assertEqual(len(self.report("REUSE.toml", body).problems), 1)

    def test_no_reuse_toml_is_nobody_elses(self) -> None:
        self.assertEqual(len(self.found("package.json", f'{{"author": "{MAIL}"}}')), 1)

    def test_a_kit_copy_is_checked_where_it_comes_from(self) -> None:
        fx.write(self.root, "package.json", f'{{"author": "{MAIL}"}}')
        repo = cq.Repo(self.root)
        repo.foreign = {"package.json"}
        report = cq.Report()
        sf.check(repo, report)
        self.assertEqual(report.problems, [])


class InTheCheckTest(unittest.TestCase):
    """The kit check runs it, in the run form and in the kit's home."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fx.called(Path(self._tmp.name) / "repo")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def supplier(self) -> list[str]:
        report = cq.run(self.root, kit=cq.DirKit(fx.CENTRAL), today=TODAY)
        return [
            f"{p.where}: {p.message}"
            for p in report.problems
            if p.rule == "supplier" or (p.rule == "waivers" and "supplier" in p.where)
        ]

    def waive(self, **over: str) -> None:
        entry = {
            "tool": "supplier",
            "what": "address:SPDX-PackageSupplier",
            "reason": "The tool refuses a name alone",
            "decided": "owner 2026-11-25",
        } | over
        lines = "".join(f'{key} = "{value}"\n' for key, value in entry.items())
        path = self.root / cq.WAIVERS
        self.before = path.read_text(encoding="utf-8")
        path.write_text(f"{self.before}\n[[waiver]]\n{lines}", encoding="utf-8")

    def test_a_clean_repository(self) -> None:
        self.assertEqual(self.supplier(), [])

    def test_another_address_has_no_waiver(self) -> None:
        fx.write(self.root, "REUSE.toml", reuse(f'SPDX-PackageSupplier = "{H} <{MAIL}>"'))
        self.assertEqual(len(self.supplier()), 1)
        self.waive()
        found = self.supplier()
        self.assertEqual(len(found), 2, found)
        self.assertIn("SPDX-PackageSupplier holds an e-mail address", found[0])
        self.assertNotIn(MAIL, found[0])
        self.assertIn("matches nothing any more", found[1])

    def test_the_one_address_is_waived_with_its_reason(self) -> None:
        fx.write(self.root, "REUSE.toml", reuse(f'SPDX-PackageSupplier = "{H} <{OWN}>"'))
        found = self.supplier()
        self.assertEqual(len(found), 1, found)
        self.assertIn("has no waiver", found[0])
        self.waive(reason="")
        self.assertTrue(any("needs reason" in line for line in self.supplier()))
        (self.root / cq.WAIVERS).write_text(self.before, encoding="utf-8")
        self.waive()
        self.assertEqual(self.supplier(), [])
        fx.write(self.root, "REUSE.toml", reuse(f'SPDX-PackageSupplier = "{H}"'))
        self.assertIn("matches nothing any more", self.supplier()[0])

    def test_the_kits_home_is_held_too(self) -> None:
        seen: list[Path] = []
        with unittest.mock.patch.object(sf, "check", lambda repo, _: seen.append(repo.root)):
            cq.run(fx.CENTRAL, kit=cq.DirKit(fx.CENTRAL), today=TODAY)
        self.assertEqual(seen, [fx.CENTRAL])

    def test_the_held_form_is_not(self) -> None:
        held = fx.consumer(Path(self._tmp.name) / "held")
        fx.sync.write(held, commit=fx.FAKE_COMMIT)
        fx.write(held, "REUSE.toml", reuse(f'SPDX-PackageSupplier = "{MAIL}"'))
        report = cq.run(held, kit=cq.DirKit(fx.CENTRAL), today=TODAY)
        self.assertEqual([p for p in report.problems if p.rule == "supplier"], [])


if __name__ == "__main__":
    unittest.main()
