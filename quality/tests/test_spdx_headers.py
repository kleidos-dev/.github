# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""spdx_headers.py: both lines, copyright first, the first-commit year, no e-mail."""

from __future__ import annotations

import datetime as dt
import tempfile
import unicodedata
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
        text = f"# {C} 2014 Someone Else\n# {C} 2026 {H}\n# {L} MIT\n"
        self.assertEqual(sh.check_text("a.py", text, "2026"), [])

    def test_a_copyright_line_names_the_owner(self) -> None:
        text = f"# {C} 2026 Jose Requena\n# {L} MIT\n"
        self.assertTrue(any("names" in p for p in sh.check_text("a.py", text, "2026")))

    def test_the_year_before_is_accepted_for_a_squash_across_new_year(self) -> None:
        self.assertEqual(sh.check_text("a.py", fx.header(year="2026"), "2027"), [])
        self.assertTrue(sh.check_text("a.py", fx.header(year="2025"), "2027"))
        self.assertTrue(sh.check_text("a.py", fx.header(year="2028"), "2027"))

    def test_the_lines_sit_in_a_comment_at_the_top(self) -> None:
        late = '"""Doc."""\n' + fx.header()
        self.assertTrue(any("top" in p for p in sh.check_text("a.py", late, "2026")))
        in_docstring = f'"""Doc.\n\n{C} 2026 {H}\n{L} MIT\n"""\n'
        self.assertTrue(any("top" in p for p in sh.check_text("a.py", in_docstring, "2026")))
        shebang = "#!/usr/bin/env python3\n" + fx.header()
        self.assertEqual(sh.check_text("a.py", shebang, "2026"), [])
        md_late = f"# Title\n\n<!--\n{C} 2026 {H}\n{L} MIT\n-->\n"
        self.assertTrue(any("top" in p for p in sh.check_text("a.md", md_late, "2026")))
        md = f"---\ntitle: x\n---\n<!--\n{C} 2026 {H}\n{L} MIT\n-->\n\n# T\n"
        self.assertEqual(sh.check_text("a.md", md, "2026"), [])
        css = f"/*\n * {C} 2026 {H}\n * {L} MIT\n */\nbody {{}}\n"
        self.assertEqual(sh.check_text("a.css", css, "2026"), [])
        css_late = f"body {{}}\n/*\n * {C} 2026 {H}\n * {L} MIT\n */\n"
        self.assertTrue(sh.check_text("a.css", css_late, "2026"))

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

    def test_astro_takes_slashes_inside_its_front_matter(self) -> None:
        text = "---\nconst { title } = Astro.props;\n---\n<article>{title}</article>\n"
        new, why = sh.fix_text("Card.astro", text, "2026", "MIT")
        self.assertIsNone(why)
        self.assertTrue(new.startswith(f"---\n// {C} 2026 {H}\n// {L} MIT\n"), new)
        self.assertNotIn("<!--", new)
        self.assertEqual(sh.check_text("Card.astro", new, "2026"), [])
        bare, why = sh.fix_text("Bare.astro", "<p>hi</p>\n", "2026", "MIT")
        self.assertIsNone(why)
        self.assertEqual(bare, f"---\n// {C} 2026 {H}\n// {L} MIT\n---\n<p>hi</p>\n")
        html_comment = text.replace("<article>", f"<!--\n{C} 2026 {H}\n{L} MIT\n-->\n<article>")
        self.assertTrue(
            any("front matter" in p for p in sh.check_text("C.astro", html_comment, "2026"))
        )
        moved, why = sh.fix_text("C.astro", html_comment, "2026", None)
        self.assertIsNone(why)
        self.assertNotIn("<!--", moved)
        self.assertEqual(sh.check_text("C.astro", moved, "2026"), [])
        self.assertIn("<article>{title}</article>", moved)

    def test_every_header_line_sits_at_the_top(self) -> None:
        split = f"<!--\n{C} 2026 {H}\n-->\n\n# Title\n\n<!--\n{L} MIT\n-->\n"
        self.assertTrue(any("top" in p for p in sh.check_text("a.md", split, "2026")))

    def test_only_shell_like_shebangs_take_hash_lines(self) -> None:
        for shebang in ("#!/bin/sh", "#!/usr/bin/env bash", "#!/usr/bin/env python3", "#!/bin/zsh"):
            self.assertIsNotNone(sh.style_for("tools/run", shebang + "\n"), shebang)
        self.assertIsNone(sh.style_for("tools/run", "#!/usr/bin/env node\n"))

    def test_more_formats_take_comments(self) -> None:
        for rel in (
            ".git-blame-ignore-revs",
            "Doxyfile",
            "docs/groups.dox",
            "firmware/sdkconfig.defaults",
            "Kconfig.projbuild",
            "variants/partitions_8mb.csv",
            "src/linker.lf",
            "test/lsan.supp",
            "boot.S",
            "memory.ld",
            "quality/shellcheck/shellcheckrc",
            ".cppcheck-suppress",
        ):
            self.assertIsNotNone(sh.style_for(rel), rel)
        self.assertIsNone(sh.style_for("hardware/bom.csv"))

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
            'SPDX-FileCopyrightText = "2014 Someone Else"\nSPDX-License-Identifier = "MIT"\n\n'
            '[[annotations]]\npath = ["**/*.json"]\nprecedence = "aggregate"\n'
            f'SPDX-FileCopyrightText = "2025 {H}"\nSPDX-License-Identifier = "MIT"\n',
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

    def test_a_text_file_of_an_unknown_format_is_named(self) -> None:
        fx.write(self.root, "notes.weird", "plain text\n")
        (self.root / "blob.bin").write_bytes(b"\x00\x01\x02")
        fx.write(self.root, "tools/build", "#!/bin/sh\necho hi\n")
        problems, _notes = sh.check_repo(self.root)
        files = {p.split(":", 1)[0] for p in problems}
        self.assertIn("notes.weird", files)
        self.assertIn("tools/build", files)  # a script by its shebang: held to the rule
        self.assertNotIn("blob.bin", files)
        self.assertNotIn("data.json", files)  # named by an annotation of its own

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


