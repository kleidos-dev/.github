# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""No e-mail address in the fields that say who a thing comes from.

The owner's statement is year and name in a copyright (spdx_headers.py), and
a name alone in the metadata too (owner, 2026-11-25): the supplier and the
originator of REUSE.toml, the authors and maintainers of a manifest, the
people of a citation or of a software bill of materials.

  the fields   METADATA, one list: the files, and the keys of each; and a
               mailto: link anywhere in them
  what passes  a name; and mail@kleidos.dev where the tool that reads the
               field needs an address, which is a weakening whose waiver
               (tool = "supplier") names that tool. No other address, with
               no waiver

A file that cannot be read as its format says is searched whole, and so is
one whose format has no fields here. A file that REUSE.toml states is a third
party's is not ours to correct. What is an address, and what the rule does
not read: docs/quality.md, "Supplier fields".

Python 3.14 or newer; PyYAML.
"""

from __future__ import annotations

import ast
import base64
import fnmatch
import html
import json
import re
import tomllib
import unicodedata
import urllib.parse
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from xml.parsers import expat

import check_quality as cq
import spdx_headers
import yaml

ALLOWED = "mail@kleidos.dev"
WHOLE = "the file"


@dataclass(frozen=True)
class Metadata:
    """Files that say who a thing comes from, and the fields that say it.

    A file is named by its name, by the end of its path, or (`/name`) from the
    root, in any case. A field is named from the top of the file, `**.` at any
    depth, and holds all that is below it; case and the two dashes
    (`author_email`, `author-email`) are one, and a list adds no name. Files
    with no fields are searched whole. A bill is a software bill of materials:
    the packages it lists are other people's.
    """

    files: tuple[str, ...]
    fields: tuple[str, ...] = ()
    bill: bool = False


METADATA = (
    Metadata(
        ("reuse.toml",),
        ("**.spdx-packagesupplier", "**.spdx-packageoriginator", "**.spdx-filecontributor"),
    ),
    Metadata(
        ("package.json", "package.yaml", "composer.json", "bower.json", "deno.json", "jsr.json"),
        ("author", "authors", "bugs", "contributors", "funding", "maintainers", "publisher")
        + ("support",),
    ),
    Metadata(
        ("pyproject.toml", "cargo.toml"),
        ("**.author", "**.author-email", "**.authors")
        + ("**.maintainer", "**.maintainer-email", "**.maintainers"),
    ),
    Metadata(
        ("citation.cff",), ("authors", "contact", "preferred-citation", "references", "**.email")
    ),
    Metadata(
        ("codemeta.json", ".zenodo.json"),
        ("**.author", "**.contactpoint", "**.contributor", "**.contributors")
        + ("**.copyrightholder", "**.creator", "**.creators", "**.editor", "**.email")
        + ("**.funder", "**.maintainer", "**.producer", "**.provider", "**.publisher")
        + ("**.sponsor",),
    ),
    Metadata(
        ("idf_component.yml", "idf_component.yaml", "library.json"), ("authors", "maintainers")
    ),
    Metadata(
        (".claude-plugin/*.json",),
        ("**.author", "**.authors", "**.contributors")
        + ("**.maintainer", "**.maintainers", "**.owner"),
    ),
    Metadata(("action.yml", "action.yaml"), ("author",)),
    Metadata(("manifest.json",), ("author", "developer")),
    # SPDX or CycloneDX, and the fields of the document and of what it describes.
    Metadata(
        ("bom.json", "bom.xml", "*sbom*.json", "*sbom*.xml", "*sbom*.yaml", "*sbom*.yml")
        + ("*.cdx.json", "*.cdx.xml", "cyclonedx.json")
        + ("spdx.json", "*.spdx", "*.spdx.json", "*.spdx.yaml", "*.spdx.yml"),
        ("author", "authors", "creators", "manufacturer", "originator", "publisher", "supplier")
        + ("metadata.author", "metadata.authors", "metadata.component", "metadata.manufacture")
        + ("metadata.manufacturer", "metadata.publisher", "metadata.supplier")
        + ("annotations.annotator", "creationinfo", "packages.annotations")
        + ("packages.originator", "packages.supplier", "revieweds.reviewer"),
        bill=True,
    ),
    Metadata(
        ("setup.py", "setup.cfg", "library.properties", "*.gemspec", "debian/control")
        + (".reuse/dep5",)
    ),
    Metadata(
        tuple(
            folder + name + suffix
            for name in ("authors", "contributors", "maintainers")
            for suffix in ("", ".md", ".txt")
            for folder in ("/", "/.github/")
        )
        + ("/codeowners", "/.github/codeowners", "/docs/codeowners", "/.mailmap")
    ),
)

# Folders whose files are planted examples, and the domains that are nobody's.
EXAMPLES = {"test", "tests", "__tests__", "fixtures", "__fixtures__", "testdata"}
RESERVED = re.compile(
    r"""(?<![\w.+-])[\w.+-]+@ (?:[\w-]+\.)*
    (?: example\.(?:com|net|org) | [\w-]+\.(?:example|invalid|test) ) (?![\w-]|\.\w)""",
    re.IGNORECASE | re.VERBOSE,
)

# What has the shape of an address and is none: the user of a URL, a clone
# address, a version (name@1.2.3), an image at a scale or a theme (a@2x.png).
NO_ADDRESS = re.compile(
    r"""(?<![\w+.-]) (?:(?:git|hg|svn|bzr)\+)? (?:https?|ftps?|sftp|ssh|git|svn|rsync)
        :// [^\s/@<>"'?\#,;()]* @
    | (?<![\w.+-]) (?: git@[\w.-]+: (?=[\w~/.]) | [\w.+-]+@[\w.-]+:[\w~/.-]+\.git\b )
    | @ (?! [v\d.]* \.[^\W\d][\w-]*\.[^\W\d] ) v?\d+\.(?:\d|x\b)
    | @ [\w.-]+ \.(?:avif|bmp|gif|ico|jpe?g|png|svg|webp)\b (?![\w-]|\.\w)""",
    re.IGNORECASE | re.VERBOSE,
)
# A handle of the fediverse, in a text: @user@host.
HANDLE = re.compile(r"(?<![\w.%+-])@[\w.+-]+@[\w.-]+")

# The marks of an address, as they are written or in words. A label is bounded,
# as a domain's is, and every alternative starts at a mark: the search is linear.
LABEL = r"[\w-]{1,63}"
NAME = r"[^\W_](?:[^\W_]|-){0,62}"
INSIDE = r"\s?[\[({{<]\s?(?:{0})\s?[\])}}>]\s?"
DOT = rf"(?: \. | {INSIDE.format(r'\.|dot')} | [\W_]{{1,3}}dot[\W_]{{1,3}} )"
ADDRESS = re.compile(
    rf"""(?: (?<=[\w!\#$%&*+.?^}}~-])@ | (?<=\w["'])@ | (?<=\w)\s{{0,3}}@\s{{0,3}} )
        (?: {LABEL}{DOT}\w | \[(?:IPv6:)?[0-9a-f:.]{{2,45}}\] )
    | (?<=\w) (?: {INSIDE.format("at|@")} {LABEL}{DOT}\w
      | [\W_]{{1,3}}at[\W_]{{1,3}} (?!(?:an?|th(?:e|is|at|ese|ose))\b)
        (?:{NAME}\.){{0,4}} {NAME} [\W_]{{1,3}}dot[\W_]{{1,3}} [^\W\d_]{{2}} )
    | [\[(<{{]\s? [\w.+-]{{1,64}} \s{{1,3}}at\s{{1,3}} (?:{LABEL}\.){{1,5}} [^\W\d_]{{2,24}}
        \s?[\])>}}]
    | <[^<>@\s/]{{1,64}}@[^<>@\s]+>""",
    re.IGNORECASE | re.VERBOSE,
)
# The one address, with a mark of its own before it and nothing that goes on
# after it; in a whole file also after `email=`.
OWN, OWN_IN_TEXT = (
    re.compile(
        rf"(?<![^\s<(\[,;:\"'{marks}])(?<!\w')(?:{re.escape(ALLOWED)})(?![\w@%!-]|\.\w)",
        re.IGNORECASE,
    )
    for marks in ("", "=")
)

ESCAPE = re.compile(
    r"\\(?:x([0-9A-Fa-f]{2})|u([0-9A-Fa-f]{4})|u\{([0-9A-Fa-f]{1,5})\}|U000([0-9A-Fa-f]{5}))"
)


class Letters(dict[int, str]):
    """A character without its variants: compatibility forms, marks, what does not show."""

    def __missing__(self, code: int) -> str:
        letters = unicodedata.normalize("NFKD", chr(code)).replace("\u3002", ".")
        self[code] = "".join(
            ch
            for ch in letters
            if ch in "\t\n\r" or not (unicodedata.category(ch)[0] in "CM" or ch == "\u2800")
        )
        return self[code]


LETTERS = Letters()


def plain(value: str) -> str:
    """A text as a person reads it: decoded, and with nothing that does not show."""
    value = ESCAPE.sub(lambda m: chr(int("".join(filter(None, m.groups())), 16)), value)
    for _ in range(3):  # what one decoding shows may be another's
        value = re.sub("&(?:amp;)+", "&", re.sub("%(?:25)+", "%", value).translate(LETTERS))
        value = urllib.parse.unquote(html.unescape(value))
    return value.translate(LETTERS)


def addresses(value: str, *, whole: bool = False, examples: bool = False) -> tuple[bool, bool]:
    """Whether a text holds the one allowed address, and whether it holds another.

    In a whole file a handle is no address, and where examples are, nor is
    one at a domain reserved for them.
    """
    text = plain(value)
    own = OWN_IN_TEXT if whole else OWN
    # Written as it is: one that only reads like it is another address.
    allowed = len(own.findall(text))
    if len(re.findall(re.escape(ALLOWED), value, re.IGNORECASE | re.ASCII)) >= allowed:
        text = own.sub(";", text)
    for pattern in (NO_ADDRESS, *([HANDLE] * whole), *([RESERVED] * examples)):
        text = pattern.sub(" ; ", text)
    return allowed > 0, ADDRESS.search(text) is not None


# --------------------------------------------------------------------------
# The readers


class Pairs(list[tuple[str, Any]]):
    """A mapping as it is written: a key that is there twice counts twice."""

    def of(self, name: str) -> list[Any]:
        """Every value of a key, the items of a list one by one."""
        values = (value for key, value in self if key.casefold() == name)
        return [
            item
            for value in values
            for item in (
                value if isinstance(value, list) and not isinstance(value, Pairs) else [value]
            )
        ]


class OfYaml:
    """A YAML document's values, unread: a scalar is its text.

    Aliases are unfolded where they stand, so what they add up to is bounded
    by what is written: a text of so many characters has no more nodes.
    """

    def __init__(self, text: str) -> None:
        self.left = 2 * len(text) + 10
        self.value = self.of(yaml.compose(text, Loader=yaml.SafeLoader))

    def of(self, node: yaml.Node | None) -> Any:
        self.left -= 1
        if self.left < 0:
            raise ValueError("its aliases add up to more than it is")
        if isinstance(node, yaml.MappingNode):
            return Pairs(self.pairs(node))
        if isinstance(node, yaml.SequenceNode):
            return [self.of(item) for item in node.value]
        if node is not None and node.tag == "tag:yaml.org,2002:binary":
            return decoded(node.value)
        return node.value if node else None

    def pairs(self, node: yaml.MappingNode) -> Iterator[tuple[str, Any]]:
        """Every key and value, those of a merge (`<<`) in its place."""
        for key, value in node.value:
            self.left -= 1
            if not isinstance(key, yaml.ScalarNode):
                yield "?", [self.of(key), self.of(value)]
            elif key.value == "<<" and isinstance(value, yaml.CollectionNode):
                for item in value.value if isinstance(value, yaml.SequenceNode) else [value]:
                    merged = self.of(item)
                    yield from merged if isinstance(merged, Pairs) else ()
            else:
                yield key.value, self.of(value)


def decoded(text: str) -> str:
    """A base64 text's own text."""
    try:
        return base64.b64decode(text).decode("utf-8", "replace")
    except ValueError:
        return text


def read_yaml(text: str) -> Any:
    return OfYaml(text).value


def read_json(text: str) -> Any:
    return json.loads(text, object_pairs_hook=Pairs)


def read_python(text: str) -> Any:
    """Every string of a module."""
    return [
        node.value
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


class OfXml:
    """An XML document's values, below its root: an element's text, its attributes, its elements.

    A document type is refused, and with it the entities it may declare.
    """

    DEEPEST = 100

    def __init__(self, text: str) -> None:
        self.root = Pairs()
        self.open: list[tuple[Pairs, list[str]]] = [(self.root, [])]
        parser = expat.ParserCreate()
        parser.StartDoctypeDeclHandler = self.refuse
        parser.StartElementHandler = self.start
        parser.EndElementHandler = self.end
        parser.CharacterDataHandler = self.text
        parser.Parse(text, True)

    def refuse(self, *_args: object) -> None:
        raise ValueError("a document type")

    def start(self, name: str, attributes: dict[str, str]) -> None:
        if len(self.open) > self.DEEPEST:
            raise ValueError("too deep")
        below = Pairs(attributes.items())
        self.open[-1][0].append((name.rpartition(":")[2], below))
        self.open.append((below, []))

    def end(self, _name: str) -> None:
        below, text = self.open.pop()
        below.append(("", "".join(text)))

    def text(self, data: str) -> None:
        self.open[-1][1].append(data)


def read_xml(text: str) -> Any:
    return [below for _root, below in OfXml(text).root]


# The tags of SPDX's own format that name people, and what JSON calls them.
SPDX_TAGS = {
    "creator": ("creationInfo", "creators"),
    "reviewer": ("revieweds", "reviewer"),
    "annotator": ("annotations", "annotator"),
    "packagesupplier": ("packages", "supplier"),
    "packageoriginator": ("packages", "originator"),
}


def read_spdx(text: str) -> Any:
    """SPDX's own format, one tag on a line, as the JSON of the same document."""
    doc, package = Pairs(), Pairs()
    for line in text.splitlines():
        tag, _sep, value = (part.strip() for part in line.partition(":"))
        tag = tag.casefold()
        if tag == "packagename":
            package = Pairs()
            doc.append(("packages", package))
        elif tag == "spdxid":
            package.append(("SPDXID", value))
        elif tag == "relationship":
            names = ("spdxElementId", "relationshipType", "relatedSpdxElement")
            doc.append(("relationships", Pairs(zip(names, value.split(), strict=False))))
        elif tag in SPDX_TAGS:
            table, name = SPDX_TAGS[tag]
            if table == "packages":
                package.append((name, value))
            else:
                doc.append((table, Pairs([(name, value)])))
    return doc


READERS: dict[str, Callable[[str], Any]] = {
    ".toml": tomllib.loads,
    ".json": read_json,
    ".yml": read_yaml,
    ".yaml": read_yaml,
    ".cff": read_yaml,
    ".py": read_python,
    ".xml": read_xml,
    ".spdx": read_spdx,
}


def own_packages(doc: Any) -> Any:
    """An SPDX document with the packages it describes only, where it says which."""
    if not isinstance(doc, Pairs):
        return doc
    described = {str(name) for name in doc.of("documentdescribes")}
    for relation in doc.of("relationships"):
        if isinstance(relation, Pairs):
            ends = [
                str(name)
                for key in ("spdxelementid", "relationshiptype", "relatedspdxelement")
                for name in relation.of(key)
            ]
            if ends[:2] == ["SPDXRef-DOCUMENT", "DESCRIBES"]:
                described.update(ends[2:])
            elif ends[1:] == ["DESCRIBED_BY", "SPDXRef-DOCUMENT"]:
                described.add(ends[0])
    if not described:
        return doc
    kept = [
        package
        for package in doc.of("packages")
        if isinstance(package, Pairs) and described & {str(n) for n in package.of("spdxid")}
    ]
    return Pairs([*(pair for pair in doc if pair[0] != "packages"), ("packages", kept)])


def texts(value: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str]]:
    """Every text of a document, keys included, with the names that lead to it."""
    if isinstance(value, dict):
        value = Pairs(value.items())
    if isinstance(value, Pairs):
        for key, below in value:
            at = (*path, key) if key else path
            yield at, key
            yield from texts(below, at)
    elif isinstance(value, list):
        for item in value:
            yield from texts(item, path)
    elif isinstance(value, str):
        yield path, value


# --------------------------------------------------------------------------
# The rule


def holds(field: str, path: tuple[str, ...]) -> bool:
    """Whether a field of the list holds what is at this path."""
    names = [name.casefold().replace("_", "-") for name in path]
    anywhere = field.startswith("**.")
    want = field.removeprefix("**.").split(".")
    starts = range(len(names)) if anywhere else range(1)
    return any(names[at : at + len(want)] == want for at in starts)


def covers(row: Metadata, rel: str) -> bool:
    """Whether a row of the list names this file."""
    path = f"/{rel}".casefold()
    name = PurePosixPath(path).name
    return any(
        path == file
        if file.startswith("/")
        else fnmatch.fnmatchcase(path, f"*/{file}")
        if "/" in file
        else fnmatch.fnmatchcase(name, file)
        for file in row.files
    )


def read(row: Metadata, rel: str, text: str) -> list[tuple[tuple[str, ...], str]] | None:
    """Every text of a file with its path, or None for a file that is searched whole."""
    reader = READERS.get(PurePosixPath(rel).suffix.lower())
    if reader is None:
        return None
    try:
        doc = reader(text)
        return list(texts(own_packages(doc) if row.bill else doc))
    except ValueError, SyntaxError, yaml.YAMLError, expat.ExpatError:
        return None
    except RecursionError, MemoryError:  # nested deeper than its parser takes
        return None


def name_of(path: tuple[str, ...]) -> str:
    """A field's name, with no address in it: a log is read by anybody."""
    return (
        ".".join(
            "*" if any(addresses(key)) else "".join(c if c.isprintable() else "?" for c in key)
            for key in path
        )
        or WHOLE
    )


def fields_of(row: Metadata, rel: str, text: str) -> Iterator[tuple[str, tuple[bool, bool]]]:
    """The fields of a file that hold an address: the one allowed, another."""
    folders = {part.casefold() for part in PurePosixPath(rel).parts[:-1]}
    examples = bool(folders & EXAMPLES) or rel.casefold().endswith(".md")
    values = read(row, rel, text)
    whole = values is None or not row.fields
    for path, value in [((), text)] if values is None else values:
        if (
            whole
            or any(holds(field, path) for field in row.fields)
            or (not row.bill and "mailto:" in plain(value).casefold())
        ):
            found = addresses(value, whole=whole, examples=examples)
            if any(found):
                yield name_of(path), found


def third_partys(tables: list[dict[str, Any]], rel: str) -> bool:
    """Whether REUSE.toml states, by an annotation of its own, that the file is somebody else's.

    REUSE.toml itself speaks for the repository, whatever it says of itself.
    """
    table = spdx_headers.annotation_for(tables, rel)
    if table is None or rel == "REUSE.toml":
        return False
    paths, stated = (
        [value] if isinstance(value, str) else [str(item) for item in value]
        for value in (table.get("path", []), table.get(spdx_headers.COPYRIGHT_TAG[:-1], []))
    )
    named = [path for path in paths if path.strip("*/")]  # not a catch-all
    return (
        spdx_headers.annotation_for([{"path": named}], rel) is not None
        and any(stated)
        and not re.search("requena|kleidos", plain(" ".join(stated)), re.IGNORECASE)
    )


def annotated(repo: cq.Repo) -> list[dict[str, Any]]:
    """The annotations of REUSE.toml; none of one that cannot be read."""
    try:
        tables = spdx_headers.reuse_annotations(repo.root)
    except ValueError, TypeError:
        return []
    return [table for table in tables if isinstance(table, dict)]


def check(repo: cq.Repo, report: cq.Report) -> None:
    """No address in any field of the list, but the one allowed, with its waiver."""
    tables = annotated(repo)
    for rel in repo.own(("",)):
        row = next((row for row in METADATA if covers(row, rel)), None)
        if row is None or third_partys(tables, rel):
            continue
        text = repo.path(rel).read_bytes().decode("utf-8-sig", "replace")
        found: dict[str, bool] = {}
        for field, (_allowed, other) in fields_of(row, rel, text):
            found[field] = found.get(field, False) or other
        for field, other in found.items():
            if not other:
                report.weaken("supplier", f"address:{field}", rel)
            else:
                report.add(
                    "supplier",
                    rel,
                    f"{field} holds an e-mail address: a name only, or {ALLOWED}, as it is, where"
                    " the tool that reads it needs an address (with a waiver that names the tool)",
                )
