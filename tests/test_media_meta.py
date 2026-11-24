# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Tests of the media metadata module, the stamp and the checker.

Run with ``python3 -m unittest discover -s tests``. The REUSE comparison
runs only where the ``reuse`` tool is installed (CI installs it).
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
import zlib
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_metadata  # noqa: E402  found through the path set above
import media_meta as mm  # noqa: E402  found through the path set above
import stamp_media_meta  # noqa: E402  found through the path set above

FIXTURES = ROOT / "tests" / "fixtures" / "meta"

EXAMPLE = mm.MediaMeta(
    title="Example drawing, test fixture",
    description="A fixed record that pins how the profile writes an SVG.",
    keywords=("Kleidos", "hardware password manager", "open source", "test & fixture"),
    digital_source_type="digitalCreation",
    spdx="GPL-3.0-or-later AND MIT",
    own_license="GPL-3.0-or-later",
    holders=("2026 José M. Requena Plens", "2021 M5Stack"),
    identifier_url="https://github.com/kleidos-dev/.github/blob/main/example.svg",
    source_url="https://github.com/kleidos-dev/boards/blob/main/example.svg",
)
EXAMPLE_ES = replace(
    EXAMPLE,
    language="es",
    title_es="Dibujo de ejemplo, prueba",
    description_es="Un registro fijo que muestra cómo escribe el perfil un SVG.",
)

DRAWING = '<rect width="10" height="10" fill="#123456"/></svg>\n'
SVG_LEGACY = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" role="img" aria-labelledby="t d">'
    '<!-- a credit --><title id="t">Old</title><desc id="d">Old desc</desc>' + DRAWING
)
RECORD: dict[str, Any] = {
    "id": "kl-x",
    "title": "Example square, test",
    "description": "A blue square used by the checker's tests.",
    "keywords": ["Kleidos", "test"],
    "digital_source_type": "digitalCreation",
    "own_license": "GPL-3.0-or-later",
    "language": "en",
    "notice": "A credit.",
}
REUSE_TOML = """version = 1
[[annotations]]
path = ["**"]
precedence = "aggregate"
SPDX-FileCopyrightText = "2026 José M. Requena Plens <someone(at)example.org>"
SPDX-License-Identifier = "GPL-3.0-or-later"
""".replace("(at)", "@")  # a planted e-mail, which no file of the tree may carry


#: How many characters a hostile value has, and the seconds reading it may
#: take. Linear code needs a few milliseconds and a pattern that backtracks
#: over the whole value for each character needs well over the bound.
HOSTILE_LENGTH = 50_000
HOSTILE_SECONDS = 1.0


