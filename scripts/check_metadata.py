#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Check that every published media file carries the Kleidos metadata profile.

Every tracked file with a media extension either has a record in
``profile/assets/assets.json`` or is listed there as exempt with a reason.
A file with a record must hold exactly the metadata its record gives
(``kleidos-media-meta/1``), the license and holders REUSE gives its path,
nothing outside the profile, nothing from the privacy deny-list, and the
digest the manifest records.

Usage: python3 scripts/check_metadata.py [--json] [PATH ...]
Exit codes: 0 clean, 1 findings, 2 usage or internal error.

Rules (one finding per line, ``path: Mxxx: message``):
  M001 a required field is missing
  M002 a field or the file differs from what its record generates
  M003 license or holders differ from REUSE, or own_license is not in it
  M004 a value hits the privacy deny-list
  M005 a container, element, namespace or chunk outside the profile
  M006 a format error (malformed XML, a byte limit, an unsupported format)
  M008 a media file with neither a record nor an exemption
  M011 a metadata block outside the REUSE ignore markers
  M012 a missing or unknown digital source type
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import media_meta as mm

MEDIA_EXTENSIONS = frozenset(
    [
        "png",
        "jpg",
        "jpeg",
        "webp",
        "avif",
        "gif",
        "svg",
        "pdf",
        "mp4",
        "webm",
        "mkv",
        "glb",
        "gltf",
        "obj",
        "mtl",
        "ico",
        "ttf",
        "otf",
        "woff",
        "woff2",
        "stl",
        "ksm",
        "wav",
        "mp3",
        "vtt",
        "srt",
    ]
)

