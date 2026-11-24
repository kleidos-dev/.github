#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""Every measured file keeps the share of line and branch coverage it has reached.

The organization's norm is the maximum of tests (docs/quality.md, "Tests"):
a file is held to 100 % of its lines and of its branches, unless FLOORS names
it with what it has reached, so a share only rises. It reads the data of the
last `coverage run` through `coverage json`; what coverage.py does not count
is in .coveragerc, each exclusion with its reason.

Usage: coverage_floor.py [REPORT.json]   (a `coverage json` report; made when not given)

Exit status: 0 every file keeps its floor, 1 one does not, 2 no coverage data.

Python 3.14 or newer; coverage.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# Written before the norm, with the share of lines and branches, in whole
# percent, each has reached; a file that is not here is at 100 and 100.
FLOORS: dict[str, tuple[int, int]] = {
    "quality/agent_docs.py": (97, 95),
    "quality/check_quality.py": (83, 80),
    "quality/fetch_tool.py": (41, 22),
    "quality/latest_releases.py": (76, 75),
    "quality/md_nowrap.py": (71, 61),
    "quality/mypy_groups.py": (96, 92),
    "quality/spdx_headers.py": (88, 82),
    "quality/sync.py": (81, 75),
    "scripts/check_metadata.py": (76, 75),
    "scripts/media_meta.py": (95, 88),
    "scripts/stamp_media_meta.py": (81, 50),
}


def share(covered: int, total: int) -> float:
    """A percentage; nothing to cover is all of it."""
    return 100.0 * covered / total if total else 100.0


def below(files: dict[str, dict[str, Any]], floors: dict[str, tuple[int, int]]) -> list[str]:
    """The files under their floor, and the floors of files that are not measured."""
    out = []
    for name, data in sorted(files.items()):
        summary = data["summary"]
        lines = share(summary["covered_lines"], summary["num_statements"])
        branches = share(summary["covered_branches"], summary["num_branches"])
        want = floors.get(name, (100, 100))
        if lines < want[0] or branches < want[1]:
            missing = ", ".join(str(n) for n in data.get("missing_lines", ())[:10])
            out.append(
                f"{name}: {lines:.1f} % of lines and {branches:.1f} % of branches,"
                f" its floor is {want[0]} and {want[1]}"
                + (f" (lines {missing})" if missing else "")
            )
    out += [
        f"{name}: has a floor and is not measured" for name in sorted(floors.keys() - files.keys())
    ]
    return out


def measured(argv: list[str]) -> dict[str, dict[str, Any]] | None:
    """The files of a coverage report, None when there is none."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(argv[0]) if argv else Path(tmp) / "coverage.json"
        if not argv:
            subprocess.run(
                [sys.executable, "-m", "coverage", "json", "-q", "-o", str(path)], check=False
            )
        if not path.is_file():
            return None
        files: dict[str, dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["files"]
        return files


def main(argv: list[str]) -> int:
    """Compare the last run with the floors."""
    files = measured(argv)
    if files is None:
        print("coverage_floor: no coverage data", file=sys.stderr)
        return 2
    found = below(files, FLOORS)
    for line in found:
        print(f"coverage_floor: {line}")
    if not found:
        print(f"coverage: {len(files)} files keep their floor")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