def png(chunks: list[tuple[bytes, bytes]]) -> bytes:
    """A 1x1 grey PNG with extra chunks before IDAT."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    body = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    for kind, data in chunks:
        body += chunk(kind, data)
    body += chunk(b"IDAT", zlib.compress(b"\x00\x80")) + chunk(b"IEND", b"")
    return b"\x89PNG\r\n\x1a\n" + body


class ModuleTest(unittest.TestCase):
    def test_golden_svg_block(self) -> None:
        self.assertEqual(
            mm.svg_block(EXAMPLE, "kl-example"),
            (FIXTURES / "example.svg-block").read_text(encoding="utf-8"),
        )

    def test_golden_spanish_svg_block(self) -> None:
        self.assertEqual(
            mm.svg_block(EXAMPLE_ES, "kl-example"),
            (FIXTURES / "example-es.svg-block").read_text(encoding="utf-8"),
        )

    def test_copyright_line(self) -> None:
        sign = mm.COPYRIGHT_SIGN
        self.assertEqual(
            EXAMPLE.copyright,
            f"{sign} 2026 José M. Requena Plens; {sign} 2021 M5Stack. GPL-3.0-or-later AND MIT.",
        )

    def test_limits_are_refused_never_truncated(self) -> None:
        for bad in (
            replace(EXAMPLE, title="x" * 65),
            replace(EXAMPLE, description="x" * 301),
            replace(EXAMPLE, holders=("y" * 130,)),
            replace(EXAMPLE, keywords=tuple(f"k{i}" for i in range(13))),
            replace(EXAMPLE, digital_source_type="digitalArt"),
            replace(EXAMPLE, own_license="Apache-2.0"),
            replace(EXAMPLE, language="es"),
            replace(EXAMPLE, notice="two -- dashes"),
            replace(EXAMPLE, description="Built in /Users/someone/x"),
        ):
            with self.assertRaises(mm.MetaError):
                mm.svg_block(bad, "kl-x")

    def test_license_urls(self) -> None:
        self.assertEqual(mm.license_url("MIT"), "https://spdx.org/licenses/MIT.html")
        with self.assertRaises(mm.MetaError):
            mm.license_url("LicenseRef-Nowhere")
        with self.assertRaises(mm.MetaError):
            mm.license_url("WTFPL")

    def test_strip_email(self) -> None:
        for holder, expected in (
            ("2026 A B <a@b.c>", "2026 A B"),
            ("2026 A B", "2026 A B"),
            (" A <a@b.c> B  <d@e.f> ", "A B"),
            ("<a@b.c>", ""),
            ("A <b <c> D", "A D"),
            ("A > B <c>> D", "A > B> D"),
            ("A <unclosed", "A <unclosed"),
        ):
            self.assertEqual(mm.strip_email(holder), expected, holder)

    def test_in_file_license(self) -> None:
        tag = "SPDX-" + "License-Identifier:"
        for line, expected in (
            (f"# {tag} MIT", "MIT"),
            (f"/* {tag}  MIT OR Apache-2.0  */", "MIT OR Apache-2.0"),
            (f"<!-- {tag} GPL-3.0-or-later --> text", "GPL-3.0-or-later"),
            (f"<!-- {tag}MIT-->", "MIT"),
            (f"/* {tag} */", ""),
            (f"# {tag}", ""),
            ("# no tag", ""),
        ):
            self.assertEqual(mm.in_file_license(line), expected, line)

    def test_hostile_values_cost_linear_time(self) -> None:
        """A long run that never becomes a match is read once."""
        spaces, letters = " " * HOSTILE_LENGTH, "a" * HOSTILE_LENGTH
        tag = "SPDX-" + "License-Identifier:"
        cases = (
            ("strip_email, spaces", lambda: mm.strip_email("A" + spaces + "B")),
            ("strip_email, brackets", lambda: mm.strip_email("A" + "<" * HOSTILE_LENGTH)),
            ("in_file_license", lambda: mm.in_file_license(f"{tag} A{spaces}B")),
            ("deny_hits, e-mail", lambda: mm.deny_hits([letters])),
            ("root_attributes", lambda: mm.root_attributes(f'<svg {letters}="{letters}">')),
        )
        for name, read in cases:
            with self.subTest(name):
                start = time.perf_counter()
                read()
                self.assertLess(time.perf_counter() - start, HOSTILE_SECONDS)
        with self.subTest("root_attributes, no value"):
            start = time.perf_counter()
            with self.assertRaises(mm.MetaError):
                mm.root_attributes(f"<svg {letters}>")
            self.assertLess(time.perf_counter() - start, HOSTILE_SECONDS)
        with self.subTest("stamp_svg, root tags that never close"):
            start = time.perf_counter()
            with self.assertRaises(mm.MetaError):
                mm.stamp_svg("<svg " * HOSTILE_LENGTH, EXAMPLE, "kl-x")
            self.assertLess(time.perf_counter() - start, HOSTILE_SECONDS)

    def test_deny_list_finds_an_address_anywhere(self) -> None:
        for value in ("a@b.example", "by <a.b+c@d-e.example>", "x@y z@w.example", "(q@r.st)"):
            with self.subTest(value):
                self.assertTrue(mm.deny_hits([value])[0].startswith("e-mail ("))
        self.assertEqual(mm.deny_hits(["by a.b+c@d-e.example"]), ["e-mail ('a.b+c@d-e.example')"])
        self.assertEqual(mm.deny_hits(["@kleidos-dev", "a@b", "a @b.example"]), [])

    def test_namespace_names(self) -> None:
        """The names are the vocabularies' own; every byte of them counts."""
        self.assertEqual(
            mm.SVG_NAMESPACES,
            (
                "http://www.w3.org/2000/svg",
                "http://www.w3.org/1999/xlink",
                "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                "http://purl.org/dc/elements/1.1/",
                "http://creativecommons.org/ns#",
                "http://iptc.org/std/Iptc4xmpExt/2008-02-29/",
                "http://www.w3.org/XML/1998/namespace",
            ),
        )
        self.assertEqual(mm.DST_BASE, "http://cv.iptc.org/newscodes/digitalsourcetype/")

    def test_namespace_declarations_are_xml(self) -> None:
        """An XML parser reads from each declaration the name the module uses."""
        for declaration in mm.NAMESPACE_DECLARATIONS:
            prefix = declaration.partition("=")[0].removeprefix("xmlns:")
            element = ET.fromstring(f"<{prefix}:x {declaration}/>")  # noqa: S314  the module's own constants
            self.assertEqual(
                element.tag,
                f"{{{mm.namespace_names((declaration,))[prefix]}}}x",
            )

    def test_no_string_of_the_tools_is_a_cleartext_address(self) -> None:
        """A string that is an http URL reads as an address to fetch: the
        tools fetch nothing, and name a vocabulary only in a declaration."""
        for path in sorted((ROOT / "scripts").glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertFalse(
                        node.value.startswith(("http://", "ftp://", "telnet://")),
                        f"{path.name}:{node.lineno}",
                    )

    def test_root_attributes(self) -> None:
        for tag, expected in (
            ("<svg>", []),
            ("<svg/>", []),
            (
                '<svg a="1" b:c="x=y &quot; z" d="">',
                [("a", "1"), ("b:c", "x=y &quot; z"), ("d", "")],
            ),
            ('<svg\n  a = "1"\n  b="2" />', [("a", "1"), ("b", "2")]),
        ):
            self.assertEqual(mm.root_attributes(tag), expected, tag)

    def test_root_tag_that_would_lose_something_is_refused(self) -> None:
        for tag in (
            "<svg a='1'>",
            "<svg a='1' b=\"2\">",
            '<svg hidden a="1">',
            '<svg a="1" hidden>',
            '<svg a="1>',
            '<svg ="1">',
            '<svg a=b="1">',
        ):
            with self.subTest(tag), self.assertRaises(mm.MetaError):
                mm.root_attributes(tag)
        with self.assertRaises(mm.MetaError):
            mm.stamp_svg(SVG_LEGACY.replace('role="img"', "role='img'"), EXAMPLE, "kl-x")

    def test_root_tag_is_the_first_whole_one(self) -> None:
        for text, span in (
            ("<svg>", (0, 5)),
            ("<?xml?>\n<svg a='1'/>", (8, 20)),
            ("<svgx><svg-y>", (6, 13)),
            ("<svg_a><svg\n>", (7, 13)),
            ("<svg <svg>", (0, 10)),
        ):
            self.assertEqual(mm.root_tag_span(text), span, text)
        for text in ("", "<g>", "<svg", "a><svg", "<svgx>"):
            with self.subTest(text), self.assertRaises(mm.MetaError):
                mm.root_tag_span(text)

    def test_glob(self) -> None:
        self.assertTrue(mm._glob_match("profile/assets/*.svg", "profile/assets/a.svg"))
        self.assertFalse(mm._glob_match("profile/*.svg", "profile/assets/a.svg"))
        self.assertTrue(mm._glob_match("**", "a/b/c.svg"))
        self.assertTrue(mm._glob_match("scripts/**", "scripts/x/y.py"))

    def test_deny_list(self) -> None:
        self.assertEqual(mm.deny_hits(["Kleidos, https://kleidos.dev"], ["secret"]), [])
        self.assertEqual(mm.deny_hits(["made by Secret"], ["secret"]), ["identity"])
        for value in ("a@b.example", "/home/x", "host.local", "2026-11-19T10:00", "Inkscape 1.4"):
            self.assertTrue(mm.deny_hits([value]), value)
        # Structural names are not values: the text layer leaves them alone.
        self.assertEqual(mm.deny_hits(["http://ns.adobe.com/xap/1.0/"]), [])

    def test_stamp_keeps_the_drawing_and_is_idempotent(self) -> None:
        meta = replace(EXAMPLE, notice="A credit.")
        once = mm.stamp_svg(SVG_LEGACY, meta, "kl-x")
        self.assertTrue(once.endswith(mm.IGNORE_END + "\n" + DRAWING))
        self.assertIn('role="img" aria-labelledby="kl-x-t kl-x-d" lang="en">', once)
        self.assertNotIn(">Old<", once)
        self.assertEqual(mm.stamp_svg(once, meta, "kl-x"), once)


class CheckerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "profile" / "assets").mkdir(parents=True)
        (self.root / "REUSE.toml").write_text(REUSE_TOML, encoding="utf-8")
        self.svg = "profile/assets/x.svg"
        self.write(SVG_LEGACY)
        self.record = dict(RECORD)
        self.restamp()
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, text: str) -> None:
        (self.root / self.svg).write_text(text, encoding="utf-8")

    def read(self) -> str:
        return (self.root / self.svg).read_text(encoding="utf-8")

    def save_manifest(self) -> None:
        data = (self.root / self.svg).read_bytes()
        self.record["bytes"] = len(data)
        self.record["sha256"] = hashlib.sha256(data).hexdigest()
        manifest = {"profile": mm.META_PROFILE, "files": {self.svg: self.record}, "exempt": []}
        (self.root / mm.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")

    def restamp(self) -> None:
        meta = mm.meta_from_record(self.svg, self.record, self.root)
        self.write(mm.stamp_svg(self.read(), meta, self.record["id"]))
        self.save_manifest()

    def rules(self, identity: tuple[str, ...] = ()) -> set[str]:
        return {f.rule for f in check_metadata.check(self.root, None, list(identity))}

    def test_clean(self) -> None:
        self.assertEqual(check_metadata.check(self.root, None, ["secret"]), [])
        self.assertIn(
            f"{mm.COPYRIGHT_SIGN} 2026 José M. Requena Plens. GPL-3.0-or-later.", self.read()
        )
        self.assertNotIn("example.org", self.read())

    def test_m001_missing_desc(self) -> None:
        self.write(
            self.read().replace('<desc id="kl-x-d">', '<g id="kl-x-d">').replace("</desc>", "</g>")
        )
        self.save_manifest()
        self.assertIn("M001", self.rules())

    def test_m002_hand_edit(self) -> None:
        self.write(self.read().replace("Example square, test</title>", "Edited</title>"))
        self.save_manifest()
        self.assertEqual(self.rules(), {"M002"})

    def test_m002_digest(self) -> None:
        self.write(self.read().replace("#123456", "#123457"))
        self.assertEqual(self.rules(), {"M002"})

    def test_m003_notice_outside_markers(self) -> None:
        notice = "<!-- Copy" + "right 2020 Someone Else -->"
        self.write(self.read().replace("<rect", notice + "<rect"))
        self.save_manifest()
        self.assertIn("M003", self.rules())

    def test_m003_license_tag_outside_markers(self) -> None:
        """A tag is REUSE information even when no expression follows it.

        REUSE reads an empty expression from such a line, and the banners'
        ``aggregate`` precedence hides that from ``reuse lint``.
        """
        tag = "SPDX-" + "License-Identifier:"
        for precedence in ("aggregate", "closest"):
            (self.root / "REUSE.toml").write_text(
                REUSE_TOML.replace("aggregate", precedence), encoding="utf-8"
            )
            for statement in (
                f"<!-- {tag} MIT -->",
                f"<!-- {tag} -->",
                f"<!-- {tag}-->",
                f"<style>/* {tag} */</style>",
                f"<style>/* {tag}*/</style>",
                f"<!--\n{tag}\n-->",
            ):
                with self.subTest(precedence=precedence, statement=statement):
                    self.write(SVG_LEGACY.replace("</svg>", statement + "\n</svg>"))
                    self.restamp()
                    self.assertEqual(self.rules(), {"M003"})

    def test_m003_own_license(self) -> None:
        self.record["own_license"] = "MIT"
        self.save_manifest()
        self.assertIn("M003", self.rules())

    def test_m004_identity_and_paths(self) -> None:
        self.write(
            self.read().replace("<!-- A credit. -->", "<!-- Exported by Secret from /Users/x -->")
        )
        self.save_manifest()
        rules = check_metadata.check(self.root, None, ["secret"])
        self.assertIn("M004: deny-list hit: identity", [f"{f.rule}: {f.message}" for f in rules])
        self.assertIn("M004", {f.rule for f in rules})
        self.assertNotIn("Secret", " ".join(f.message for f in rules if f.rule == "M004"))

    def test_m005_foreign_namespace(self) -> None:
        self.write(
            self.read().replace(
                "<svg ", '<svg xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
            )
        )
        self.restamp()
        self.assertEqual(self.rules(), {"M005"})

    def test_m005_embedded_png_with_text(self) -> None:
        bare = base64.b64encode(png([])).decode()
        dirty = base64.b64encode(png([(b"tEXt", b"Software\x00GIMP")])).decode()
        for payload, expected in ((bare, set()), (dirty, {"M005"})):
            image = f'<image width="1" height="1" href="data:image/png;base64,{payload}"/>'
            self.write(
                mm.stamp_svg(
                    SVG_LEGACY.replace("<rect", image + "<rect"),
                    mm.meta_from_record(self.svg, self.record, self.root),
                    "kl-x",
                )
            )
            self.save_manifest()
            self.assertEqual(self.rules(), expected)

    def test_spans(self) -> None:
        comment = re.compile("<!--")
        for text, pieces in (
            ("", []),
            ("<!---->", ["<!---->"]),
            ("<!-->", []),
            ("<!--a--><g/><!-- b\n-->", ["<!--a-->", "<!-- b\n-->"]),
            ("<!-- <!-- a --> -->", ["<!-- <!-- a -->"]),
            ("<!--a--><!-- b", ["<!--a-->"]),
        ):
            found = [text[i:j] for i, j in check_metadata.spans(text, comment, "-->")]
            self.assertEqual(found, pieces, text)

    def test_hostile_drawing_costs_linear_time(self) -> None:
        """A well-formed drawing full of openers that never close."""
        for opener in ("<!--", "<metadata ", "<svg ", "xmlns:", "data:", "<title>"):
            with self.subTest(opener):
                style = f"<style><![CDATA[{opener * HOSTILE_LENGTH}]]></style>"
                self.write(SVG_LEGACY.replace("<rect", style + "<rect"))
                self.restamp()
                start = time.perf_counter()
                self.assertEqual(self.rules(), set())
                self.assertLess(time.perf_counter() - start, HOSTILE_SECONDS)

    def test_m006_root_tag(self) -> None:
        """A root tag that cannot be written back is the file's fault."""
        self.write(self.read().replace('lang="en"', "lang='en'"))
        self.save_manifest()
        findings = [f.message for f in check_metadata.check(self.root, None, [])]
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].startswith("the file cannot be stamped: the root <svg> tag"))

    def test_m006_malformed(self) -> None:
        self.write(self.read().replace("</svg>", ""))
        self.save_manifest()
        self.assertEqual(self.rules(), {"M006"})

    def test_m008_unrecorded_media(self) -> None:
        (self.root / "profile" / "assets" / "y.png").write_bytes(png([]))
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        self.assertEqual(self.rules(), {"M008"})

    def test_m011_metadata_outside_markers(self) -> None:
        text = self.read().replace(mm.IGNORE_START + "\n", "").replace(mm.IGNORE_END + "\n", "")
        self.write(text)
        self.save_manifest()
        self.assertIn("M011", self.rules())

    def test_m012_unknown_source_type(self) -> None:
        self.write(
            self.read().replace("digitalsourcetype/digitalCreation", "digitalsourcetype/digitalArt")
        )
        self.save_manifest()
        self.assertIn("M012", self.rules())


