# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""supplier_fields.py: no e-mail address in the fields that say who a thing comes from."""

from __future__ import annotations

import base64
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
REAL = "owner@kleidos.dev"  # one whose domain is not reserved for examples
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
    ("package.json", '{"maintainers": {"{}": true}}', "maintainers.*"),
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
    (".claude-plugin/marketplace.json", '{"metadata": {"author": "{}"}}', "metadata.author"),
    (".claude-plugin/plugin.json", '{"maintainers": ["{}"]}', "maintainers"),
    ("codemeta.json", '{"@graph": [{"author": {"email": "{}"}}]}', "@graph.author.email"),
    ("codemeta.json", '{"contactPoint": {"email": "{}"}}', "contactPoint.email"),
    ("REUSE.toml", "[meta]\nSPDX-PackageSupplier = '{}'\n", "meta.SPDX-PackageSupplier"),
    ("package.json", '{"homepage": "mailto:{}"}', "homepage"),
    ("pyproject.toml", '[project.urls]\nContact = "MAILTO:{}"', "project.urls.Contact"),
    ("idf_component.yml", "issues: mailto:{}\n", "issues"),
    ("action.yml", "author: {}\nname: x\n", "author"),
    ("x/action.yaml", "author: {}\nname: x\n", "author"),
    ("manifest.json", '{"author": {"email": "{}"}}', "author.email"),
    (
        "bom.json",
        '{"metadata": {"supplier": {"contact": [{"email": "{}"}]}}}',
        "metadata.supplier.contact.email",
    ),
    ("x.cdx.json", '{"metadata": {"component": {"author": "{}"}}}', "metadata.component.author"),
    ("x.spdx.json", '{"packages": [{"supplier": "Person: A ({})"}]}', "packages.supplier"),
    ("x.spdx.yaml", "creationInfo: {creators: ['Person: A ({})']}\n", "creationInfo.creators"),
    ("x.spdx", "PackageName: x\nPackageSupplier: Person: A ({})\n", "packages.supplier"),
    ("x.spdx", "Creator: Person: A ({})\n", "creationInfo.creators"),
    (
        "bom.xml",
        "<bom><metadata><supplier><c:email>{}</c:email></supplier></metadata></bom>\n",
        "metadata.supplier.email",
    ),
    ("setup.cfg", "[metadata]\nauthor_email = {}\n", ""),
    ("setup.py", 'setup(author_email="{}")\n', ""),
    ("library.properties", "maintainer=A <{}>\n", ""),
    ("x.gemspec", 'spec.email = ["{}"]\n', ""),
    ("debian/control", "Maintainer: A <{}>\n", ""),
    (".reuse/dep5", "Upstream-Contact: A <{}>\n", ""),
)

# A file of people is one at the root and in .github/ only.
PEOPLE: tuple[tuple[str, str], ...] = (
    ("AUTHORS", "A <{}>\n"),
    ("Contributors.md", "- A <{}>\n"),
    ("MAINTAINERS.txt", "A <{}>\n"),
    (".github/CODEOWNERS", "* {}\n"),
    (".mailmap", "A <{}>\n"),
)

