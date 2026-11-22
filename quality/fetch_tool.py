#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Install a release binary pinned in tools.lock, or list the outdated ones.

Usage:
    fetch_tool.py NAME DEST_DIR     download NAME, check its SHA-256, install DEST_DIR/NAME
    fetch_tool.py --outdated        print each pinned tool whose upstream release is newer

Standard library only (Python 3.11 or newer).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tarfile
import tomllib
import urllib.request
from pathlib import Path
from typing import Any

LOCK = Path(__file__).resolve().with_name("tools.lock")


def load(lock: Path = LOCK) -> dict[str, dict[str, Any]]:
    """The tools.lock table, tool name to its entry."""
    with lock.open("rb") as fh:
        return tomllib.load(fh)


def _get(url: str, headers: dict[str, str] | None = None) -> bytes:
    if not url.startswith("https://"):
        raise ValueError(f"refusing a non-https URL: {url}")
    request = urllib.request.Request(url, headers=headers or {})  # noqa: S310  https only, checked above
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310  https only, checked above
        data: bytes = response.read()
    return data


def verify(data: bytes, sha256: str) -> None:
    """Raise when data does not have the pinned digest."""
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        raise ValueError(f"SHA-256 mismatch: got {digest}, tools.lock pins {sha256}")


def extract(data: bytes, entry: dict[str, Any]) -> bytes:
    """The binary itself: the download, or one member of a .tar.gz."""
    member = entry.get("member")
    if not member:
        return data
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        handle = tar.extractfile(str(member))
        if handle is None:
            raise ValueError(f"{member} is not a file in the archive")
        return handle.read()


def install(name: str, dest: Path, lock: Path = LOCK) -> Path:
    """Download, verify and install one tool; return its path."""
    tools = load(lock)
    if name not in tools:
        raise KeyError(f"{name} is not in {lock.name} (known: {', '.join(sorted(tools))})")
    entry = tools[name]
    data = _get(str(entry["url"]))
    verify(data, str(entry["sha256"]))
    binary = extract(data, entry)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / name
    target.write_bytes(binary)
    target.chmod(0o755)
    return target


def outdated(lock: Path = LOCK) -> list[str]:
    """One line per tool whose latest upstream release differs from the pin."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    lines = []
    for name, entry in sorted(load(lock).items()):
        api = f"https://api.github.com/repos/{entry['repo']}/releases/latest"
        latest = str(json.loads(_get(api, headers))["tag_name"]).lstrip("v")
        if latest != str(entry["version"]):
            lines.append(f"{name}: pinned {entry['version']}, latest {latest}")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("name", nargs="?")
    ap.add_argument("dest", nargs="?", type=Path)
    ap.add_argument("--outdated", action="store_true")
    args = ap.parse_args(argv)
    if args.outdated:
        lines = outdated()
        for line in lines:
            print(line)
        return 1 if lines else 0
    if not args.name or not args.dest:
        ap.error("NAME and DEST_DIR are required")
    try:
        print(install(args.name, args.dest))
    except (KeyError, ValueError) as exc:
        print(f"fetch_tool: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
