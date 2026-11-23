# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Tests of the media metadata module, the stamp and the checker.

Run with ``python3 -m unittest discover -s tests``. The REUSE comparison
runs only where the ``reuse`` tool is installed (CI installs it).
"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
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
SPDX-FileCopyrightText = "2026 José M. Requena Plens <someone@example.org>"
SPDX-License-Identifier = "GPL-3.0-or-later"
"""


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
        self.assertEqual(mm.strip_email("2026 A B <a@b.c>"), "2026 A B")

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
