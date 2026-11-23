# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Kleidos media metadata, profile ``kleidos-media-meta/1``: the SVG part.

This module writes the metadata a published SVG carries (a descriptive
``<title>`` and ``<desc>``, a Dublin Core + ccREL ``<metadata>`` block
between the two REUSE ignore markers), resolves a
file's license and copyright holders from ``REUSE.toml``, and holds the
privacy deny-list every metadata value is matched against. It is the SVG
and deny-list part of the module every kleidos-dev repository keeps, and
it uses the Python standard library only.

Every value comes from fixed constants and the file's row in
``profile/assets/assets.json``: no date, no machine name, no tool version.
"""

from __future__ import annotations

import fnmatch
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

META_PROFILE = "kleidos-media-meta/1"

ROOT = Path(__file__).resolve().parent.parent
REPO = ".github"

CREATOR = "José M. Requena Plens"
CREATOR_URL = "https://kleidos.dev"
PROJECT = "Kleidos"
PROJECT_URL = "https://kleidos.dev"
CREDIT = "José M. Requena Plens"
BASE_KEYWORDS = ("Kleidos", "hardware password manager", "open source")
RIGHTS_URL = "https://github.com/kleidos-dev/.github/blob/main/LICENSE"

#: IPTC NewsCodes ``digitalsourcetype`` this profile accepts (standard 3.5).
DIGITAL_SOURCE_TYPES = (
    "digitalCapture",
    "screenCapture",
    "digitalCreation",
    "dataDrivenMedia",
    "composite",
    "trainedAlgorithmicMedia",
    "compositeWithTrainedAlgorithmicMedia",
    "compositeSynthetic",
)

#: SPDX identifiers whose license text lives on spdx.org.
SPDX_LIST_IDS = (
    "GPL-3.0-or-later",
    "MIT",
    "OFL-1.1",
    "Apache-2.0",
    "BSD-3-Clause",
    "CC0-1.0",
    "CC-BY-4.0",
)

TITLE_MAX_BYTES = 64
DESCRIPTION_MAX_CHARS = 300
COPYRIGHT_MAX_BYTES = 128
KEYWORDS_MAX = 12
KEYWORD_MAX_BYTES = 64

#: The vocabularies the profile names, as XML declares them: a prefix bound
#: to a namespace name. A namespace name is an identifier that is compared
#: character by character (Namespaces in XML 1.0, section 2.3), never an
#: address that is fetched, so each one is spelled as its vocabulary spells it.
NAMESPACE_DECLARATIONS = (
    'xmlns:svg="http://www.w3.org/2000/svg"',
    'xmlns:xlink="http://www.w3.org/1999/xlink"',
    'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"',
    'xmlns:dc="http://purl.org/dc/elements/1.1/"',
    'xmlns:cc="http://creativecommons.org/ns#"',
    'xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"',
    'xmlns:xml="http://www.w3.org/XML/1998/namespace"',
    'xmlns:digsrctype="http://cv.iptc.org/newscodes/digitalsourcetype/"',
)


def namespace_names(declarations: tuple[str, ...]) -> dict[str, str]:
    """The namespace name each declaration binds its prefix to."""
    names: dict[str, str] = {}
    for declaration in declarations:
        attribute, _, name = declaration.partition("=")
        names[attribute.removeprefix("xmlns:")] = name.strip('"')
    return names


_NAMES = namespace_names(NAMESPACE_DECLARATIONS)
NS_SVG = _NAMES["svg"]
NS_XLINK = _NAMES["xlink"]
NS_RDF = _NAMES["rdf"]
NS_DC = _NAMES["dc"]
NS_CC = _NAMES["cc"]
NS_IPTC_EXT = _NAMES["Iptc4xmpExt"]
NS_XML = _NAMES["xml"]
#: The namespaces a published SVG may use, and nothing else.
SVG_NAMESPACES = (NS_SVG, NS_XLINK, NS_RDF, NS_DC, NS_CC, NS_IPTC_EXT, NS_XML)
#: IPTC's vocabulary of digital source types (its own alias is ``digsrctype``);
#: a term's identifier is this name with the term after it.
DST_BASE = _NAMES["digsrctype"]

#: The REUSE tool skips what lies between these two markers. The words are
#: split here so the tool does not read this file's own lines as markers.
_MARK = "REUSE-Ignore"
IGNORE_START = f"<!-- {_MARK}Start -->"
IGNORE_END = f"<!-- {_MARK}End -->"
#: The copyright sign, written as an escape so REUSE reads no notice here.
COPYRIGHT_SIGN = "\u00a9"


class MetaError(ValueError):
    """A record that cannot be written as the profile asks."""


@dataclass(frozen=True)
class MediaMeta:
    """What one published file says about itself (standard 2.5)."""

    title: str
    description: str
    keywords: tuple[str, ...]
    digital_source_type: str
    spdx: str
    own_license: str
    holders: tuple[str, ...]
    identifier_url: str
    source_url: str | None = None
    rights_url: str = RIGHTS_URL
    language: str = "en"
    title_es: str | None = None
    description_es: str | None = None
    notice: str | None = None
    credits: tuple[str, ...] = field(default_factory=tuple)

    @property
    def copyright(self) -> str:
        """The short rights line: holders and the REUSE expression."""
        return (
            COPYRIGHT_SIGN
            + " "
            + ("; " + COPYRIGHT_SIGN + " ").join(self.holders)
            + ". "
            + self.spdx
            + "."
        )


# --------------------------------------------------------------------------
# URLs


def license_url(spdx_id: str) -> str:
    """The page that holds the text of one license (standard 2.1)."""
    if spdx_id in SPDX_LIST_IDS:
        return f"https://spdx.org/licenses/{spdx_id}.html"
    if spdx_id.startswith("LicenseRef-"):
        text = ROOT / "LICENSES" / f"{spdx_id}.txt"
        if not text.is_file():
            raise MetaError(f"{spdx_id} has no license text in this repository")
        return f"https://github.com/kleidos-dev/{REPO}/blob/main/LICENSES/{spdx_id}.txt"
    raise MetaError(f"{spdx_id} is not a license this profile knows")


def identifier_url(path: str) -> str:
    """The public URL of a file's own path in this repository."""
    return f"https://github.com/kleidos-dev/{REPO}/blob/main/{path}"