# The whole list, as it is meant to be: its files, each with every field
# ("" for a file that is searched whole).
LISTED: dict[str, str] = {
    "REUSE.toml": "x.SPDX-PackageSupplier x.SPDX-PackageOriginator x.SPDX-FileContributor",
    "package.json package.yaml composer.json bower.json deno.json jsr.json": (
        "author authors bugs contributors funding maintainers publisher support"
    ),
    "pyproject.toml Cargo.toml": (
        "x.author x.author_email x.authors x.maintainer x.maintainer-email x.maintainers"
    ),
    "CITATION.cff": "authors contact preferred-citation references x.email",
    "codemeta.json .zenodo.json": (
        "x.author x.contactPoint x.contributor x.contributors x.copyrightHolder x.creator"
        " x.creators x.editor x.email x.funder x.maintainer x.producer x.provider x.publisher"
        " x.sponsor"
    ),
    "idf_component.yml idf_component.yaml library.json": "authors maintainers",
    ".claude-plugin/x.json": "x.author x.authors x.contributors x.maintainer x.maintainers x.owner",
    "action.yml action.yaml": "author",
    "manifest.json": "author developer",
    "bom.json bom.xml xsbomx.json xsbomx.xml xsbomx.yaml xsbomx.yml x.cdx.json x.cdx.xml"
    " cyclonedx.json spdx.json x.spdx x.spdx.json x.spdx.yaml x.spdx.yml": (
        "author authors creators manufacturer originator publisher supplier"
        " metadata.author metadata.authors metadata.component metadata.manufacture"
        " metadata.manufacturer metadata.publisher metadata.supplier"
        " annotations.annotator creationInfo packages.annotations packages.originator"
        " packages.supplier revieweds.reviewer"
    ),
    "setup.py setup.cfg library.properties x.gemspec debian/control .reuse/dep5": "",
    "/AUTHORS /.github/AUTHORS /AUTHORS.md /.github/AUTHORS.md /AUTHORS.txt /.github/AUTHORS.txt"
    " /CONTRIBUTORS /.github/CONTRIBUTORS /CONTRIBUTORS.md /.github/CONTRIBUTORS.md"
    " /CONTRIBUTORS.txt /.github/CONTRIBUTORS.txt /MAINTAINERS /.github/MAINTAINERS"
    " /MAINTAINERS.md /.github/MAINTAINERS.md /MAINTAINERS.txt /.github/MAINTAINERS.txt"
    " /CODEOWNERS /.github/CODEOWNERS /docs/CODEOWNERS /.mailmap": "",
}


