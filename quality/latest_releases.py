#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Report every kit pin that has a newer upstream stable release.

Owner, 2026-11-23: every pinned version is the latest stable release. The
kit's pins are the newest it knows, and check_quality.py holds every
repository to them (LATEST_PYTHON, LATEST_ACTIONS, LATEST_HOOKS,
LATEST_IMAGES); this script, run by the CI's weekly "📦 Pinned versions
current" job, compares them with upstream:

  Python       the newest stable CPython setup-python serves
               (actions/python-versions' manifest)
  actions      each action's latest GitHub release
  hooks        each hook repository's latest GitHub release, else its
               newest version tag
  images       each container image's newest stable x.y.z tag on Docker
               Hub, and the digest that tag names (a tag pushed again
               counts too)
  PyPI tools   each pin of quality/requirements-tools.in
  binaries     quality/tools.lock (fetch_tool.py --outdated)

Usage:
    latest_releases.py [--summary FILE]

Exit status: 0 every pin is the latest, 1 something is behind (one line
each, and a Markdown list in --summary), 2 a lookup failed. GH_TOKEN or
GITHUB_TOKEN, when set, authenticates the GitHub API calls.

Python 3.15 or newer; PyYAML (check_quality.py imports it).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_quality as cq  # noqa: E402  the sibling module, found through the path set above
import fetch_tool  # noqa: E402  the sibling module, found through the path set above

PYTHON_MANIFEST = (
    "https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json"
)
GITHUB_URL = re.compile(r"^https://github\.com/(?P<repo>[\w.-]+/[\w.-]+?)(?:\.git)?/?$")
RELEASE_TAG = re.compile(r"^v?\d+(?:\.\d+)*$")
IMAGE_TAG = re.compile(r"^\d+\.\d+\.\d+$")
DOCKER_TAGS = (
    "https://hub.docker.com/v2/repositories/{name}/tags?page_size=100&ordering=last_updated"
)
DOCKER_PAGES = 50  # at most 5,000 tags read; kicad/kicad has two pages
PIN = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)(?:\[[^\]]*\])?==(?P<version>[^\s;#]+)")

GetJson = Callable[[str], Any]


def get_json(url: str) -> Any:
    """GET a JSON document over https, with the GitHub token for api.github.com."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "kleidos-quality-kit"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    return json.loads(fetch_tool._get(url, headers))


def newest_python(get: GetJson) -> tuple[int, int]:
    """The newest stable CPython (major, minor) that setup-python serves."""
    for entry in get(PYTHON_MANIFEST):
        if entry.get("stable"):
            major, minor = str(entry["version"]).split(".")[:2]
            return int(major), int(minor)
    raise ValueError("the python-versions manifest lists no stable release")


def newest_release(repo: str, get: GetJson) -> str:
    """A GitHub repository's latest release tag, else its newest version tag."""
    try:
        return str(get(f"https://api.github.com/repos/{repo}/releases/latest")["tag_name"])
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    tags = [str(t["name"]) for t in get(f"https://api.github.com/repos/{repo}/tags?per_page=100")]
    versions = [t for t in tags if RELEASE_TAG.match(t)]
    if not versions:
        raise ValueError(f"{repo} has no release and no version tag")
    return max(versions, key=lambda t: cq.version_tuple(t) or ())


def newest_image(name: str, get: GetJson) -> tuple[str, str]:
    """A Docker Hub image's newest stable x.y.z tag, and the digest it names (every page read)."""
    tags: dict[str, str] = {}
    url: str | None = DOCKER_TAGS.format(name=name)
    pages = 0
    while url:
        pages += 1
        if pages > DOCKER_PAGES:
            raise ValueError(f"{name} has more than {DOCKER_PAGES} pages of tags on Docker Hub")
        page = get(url)
        for t in page["results"]:
            if IMAGE_TAG.match(str(t["name"])) and t.get("digest"):
                tags[str(t["name"])] = str(t["digest"])
        url = page.get("next")
    if not tags:
        raise ValueError(f"{name} has no x.y.z tag on Docker Hub")
    tag = max(tags, key=lambda t: cq.version_tuple(t) or ())
    return tag, tags[tag]


def newest_pypi(name: str, get: GetJson) -> str:
    return str(get(f"https://pypi.org/pypi/{name}/json")["info"]["version"])


def behind(pinned: str, latest: str) -> bool:
    have, want = cq.version_tuple(pinned), cq.version_tuple(latest)
    return have is not None and want is not None and cq.is_below(have, want)


def tool_pins(path: Path = HERE / "requirements-tools.in") -> dict[str, str]:
    """The name==version pins of requirements-tools.in."""
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = PIN.match(line.strip())
        if m:
            pins[m.group("name")] = m.group("version")
    return pins


def outdated(get: GetJson = get_json, binaries: bool = True) -> list[str]:
    """One line per pin with a newer upstream stable release."""
    lines = []
    python = newest_python(get)
    if cq.is_below(cq.LATEST_PYTHON, python):
        have = ".".join(map(str, cq.LATEST_PYTHON))
        lines.append(f"Python: the kit knows {have}, latest {python[0]}.{python[1]}")
    for action, pinned in sorted(cq.LATEST_ACTIONS.items()):
        latest = newest_release(action, get)
        if behind(pinned, latest):
            lines.append(f"action {action}: pinned {pinned}, latest {latest}")
    for url, pinned in sorted(cq.LATEST_HOOKS.items()):
        m = GITHUB_URL.match(url)
        if not m:
            raise ValueError(f"{url} is not a GitHub repository")
        latest = newest_release(m.group("repo"), get)
        if behind(pinned, latest):
            lines.append(f"hook {url}: pinned {pinned}, latest {latest}")
    for name, (tag, digest) in sorted(cq.LATEST_IMAGES.items()):
        latest, latest_digest = newest_image(name, get)
        if behind(tag, latest):
            lines.append(f"image {name}: pinned {tag}, latest {latest} ({latest_digest})")
        elif tag == latest and digest != latest_digest:
            lines.append(f"image {name}: {tag} now names {latest_digest}, the kit knows {digest}")
    for name, pinned in sorted(tool_pins().items()):
        latest = newest_pypi(name, get)
        if behind(pinned, latest):
            lines.append(f"PyPI {name}: pinned {pinned}, latest {latest}")
    if binaries:
        lines += [f"binary {line}" for line in fetch_tool.outdated()]
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--summary", type=Path, help="append a Markdown report to this file")
    args = ap.parse_args(argv)
    try:
        lines = outdated()
    except (OSError, ValueError, KeyError) as exc:
        print(f"latest_releases: a lookup failed: {exc}", file=sys.stderr)
        return 2
    for line in lines:
        print(line)
    if lines and args.summary:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write("## A kit pin has a newer stable release\n\n")
            fh.write(
                "Move it in one pull request here: the pin, the matching LATEST_* entry of"
                " quality/check_quality.py, quality/VERSION and quality/CHANGELOG.md"
                ' (docs/quality.md, "Versions"); the sync then carries it to every'
                " repository. An image is only its LATEST_IMAGES entry here; each"
                " repository that runs it moves its digest when it takes the release.\n\n"
            )
            fh.writelines(f"- {line}\n" for line in lines)
    return 1 if lines else 0


if __name__ == "__main__":
    sys.exit(main())