def spdx_ids(expression: str) -> list[str]:
    """The license identifiers in an SPDX expression, in order."""
    words = re.findall(r"[A-Za-z0-9.+-]+", expression)
    return [w for w in words if w not in ("AND", "OR", "WITH")]


# --------------------------------------------------------------------------
# REUSE


_IN_FILE_COPYRIGHT = re.compile(
    "(SPDX-(File|Snippet)"
    + "CopyrightText:|"
    + "Copy"
    + r"right(\s?\([cC]\))?\s|"
    + COPYRIGHT_SIGN
    + ")"
)
_IN_FILE_LICENSE = "SPDX-" + "License-Identifier:"
_IGNORED = re.compile(_MARK + r"Start.*?(" + _MARK + r"End|\Z)", re.S)


def strip_email(holder: str) -> str:
    """A copyright holder with any ``<address>`` removed (standard 2.4)."""
    *closed, tail = holder.split(">")
    kept = []
    for piece in closed:
        before, opened, _ = piece.partition("<")
        kept.append(before.rstrip() if opened else piece + ">")
    return ("".join(kept) + tail).strip()


def _glob_match(pattern: str, path: str) -> bool:
    """REUSE glob: ``*`` stays inside one folder, ``**`` crosses folders."""
    regex = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            regex += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            regex += ".*"
            i += 2
        elif pattern[i] == "*":
            regex += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            regex += "[^/]"
            i += 1
        else:
            regex += re.escape(pattern[i])
            i += 1
    return re.fullmatch(regex, path) is not None


