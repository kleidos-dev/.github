# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""The one way the kit's tools write into a repository: its own files, and nothing outside.

A path may come from a record in the tree or from a file name there, so
none is written through a symbolic link, out of the repository, or in git's
own folder. Nothing but this module opens a repository's file for writing.

Python 3.14 or newer.
"""

from __future__ import annotations

import posixpath
import unicodedata
from pathlib import Path, PurePosixPath


class RefusedError(Exception):
    """What a tool will not do, and why."""


def folded(name: str) -> str:
    """A name as a file system that folds case and compatibility forms reads it.

    APFS and NTFS fold case, and APFS folds as Unicode does: `workflo\u017fs`
    (a long s) and `work\ufb02ows` (a ligature) open `workflows`.
    """
    return unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", name).casefold())


def reaches(root: Path, rel: str, protected: str) -> bool:
    """Whether a path of the repository is, or is under, a protected one.

    By its spelling, folded as above, and by what the file system resolves
    it to: a spelling no rule here foresees is still the same file.
    """
    parts = PurePosixPath(posixpath.normpath(rel)).parts
    want = tuple(folded(part) for part in PurePosixPath(protected).parts)
    if tuple(folded(part) for part in parts[: len(want)]) == want:
        return True
    try:
        place = (root / protected).stat()
    except OSError:  # not there: nothing resolves to it
        return False
    path = root
    for part in parts:
        path /= part
        if not path.exists():
            return False
        real = path.resolve()
        for up in (real, *real.parents):
            seen = up.stat()
            if (seen.st_dev, seen.st_ino) == (place.st_dev, place.st_ino):
                return True
    return False


def problem(root: Path, rel: str) -> str | None:
    """Why a path is not one of the repository's own files, or None."""
    parts = PurePosixPath(rel).parts
    if any(folded(part) == ".git" for part in parts) or reaches(root, rel, ".git"):
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