def document(rel: str, field: str, value: str) -> str:
    """A file of that format with the value in that field."""
    if not field:
        return f'x = "{value}"\n' if rel.endswith(".py") else value
    if rel.endswith(".xml"):
        names = field.split(".")
        tags = "".join(f"<{name}>" for name in names), "".join(f"</{n}>" for n in names[::-1])
        return f"<bom>{tags[0]}{value}{tags[1]}</bom>"
    if rel.endswith(".spdx"):
        return f"Creator: {value}\n"
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
        for rel, text in PEOPLE:
            fx.write(self.root, rel, text.replace("{}", value))
            where.append((rel, sf.WHOLE))
        for n, (rel, text, field) in enumerate(PLANTED):
            fx.write(self.root, f"{n}/{rel}", text.replace("{}", value))
            where.append((f"{n}/{rel}", field or sf.WHOLE))
        report = cq.Report()
        sf.check(cq.Repo(self.root), report)
        return report, sorted(where)

    # ----------------------------------------------------------------- fields

    def test_an_address_in_every_field_is_found(self) -> None:
        report, where = self.planted(REAL)
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
            tuple(name.casefold().removeprefix("/") for name in files.split()): tuple(
                field.casefold().replace("_", "-") for field in fields.split()
            )
            for files, fields in LISTED.items()
        }
        self.assertEqual(
            {
                tuple(name.replace("*", "x").removeprefix("/") for name in row.files): tuple(
                    field.replace("**", "x") for field in row.fields
                )
                for row in sf.METADATA
            },
            listed,
        )
        where = [
            fx.write(
                self.root,
                rel[1:] if rel.startswith("/") else f"{n}/{i}/{j}/{rel}",
                document(rel, field, REAL),
            )
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
            ("docs/contributors.md", f"Write {REAL}.\n"),
            ("site/.mailmap", f"A <{REAL}>\n"),
            ("setup.py", f"# {REAL}\nx = lhs@rhs.shape\n"),
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
            ("@owner@example.org, on the fediverse", True),
            ("mailto://owner@example.org", True),
            ("//owner@example.org", True),
            ("https://kleidos.dev owner@example.org", True),
            ("ftp://x@owner@example.org", True),
            ("https://kleidos.dev?to=owner@example.org", True),
            ("https://kleidos.dev#owner@example.org", True),
            ("https://kleidos.dev,owner@example.org", True),
            ("https://kleidos.dev;owner@example.org", True),
            ("xhttps://owner@example.org", True),
            ("owner @ example.org", True),
            ("owner@\\nexample.org", True),
            ("owner@\u200bexample.org", True),
            ("owner\u00ad@example.org", True),
            ("owner\u200f@example.org", True),
            ("owner@\ufe0fexample.org", True),
            ("owner@\U000e0100example.org", True),
            ("owner@\u034fexample.org", True),
            ("owner@\\u0000example.org", True),
            ("owner@\u2800example.org", True),
            ("owner@example\u3002org", True),
            ("owner@example\uff0eorg", True),
            ("owner@example\uff61org", True),
            ("owner@exa\u0301mple.org", True),
            ("owner&#64;example.org", True),
            ("owner&commat;example.org", True),
            ("owner&amp;amp;#64;example.org", True),
            ("mailto:owner%40example.org", True),
            ("mailto:owner%252525252540example.org", True),
            ("owner\\\\x40example.org", True),
            ("owner\\\\u0040example.org", True),
            ("owner\\\\u{40}example.org", True),
            ("owner\\\\U00000040example.org", True),
            ("(owner at example.org)", True),
            (f"{H} (owner at mail.example.org)", True),
            ("<owner at example.org>", True),
            ("owner[at]example[.]org", True),
            ("owner@example[.]org", True),
            ("owner@example(.)org", True),
            ("owner@example (dot) org", True),
            ("owner(at)example(dot)org", True),
            ("owner<at>example.org", True),
            ("owner <at> example <dot> org", True),
            ("owner_at_example_dot_org", True),
            ("owner-at-example-dot-org", True),
            ("OWNER AT mail DOT example DOT org", True),
            ("owner at mail.example dot org", True),
            ('\\"owner\\"@example.org', True),
            ("o'@example.org", True),
            ("owner!@example.org", True),
            ("owner@[192.0.2.1]", True),
            ("owner@[IPv6:2001:db8::1]", True),
            ("owner@163.com", True),
            ("owner@1.2.mail.org", True),
            ("owner@example.org: the maintainer", True),
            ("owner@example.org:x", True),
            ("xgit@example.org:a/b", True),
            ("git@example.org", True),
            ("owner@png.example.org", True),
            ("hibernate-core@5.4.0.Final", False),
            ("vite@7.0.0-beta.rc", False),
            ("django@4.2.dev0", False),
            ("x@3.1.4.post1", False),
            ("pkg:golang/example.org/b@v0.0.0-20210101000000-abcdefabcdef", False),
            ("actions/checkout@v4.2.main", False),
            ("git@github.com:a/b.git", False),
            ("aur@aur.example.org:x.git", False),
            ("https://user:pw@example.org/x", False),
            ("https://user@example.org", False),
            ("logo@2x.png", False),
            ("logo@dark.svg", False),
            ("look at the dot com", False),
            ("look at a dot matrix", False),
            ("https://example.org/@first.last", False),
            ("@scope/name.js", False),
            ("x @ y", False),
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

    def test_an_address_that_is_not_the_one_allowed(self) -> None:
        for value in (
            f"first/{OWN}",
            f"o!{OWN}",
            f"o'{OWN}",
            f"o={OWN}",
            f"mailto://{OWN}",
            f"x+{OWN}",
            f"x\u00ad{OWN}",
            f"{OWN}@example.org",
            f"{OWN}!example.org",
            f"{OWN}-x",
            f"{OWN}\u0430",
            OWN.replace("@", "&#64;"),
            OWN.replace("@", " @ "),
            OWN.replace("m", "\uff4d", 1),
            OWN.replace("s", "\u017f"),
            OWN.replace("a", "a\u0308", 1),
            f"{OWN}, {OWN.replace('m', chr(0xFF4D), 1)}",
        ):
            with self.subTest(value=value):
                report = self.report("package.json", json.dumps({"author": value}))
                self.assertEqual((len(report.problems), report.weakenings), (1, []))

    def test_the_one_allowed_in_whole_files(self) -> None:
        for rel, text in (
            ("setup.cfg", f"author_email={OWN}\n"),
            ("setup.py", f"setup(author_email='{OWN}')\n"),
            ("x.gemspec", f"spec.email='{OWN}'\n"),
            ("AUTHORS", f"A <{OWN}>, {OWN}.\n"),
        ):
            with self.subTest(rel=rel):
                report = self.report(rel, text)
                self.assertEqual((report.problems, len(report.weakenings)), ([], 1))

    def test_what_a_whole_file_may_hold(self) -> None:
        for rel, text, found in (
            ("CONTRIBUTORS.md", "git clone git@github.com:kleidos-dev/boards.git\n", False),
            ("CONTRIBUTORS.md", "- @owner@example.social\n", False),
            ("CONTRIBUTORS.md", "- https://example.social/@owner@example.social\n", False),
            ("CONTRIBUTORS.md", "![a](logo@2x.png)\n", False),
            ("CONTRIBUTORS.md", "Write a name, never `name@example.org`.\n", False),
            ("MAINTAINERS.md", "git -c user.email=you@example.com commit\n", False),
            ("MAINTAINERS.md", "you@mail.example.net, you@x.invalid, you@a.test.\n", False),
            ("MAINTAINERS.md", "you@example.org.kleidos.dev\n", True),
            ("MAINTAINERS.md", f"`{REAL}`\n", True),
            ("MAINTAINERS", f"{MAIL}\n", True),
            ("AUTHORS.md", "owner&#64;kleidos.dev\n", True),
            ("setup.py", 'setup(url="git@github.com:a/b.git", x="a@2x.png")\n', False),
            ("setup.py", 'setup(install_requires=["x @ https://u@example.org/x.whl"])\n', False),
            ("setup.py", 'setup(author_email="owner@" "example.org")\n', True),
            ("setup.py", 'setup(author_email="owner\\x40example.org")\n', True),
            ("setup.py", f'setup(author_email=f"{{x}} {MAIL}")\n', True),
            ("setup.py", f"setup(  # {MAIL}\n", True),
            ("setup.cfg", f"# {MAIL}\n", True),
            ("tests/fixtures/package.json", f'{{"author": "{MAIL}"}}', False),
            ("x/__tests__/package.json", f'{{"author": "{MAIL}"}}', False),
            ("tests/fixtures/package.json", f'{{"author": "{REAL}"}}', True),
            ("tests.d/package.json", f'{{"author": "{MAIL}"}}', True),
        ):
            with self.subTest(rel=rel, text=text):
                self.assertEqual(bool(self.found(rel, text)), found)

    def test_a_bill_names_its_own_people(self) -> None:
        component = {"name": "left-pad", "author": f"A <{MAIL}>", "url": f"mailto:{MAIL}"}
        supplier = f"Person: A ({MAIL})"
        root = {"SPDXID": "SPDXRef-r", "supplier": "Person: A"}
        other = {"SPDXID": "SPDXRef-o", "supplier": supplier}
        of = {"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES"}
        by = {"relatedSpdxElement": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBED_BY"}
        depends = {"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DEPENDS_ON"}
        names = "PackageName: r\nSPDXID: SPDXRef-r\nPackageName: o\nSPDXID: SPDXRef-o\n"
        tags = "SPDXID: SPDXRef-DOCUMENT\n" + names + f"PackageSupplier: {supplier}\n"
        relation = "Relationship: SPDXRef-DOCUMENT DESCRIBES SPDXRef-"
        xml = f"<bom>{{}}<components><author>{MAIL}</author></components></bom>"
        for rel, doc, found in (
            ("sbom.cdx.json", {"components": [component]}, []),
            (
                "bom.json",
                {"metadata": {"component": component}},
                ["metadata.component.author", "metadata.component.url"],
            ),
            ("x.spdx.json", {"packages": [other]}, ["packages.supplier"]),
            ("x.spdx.json", {"packages": [root, other], "documentDescribes": ["SPDXRef-r"]}, []),
            (
                "x.spdx.json",
                {"packages": [root, other], "documentDescribes": ["SPDXRef-o"]},
                ["packages.supplier"],
            ),
            (
                "spdx.json",
                {"packages": [other], "relationships": [of | {"relatedSpdxElement": "SPDXRef-r"}]},
                [],
            ),
            (
                "spdx.json",
                {"packages": [other], "relationships": [by | {"spdxElementId": "SPDXRef-r"}]},
                [],
            ),
            (
                "spdx.json",
                {
                    "packages": [other],
                    "relationships": [depends | {"relatedSpdxElement": "SPDXRef-r"}],
                },
                ["packages.supplier"],
            ),
            ("spdx.json", {"packages": "x", "relationships": [1], "documentDescribes": [1]}, []),
            ("x.sbom.json", {"supplier": MAIL}, ["supplier"]),
            ("sbom-firmware.json", {"supplier": MAIL}, ["supplier"]),
            ("sbom.yml", {"supplier": MAIL}, ["supplier"]),
            ("cyclonedx.json", {"supplier": MAIL}, ["supplier"]),
            ("sbom/x.json", {"supplier": MAIL}, []),
            ("x.spdx", tags, ["packages.supplier"]),
            ("x.spdx", f"{tags}{relation}r\n", []),
            ("x.spdx", f"{tags}{relation}o\n", ["packages.supplier"]),
            ("x.spdx", f"Reviewer: Person: A ({MAIL})\n", ["revieweds.reviewer"]),
            ("x.spdx", f"Annotator: Person: A ({MAIL})\n", ["annotations.annotator"]),
            (
                "x.spdx",
                f"PackageName: x\nPackageOriginator: Person: A ({MAIL})\n",
                ["packages.originator"],
            ),
            ("x.spdx", f"PackageComment: ask {MAIL}\nPackageSupplier: {supplier}\n", []),
            ("bom.xml", xml.format("<!-- x -->"), []),
            ("x.cdx.xml", "", []),
            (
                "bom.xml",
                xml.format(
                    "<metadata><x/><authors>&#111;wner@<b/>example.org</authors></metadata>"
                ),
                ["metadata.authors"],
            ),
            (
                "bom.xml",
                xml.format(f"<metadata><supplier><![CDATA[{MAIL}]]></supplier></metadata>"),
                ["metadata.supplier"],
            ),
            (
                "bom.xml",
                xml.format(f'<metadata><supplier mail="{MAIL}" x=""/><x/></metadata>'),
                ["metadata.supplier.mail"],
            ),
            ("bom.xml", xml.format("<metadata>"), ["the file"]),
            ("bom.xml", f"<!DOCTYPE bom>{xml.format('')}", ["the file"]),
            (
                "bom.xml",
                xml.format(f"<metadata><author>{'a' * 70_000}{MAIL}</author></metadata>"),
                ["metadata.author"],
            ),
            ("bom.xml", "<a>" * 100 + MAIL + "</a>" * 100, []),
            ("bom.xml", "<a>" * 101 + MAIL + "</a>" * 101, ["the file"]),
        ):
            with self.subTest(rel=rel, doc=str(doc)[:200]):
                text = doc if isinstance(doc, str) else json.dumps(doc)
                self.assertEqual(self.found(rel, text), found)

    def test_yaml_however_it_is_written(self) -> None:
        coded = base64.b64encode(MAIL.encode()).decode()
        for rel, text, found in (
            ("CITATION.cff", f"x: &a\n  authors: [{{name: {MAIL}}}]\n<<: *a\n", ["authors.name"]),
            (
                "CITATION.cff",
                f"x: &a {{authors: A}}\ny: &b\n  contact: {MAIL}\n<<: [*a, *b, 1]\n",
                ["contact"],
            ),
            ("CITATION.cff", "x: 1\n<<: 1\n", []),
            ("idf_component.yml", f"x: &a\n  maintainers: [{MAIL}]\n<<: *a\n", ["maintainers"]),
            ("action.yml", f"x: &a {MAIL}\nauthor: *a\n", ["author"]),
            ("action.yml", f"author: !!binary {coded}\n", ["author"]),
            ("action.yml", "author: !!binary a\n", []),
            ("action.yml", "author: !!binary '*'\n", []),
            ("action.yml", f"author: {coded}\n", []),
            ("action.yml", f"author:\n  ? [{MAIL}]\n  : x\n", ["author.?"]),
            ("action.yml", 'author: "owner\\x40example.org"\n---\na: 1\n', ["the file"]),
            ("package.json", '{"author": "owner\\u0040example.org",}', ["the file"]),
            ("package.yaml", f"author: {MAIL}\n", ["author"]),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.found(rel, text), found)

    def test_a_key_is_not_printed(self) -> None:
        for key, value in ((MAIL, 1), (f"x {MAIL}", {"y": MAIL}), ("a\n::error::b", MAIL)):
            report = self.report("package.json", json.dumps({"maintainers": {key: value}}))
            for problem in report.problems:
                self.assertNotIn(MAIL, problem.message)
                self.assertNotIn("\n", problem.message)
            self.assertTrue(report.problems)
        self.assertEqual(
            self.found("package.json", json.dumps({"maintainers": {MAIL: {"y": MAIL}}})),
            ["maintainers.*", "maintainers.*.y"],
        )
        report = self.report("package.json", json.dumps({"maintainers": {OWN: 1}}))
        self.assertEqual([w.what for w in report.weakenings], ["address:maintainers.*"])

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
            "a-" * 100_000,
            "-at-" * 50_000,
            "a at b." * 30_000,
            "[at]" * 50_000,
            "a@a_dot_" * 25_000,
            "@" + "a_dot_" * 40_000,
            "@a" * 100_000,
            "git@" * 50_000,
            "a@b:" * 50_000,
            "a@" + "b." * 100_000,
            "a@v" + "1." * 100_000,
            "http://" * 30_000,
            "mailto:" * 30_000,
            "%25" * 70_000,
            "&amp;" * 40_000,
            "\u0315\u0300" * 100_000,
            " " * 200_000,
            "(" * 200_000,
            "(a at " * 30_000,
            "\\x" * 100_000,
            "a@[" * 60_000,
            "a@[" + "1" * 200_000,
        ):
            for whole in (False, True):
                start = time.monotonic()
                sf.addresses(value, whole=whole, examples=True)
                self.assertLess(time.monotonic() - start, 5, value[:12])

    def test_aliases_are_not_unfolded(self) -> None:
        bomb = "a0: &a0 [x,x,x,x,x,x,x,x,x,x]\n" + "".join(
            f"a{i}: &a{i} [{','.join([f'*a{i - 1}'] * 10)}]\n" for i in range(1, 12)
        )
        merges = "a0: &a0 {x: 1}\n" + "".join(
            f"a{i}: &a{i} {{<<: [{','.join([f'*a{i - 1}'] * 10)}]}}\n" for i in range(1, 12)
        )
        keys = "a0: &a0 [x, x]\n" + "".join(
            f"a{i}: &a{i} {{? *a{i - 1} : *a{i - 1}}}\n" for i in range(1, 40)
        )
        for text in (bomb, merges, keys):
            start = time.monotonic()
            self.assertEqual(self.found("action.yml", text), [])
            self.assertEqual(self.found("action.yml", f"{text}z: {MAIL}\n"), ["the file"])
            self.assertLess(time.monotonic() - start, 5)
        cycle = f"author: &a\n  <<: *a\n  x: {MAIL}\n"
        self.assertEqual(self.found("action.yml", cycle), ["the file"])

    # ------------------------------------------------------------ the readers

    def test_a_file_that_cannot_be_read_is_searched_whole(self) -> None:
        for rel, text in (
            ("package.json", f'{{"description": "{MAIL}"'),
            ("package.json", "[" * 100_000 + MAIL),
            ("pyproject.toml", f'x = "{MAIL}"\nx = 1\n'),
            ("CITATION.cff", f"a: 1\n---\nb: {MAIL}\n"),
            ("setup.py", f"x = {'-' * 100_000}1  # {MAIL}\n"),
            ("setup.py", f"x = '\0'  # {MAIL}\n"),
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
        for data in (b"A\xff " + MAIL.encode() + b"\n", f"A {MAIL}\n".encode("utf-16")):
            (self.root / "AUTHORS").write_bytes(data)
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

    def test_reuse_toml_is_never_a_third_partys(self) -> None:
        for body in (
            '[[annotations]]\npath = "REUSE.toml"\nSPDX-FileCopyrightText = "2026 Kleidos"\n',
            '[[annotations]]\npath = "REUSE.toml"\nSPDX-FileCopyrightText = "2020 Someone"\n',
        ):
            text = f'SPDX-PackageSupplier = "{MAIL}"\n{body}'
            self.assertEqual(self.found("REUSE.toml", text), ["SPDX-PackageSupplier"])

    def test_who_is_not_a_third_party(self) -> None:
        fx.write(self.root, "package.json", f'{{"author": "{MAIL}"}}')
        for path, holder, found in (
            ('"**"', "2020 Someone", 1),
            ('["**/*", "*/**"]', "2020 Someone", 1),
            ('"*"', "2020 Someone", 1),
            ('["**", "package.json"]', "2020 Someone", 0),
            ('["**", "x/**"]', "2020 Someone", 1),
            ('"package.json"', "2026 Kleidos", 1),
            ('"package.json"', unicodedata.normalize("NFD", f"2026 {H}"), 1),
            ('"package.json"', "2026 REQUENA Plens, J. M.", 1),
            ('"package.json"', "2026 J. M. Requena", 1),
            ('"package.json"', "", 1),
            ('"package.json"', "2020 Someone", 0),
        ):
            for annotation in (
                f'SPDX-FileCopyrightText = "{holder}"',
                f'SPDX-FileCopyrightText = ["{holder}"]',
            ):
                body = f"[[annotations]]\npath = {path}\n{annotation}\n"
                with self.subTest(body=body):
                    self.assertEqual(len(self.report("REUSE.toml", body).problems), found)
        # The last annotation that covers a file is the one that states it.
        both = '[[annotations]]\npath = "{}"\nSPDX-FileCopyrightText = "{}"\n'
        body = both.format("package.json", "2020 Someone") + both.format("**", f"2026 {H}")
        self.assertEqual(len(self.report("REUSE.toml", body).problems), 1)

    def test_a_reuse_toml_that_cannot_be_read(self) -> None:
        for body in ("x = 1\nx = 1\n", 'annotations = "x"\n', "annotations = 1\n"):
            fx.write(self.root, "package.json", f'{{"author": "{MAIL}"}}')
            with self.subTest(body=body):
                where = [p.where for p in self.report("REUSE.toml", body).problems]
                self.assertEqual(where, ["package.json"])
        broken = f'SPDX-PackageSupplier = "{MAIL}"\nx = 1\nx = 1\n'
        self.assertEqual(self.found("REUSE.toml", broken), ["the file", "author"])

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