def _as_list(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def in_file_license(line: str) -> str:
    """The license expression a line states, or nothing.

    The expression ends where the comment that holds it closes (``*/`` or
    ``-->``) or with the line.
    """
    expression = line.partition(_IN_FILE_LICENSE)[2]
    for closing in ("*/", "-->"):
        expression = expression.partition(closing)[0]
    return expression.strip()


def in_file_reuse(path: Path) -> tuple[list[str], list[str]]:
    """The notices and license expressions a file states itself.

    It reads what the REUSE tool reads in a text file: ``SPDX-*`` tags and
    the lines that hold a notice (the word or the sign), outside any region
    between the two ignore markers.
    """
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        return [], []
    text = _IGNORED.sub("", data.decode("utf-8", errors="replace"))
    copyrights: list[str] = []
    licenses: list[str] = []
    for line in text.splitlines():
        if _IN_FILE_COPYRIGHT.search(line):
            copyrights.append(line.strip())
        license_expression = in_file_license(line)
        if license_expression:
            licenses.append(license_expression)
    return copyrights, licenses


def reuse_annotation(path: str, root: Path = ROOT) -> dict[str, Any]:
    """The last ``[[annotations]]`` table of ``REUSE.toml`` that matches a path."""
    config = tomllib.loads((root / "REUSE.toml").read_text(encoding="utf-8"))
    chosen: dict[str, Any] = {}
    for table in config.get("annotations", []):
        if any(_glob_match(p, path) for p in _as_list(table.get("path"))):
            chosen = table
    return chosen


def reuse_toml_truth(path: str, root: Path = ROOT) -> tuple[str, tuple[str, ...]]:
    """The license expression and holders ``REUSE.toml`` alone gives a path.

    A file this module stamps states no REUSE information itself (its
    metadata sits between the ignore markers), so this is what its
    metadata says; the checker proves the file adds nothing to it.
    """
    chosen = reuse_annotation(path, root)
    holders = _as_list(chosen.get("SPDX-FileCopyrightText"))
    licenses = _as_list(chosen.get("SPDX-" + "License-Identifier"))
    expression = " AND ".join(licenses)
    return expression, tuple(strip_email(h) for h in holders)


def reuse_truth(path: str, root: Path = ROOT) -> tuple[str, tuple[str, ...]]:
    """The license expression and holders REUSE gives one path.

    It follows REUSE 3.3: the last ``[[annotations]]`` table whose ``path``
    matches decides, with its ``precedence`` (``closest``, ``aggregate`` or
    ``override``) weighed against what the file states itself. Holders
    come back without e-mail addresses.
    """
    chosen = reuse_annotation(path, root)
    toml_holders = _as_list(chosen.get("SPDX-FileCopyrightText"))
    toml_licenses = _as_list(chosen.get("SPDX-" + "License-Identifier"))
    precedence = chosen.get("precedence", "closest")
    file_holders, file_licenses = (
        ([], []) if precedence == "override" else in_file_reuse(root / path)
    )
    if precedence == "override":
        holders, licenses = toml_holders, toml_licenses
    elif precedence == "aggregate":
        holders = toml_holders + [h for h in file_holders if h not in toml_holders]
        licenses = toml_licenses + [x for x in file_licenses if x not in toml_licenses]
    else:
        holders = file_holders or toml_holders
        licenses = file_licenses or toml_licenses
    expression = " AND ".join(licenses) if len(licenses) > 1 else (licenses[0] if licenses else "")
    return expression, tuple(strip_email(h) for h in holders)


# --------------------------------------------------------------------------
# The SVG block


def escape(text: str) -> str:
    """XML escaping of the four characters the profile escapes."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def validate(meta: MediaMeta) -> None:
    """Refuse a record the profile cannot write; never truncate."""
    if len(meta.title.encode("utf-8")) > TITLE_MAX_BYTES:
        raise MetaError(f"title over {TITLE_MAX_BYTES} bytes: {meta.title!r}")
    if len(meta.description) > DESCRIPTION_MAX_CHARS:
        raise MetaError(f"description over {DESCRIPTION_MAX_CHARS} characters")
    if len(meta.copyright.encode("utf-8")) > COPYRIGHT_MAX_BYTES:
        raise MetaError(f"copyright over {COPYRIGHT_MAX_BYTES} bytes: {meta.copyright!r}")
    if len(meta.keywords) > KEYWORDS_MAX:
        raise MetaError(f"more than {KEYWORDS_MAX} keywords")
    for word in meta.keywords:
        if len(word.encode("utf-8")) > KEYWORD_MAX_BYTES:
            raise MetaError(f"keyword over {KEYWORD_MAX_BYTES} bytes: {word!r}")
    if meta.digital_source_type not in DIGITAL_SOURCE_TYPES:
        raise MetaError(f"unknown digital source type {meta.digital_source_type!r}")
    if meta.own_license not in spdx_ids(meta.spdx):
        raise MetaError(f"{meta.own_license} is not in {meta.spdx}")
    if meta.language not in ("en", "es"):
        raise MetaError(f"unknown language {meta.language!r}")
    if meta.language == "es" and not (meta.title_es and meta.description_es):
        raise MetaError("a Spanish file needs title_es and description_es")
    if meta.notice is not None and ("--" in meta.notice or meta.notice != meta.notice.strip()):
        raise MetaError("the notice cannot hold '--' or leading or trailing spaces")
    for hit in deny_hits(svg_texts_of(meta)):
        raise MetaError(f"deny-list: {hit}")


def svg_texts_of(meta: MediaMeta) -> list[str]:
    """Every value of a record that ends up in the file."""
    values = [meta.title, meta.description, meta.copyright, meta.identifier_url]
    values += list(meta.keywords)
    values += [v for v in (meta.source_url, meta.title_es, meta.description_es, meta.notice) if v]
    return values


def svg_root_attributes(svg_id: str, language: str) -> dict[str, str]:
    """The attributes the profile sets on the root ``<svg>``."""
    return {
        "role": "img",
        "aria-labelledby": f"{svg_id}-t {svg_id}-d",
        "lang": language,
    }


def svg_block(meta: MediaMeta, svg_id: str) -> str:
    """The text that follows the root ``<svg>`` start tag (standard 5.7)."""
    validate(meta)
    title, description = meta.title, meta.description
    if meta.language == "es":
        if meta.title_es is None or meta.description_es is None:  # validate() refuses it
            raise MetaError("a Spanish file needs title_es and description_es")
        title, description = meta.title_es, meta.description_es
        dc_title = (
            "<dc:title><rdf:Alt>"
            f'<rdf:li xml:lang="x-default">{escape(meta.title)}</rdf:li>'
            f'<rdf:li xml:lang="es">{escape(title)}</rdf:li>'
            "</rdf:Alt></dc:title>"
        )
        dc_description = (
            "<dc:description><rdf:Alt>"
            f'<rdf:li xml:lang="x-default">{escape(meta.description)}</rdf:li>'
            f'<rdf:li xml:lang="es">{escape(description)}</rdf:li>'
            "</rdf:Alt></dc:description>"
        )
    else:
        dc_title = f"<dc:title>{escape(meta.title)}</dc:title>"
        dc_description = f"<dc:description>{escape(meta.description)}</dc:description>"
    lines = [
        f'<title id="{svg_id}-t">{escape(title)}</title>',
        f'<desc id="{svg_id}-d">{escape(description)}</desc>',
        IGNORE_START,
        f'<metadata id="{svg_id}-m">',
        f'  <rdf:RDF xmlns:rdf="{NS_RDF}"',
        f'           xmlns:dc="{NS_DC}"',
        f'           xmlns:cc="{NS_CC}"',
        f'           xmlns:Iptc4xmpExt="{NS_IPTC_EXT}">',
        '    <cc:Work rdf:about="">',
        "      <dc:format>image/svg+xml</dc:format>",
        '      <dc:type rdf:resource="http://purl.org/dc/dcmitype/StillImage"/>',
        f"      {dc_title}",
        f"      {dc_description}",
        (
            "      <dc:creator><cc:Agent>"
            f"<dc:title>{escape(CREATOR)}</dc:title>"
            "</cc:Agent></dc:creator>"
        ),
        (
            "      <dc:publisher><cc:Agent>"
            f"<dc:title>{escape(PROJECT)}</dc:title>"
            "</cc:Agent></dc:publisher>"
        ),
        (
            "      <dc:rights><cc:Agent>"
            f"<dc:title>{escape(meta.copyright)}</dc:title>"
            "</cc:Agent></dc:rights>"
        ),
        f"      <dc:identifier>{escape(meta.identifier_url)}</dc:identifier>",
    ]
    if meta.source_url:
        lines.append(f"      <dc:source>{escape(meta.source_url)}</dc:source>")
    lines.append(f"      <dc:language>{meta.language}</dc:language>")
    lines.append("      <dc:subject><rdf:Bag>")
    lines += [f"        <rdf:li>{escape(k)}</rdf:li>" for k in meta.keywords]
    lines.append("      </rdf:Bag></dc:subject>")
    lines.append(
        "      <Iptc4xmpExt:DigitalSourceType"
        f' rdf:resource="{DST_BASE}{meta.digital_source_type}"/>'
    )
    lines.append(f'      <cc:license rdf:resource="{license_url(meta.own_license)}"/>')
    lines += ["    </cc:Work>", "  </rdf:RDF>", "</metadata>"]
    if meta.notice:
        lines.append(f"<!-- {meta.notice} -->")
    lines.append(IGNORE_END)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Privacy deny-list (standard 7, text layer)

#: The top directories of a local file system whose names give a path away.
_LOCAL_ROOTS = ("Users", "home", "private", "var/folders", "tmp", "Volumes")

DENY: dict[str, tuple[str, ...]] = {
    # The lookbehind starts a match only where a run of address characters
    # starts, so a run that holds no "@" is read once.
    "e-mail": (r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",),
    "local path": (
        *(f"/{re.escape(root)}/" for root in _LOCAL_ROOTS),
        r"file://",
        r"~/",
        r"\b[A-Za-z]:\\",
        r"\\Users\\",
    ),
    "host or network": (
        r"\.local\b",
        r"\.lan\b",
        r"\.home\b",
        r"\blocalhost\b",
        r"\b192\.168\.\d+\.\d+\b",
        r"\b10\.\d+\.\d+\.\d+\b",
        r"\b172\.(1[6-9]|2\d|3[01])\.\d+\.\d+\b",
        r"\bMacBook",
        r"\biMac\b",
        r"-mbp\b",
    ),
    "machine time": (r"\d{4}[-:]\d{2}[-:]\d{2}[ T]\d{2}:\d{2}",),
    "tool or version": (
        r"\bLavf\d",
        r"\bLavc\d",
        r"x264 - core",
        r"\blibx264\b",
        r"\bImageMagick\b",
        r"\bGIMP\b",
        r"\bInkscape\b",
        r"sodipodi:",
        r"\bIllustrator\b",
        r"\bPillow\b",
        r"\bHeadlessChrome\b",
        r"Eeschema-SVG",
        r"Image::ExifTool",
    ),
}

DENY_LOCAL_FILE = Path(__file__).resolve().parent / "deny-local.txt"
DENY_ENV = "KLEIDOS_DENY_EXTRA"


def identity_patterns() -> list[str]:
    """Identity patterns, kept out of the public tree (standard 7).

    They come from the ``KLEIDOS_DENY_EXTRA`` variable (a CI secret, one
    pattern per line) or from an untracked ``scripts/deny-local.txt``.
    """
    lines = os.environ.get(DENY_ENV, "").splitlines()
    if DENY_LOCAL_FILE.is_file():
        lines += DENY_LOCAL_FILE.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def deny_hits(values: list[str], identity: list[str] | None = None) -> list[str]:
    """The deny-list classes the values hit; identity hits name no text."""
    hits: list[str] = []
    for value in values:
        for name, patterns in DENY.items():
            for pattern in patterns:
                found = re.search(pattern, value)
                if found:
                    hits.append(f"{name} ({found.group(0)!r})")
        hits.extend("identity" for pattern in identity or [] if re.search(pattern, value, re.I))
    return hits


def fnmatch_any(path: str, patterns: list[str]) -> bool:
    """Whether a path matches one of the exemption globs."""
    return any(fnmatch.fnmatchcase(path, p) or _glob_match(p, path) for p in patterns)


# --------------------------------------------------------------------------
# Records and stamping

#: Where this repository keeps its media records and their digests.
MANIFEST = "profile/assets/assets.json"

_ROOT_TAG = re.compile(r"<svg\b[^>]*>", re.S)
_HEAD = re.compile(
    r"(?:\s*(?:<!--.*?-->|<title\b[^>]*>.*?</title>|<desc\b[^>]*>.*?</desc>"
    r"|<metadata\b[^>]*>.*?</metadata>))*\s*",
    re.S,
)


def meta_from_record(path: str, record: dict[str, Any], root: Path = ROOT) -> MediaMeta:
    """The record of one file, with its license and holders from REUSE."""
    spdx, holders = reuse_toml_truth(path, root)
    return MediaMeta(
        title=record["title"],
        description=record["description"],
        keywords=tuple(record["keywords"]),
        digital_source_type=record["digital_source_type"],
        spdx=spdx,
        own_license=record["own_license"],
        holders=holders,
        identifier_url=identifier_url(path),
        source_url=record.get("source_url"),
        language=record.get("language", "en"),
        title_es=record.get("title_es"),
        description_es=record.get("description_es"),
        notice=record.get("notice"),
    )


def root_attributes(tag: str) -> list[tuple[str, str]]:
    """The attributes of the root start tag, in order.

    Between one double quote and the next the tag alternates a name with its
    ``=`` and a value. A tag that reads otherwise (a single-quoted value, a
    bare name, a ``>`` inside a value) is refused: writing it back would lose
    part of it.
    """
    pieces = tag.removeprefix("<svg").removesuffix(">").removesuffix("/").split('"')
    names = [piece.strip() for piece in pieces[0::2]]
    values = pieces[1::2]
    if names.pop() or len(names) != len(values):
        raise MetaError("the root <svg> tag holds something that is not an attribute")
    attributes = []
    for name, value in zip(names, values, strict=True):
        key = name.removesuffix("=").rstrip()
        if key == name or not key or any(c.isspace() or c in "='<" for c in key):
            raise MetaError(f"the root <svg> tag holds {name!r}, not an attribute")
        attributes.append((key, value))
    return attributes


def stamp_svg(text: str, meta: MediaMeta, svg_id: str) -> str:
    """An SVG with its profile metadata written, the drawing left as it is.

    Only the root start tag's ``role``, ``aria-labelledby`` and ``lang``
    and the run of comments, ``<title>``, ``<desc>`` and ``<metadata>``
    that follows it are rewritten; every byte after that run is kept.
    Stamping a stamped file gives the same bytes back.
    """
    found = _ROOT_TAG.search(text)
    if found is None:
        raise MetaError("no root <svg> element")
    tag = found.group(0)
    attributes = root_attributes(tag)
    wanted = svg_root_attributes(svg_id, meta.language)
    kept = [(k, wanted.pop(k) if k in wanted else v) for k, v in attributes]
    kept += list(wanted.items())
    closing = "/>" if tag.endswith("/>") else ">"
    new_tag = "<svg " + " ".join(f'{k}="{v}"' for k, v in kept) + closing
    rest = text[found.end() :]
    head = _HEAD.match(rest)  # matches every string: each part of it is optional
    drawing = rest[head.end() :] if head else rest
    return text[: found.start()] + new_tag + svg_block(meta, svg_id) + drawing
