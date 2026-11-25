# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""No e-mail address in the fields that say who a thing comes from.

The owner's statement is year and name in a copyright (spdx_headers.py), and
a name alone in the metadata too (owner, 2026-11-25): the supplier and the
originator of REUSE.toml, the authors and maintainers of a manifest, the
people of a citation or of a software bill of materials.

  the fields   METADATA, one list: the files, and the keys of each
  what passes  a name; and mail@kleidos.dev where the tool that reads the
               field needs an address, which is a weakening whose waiver
               (tool = "supplier") names that tool. No other address, with
               no waiver

A file that cannot be read as its format says is searched whole, and so is
one whose format has no fields here. A file that REUSE.toml states is a third
party's is not ours to correct.

Python 3.14 or newer; PyYAML.
"""

from __future__ import annotations

import fnmatch
import json
import re
import tomllib
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import check_quality as cq
import spdx_headers
import yaml

ALLOWED = "mail@kleidos.dev"
WHOLE = "the file"


@dataclass(frozen=True)
class Metadata:
    """Files that say who a thing comes from, and the fields that say it.

    A file is named by the end of its path, in any case. A field is named
    from the top of the file, `**.` at any depth, and holds all that is below
    it; case and the two dashes (`author_email`, `author-email`) are one, and
    a list adds no name. Files with no fields are searched whole.
    """

    files: tuple[str, ...]
    fields: tuple[str, ...] = ()


METADATA = (
    Metadata(
        ("reuse.toml",),
        ("spdx-packagesupplier", "spdx-packageoriginator", "annotations.spdx-filecontributor"),
    ),
    Metadata(
        ("package.json", "composer.json"),
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
        ("author", "contributor", "contributors", "copyrightholder", "creator", "creators")
        + ("editor", "funder", "maintainer", "producer", "provider", "publisher", "sponsor"),
    ),
    Metadata(
        ("idf_component.yml", "idf_component.yaml", "library.json"), ("authors", "maintainers")
    ),
    Metadata((".claude-plugin/*.json",), ("author", "owner", "plugins.author")),
    Metadata(("action.yml", "action.yaml"), ("author",)),
    Metadata(("manifest.json",), ("author", "developer")),
    # A software bill of materials: SPDX or CycloneDX.
    Metadata(
        ("bom.json", "sbom.json", "*.cdx.json", "*.spdx.json", "*.spdx.yaml", "*.spdx.yml"),
        ("**.annotator", "**.author", "**.authors", "**.contact", "**.creators", "**.email")
        + ("**.manufacture", "**.manufacturer", "**.originator", "**.publisher")
        + ("**.reviewer", "**.supplier"),
    ),
    Metadata(("bom.xml", "sbom.xml", "*.cdx.xml", "*.spdx", ".reuse/dep5")),
    Metadata(("setup.py", "setup.cfg", "library.properties", "*.gemspec", "debian/control")),
    Metadata(
        tuple(
            name + suffix
            for name in ("authors", "contributors", "maintainers")
            for suffix in ("", ".md", ".txt")
        )
        + ("codeowners", ".mailmap")
    ),
)

# An address, however it is written: user@host.tld, <user@host>, and with the
# marks in words (user at host dot tld, user [at] host.tld). Not one: the
# user of a URL (//git@host), a handle (@user@host) and a version (name@1.2.3).
LABEL = r"[\w-]+"
ADDRESS = re.compile(
    rf"""(?<![\w.%+@-])(?<!//)
    [\w.%+-]+
    (?: @ (?:{LABEL}\.)+ [^\W\d]{LABEL}
      | (?: @ | \W{{1,3}}at\W{{1,3}} ) {LABEL} \W{{1,3}}dot\W{{1,3}} {LABEL}
      | \s?[\[({{]\s?at\s?[\])}}]\s? {LABEL}\.{LABEL}
    )
    | <[^<>@\s/]+@[^<>\s]+>""",
    re.IGNORECASE | re.VERBOSE,
)


class Pairs(list[tuple[str, Any]]):
    """A mapping as it is written: a key that is there twice counts twice."""


def of_yaml(node: yaml.Node | None) -> Any:
    """A YAML document's values, unread: a scalar is its text."""
    if isinstance(node, yaml.MappingNode):
        return Pairs((str(key.value), of_yaml(value)) for key, value in node.value)
    if isinstance(node, yaml.SequenceNode):
        return [of_yaml(item) for item in node.value]
    return node.value if node else None


def read_yaml(text: str) -> Any:
    return of_yaml(yaml.compose(text, Loader=yaml.SafeLoader))


def read_json(text: str) -> Any:
    return json.loads(text, object_pairs_hook=Pairs)


READERS: dict[str, Callable[[str], Any]] = {
    ".toml": tomllib.loads,
    ".json": read_json,
    ".yml": read_yaml,
    ".yaml": read_yaml,
    ".cff": read_yaml,
}


def texts(value: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str]]:
    """Every text of a document, keys included, with the names that lead to it."""
    if isinstance(value, dict):
        value = Pairs(value.items())
    if isinstance(value, Pairs):
        for key, below in value:
            at = (*path, key)
            yield at, key
            yield from texts(below, at)
    elif isinstance(value, list):
        for item in value:
            yield from texts(item, path)
    elif isinstance(value, str):
        yield path, value


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
    return any(fnmatch.fnmatchcase(path, f"*/{name}") for name in row.files)


def fields_of(row: Metadata, rel: str, text: str) -> Iterator[tuple[str, str]]:
    """The fields of a file that hold an address, and each address."""
    values: list[tuple[tuple[str, ...], str]] = [((), text)]
    if row.fields:
        try:
            values = list(texts(READERS[PurePosixPath(rel).suffix.lower()](text)))
        except ValueError, yaml.YAMLError, RecursionError:
            row = Metadata(row.files)
    for path, value in values:
        if not row.fields or any(holds(field, path) for field in row.fields):
            for found in ADDRESS.finditer(unicodedata.normalize("NFKC", value)):
                address = found.group().strip("<>").casefold().removeprefix("mailto:")
                yield ".".join(path) or WHOLE, address


def third_partys(tables: list[dict[str, Any]], rel: str) -> bool:
    """Whether REUSE.toml states that the file is somebody else's."""
    table = spdx_headers.annotation_for(tables, rel) or {}
    stated = str(table.get(spdx_headers.COPYRIGHT_TAG.rstrip(":"), ""))
    return bool(stated) and spdx_headers.HOLDER not in stated


def check(repo: cq.Repo, report: cq.Report) -> None:
    """No address in any field of the list, but the one allowed, with its waiver."""
    tables = spdx_headers.reuse_annotations(repo.root)
    for rel in repo.own(("",)):
        row = next((row for row in METADATA if covers(row, rel)), None)
        if row is None or third_partys(tables, rel):
            continue
        text = repo.path(rel).read_bytes().decode("utf-8-sig", "replace")
        found: dict[str, set[str]] = {}
        for field, address in fields_of(row, rel, text):
            found.setdefault(field, set()).add(address)
        for field, addresses in found.items():
            if addresses == {ALLOWED}:
                report.weaken("supplier", f"address:{field}", rel)
            else:
                report.add(
                    "supplier",
                    rel,
                    f"{field} holds an e-mail address: a name only, or {ALLOWED} where the tool"
                    " that reads it needs an address (with a waiver that names the tool)",
                )