#: Chunks an image embedded in a published SVG may hold: pixels only.
BARE_PNG_CHUNKS = frozenset({b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"})

_COMMENT_OPEN = re.compile(r"<!--")
_METADATA_OPEN = re.compile(r"<metadata\b")
_DATA_URI = re.compile(r"data:([a-z0-9.+/-]+);base64,([A-Za-z0-9+/=\s]+)")


@dataclass(frozen=True)
class Finding:
    """One rule a file breaks."""

    path: str
    rule: str
    message: str

    def line(self) -> str:
        return f"{self.path}: {self.rule}: {self.message}"


def tracked_media(root: Path) -> list[str]:
    """The tracked files with a media extension, in git's order."""
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    ).stdout.decode("utf-8")
    paths = [p for p in out.split("\0") if p]
    return [p for p in paths if p.rsplit(".", 1)[-1].lower() in MEDIA_EXTENSIONS]


def _local(tag: str) -> tuple[str, str]:
    if tag.startswith("{"):
        ns, _, name = tag[1:].partition("}")
        return ns, name
    return "", tag


def _png_chunks(data: bytes) -> list[bytes]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG")
    chunks, i = [], 8
    while i + 8 <= len(data):
        (length,) = struct.unpack(">I", data[i : i + 4])
        chunks.append(data[i + 4 : i + 8])
        i += 12 + length
    return chunks


def spans(text: str, opener: re.Pattern[str], closer: str) -> list[tuple[int, int]]:
    """Where each piece from an opener to the next closer begins and ends.

    The search stops at the first opener that no closer follows: no later
    one has a closer either, so the text is read once.
    """
    found: list[tuple[int, int]] = []
    position = 0
    while start := opener.search(text, position):
        end = text.find(closer, start.end())
        if end < 0:
            break
        position = end + len(closer)
        found.append((start.start(), position))
    return found


def check_svg(root: Path, path: str, record: dict[str, Any], identity: list[str]) -> list[Finding]:
    """Every rule for one SVG that has a record."""
    findings: list[Finding] = []

    def add(rule: str, message: str) -> None:
        findings.append(Finding(path, rule, message))

    raw = (root / path).read_bytes()
    text = raw.decode("utf-8")
    try:
        # The repository's own tracked SVG files; expat resolves no external entity.
        tree = ET.fromstring(raw)  # noqa: S314  tracked files of this repository, not untrusted input
    except ET.ParseError as error:
        return [Finding(path, "M006", f"malformed XML: {error}")]
    svg_id = record.get("id", "")

    # M005: namespaces and where the metadata vocabularies may appear.
    metadata_elements = [e for e in tree.iter() if _local(e.tag) == (mm.NS_SVG, "metadata")]
    inside = {id(e) for m in metadata_elements for e in m.iter()}
    for element in tree.iter():
        ns, name = _local(element.tag)
        if ns not in mm.SVG_NAMESPACES:
            add("M005", f"element {name} in namespace {ns or '(none)'} is outside the profile")
        elif ns != mm.NS_SVG and id(element) not in inside:
            add("M005", f"element {name} outside <metadata>")
        for attribute in element.attrib:
            a_ns, a_name = _local(attribute)
            if a_ns and a_ns not in mm.SVG_NAMESPACES:
                add("M005", f"attribute {a_name} in namespace {a_ns} is outside the profile")
    for prefix in re.findall(r"xmlns:([A-Za-z0-9_.-]+)=", text):
        if prefix not in ("rdf", "dc", "cc", "Iptc4xmpExt", "xlink"):
            add("M005", f"namespace prefix {prefix} is outside the profile")
    if len(metadata_elements) > 1:
        add("M005", f"{len(metadata_elements)} <metadata> elements; the profile has one")
    for kind, payload in _DATA_URI.findall(text):
        if kind == "image/png":
            try:
                chunks = _png_chunks(base64.b64decode("".join(payload.split())))
            except ValueError as error:
                add("M006", f"embedded PNG: {error}")
                continue
            extra = sorted(
                {c.decode("latin-1") for c in chunks} - {c.decode() for c in BARE_PNG_CHUNKS}
            )
            if extra:
                add("M005", f"embedded PNG holds chunks outside the bare set: {', '.join(extra)}")
        else:
            add("M005", f"embedded {kind} is a format this checker does not inspect")

    # M001: the required fields.
    root_title = tree.find(f"{{{mm.NS_SVG}}}title")
    root_desc = tree.find(f"{{{mm.NS_SVG}}}desc")
    if root_title is None or not (root_title.text or "").strip():
        add("M001", "no root <title>")
    if root_desc is None or not (root_desc.text or "").strip():
        add("M001", "no root <desc>")
    if not metadata_elements:
        add("M001", "no <metadata> block")
    for key, value in mm.svg_root_attributes(svg_id, record.get("language", "en")).items():
        if tree.get(key) != value:
            add("M001", f"root attribute {key} is {tree.get(key)!r}, not {value!r}")

    # M011: the metadata between the REUSE ignore markers.
    start, end = text.find(mm.IGNORE_START), text.find(mm.IGNORE_END)
    for m_start, m_end in spans(text, _METADATA_OPEN, "</metadata>"):
        if not (0 <= start < m_start and m_end < end):
            add("M011", "a <metadata> block lies outside the REUSE ignore markers")

    # M012: the digital source type.
    dst = [
        e.get(f"{{{mm.NS_RDF}}}resource", "")
        for e in tree.iter(f"{{{mm.NS_IPTC_EXT}}}DigitalSourceType")
    ]
    if not dst:
        add("M012", "no DigitalSourceType")
    for value in dst:
        if value.removeprefix(mm.DST_BASE) not in mm.DIGITAL_SOURCE_TYPES or not value.startswith(
            mm.DST_BASE
        ):
            add("M012", f"unknown DigitalSourceType {value!r}")

    # M004: every metadata value and every comment.
    values = [
        text[c_start:c_end].removeprefix("<!--").removesuffix("-->").strip()
        for c_start, c_end in spans(text, _COMMENT_OPEN, "-->")
    ]
    for node in [root_title, root_desc, *metadata_elements]:
        if node is not None:
            values += [t for t in node.itertext() if t.strip()]
            for sub in node.iter():
                values += list(sub.attrib.values())
    for hit in mm.deny_hits(values, identity):
        add("M004", f"deny-list hit: {hit}")

    # M003: license and holders against REUSE.
    try:
        meta = mm.meta_from_record(path, record, root)
    except (KeyError, mm.MetaError) as error:
        add("M006", f"record: {error}")
        return findings
    toml = mm.reuse_toml_truth(path, root)
    full = mm.reuse_truth(path, root)
    if not toml[0]:
        add("M003", "REUSE.toml gives this path no license")
    if full != toml:
        add(
            "M003",
            "the file states REUSE information of its own (a notice outside the ignore markers)",
        )
    if meta.own_license not in mm.spdx_ids(meta.spdx):
        add("M003", f"own_license {meta.own_license} is not in {meta.spdx}")
    licenses = [e.get(f"{{{mm.NS_RDF}}}resource") for e in tree.iter(f"{{{mm.NS_CC}}}license")]
    try:
        wanted_license = mm.license_url(meta.own_license)
    except mm.MetaError as error:
        add("M003", str(error))
        wanted_license = None
    if wanted_license and licenses != [wanted_license]:
        add("M003", f"cc:license is {licenses}, not [{wanted_license!r}]")
    rights = [t for e in tree.iter(f"{{{mm.NS_DC}}}rights") for t in e.itertext() if t.strip()]
    if rights != [meta.copyright]:
        add("M003", f"dc:rights is {rights}, not [{meta.copyright!r}]")

    # M006 and M002: the record itself, then the whole file against it.
    try:
        expected = mm.stamp_svg(text, meta, svg_id).encode("utf-8")
    except mm.MetaError as error:
        add("M006", f"the file cannot be stamped: {error}")
        return findings
    if expected != raw:
        add(
            "M002",
            "the metadata differs from what the record generates"
            " (scripts/stamp_media_meta.py --write)",
        )
    if hashlib.sha256(raw).hexdigest() != record.get("sha256") or len(raw) != record.get("bytes"):
        add("M002", "bytes or SHA-256 differ from profile/assets/assets.json")
    return findings


def check(root: Path, paths: list[str] | None, identity: list[str]) -> list[Finding]:
    """Every finding for the given paths, or for every tracked media file."""
    manifest = json.loads((root / mm.MANIFEST).read_text(encoding="utf-8"))
    records = manifest.get("files", {})
    exempt = [row["path"] for row in manifest.get("exempt", [])]
    findings: list[Finding] = []
    findings.extend(
        Finding(mm.MANIFEST, "M006", f"exemption {row.get('path')!r} has no reason")
        for row in manifest.get("exempt", [])
        if not row.get("reason")
    )
    for path in paths if paths is not None else tracked_media(root):
        if path in records:
            if path.endswith(".svg"):
                findings += check_svg(root, path, records[path], identity)
            else:
                findings.append(Finding(path, "M006", "this repository checks SVG only"))
        elif not mm.fnmatch_any(path, exempt):
            findings.append(
                Finding(path, "M008", "a media file with neither a record nor an exemption")
            )
    for path in records:
        if not (root / path).is_file():
            findings.append(Finding(path, "M001", "recorded in the manifest but missing"))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print the findings as JSON")
    parser.add_argument(
        "paths", nargs="*", help="files to check (default: every tracked media file)"
    )
    args = parser.parse_args(argv)
    identity = mm.identity_patterns()
    if not identity:
        in_ci = os.environ.get("GITHUB_ACTIONS") == "true"
        if in_ci and os.environ.get("KLEIDOS_DENY_OPTIONAL") != "1":
            print(
                f"check_metadata: no identity patterns ({mm.DENY_ENV} is empty); refusing to pass",
                file=sys.stderr,
            )
            return 2
        message = (
            f"no identity patterns ({mm.DENY_ENV} or scripts/deny-local.txt);"
            " identity is not checked"
        )
        print(
            f"::warning::{message}" if in_ci else f"check_metadata: warning: {message}",
            file=sys.stderr,
        )
    root = mm.ROOT
    media = [p for p in args.paths if p.rsplit(".", 1)[-1].lower() in MEDIA_EXTENSIONS]
    try:
        findings = check(root, media if args.paths else None, identity)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"check_metadata: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([f.__dict__ for f in findings], indent=2, ensure_ascii=False))
    else:
        for finding in findings:
            print(finding.line())
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
