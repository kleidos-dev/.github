#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Install a release binary pinned in tools.lock, or list the outdated ones.

Usage:
    fetch_tool.py NAME DEST_DIR     download NAME, check its SHA-256, install DEST_DIR/NAME
    fetch_tool.py --outdated        print each pinned tool whose upstream release is newer

NAME is a tool tools.lock pins, and the file installed takes the lock's
spelling of it, never the command line's. DEST_DIR must resolve, links
followed, to the working directory, the temporary directory or the runner's
(RUNNER_TEMP), or to a folder in one of them: a command line an agent or a
script wrote cannot make the tool write anywhere else. The binary is written
to a new file in that folder and renamed over DEST_DIR/NAME, so a link there
is replaced, never followed.

Standard library only (Python 3.15 or newer).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
from pathlib import Path
from typing import Any

LOCK = Path(__file__).resolve().with_name("tools.lock")

#: A tool's name in tools.lock, which is also the name of the file installed.
TOOL_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


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


def install_roots() -> list[str]:
    """The folders a tool may be installed in or under, links resolved."""
    roots = [os.getcwd(), tempfile.gettempdir()]
    runner = os.environ.get("RUNNER_TEMP", "")
    if runner:
        roots.append(runner)
    return [os.path.realpath(root) for root in roots]


def install_folder(dest: Path) -> str:
    """dest with its links resolved; refused unless it is, or lies in, one of install_roots()."""
    real = os.path.realpath(dest)
    for root in install_roots():
        if real == root or real.startswith(root.rstrip(os.sep) + os.sep):
            return real
    raise ValueError(
        f"refusing to install into {dest}: it is not the working directory, the"
        " temporary directory or the runner's, nor a folder in one of them"
    )


def lock_name(tools: dict[str, dict[str, Any]], name: str, lock: Path) -> str:
    """The lock's own spelling of a tool's name, which the installed file takes."""
    for known in tools:
        if known == name:
            if not TOOL_NAME.fullmatch(known):
                raise ValueError(f"{lock.name} pins a tool named {known!r}, which is no file name")
            return known
    raise KeyError(f"{name} is not in {lock.name} (known: {', '.join(sorted(tools))})")


def install(name: str, dest: Path, lock: Path = LOCK) -> Path:
    """Download, verify and install one tool; return its path."""
    tools = load(lock)
    file_name = lock_name(tools, name, lock)
    folder = install_folder(dest)
    entry = tools[file_name]
    data = _get(str(entry["url"]))
    verify(data, str(entry["sha256"]))
    binary = extract(data, entry)
    os.makedirs(folder, exist_ok=True)
    target = Path(folder, file_name)
    handle, fresh = tempfile.mkstemp(dir=folder, prefix=f".{file_name}.")
    os.close(handle)
    staged = Path(fresh)
    try:
        staged.write_bytes(binary)
        staged.chmod(0o755)
        os.replace(staged, target)
    except BaseException:
        staged.unlink()
        raise
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
