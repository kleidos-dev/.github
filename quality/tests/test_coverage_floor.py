# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""coverage_floor.py: a file under its floor is named, and so is a floor with no file."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import kit_fixtures as fx
from kit_fixtures import coverage_floor as cf


def measured(lines: tuple[int, int], branches: tuple[int, int]) -> dict[str, Any]:
    return {
        "summary": {
            "covered_lines": lines[0],
            "num_statements": lines[1],
            "covered_branches": branches[0],
            "num_branches": branches[1],
        },
        "missing_lines": list(range(1, lines[1] - lines[0] + 1)),
    }


class FloorTest(unittest.TestCase):
    def test_a_file_is_held_to_all_of_it(self) -> None:
        for lines, branches, fine in (
            ((10, 10), (4, 4), True),
            ((10, 10), (0, 0), True),
            ((0, 0), (0, 0), True),
            ((9, 10), (4, 4), False),
            ((10, 10), (3, 4), False),
        ):
            with self.subTest(lines=lines, branches=branches):
                found = cf.below({"a.py": measured(lines, branches)}, {})
                self.assertEqual(found == [], fine, found)
        found = cf.below({"a.py": measured((8, 10), (4, 4))}, {})
        self.assertEqual(
            found,
            [
                "a.py: 80.0 % of lines and 100.0 % of branches, its floor is 100 and 100"
                " (lines 1, 2)"
            ],
        )
        found = cf.below({"a.py": measured((10, 10), (3, 4))}, {})
        said = "a.py: 100.0 % of lines and 75.0 % of branches, its floor is 100 and 100"
        self.assertEqual(found, [said])

    def test_a_floor_is_what_a_file_has_reached(self) -> None:
        files = {"a.py": measured((8, 10), (1, 2))}
        self.assertEqual(cf.below(files, {"a.py": (80, 50)}), [])
        self.assertEqual(len(cf.below(files, {"a.py": (81, 50)})), 1)
        self.assertEqual(len(cf.below(files, {"a.py": (80, 51)})), 1)

    def test_a_floor_without_a_file_is_found(self) -> None:
        self.assertEqual(cf.below({}, {"b.py": (1, 1)}), ["b.py: has a floor and is not measured"])

    def test_the_floors_name_files_that_exist_and_are_below_all(self) -> None:
        for name, floor in cf.FLOORS.items():
            self.assertTrue((fx.CENTRAL / name).is_file(), name)
            self.assertNotEqual(floor, (100, 100), name)

    def run_main(self, files: dict[str, Any] | None) -> tuple[int, str]:
        """The command, with what coverage would say of its last run."""

        def report(cmd: list[str], check: bool) -> None:
            self.assertEqual(cmd[1:6], ["-m", "coverage", "json", "-q", "-o"])
            self.assertFalse(check)
            if files is not None:
                Path(cmd[-1]).write_text(json.dumps({"files": files}), encoding="utf-8")

        with (
            mock.patch.object(subprocess, "run", side_effect=report) as run,
            mock.patch.object(cf, "FLOORS", {}),
            contextlib.redirect_stdout(io.StringIO()) as out,
            contextlib.redirect_stderr(out),
        ):
            status = cf.main()
        run.assert_called_once()
        return status, out.getvalue()

    def test_the_command(self) -> None:
        self.assertEqual(self.run_main(None), (2, "coverage_floor: no coverage data\n"))
        kept = {"a.py": measured((1, 1), (0, 0))}
        self.assertEqual(self.run_main(kept), (0, "coverage: 1 files keep their floor\n"))
        status, said = self.run_main({"a.py": measured((0, 1), (0, 0))})
        self.assertEqual(status, 1)
        self.assertIn("coverage_floor: a.py: 0.0 % of lines", said)


if __name__ == "__main__":
    unittest.main()
