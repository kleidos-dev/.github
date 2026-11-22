#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Write each published file's metadata from its record, or check it is written.

The records are ``profile/assets/assets.json``. ``--write`` rewrites the
``<title>``, ``<desc>`` and ``<metadata>`` of every SVG listed there (and
the three root attributes that point at them), then records each file's
bytes and SHA-256. ``--check`` changes nothing and fails when a file or a
digest differs from what ``--write`` would leave. Nothing in the drawing
is touched.

Usage: python3 scripts/stamp_media_meta.py --write | --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import media_meta


def stamped(root: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    """The manifest and the file contents ``--write`` would leave."""
    manifest_path = root / media_meta.MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contents: dict[str, bytes] = {}
    for path, record in manifest["files"].items():
        if not path.endswith(".svg"):
            raise media_meta.MetaError(f"{path}: this repository stamps SVG only")
        text = (root / path).read_text(encoding="utf-8")
        meta = media_meta.meta_from_record(path, record, root)
        data = media_meta.stamp_svg(text, meta, record["id"]).encode("utf-8")
        contents[path] = data
        record["bytes"] = len(data)
        record["sha256"] = hashlib.sha256(data).hexdigest()
    return manifest, contents


def manifest_bytes(manifest: dict[str, Any]) -> bytes:
    """The manifest as it is written: two-space indent, UTF-8, final newline."""
    return (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write the metadata and the digests")
    mode.add_argument("--check", action="store_true", help="fail when anything would change")
    args = parser.parse_args(argv)
    root = media_meta.ROOT
    try:
        manifest, contents = stamped(root)
    except (media_meta.MetaError, KeyError, OSError, ValueError) as error:
        print(f"stamp_media_meta: {error}", file=sys.stderr)
        return 2
    outputs = dict(contents)
    outputs[media_meta.MANIFEST] = manifest_bytes(manifest)
    stale = [p for p, data in outputs.items() if (root / p).read_bytes() != data]
    if args.write:
        for path in stale:
            (root / path).write_bytes(outputs[path])
            print(f"wrote {path}")
        return 0
    for path in stale:
        print(f"{path}: differs from what --write leaves; run scripts/stamp_media_meta.py --write")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
