# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""The one way the kit's tools write into a repository: its own files, and nothing outside.

A path may come from a record in the tree or from a file name there, so
none is written through a symbolic link, out of the repository, or in git's
own folder. Nothing but this module opens a repository's file for writing.

Python 3.14 or newer.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath


class RefusedError(Exception):
    """What a tool will not do, and why."""


def problem(root: Path, rel: str) -> str | None:
    """Why a path is not one of the repository's own files, or None."""
    parts = PurePosixPath(rel).parts
    if any(part.lower() == ".git" for part in parts):
        return f"{rel} is in git's own folder"
    if not parts or PurePosixPath(rel).is_absolute() or ".." in parts:
        return f"{rel} is not in the repository"
    path = root
    for part in parts:
        path /= part
        if path.is_symlink():
            return f"{path.relative_to(root).as_posix()} is a symbolic link"
    return None


def own_file(root: Path, rel: str) -> Path:
    """The path of one of the repository's own files; refused when it leads elsewhere."""
    why = problem(root, rel)
    if why:
        raise RefusedError(why)
    return root / rel


def write(root: Path, rel: str, data: str | bytes) -> bool:
    """Write one of the repository's own files; whether that changed it."""
    path = own_file(root, rel)
    content = data.encode("utf-8") if isinstance(data, str) else data
    if path.is_file() and path.read_bytes() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return True