class OwnerStatementTest(unittest.TestCase):
    """The owner's copyright is year and name, in the license texts too."""

    MAIL = "mail" + "@" + "kleidos.dev"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fx.init(Path(self._tmp.name) / "repo")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_the_header_holds_year_and_name_only(self) -> None:
        for value, fine in (
            (f"2026 {H}", True),
            (f"2024-2026 {H}", True),
            (f"2024, 2026 {H}", True),
            (f"2026 {H} (Spanish translation)", True),
            (f"2026 {H} and contributors", False),
            (f"2026 {H}, all rights reserved", False),
            (f"2026 {H} (write to me)(now)", False),
            (f"2026 {H}.", False),
            (f"2026 The {H}", False),
        ):
            with self.subTest(value=value):
                found = sh.check_text("a.py", f"# {C} {value}\n# {L} MIT\n", None)
                only = [p for p in found if "year and name only" in p]
                self.assertEqual(not only, fine, found)

    def test_an_e_mail_is_named_once_and_as_one(self) -> None:
        found = sh.check_text("a.py", f"# {C} 2026 {H} <{self.MAIL}>\n# {L} MIT\n", None)
        self.assertEqual(len(found), 1, found)
        self.assertIn("e-mail", found[0])

    def test_the_lines_of_a_license_text(self) -> None:
        for line, fine in (
            (f"Copyright (c) 2026 {H}", True),
            (f"Copyright (C) 2026 {H}", True),
            (f"Copyright © 2025-2026 {H}", True),
            (f"   Copyright (c) 2026 {H}  ", True),
            (f"Copyright (c) 2026 {H}. All rights reserved.", True),
            ("Copyright (c) <year> <copyright holders>", True),
            ("Copyright (C) 2007 Free Software Foundation, Inc. <https://fsf.org/>", True),
            ("Copyright (c) 2014 Someone Else <someone@example.org>", True),
            (f"The work of {H} is under this copyright notice", False),
            (f"Copyright (c) 2026 {H} <{self.MAIL}>", False),
            (f"Copyright (c) 2026 {H} <me@example.org>", False),
            (f"Copyright (c) 2026 Kleidos <{self.MAIL}>", False),
            (f"Copyright (c) 2026 Kleidos <{self.MAIL.upper()}>", False),
            ("Copyright (c) 2026 Jose M. Requena Plens", False),
            (f"Copyright (c) {H}", False),
            (f"Copyright 2026 {H}", False),
            (f"© 2026 {H}", False),
        ):
            with self.subTest(line=line):
                found = sh.license_text_problems("LICENSE", f"MIT License\n\n{line}\n")
                self.assertEqual(found == [], fine, found)
                if not fine:
                    self.assertTrue(found[0].startswith("LICENSE:3: "), found)

    def test_what_is_a_license_text(self) -> None:
        for rel, is_one in (
            ("LICENSE", True),
            ("LICEN" + "CE.md", True),
            ("COPYING", True),
            ("docs/LICENSE-MIT", True),
            ("LICENSES/MIT.txt", True),
            ("LICENSES/x/y", True),
            ("LICENSED.md", False),
            ("docs/LICENSES/MIT.txt", False),
            ("NOTICE.md", False),
        ):
            self.assertIs(sh.is_license_text(rel), is_one, rel)

    def found(self) -> tuple[list[str], list[str]]:
        return sh.owner_problems(self.root)

    def test_an_e_mail_after_the_name_is_found_in_any_file(self) -> None:
        fx.write(self.root, "a.md", f"x\n\nCopyright (c) 2026 {H} <{self.MAIL}>.\n")
        fx.write(self.root, "b.py", f"NOTICE = '© 2026 {H} {self.MAIL}'\n")
        fx.write(self.root, "c.md", f"Write to {H}, {self.MAIL}.\n")  # no copyright statement
        fx.write(self.root, "d.md", f"Copyright 2026 {H}. Write to {self.MAIL}.\n")
        fx.write(self.root, "e.bin", "\0")
        problems, notes = self.found()
        self.assertEqual(
            [p.split(": ")[0] for p in sorted(problems)], ["a.md:3", "b.py:1"], problems
        )
        self.assertEqual(notes, [])

    def test_however_it_is_written(self) -> None:
        mail = "owner@example.org"
        plain = unicodedata.normalize("NFD", H)
        for text, found in (
            (f"# Copyright (c) 2026 {H} <{mail}>", True),
            (f"# Copyright (c) 2026 {H} ({mail})", True),
            (f"# Copyright (c) 2026 <{mail}> {H}", True),
            (f"# Copyright (c) 2026 {mail}, {H}", True),
            (f"# Copyright (c) 2026 {H}, e-mail: {mail}", True),
            (f"# Copyright (c) 2026 {H} (email {mail})", True),
            (f"# Copyright (c) 2026 {H}, contact {mail}", True),
            (f"# Copyright (c) 2026 J. M. Requena Plens <{mail}>", True),
            (f"# Copyright (c) 2026 Jose M Requena Plens <{mail}>", True),
            (f"# Copyright (c) 2026 José Requena Plens <{mail}>", True),
            (f"# Copyright (c) 2026 {H.upper()} <{mail}>", True),
            (f"# Copyright (c) 2026 {H.upper()} <{mail.upper()}>", True),
            (f"# Copyright (c) 2026 {plain} <{mail}>", True),
            (f"# Copyright (c) 2026 Requena Plens, José M. <{mail}>", True),
            (f"# Copyright (c) 2026 Requena Plens, José <{mail}>", True),
            (f"# Copyright (c) 2026 Requena Plens <{mail}>", True),
            (f"# Copyright (c) 2026 {H} <owner at example dot org>", True),
            (f"# Copyright (c) 2026 {H} owner [at] example [dot] org", True),
            (f"# Copyright (c) 2026 {H}\n# <{mail}>", True),
            (f"# Copyright (c) 2026 {H}\n# e-mail: {mail}", True),
            (f"# Copyright (c) 2026 {H}\n#\n# {mail}", False),
            (f"# Copyright (c) 2026 {H}", False),
            (f"# Copyright (c) 2026 {H}. Write to {mail}", False),
            (f"# Copyright (c) 2026 {H} looked at the dot", False),
            (f"# {H} <{mail}>", False),
            (f"# {H}\n# Copyright (c) 2026 Someone <{mail}>", False),
            (f"# Copyright (c) 2026 Someone <{mail}>", False),
            (f"# Copyright (c) 2026 Juan Requena <{mail}>", False),
        ):
            with self.subTest(text=text):
                for rel, number in (("a.py", 3), ("NOTICE", 1), ("LICENSES/MIT.txt", 1)):
                    fx.write(self.root, rel, "x\n" * (number - 1) + text + "\n")
                    problems, notes = self.found()
                    named = f"{rel}:{number}: a copyright statement carries the owner's e-mail"
                    self.assertEqual(
                        any(p.startswith(named) for p in problems), found, problems + notes
                    )
                    (self.root / rel).unlink()

    def test_the_owner_in_a_license_text_however_written(self) -> None:
        for name in (H.upper(), "J. M. Requena Plens", "Requena Plens, José M.", "Requena Plens"):
            found = sh.license_text_problems("LICENSE", f"Copyright (c) 2026 {name}\n")
            self.assertEqual(found == [], name == H.upper(), name)

    def test_an_e_mail_in_reuse_toml_or_a_header(self) -> None:
        for value, found in (
            (f"2026 {H}", False),
            (f"2026 {H} <{self.MAIL}>", True),
            (f"2026 {H} {self.MAIL}", True),
            ("2026 Someone someone@example.org", True),
            ("2026 Someone <x@y>", True),
            ("2026 Someone", False),
        ):
            with self.subTest(value=value):
                fx.write(
                    self.root,
                    "REUSE.toml",
                    f'# {C} 2026 {H}\n# {L} MIT\nversion = 1\n[[annotations]]\npath = ["x"]\n'
                    f'{C} "{value}"\n{L} "MIT"\n'.replace(f'{C} "', f'{C[:-1]} = "').replace(
                        f'{L} "', f'{L[:-1]} = "'
                    ),
                )
                fx.commit(self.root)
                problems = [p for p in sh.check_repo(self.root)[0] if "e-mail address" in p]
                self.assertEqual(len(problems), int(found), problems)
                if found:
                    self.assertTrue(problems[0].startswith("REUSE.toml: a copyright"), problems)
                problems = sh.check_text("a.py", f"# {C} {value}\n# {L} MIT\n", None)
                self.assertEqual(any("e-mail address" in p for p in problems), found, problems)

    def test_a_license_text_is_a_problem_unless_copies_are_held(self) -> None:
        fx.write(self.root, "LICENSES/MIT.txt", f"Copyright (c) 2026 {H} <{self.MAIL}>\n")
        fx.write(self.root, "LICENSES/blob.txt", "\0copyright " + H)
        problems, notes = self.found()
        self.assertEqual(len(problems), 1, problems)
        self.assertEqual(notes, [])
        record = ".github/quality/SOURCE.json"
        for body, held in (
            ('{"commit": "0123", "version": "2.3.0"}', True),
            ('{"schema": "kleidos.vendored-copy/1"}', False),
            ('{"commit": "self"}', False),
            ("[]", False),
            ("{", False),
        ):
            with self.subTest(body=body):
                fx.write(self.root, record, body)
                self.assertIs(sh.holds_kit_copies(self.root), held)
                problems, notes = self.found()
                self.assertEqual((len(problems), len(notes)), (0, 1) if held else (1, 0))

    def test_the_whole_check_reports_both(self) -> None:
        fx.write(self.root, "LICENSE", f"Copyright (c) 2026 {H} <{self.MAIL}>\n")
        fx.commit(self.root)
        problems, _notes = sh.check_repo(self.root)
        self.assertTrue(any(p.startswith("LICENSE:1:") for p in problems), problems)
        fx.write(self.root, ".github/quality/SOURCE.json", '{"commit": "0123"}')
        problems, notes = sh.check_repo(self.root)
        self.assertFalse(any(p.startswith("LICENSE:1:") for p in problems), problems)
        self.assertTrue(any("from the switch to the run form" in n for n in notes), notes)

    def test_the_copies_of_both_forms_are_read(self) -> None:
        rel = ".github/quality/SOURCE.json"
        self.assertEqual(sh.kit_copies(self.root), set())
        for body, copies in (
            ('{"files": {"a.toml": "0"}}', {"a.toml"}),
            ('{"files": [{"path": "b.py"}]}', {"b.py"}),
            ('{"files": [3]}', set()),
            ("{}", set()),
            ("{", set()),
        ):
            fx.write(self.root, rel, body)
            self.assertEqual(sh.kit_copies(self.root), copies, body)

    def test_the_kits_own_tree_holds_no_e_mail(self) -> None:
        self.assertEqual(sh.owner_problems(fx.CENTRAL), ([], []))


def sh_year() -> str:
    return str(dt.datetime.now(tz=dt.UTC).year)


if __name__ == "__main__":
    unittest.main()
