# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""spdx_headers.py: both lines, copyright first, the first-commit year, no e-mail."""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import kit_fixtures as fx
from kit_fixtures import spdx_headers as sh

C, L, H = fx.COPYRIGHT, fx.LICENSE, fx.HOLDER


class CheckTextTest(unittest.TestCase):
    def test_a_right_header_passes(self) -> None:
        self.assertEqual(sh.check_text("a.py", fx.header(year="2025"), "2025"), [])

    def test_each_missing_line_is_named(self) -> None:
        found = sh.check_text("a.py", "x = 1\n", "2026")
        self.assertEqual(len(found), 2)
        self.assertIn(C, found[0])
        self.assertIn(L, found[1])

    def test_the_license_line_first_is_wrong(self) -> None:
        text = f"# {L} MIT\n# {C} 2026 {H}\n"
        self.assertIn("copyright first", " ".join(sh.check_text("a.py", text, "2026")))

    def test_an_e_mail_is_refused(self) -> None:
        text = f"# {C} 2026 {H} <someone@example.org>\n# {L} MIT\n"
        self.assertIn("e-mail", " ".join(sh.check_text("a.py", text, "2026")))

    def test_the_year_is_the_first_commit_year(self) -> None:
        found = sh.check_text("a.py", fx.header(year="2027"), "2026")
        self.assertIn("git first added the file in 2026", " ".join(found))

    def test_a_kit_copy_keeps_its_source_year(self) -> None:
        self.assertEqual(sh.check_text("a.py", fx.header(year="2026"), "2030", copy=True), [])

    def test_a_third_party_holder_keeps_its_own_year(self) -> None:
        text = f"# {C} 2014 Someone Else\n# {L} MIT\n"
        self.assertEqual(sh.check_text("a.py", text, "2026"), [])

    def test_lines_inside_an_ignore_block_do_not_count(self) -> None:
        text = f"# {sh.IGNORE_START}\n# {C} 2026 {H}\n# {L} MIT\n# {sh.IGNORE_END}\n"
        self.assertEqual(len(sh.check_text("a.py", text, "2026")), 2)


class FixTextTest(unittest.TestCase):
    def fixed(self, rel: str, text: str, lic: str | None = "MIT") -> str:
        new, why = sh.fix_text(rel, text, "2026", lic)
        self.assertIsNone(why)
        self.assertEqual(sh.check_text(rel, new, "2026"), [], new)
        return new

    def test_python_after_the_shebang(self) -> None:
        new = self.fixed("a.py", '#!/usr/bin/env python3\n"""Doc."""\n')
        self.assertEqual(new, f'#!/usr/bin/env python3\n# {C} 2026 {H}\n# {L} MIT\n\n"""Doc."""\n')

    def test_yaml_with_a_leading_comment_keeps_a_comment_joint(self) -> None:
        new = self.fixed("a.yml", "# Why this file exists.\nname: x\n")
        self.assertEqual(new, f"# {C} 2026 {H}\n# {L} MIT\n#\n# Why this file exists.\nname: x\n")

    def test_a_license_line_alone_gets_its_copyright_above(self) -> None:
        new = self.fixed("a.toml", f"# {L} GPL-3.0-or-later\n#\n# Notes.\n", lic=None)
        self.assertTrue(new.startswith(f"# {C} 2026 {H}\n# {L} GPL-3.0-or-later\n"))

    def test_markdown_takes_an_html_comment_after_front_matter(self) -> None:
        new = self.fixed("a.md", "---\ntitle: x\n---\n# Title\n")
        self.assertEqual(new, f"---\ntitle: x\n---\n<!--\n{C} 2026 {H}\n{L} MIT\n-->\n\n# Title\n")

    def test_css_takes_a_block_comment(self) -> None:
        new = self.fixed("a.css", "a { color: red; }\n")
        self.assertTrue(new.startswith(f"/*\n * {C} 2026 {H}\n * {L} MIT\n */\n"))

    def test_typescript_takes_slashes(self) -> None:
        self.assertTrue(self.fixed("a.ts", "export {};\n").startswith(f"// {C} 2026 {H}\n"))

    def test_an_xml_declaration_stays_first(self) -> None:
        new = self.fixed("a.xml", '<?xml version="1.0"?>\n<root/>\n')
        self.assertTrue(new.startswith('<?xml version="1.0"?>\n<!--\n'), new)

    def test_a_one_line_comment_gets_a_one_line_sibling(self) -> None:
        new = self.fixed("a.html", f"<!-- {L} MIT -->\n<p>x</p>\n", lic=None)
        self.assertTrue(new.startswith(f"<!-- {C} 2026 {H} -->\n<!-- {L} MIT -->\n"), new)

    def test_an_e_mail_and_a_wrong_year_are_repaired(self) -> None:
        text = f"# {C} 2024 {H} <mail@example.org>\n# {L} MIT\n"
        self.assertEqual(self.fixed("a.py", text), fx.header(year="2026"))

    def test_no_license_anywhere_is_left_for_a_person(self) -> None:
        _new, why = sh.fix_text("a.py", "x = 1\n", "2026", None)
        self.assertIsNotNone(why)

    def test_a_format_without_comments_is_left_to_reuse_toml(self) -> None:
        _new, why = sh.fix_text("a.json", "{}\n", "2026", "MIT")
        self.assertIn("REUSE.toml", str(why))

    def test_set_year_changes_only_the_owner_line(self) -> None:
        text = f"# {C} 2026 {H}\n# {C} 2014 Someone Else\n# {L} MIT\n"
        self.assertEqual(
            sh.set_year(text, "2031"), f"# {C} 2031 {H}\n# {C} 2014 Someone Else\n# {L} MIT\n"
        )


class RepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fx.init(Path(self._tmp.name) / "repo")
        fx.write(
            self.root,
            "REUSE.toml",
            'version = 1\n\n[[annotations]]\npath = ["**"]\nprecedence = "aggregate"\n'
            f'SPDX-FileCopyrightText = "2025 {H}"\nSPDX-License-Identifier = "MIT"\n\n'
            '[[annotations]]\npath = ["vendor/**"]\nprecedence = "override"\n'
            'SPDX-FileCopyrightText = "2014 Someone Else"\nSPDX-License-Identifier = "MIT"\n',
        )
        fx.write(self.root, "old.py", "x = 1\n")
        fx.write(self.root, "vendor/lib.py", "y = 2\n")
        fx.write(self.root, "data.json", "{}\n")
        fx.write(self.root, "pnpm-lock.yaml", "lockfileVersion: '9.0'\n")
        fx.write(self.root, ".github/PULL_REQUEST_TEMPLATE.md", "## What\n")
        fx.commit(self.root, date="2025-03-01T12:00:00+00:00")
        fx.write(self.root, "new.sh", "#!/bin/sh\necho hi\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_only_the_files_that_can_carry_a_comment_are_held_to_it(self) -> None:
        problems, _notes = sh.check_repo(self.root)
        files = {p.split(":", 1)[0] for p in problems}
        self.assertEqual(files, {"old.py", "new.sh"})

    def test_write_uses_the_first_commit_year_and_the_reuse_license(self) -> None:
        changed, left = sh.write_repo(self.root, None, None)
        self.assertEqual(left, [])
        self.assertEqual(sorted(changed), ["new.sh", "old.py"])
        self.assertEqual((self.root / "old.py").read_text(), fx.header(year="2025") + "\nx = 1\n")
        new = (self.root / "new.sh").read_text()
        self.assertTrue(new.startswith("#!/bin/sh\n" + fx.header(year=sh_year())), new)
        self.assertEqual(sh.check_repo(self.root)[0], [])

    def test_a_wrong_year_is_found_against_the_history(self) -> None:
        (self.root / "old.py").write_text(fx.header(year="2026") + "x = 1\n")
        problems, _notes = sh.check_repo(self.root)
        self.assertTrue(any("old.py" in p and "2025" in p for p in problems), problems)

    def test_a_shallow_clone_checks_presence_only(self) -> None:
        (self.root / "old.py").write_text(fx.header(year="2019") + "x = 1\n")
        (self.root / "new.sh").unlink()
        fx.commit(self.root, "Edit", date="2025-04-01T12:00:00+00:00")
        clone = Path(self._tmp.name) / "shallow"
        fx.git(
            Path(self._tmp.name), "clone", "-q", "--depth", "1", f"file://{self.root}", str(clone)
        )
        problems, notes = sh.check_repo(clone)
        self.assertEqual(problems, [])
        self.assertTrue(any("shallow" in n for n in notes), notes)


def sh_year() -> str:
    return str(dt.datetime.now(tz=dt.UTC).year)


if __name__ == "__main__":
    unittest.main()