class RepositoryTest(unittest.TestCase):
    def test_tree_is_clean(self) -> None:
        self.assertEqual(check_metadata.check(ROOT, None, mm.identity_patterns()), [])

    def test_stamp_check_passes(self) -> None:
        self.assertEqual(stamp_media_meta.main(["--check"]), 0)

    @unittest.skipUnless(shutil.which("reuse"), "the reuse tool is not installed")
    def test_reuse_reads_only_reuse_toml(self) -> None:
        """REUSE reads no notice from the metadata: holders = REUSE.toml's."""
        out = subprocess.run(
            ["reuse", "spdx"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout
        manifest = json.loads((ROOT / mm.MANIFEST).read_text(encoding="utf-8"))
        for path in manifest["files"]:
            block = out.split(f"FileName: ./{path}\n", 1)[1].split("\n\n", 1)[0]
            text = block.split("FileCopyrightText: <text>", 1)[1].split("</text>", 1)[0]
            holders = tuple(mm.strip_email(line.split(":", 1)[1]) for line in text.splitlines())
            licenses = [
                line.split(": ", 1)[1]
                for line in block.splitlines()
                if line.startswith("LicenseInfoInFile:")
            ]
            spdx, toml_holders = mm.reuse_toml_truth(path)
            self.assertEqual(holders, toml_holders, path)
            self.assertEqual(licenses, mm.spdx_ids(spdx), path)


if __name__ == "__main__":
    unittest.main()
