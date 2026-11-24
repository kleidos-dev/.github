# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""check_quality.py: each conformance rule fires on the weakening it names."""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import kit_fixtures as fx
from kit_fixtures import check_quality as cq
from kit_fixtures import sync

TODAY = dt.date(2026, 11, 22)
FOREIGN = (
    "hold a pattern the kit cannot read as gitleaks does (\\p, a POSIX class, the flag U or -u,"
    " or one Python refuses): refused (no waiver)"
)
FOREIGN_PATHS = f"its paths {FOREIGN}"
FOREIGN_REGEXES = f"its regexes {FOREIGN}"


class ConformanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fx.consumer(Path(self._tmp.name) / "repo")
        sync.write(self.root, commit=fx.FAKE_COMMIT)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def found(self) -> list[str]:
        report = cq.run(self.root, kit=cq.DirKit(fx.CENTRAL), today=TODAY)
        return [f"{p.where}: [{p.rule}] {p.message}" for p in report.problems]

    def edit(self, rel: str, old: str, new: str) -> None:
        path = self.root / rel
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text, rel)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def append(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")

    def assertFound(self, *needles: str) -> None:
        found = self.found()
        for needle in needles:
            self.assertTrue(any(needle in f for f in found), f"{needle!r} not in {found}")

    def test_the_fixture_starts_clean(self) -> None:
        self.assertEqual(self.found(), [])

    # --- mypy: owner, 2026-11-22: every error fixed, no baseline ---------

    def test_mypy_error_silencing_keys_are_refused(self) -> None:
        pyproject = self.root / "pyproject.toml"
        original = pyproject.read_text(encoding="utf-8")
        for key, value in (
            ("ignore_errors", "true"),
            ("disable_error_code", '["arg-type"]'),
            ("warn_return_any", "false"),
            ("follow_imports", '"skip"'),
            ("allow_untyped_defs", "true"),
        ):
            with self.subTest(key=key):
                pyproject.write_text(original + f"{key} = {value}\n", encoding="utf-8")
                self.assertFound(f"{key}")

    def test_a_mypy_override_may_only_declare_missing_types(self) -> None:
        self.append(
            "pyproject.toml",
            '\n# pcbnew ships no types\n[[tool.mypy.overrides]]\nmodule = ["pcbnew"]\n'
            "ignore_missing_imports = true\n",
        )
        self.assertEqual(self.found(), [])
        self.append(
            "pyproject.toml",
            '\n[[tool.mypy.overrides]]\nmodule = ["pkg.mod"]\ndisallow_untyped_defs = false\n',
        )
        self.assertFound(
            "an override may only set ignore_missing_imports", "needs a comment above it"
        )

    def test_a_python_file_outside_mypy_files_is_reported(self) -> None:
        fx.write(self.root, "tools/extra.py", fx.header() + "X = 1\n")
        self.assertFound("tools/extra.py: [mypy] not checked by mypy")

    def test_a_type_ignore_names_its_code_and_reason(self) -> None:
        fx.write(
            self.root,
            "pkg/bad.py",
            fx.header() + "A = 1  # type: ignore\nB = 2  # type: ignore[assignment]\n",
        )
        self.assertFound("names its error code", "carries its reason")

    # --- ruff ----------------------------------------------------------------

    def test_a_local_ruff_select_is_refused(self) -> None:
        self.append("pyproject.toml", '\n[tool.ruff.lint]\nselect = ["E"]\n')
        self.assertFound("a local select replaces the kit's rule list")

    def test_a_ruff_ignore_needs_a_waiver_and_a_waiver_needs_its_weakening(self) -> None:
        self.append("pyproject.toml", '\n[tool.ruff.lint]\nignore = ["E501"]\n')
        self.assertFound("ignore:E501 weakens a kit rule and has no waiver")
        waiver = (
            '\n[[waiver]]\ntool = "ruff"\nwhat = "ignore:E501"\n'
            'reason = "Generated tables keep their width"\ndecided = "owner 2026-11-22"\n'
        )
        self.append(cq.WAIVERS, waiver)
        self.assertEqual(self.found(), [])
        self.edit("pyproject.toml", 'ignore = ["E501"]', "")
        self.assertFound("matches nothing any more")

    def test_a_ruff_include_narrows_the_files_and_needs_a_waiver(self) -> None:
        self.edit(
            "pyproject.toml",
            'target-version = "py315"\n',
            'target-version = "py315"\ninclude = ["nothing/*.py"]\n',
        )
        self.assertFound("include:nothing/*.py weakens a kit rule")
        self.edit("pyproject.toml", 'include = ["nothing/*.py"]', "include = []")
        self.assertFound("include:(empty) weakens a kit rule")

    def test_an_expired_or_unreasoned_waiver_fails(self) -> None:
        self.append("pyproject.toml", '\n[tool.ruff.lint]\nignore = ["E501"]\n')
        self.append(
            cq.WAIVERS,
            '\n[[waiver]]\ntool = "ruff"\nwhat = "ignore:E501"\nreason = ""\n'
            'decided = "owner 2026-01-01"\nexpires = 2026-06-01\n',
        )
        self.assertFound("needs reason", "expired on 2026-06-01")

    def test_mypy_takes_only_the_settings_it_allows(self) -> None:
        pyproject = self.root / "pyproject.toml"
        original = pyproject.read_text(encoding="utf-8")
        for line in (
            'always_false = ["TYPE_CHECKED"]',
            'always_true = ["X"]',
            'untyped_calls_exclude = ["pkg"]',
            "follow_untyped_imports = true",
            "implicit_reexport = true",
            "warn_unreachable = false",
        ):
            pyproject.write_text(original + line + "\n", encoding="utf-8")
            self.assertFound("refused (no waiver)")
        for line in (
            "warn_unreachable = true",
            "pretty = true",
            'plugins = ["pydantic.mypy"]',
            "implicit_reexport = false",
            'follow_imports = "error"',
        ):
            pyproject.write_text(original + line + "\n", encoding="utf-8")
            self.assertEqual(self.found(), [], line)

    def test_mypy_cannot_be_waived(self) -> None:
        self.append(
            cq.WAIVERS,
            '\n[[waiver]]\ntool = "mypy"\nwhat = "ignore_errors"\nreason = "no"\ndecided = "x"\n',
        )
        self.assertFound("'mypy' cannot be waived")

    # --- gitleaks, OSV, Dependabot -------------------------------------------

    def test_gitleaks_keeps_every_default_rule_and_targets_its_allowlists(self) -> None:
        fx.write(
            self.root,
            ".gitleaks.toml",
            fx.header()
            + '[extend]\nuseDefault = true\ndisabledRules = ["generic-api-key"]\n'
            + "[allowlist]\npaths = ['x']\n"
            + "[[allowlists]]\npaths = ['y']\n",
        )
        self.assertFound(
            "disabledRules turns default rules off",
            "a global [allowlist] reaches every rule",
            "needs a description",
            "needs targetRules",
        )

    def test_gitleaks_extends_every_default_rule(self) -> None:
        rel = ".gitleaks.toml"
        for body in (
            "",
            "[extend]\n",
            "[extend]\nuseDefault = false\n",
            '[extend]\nuseDefault = "x"\n',
        ):
            fx.write(self.root, rel, fx.header() + body)
            self.assertEqual(
                self.found(),
                [f"{rel}: [gitleaks] [extend] useDefault = true is required: every default rule"],
                body,
            )
        fx.write(self.root, rel, fx.header() + "[extend]\nuseDefault = true\n")
        self.assertEqual(self.found(), [])
        fx.write(self.root, rel, "= 3\n")
        self.assertFound(f"{rel}: [gitleaks] not valid TOML", "useDefault = true is required")
        (self.root / rel).unlink()
        self.assertFound(f"{rel}: [gitleaks] missing")

    def test_a_gitleaks_allowlist_says_why_and_for_which_rules(self) -> None:
        body = "[extend]\nuseDefault = true\n[[allowlists]]\npaths = ['y']\n"
        for more, problems in (
            ("description = 'd'\ntargetRules = ['r']\n", 0),
            ("description = ' '\ntargetRules = ['r']\n", 1),
            ("description = 'd'\ntargetRules = []\n", 1),
            ("description = 'd'\n", 1),
            ("targetRules = ['r']\n", 1),
        ):
            fx.write(self.root, ".gitleaks.toml", fx.header() + body + more)
            self.assertEqual(len(self.found()), problems, more)

    def test_a_gitleaks_allowlist_of_everything_turns_its_rules_off(self) -> None:
        body = (
            "[extend]\nuseDefault = true\n[[allowlists]]\ndescription = 'd'\ntargetRules = ['r']\n"
        )
        for more, refused in (
            ("paths = ['.*']\n", "its paths cover every file"),
            ("paths = ['']\n", "its paths cover every file"),
            ("paths = ['^.*$']\n", "its paths cover every file"),
            ("paths = ['(?s).+', 'y']\n", "its paths cover every file"),
            ("regexes = ['.*']\n", "its regexes cover every secret"),
            ("regexes = ['[\\w-]+']\n", "its regexes cover every secret"),
            ("paths = ['^exports\\.json$']\n", ""),
            ("paths = ['\\.']\n", "its paths cover every file"),  # every file with a dot
            ("paths = ['\\.md$']\n", ""),
            ("paths = ['(']\n", FOREIGN_PATHS),
            ("regexes = ['^[0-9a-f]{64}$']\n", ""),
        ):
            with self.subTest(more=more):
                fx.write(self.root, ".gitleaks.toml", fx.header() + body + more)
                found = [f for f in self.found() if "[gitleaks]" in f]
                wanted = (
                    refused
                    if refused.startswith("its paths hold")
                    else f"{refused}: it turns its rules off, refused (no waiver)"
                )
                where = ".gitleaks.toml allowlists[0]: [gitleaks]"
                self.assertEqual(found, [f"{where} {wanted}"] if refused else [])

    def test_a_gitleaks_rule_of_the_tree_never_redefines_a_default_one(self) -> None:
        """gitleaks 8.30.1 merges a rule of the tree into the default rule of its id.

        Each of the first three silences the default rule on a generated
        api_key that the base configuration finds (1 leak, then none).
        """
        body = "[extend]\nuseDefault = true\n[[rules]]\n"
        where = ".gitleaks.toml rules[0]"
        rule = f"{where}: [gitleaks] "
        own = (
            "its id is not one of the repository's own (kleidos-*): a rule of a default"
            " rule's id redefines it, refused (no waiver)"
        )
        off = ": it turns its rules off, refused (no waiver)"
        allow = f"{where} allowlists[0]: [gitleaks] "
        for more, refused in (
            ("id = 'generic-api-key'\nentropy = 99\n", [rule + own]),
            ("id = 'generic-api-key'\npath = 'nothing-has-this-name'\n", [rule + own]),
            (
                "id = 'generic-api-key'\n[[rules.allowlists]]\nregexes = ['.*']\n",
                [rule + own, f"{allow}its regexes cover every secret{off}"],
            ),
            ("regex = 'x'\n", [rule + own]),
            ("id = 'Kleidos-x'\nregex = 'x'\n", [rule + own]),
            ("id = 'kleidos-own'\nregex = 'zzz[0-9]+'\n", []),
            (
                "id = 'kleidos-own'\nregex = 'x'\n[[rules.allowlists]]\npaths = ['.*']\n",
                [f"{allow}its paths cover every file{off}"],
            ),
            (
                "id = 'kleidos-own'\nregex = 'x'\n[rules.allowlist]\nregexes = ['']\n",
                [f"{where} allowlist: [gitleaks] its regexes cover every secret{off}"],
            ),
            ("id = 'kleidos-own'\nregex = 'x'\n[[rules.allowlists]]\npaths = ['^tests/']\n", []),
        ):
            with self.subTest(more=more):
                fx.write(self.root, ".gitleaks.toml", fx.header() + body + more)
                self.assertEqual([f for f in self.found() if "[gitleaks]" in f], refused)
        fx.write(
            self.root, ".gitleaks.toml", fx.header() + "[extend]\nuseDefault = true\nrules = 3\n"
        )
        self.assertEqual([f for f in self.found() if "[gitleaks]" in f], [])

    def gitleaks_found(self, body: str) -> list[str]:
        fx.write(self.root, ".gitleaks.toml", fx.header() + body)
        return [f for f in self.found() if "[gitleaks]" in f]

    def test_gitleaks_keys_are_read_without_regard_to_case(self) -> None:
        """gitleaks 8.30.1 reads every key without regard to case (2 leaks, then none for each)."""
        head = "[extend]\nuseDefault = true\n"
        rule = ".gitleaks.toml rules[0]: [gitleaks] its id is not one of the repository's own"
        allow = ".gitleaks.toml allowlists[0]: [gitleaks] "
        every = "its paths cover every file: it turns its rules off, refused (no waiver)"
        targets = "needs targetRules: an allowlist never covers every rule"
        for body, wanted in (
            (head + "[[Rules]]\nid = 'generic-api-key'\nentropy = 99\n", [rule]),
            (head + "[[RULES]]\nID = 'generic-api-key'\nEntropy = 99\n", [rule]),
            (
                head + "[[Allowlists]]\ndescription = 'd'\npaths = ['.']\n",
                [allow + every, allow + targets],
            ),
            (
                head + "[[allowlists]]\ndescription = 'd'\ntargetRules = ['x']\nPaths = ['.']\n",
                [allow + every],
            ),
            (
                head + "[[allowlists]]\nDescription = 'd'\nTargetRules = ['x']\nPaths = ['.']\n",
                [allow + every],
            ),
            (head + "[Allowlist]\npaths = ['.']\n", ["a global [allowlist] reaches every rule"]),
            (head + "DisabledRules = ['generic-api-key']\n", ["disabledRules turns default"]),
            ("[EXTEND]\nUseDefault = true\n", []),
            ("[extend]\nUSEDEFAULT = false\n", ["useDefault = true is required"]),
            (
                head + "UseDefault = false\n",
                [
                    "extend.usedefault is spelled more than once in different case",
                    "useDefault = true is required",
                ],
            ),
            (
                head
                + "[[allowlists]]\ndescription = 'd'\ntargetRules = ['x']\npaths = ['^a$']\n"
                + "[[Allowlists]]\ndescription = 'd'\ntargetRules = ['x']\npaths = ['.']\n",
                [
                    "allowlists is spelled more than once in different case",
                    ".gitleaks.toml allowlists[1]: [gitleaks] " + every,
                ],
            ),
            # One table alone is an array of one, one string a list of one (gitleaks 8.30.1).
            (
                head + "[allowlists]\ndescription = 'd'\ntargetRules = ['x']\npaths = ['.']\n",
                [allow + every],
            ),
            (
                head + "[[allowlists]]\ndescription = 'd'\ntargetRules = ['x']\npaths = '.'\n",
                [allow + every],
            ),
            (head + "[rules]\nid = 'generic-api-key'\nentropy = 99\n", [rule]),
        ):
            with self.subTest(body=body):
                found = self.gitleaks_found(body)
                self.assertEqual(len(found), len(wanted), found)
                ordered = sorted(found, key=lambda f: "spelled" not in f)
                for needle, line in zip(wanted, ordered, strict=True):
                    self.assertIn(needle, line)

    def test_a_gitleaks_pattern_the_kit_cannot_read_is_refused(self) -> None:
        """Go's RE2 reads these, and allows every path or secret (gitleaks 8.30.1: no leaks)."""
        body = (
            "[extend]\nuseDefault = true\n[[allowlists]]\ndescription = 'd'\ntargetRules = ['r']\n"
        )
        where = ".gitleaks.toml allowlists[0]: [gitleaks] "
        for more, wanted in (
            ("paths = ['[[:alnum:]]']\n", FOREIGN_PATHS),
            ("paths = ['\\pL']\n", FOREIGN_PATHS),
            ("paths = ['\\p{L}']\n", FOREIGN_PATHS),
            ("paths = ['\\PN']\n", FOREIGN_PATHS),
            ("regexes = ['\\pL']\n", FOREIGN_REGEXES),
            ("regexes = ['[[:alnum:]]']\n", FOREIGN_REGEXES),
            ("regexes = ['(?U).']\n", FOREIGN_REGEXES),
            ("regexes = ['(?-u:.)']\n", FOREIGN_REGEXES),
            ("regexes = ['[\\w--\\d]']\n", FOREIGN_REGEXES),  # a set operation Python warns on
            ("paths = ['(?i)^exports\\.json$']\n", ""),
            ("paths = ['\\\\pL']\n", ""),  # a backslash, then pL
            ("regexes = ['(?i)^[0-9a-f]{64}$']\n", ""),
        ):
            with self.subTest(more=more):
                found = self.gitleaks_found(body + more)
                self.assertEqual(found, [where + wanted] if wanted else [])

    def test_a_pattern_python_reads_otherwise_counts_as_covering(self) -> None:
        for pattern, foreign in (
            ("\\pL", True),
            ("\\p{L}+", True),
            ("x\\\\\\pL", True),
            ("[[:alpha:]]", True),
            ("[^[:space:]]", True),
            ("(?U).+", True),
            ("(?-u:\\w)", True),
            ("(?iU)x", True),
            ("[a&&b]", True),
            ("(", True),
            ("a(?i)b", True),  # Python takes a flag only at the start
            ("\\\\pL", False),
            ("(?i)x", False),
            ("(?Rm)^x$", False),
            ("(?R)x", False),
            ("(?R:x)", False),
            ("(?-i:x)", False),
            ("(?u)\\w", False),
            ("(?P<n>x)", False),
        ):
            with self.subTest(pattern=pattern):
                self.assertIs(cq.tool_regex(pattern) is None, foreign)
                if foreign:
                    self.assertTrue(cq.regex_covers_all(pattern, cq.PROBE_WORDS))
                    self.assertTrue(cq.ignores_every_word(pattern))
        self.assertTrue(cq.ignores_every_word("(?Rm)^.*$"))
        self.assertFalse(cq.ignores_every_word("(?Rm)^.*spellchecker:disable-line$"))

    def test_typos_patterns_the_kit_cannot_read_are_weakenings(self) -> None:
        """typos 1.52.2 finds 7 typos with no configuration and none with each of these."""
        for text, what in (
            ("[default]\nextend-ignore-re = ['\\p{L}+']\n", ["default.extend-ignore-re:\\p{L}+"]),
            ("[default]\nextend-ignore-re = ['\\pL']\n", ["default.extend-ignore-re:\\pL"]),
            (
                "[default]\nextend-ignore-re = ['[[:alpha:]]']\n",
                ["default.extend-ignore-re:[[:alpha:]]"],
            ),
            (
                "[default]\nextend-ignore-re = ['(?-u:\\w)']\n",
                ["default.extend-ignore-re:(?-u:\\w)"],
            ),
            ("[default]\nextend-ignore-re = ['(?U).+']\n", ["default.extend-ignore-re:(?U).+"]),
            (
                "[default]\nextend-ignore-identifiers-re = ['\\p{L}']\n",
                ["default.extend-ignore-identifiers-re:\\p{L}"],
            ),
            (
                "[default]\nextend-ignore-words-re = ['[[:alpha:]]']\n",
                ["default.extend-ignore-words-re:[[:alpha:]]"],
            ),
            (
                "[default]\nextend-ignore-re = ['(?Rm)^.*$']\n",
                ["default.extend-ignore-re:(?Rm)^.*$"],
            ),
            ("[default]\nextend-ignore-re = ['(?Rm)^.*spellchecker:disable-line$']\n", []),
            ("[default]\nextend-ignore-re = ['\\\\pL']\n", []),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.typos_off(text), what)

    def test_typos_globs_with_classes_and_alternates(self) -> None:
        """typos 1.52.2 reads globset's classes and alternates: no typo left with each of these."""
        for pattern, everything in (
            ("[!_]*", True),
            ("[^_]*", True),
            ("[a-zA-Z.]*", True),
            ("*[a-z]", True),
            ("{*,.*}", True),
            ("*.{md,txt,py,ts,yml}", True),
            ("[abc].md", False),
            ("[]a]*", False),
            ("{a,b}.md", False),
            ("\\*", False),
            ("[", False),
        ):
            with self.subTest(pattern=pattern):
                self.assertIs(cq.glob_covers_all(pattern), everything)
                text = f"[files]\nextend-exclude = ['{pattern}']\n"
                self.assertEqual(
                    self.typos_off(text), [f"extend-exclude:{pattern}"] if everything else []
                )
        for pattern in ("{*", "a}"):  # globs the kit cannot read, nor typos
            self.assertTrue(cq.glob_covers_all(pattern), pattern)

    def test_a_typos_table_tomllib_cannot_read_is_one(self) -> None:
        """typos reads a byte order mark and TOML 1.1, which tomllib before 3.15 refuses."""
        for text, held in (
            ("\ufeff[workspace.metadata.typos.default]\ncheck-file = false\n", True),
            ("\ufeff[tool.typos.default]\ncheck-file = false\n", True),
            ("\ufeff[tool.ruff]\n", False),
            ("[tool.typos\n", True),
            ('x = "\\q"\n[tool.typos.default]\ncheck-file = false\n', True),
            ("[tool.ruff\n", False),
        ):
            with self.subTest(text=text):
                self.assertIs(cq.has_typos_table(text), held)
        path = self.root / "Cargo.toml"
        path.write_bytes(b"\xef\xbb\xbf[workspace.metadata.typos.default]\ncheck-file = false\n")
        self.weakened("[typos] config:Cargo.toml")

    def weakened(self, needle: str) -> None:
        """A weakening the report names, with no waiver for it."""
        self.assertFound(f"{needle} weakens a kit rule and has no waiver")

    def waive(self, tool: str, what: str) -> None:
        self.append(
            cq.WAIVERS,
            f'\n[[waiver]]\ntool = "{tool}"\nwhat = "{what}"\nreason = "r"\ndecided = "d"\n',
        )

    def typos_found(self) -> list[str]:
        """What the typos rules find, with the waivers that answer them."""
        return [f for f in self.found() if "typos" in f]

    def test_a_second_typos_configuration_is_a_weakening(self) -> None:
        for rel, text in (
            ("typos.toml", "[files]\nextend-exclude = []\n"),
            ("_typos.toml", "[default]\n"),
            ("pkg/.typos.toml", "[default]\n"),
            ("pkg/typos.toml", "[default]\n"),
            ("pkg/pyproject.toml", "[tool.typos.default]\nlocale = 'en-gb'\n"),
            ("Cargo.toml", "[package.metadata.typos]\n"),
            ("crates/x/Cargo.toml", "[ workspace.metadata.typos.files ]\n"),
            # Other TOML spellings of the same table (typos 1.52.2: 6 typos, then 3).
            ("sub/pyproject.toml", "[tool]\ntypos.default.extend-ignore-re = ['.']\n"),
            ("sub/pyproject.toml", '[tool."typos".default]\nextend-ignore-re = ["."]\n'),
            ("sub/pyproject.toml", "tool = { typos = { default = { locale = 'en' } } }\n"),
            ("w/Cargo.toml", "[workspace]\nmetadata = { typos = {} }\n"),
        ):
            with self.subTest(rel=rel):
                fx.write(self.root, rel, fx.header() + text)
                self.weakened(f"[typos] config:{rel}")
                whole = (self.root / cq.WAIVERS).read_text(encoding="utf-8")
                self.waive("typos", f"config:{rel}")
                self.assertEqual(self.typos_found(), [])
                fx.write(self.root, cq.WAIVERS, whole)
                (self.root / rel).unlink()
        fx.write(self.root, "pkg/notypos.toml", fx.header())
        fx.write(self.root, "pkg/Cargo.toml", fx.header() + "[package]\nname = 'typos-free'\n")
        fx.write(self.root, "a/pyproject.toml", "[tool.ruff]\n# [tool.typos]\nx = 'tool.typos'\n")
        fx.write(self.root, "b/pyproject.toml", "[tool.ruff\n")  # no typos table, read or not
        fx.write(self.root, "c/Cargo.toml", "package = 3\n[workspace.metadata]\ntypo = 1\n")
        self.assertEqual(self.typos_found(), [])

    def typos_off(self, text: str) -> list[str]:
        """What a .typos.toml alone says is switched off."""
        root = fx.init(Path(self._tmp.name) / "typos-only")
        fx.write(root, ".typos.toml", text)
        report = cq.Report()
        cq.check_typos_off(cq.Repo(root), report)
        (root / ".typos.toml").unlink()
        return [w.what for w in report.weakenings]

    def test_typos_switched_off_from_its_configuration_is_a_weakening(self) -> None:
        for text, what in (
            ('[files]\nextend-exclude = ["*"]\n', ["extend-exclude:*"]),
            ('[files]\nextend-exclude = ["**", "a/"]\n', ["extend-exclude:**"]),
            ('[files]\nextend-exclude = ["**/*"]\n', ["extend-exclude:**/*"]),
            ('[files]\nextend-exclude = ["/"]\n', ["extend-exclude:/"]),
            ('[files]\nextend-exclude = ["_shared/kicad/", "*.md", "LICENSES/"]\n', []),
            ("[default.extend-words]\nkleidos = 'kleidos'\n", []),
            ("[default]\ncheck-file = false\n", ["default.check-file=false"]),
            ("[default]\ncheck-filename = false\n", ["default.check-filename=false"]),
            ("[default]\ncheck-file = true\n", []),
            ("[type.py]\ncheck-file = false\n", ["type.py.check-file=false"]),
            # typos 1.52.2 still checks a type made binary: 7 typos with and without.
            ("[type.py]\nbinary = true\n", []),
            ("[default]\nbinary = true\n", []),
            ('[type.py]\nextend-glob = ["*.pyi"]\n', []),
            ("[type]\npy = 'not a table'\n", []),
            ("type = 3\nfiles = 3\ndefault = 3\n", []),
            ("[default]\nextend-ignore-re = ['.*']\n", ["default.extend-ignore-re:.*"]),
            ("[default]\nextend-ignore-re = ['(?s).+']\n", ["default.extend-ignore-re:(?s).+"]),
            (
                "[type.md]\nextend-ignore-identifiers-re = ['\\w+']\n",
                ["type.md.extend-ignore-identifiers-re:\\w+"],
            ),
            (
                "[default]\nextend-ignore-words-re = ['^.*$']\n",
                ["default.extend-ignore-words-re:^.*$"],
            ),
            # typos skips what the pattern spans: no word left, nothing checked.
            ("[default]\nextend-ignore-re = ['.']\n", ["default.extend-ignore-re:."]),
            (
                "[default]\nextend-ignore-re = ['[A-Za-z]+']\n",
                ["default.extend-ignore-re:[A-Za-z]+"],
            ),
            ("[default]\nextend-ignore-re = ['.+?']\n", ["default.extend-ignore-re:.+?"]),
            ("[default]\nextend-ignore-re = ['[a-z]']\n", ["default.extend-ignore-re:[a-z]"]),
            ("[default]\nextend-ignore-re = ['[A-Z]']\n", []),
            ("[default]\nextend-ignore-re = ['']\n", []),
            ("[default]\nextend-ignore-re = ['^']\n", []),
            # An identifier or a word is skipped when the pattern is found in it.
            (
                "[default]\nextend-ignore-identifiers-re = ['[a-z]']\n",
                ["default.extend-ignore-identifiers-re:[a-z]"],
            ),
            (
                "[default]\nextend-ignore-words-re = ['[a-z]']\n",
                ["default.extend-ignore-words-re:[a-z]"],
            ),
            ("[default]\nextend-ignore-identifiers-re = ['[A-Z]']\n", []),
            ("[default]\nextend-ignore-words-re = ['e']\n", []),
            ('[files]\nextend-exclude = ["*.*"]\n', ["extend-exclude:*.*"]),
            ("[default]\nextend-ignore-re = ['\\bPNGs\\b']\n", []),
            ("[default]\nextend-ignore-re = ['\\b[0-9a-f]{7,64}\\b']\n", []),
            ("[default]\nextend-ignore-re = ['e']\n", []),
            ("[default]\nextend-ignore-re = ['(']\n", ["default.extend-ignore-re:("]),
            ("= not toml\n", []),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.typos_off(text), what)

    def test_an_actionlint_ignore_is_a_weakening(self) -> None:
        whole = (self.root / cq.WAIVERS).read_text(encoding="utf-8")
        for rel in (".github/actionlint.yaml", ".github/actionlint.yml"):
            with self.subTest(rel=rel):
                text = "paths:\n  .github/workflows/**/*.yml:\n    ignore:\n      - '.*'\n"
                fx.write(self.root, rel, fx.header() + text)
                self.weakened("[actionlint] ignore:.github/workflows/**/*.yml:.*")
                self.waive("actionlint", "ignore:.github/workflows/**/*.yml:.*")
                self.assertEqual(self.found(), [])
                fx.write(self.root, rel, fx.header() + "self-hosted-runner:\n  labels: [big]\n")
                self.assertFound("matches nothing any more")
                fx.write(self.root, rel, fx.header() + "paths: [\n")
                self.assertFound(f"{rel}: [actionlint] not valid YAML")
                (self.root / rel).unlink()
                fx.write(self.root, cq.WAIVERS, whole)
        fx.write(self.root, ".github/actionlint.yaml", fx.header() + "paths:\n  x:\n")
        self.assertEqual(self.found(), [])
        for text in (
            "- a list\n",
            "paths: [a]\n",
            "paths:\n  x: [a]\n",
            "paths:\n  x:\n    ignore:\n",
        ):
            fx.write(self.root, ".github/actionlint.yaml", fx.header() + text)
            self.assertEqual(self.found(), [], text)
        fx.write(
            self.root, ".github/actionlint.yaml", fx.header() + "paths:\n  x:\n    ignore: '.*'\n"
        )
        self.weakened("[actionlint] ignore:x:.*")

    def test_a_second_zizmor_configuration_is_refused(self) -> None:
        text = fx.header() + "rules:\n  unpinned-uses:\n    disable: true\n"
        for rel in (
            "zizmor.yml",
            "zizmor.yaml",
            ".zizmor.yml",
            ".zizmor.yaml",
            ".github/zizmor.yaml",
        ):
            with self.subTest(rel=rel):
                fx.write(self.root, rel, text)
                said = "a second zizmor configuration: the kit's .github/zizmor.yml is the one"
                self.assertEqual(
                    [f for f in self.found() if "[zizmor]" in f], [f"{rel}: [zizmor] {said}"]
                )
                (self.root / rel).unlink()
        fx.write(self.root, "docs/zizmor.yml", fx.header())
        self.assertEqual(self.found(), [])

    def test_a_markdownlint_configuration_in_a_folder_is_a_weakening(self) -> None:
        for rel in (
            "docs/.markdownlint.yaml",
            "docs/.markdownlint.json",
            "a/b/.markdownlint-cli2.jsonc",
            "docs/.markdownlint-cli2.mjs",
            ".markdownlint-cli2.yaml",
            ".markdownlint-cli2.cjs",
        ):
            with self.subTest(rel=rel):
                fx.write(self.root, rel, "// x\n" if rel.endswith("js") else "{}\n")
                self.weakened(f"[markdownlint] config:{rel}")
                (self.root / rel).unlink()
        fx.write(self.root, "node_modules/x/.markdownlint.json", "{}\n")
        fx.write(self.root, "docs/markdownlint.json", "{}\n")
        self.assertEqual(self.found(), [])

    def test_sonar_suppressions_and_exclusions_of_everything_are_refused(self) -> None:
        rel = "sonar-project.properties"
        for line, refused in (
            (
                "sonar.issue.ignore.multicriteria=e1",
                "sonar.issue.ignore.multicriteria suppresses issues",
            ),
            ("sonar.issue.ignore.allfile=a", "sonar.issue.ignore.allfile suppresses issues"),
            (
                "sonar.issue.enforce.multicriteria=e1",
                "sonar.issue.enforce.multicriteria suppresses issues",
            ),
            ("sonar.exclusions=**/*", "sonar.exclusions=**/* excludes every file"),
            ("sonar.exclusions=docs/**, **", "sonar.exclusions=** excludes every file"),
            ("sonar.coverage.exclusions=**", "sonar.coverage.exclusions=** excludes every file"),
            # Sonar reads a file by its extension: every one with a dot is every file it reads.
            ("sonar.cpd.exclusions=**/*.*", "sonar.cpd.exclusions=**/*.* excludes every file"),
            ("sonar.cpd.exclusions=**/*.md,**/*", "sonar.cpd.exclusions=**/* excludes every file"),
            ("sonar.test.exclusions = **", "sonar.test.exclusions=** excludes every file"),
            ("sonar.exclusions=*", ""),
            ("sonar.exclusions=_shared/kicad/**,_shared/fixtures/**", ""),
            ("sonar.exclusions=quality/tests/**", ""),
            ("sonar.exclusions=", ""),
            ("sonar.inclusions=**", ""),
        ):
            with self.subTest(line=line):
                fx.write(self.root, rel, fx.header() + f"sonar.projectKey=x\n{line}\n")
                found = [f for f in self.found() if "[sonar]" in f]
                wanted = f"{rel}: [sonar] {refused}: refused (no waiver)"
                self.assertEqual(found, [wanted] if refused else [])

    def test_a_step_that_forgives_itself_is_a_weakening(self) -> None:
        rel = ".github/workflows/extra.yml"

        def workflow(step: str) -> str:
            return (
                fx.header()
                + 'name: Extra\non: push\njobs:\n  build:\n    name: "🏗️ Build"\n'
                + "    runs-on: ubuntu-latest\n    timeout-minutes: 5\n    steps:\n"
                + '      - run: "true"\n'
                + step
            )

        for step, what in (
            ("      - run: make\n        continue-on-error: true\n", "build:1"),
            (
                "      - id: make\n        run: make\n        continue-on-error: true\n",
                "build:make",
            ),
            (
                "      - name: Make it\n        run: make\n        continue-on-error: true\n",
                "build:Make it",
            ),
            ("      - run: make\n        continue-on-error: 1\n", "build:1"),
            (  # the id, which a waiver can rely on, before the name
                "      - name: Make it\n        id: make\n        run: make\n"
                "        continue-on-error: true\n",
                "build:make",
            ),
        ):
            with self.subTest(step=step):
                fx.write(self.root, rel, workflow(step))
                self.weakened(f"[ci] continue-on-error:{rel}:{what}")
        fx.write(
            self.root, rel, workflow("      - run: make\n        continue-on-error: ${{ true }}\n")
        )
        self.assertFound(f"{rel} jobs.build step 1: [ci] continue-on-error is an expression")
        fx.write(self.root, rel, workflow("      - run: make\n        continue-on-error: false\n"))
        self.assertEqual(self.found(), [])
        fx.write(self.root, rel, workflow("      - make\n"))
        self.assertEqual([f for f in self.found() if "continue-on-error" in f], [])

    def test_a_glob_or_a_pattern_of_everything(self) -> None:
        for pattern, gitignore, everything in (
            ("*", True, True),
            ("*", False, False),
            ("**", False, True),
            ("**/*", False, True),
            ("/", True, True),
            ("", True, True),
            ("a/", True, False),
            ("*.md", True, False),
            ("?", True, False),
            ("**/?*", False, True),
        ):
            with self.subTest(pattern=pattern, gitignore=gitignore):
                self.assertIs(cq.glob_covers_all(pattern, gitignore), everything)

    def test_a_gitleaksignore_fingerprint_says_why(self) -> None:
        fx.write(self.root, ".gitleaksignore", "abc:file:rule:1\n")
        self.assertFound("every fingerprint has a comment line above it")
        fx.write(self.root, ".gitleaksignore", "# why\nabc:file:rule:1\n\n# why\nd:e:f:1\n")
        self.assertEqual(self.found(), [])
        fx.write(self.root, ".gitleaksignore", "# why\nabc:file:rule:1\nd:e:f:1\n")
        self.assertFound(".gitleaksignore:3: [gitleaks]")

    def test_an_osv_ignore_has_a_reason_and_a_near_end(self) -> None:
        fx.write(
            self.root,
            "osv-scanner.toml",
            '[[IgnoredVulns]]\nid = "GHSA-1"\nignoreUntil = 2027-12-01\nreason = "x"\n'
            '[[IgnoredVulns]]\nid = "GHSA-2"\nignoreUntil = 2026-12-01\n',
        )
        self.assertFound("more than 90 days ahead", "GHSA-2: [osv] needs a reason")

    def test_an_osv_ignore_ends(self) -> None:
        for until, needle in (
            ("2026-11-22", ""),
            ("2027-02-20", ""),
            ("2026-11-22T10:00:00Z", ""),
            ("2027-02-21", "ignoreUntil 2027-02-21 is more than 90 days ahead"),
            ("2026-11-21", "expired on 2026-11-21: fix the dependency"),
            ("2026-11-21T10:00:00Z", "expired on 2026-11-21"),
            ('"2026-12-01"', "needs an ignoreUntil date, at most 90 days ahead"),
            (None, "needs an ignoreUntil date, at most 90 days ahead"),
        ):
            with self.subTest(until=until):
                line = f"ignoreUntil = {until}\n" if until else ""
                body = f'[[IgnoredVulns]]\nid = "GHSA-1"\nreason = "x"\n{line}'
                fx.write(self.root, "osv-scanner.toml", body)
                found = self.found()
                self.assertEqual(len(found), 1 if needle else 0, found)
                if needle:
                    self.assertIn(needle, found[0])
        fx.write(self.root, "osv-scanner.toml", "= 3\n")
        self.assertFound("osv-scanner.toml: [osv] not valid TOML")

    def test_where_the_scan_runs_and_what_it_runs_is_the_kits(self) -> None:
        rel = "sonar-project.properties"
        head = fx.header() + "! one\nsonar.sources=a,\\\n  b\n"
        self.assertEqual(self.found(), [])
        for line, key in (
            ("sonar.scanner.autoconfig.enabled=false", ""),
            ("sonar.scanner.autoconfig.enabled : false ", ""),
            ("sonar.qualitygate.wait=true", ""),
            ("# sonar.host.url=https://evil.example", ""),
            ("sonar.projectDescription=see\\\n sonar.host.url=x", ""),
            ("sonar.scanner.autoconfig.enabled=true", "sonar.scanner.autoconfig.enabled"),
            ("sonar.scanner.javaExePath=./evil.sh", "sonar.scanner.javaExePath"),
            ("  sonar.scanner.javaExePath ./evil.sh", "sonar.scanner.javaExePath"),
            ("sonar.scanner.javaExePath: ./evil.sh", "sonar.scanner.javaExePath"),
            ("sonar.scan\\\n  ner.javaExePath=./evil.sh", "sonar.scanner.javaExePath"),
            ("\\u0073onar.scanner.javaExePath=./evil.sh", "sonar.scanner.javaExePath"),
            ("sonar\\.scanner.apiBaseUrl=https://evil.example", "sonar.scanner.apiBaseUrl"),
            ("sonar.host.url=https://evil.example", "sonar.host.url"),
            ("sonar.region=us", "sonar.region"),
            ("sonar.nodejs.executable=./evil.sh", "sonar.nodejs.executable"),
            ("sonar.working.directory=planted", "sonar.working.directory"),
            ("sonar.scanner.x", "sonar.scanner.x"),
        ):
            with self.subTest(line=line):
                fx.write(self.root, rel, f"{head}{line}\n")
                found = [f for f in self.found() if "[sonar]" in f]
                wanted = f"{rel}: [sonar] {key} is refused: the kit's job runs the scan"
                self.assertEqual(found, [wanted] if key else [])

    def test_a_waiver_is_for_the_file_it_names(self) -> None:
        self.append("pyproject.toml", '\n[tool.ruff.lint]\nignore = ["E501"]\n')
        waiver = (
            '\n[[waiver]]\ntool = "ruff"\nwhat = "ignore:E501"\nwhere = "{}"\n'
            'reason = "r"\ndecided = "d"\n'
        )
        whole = (self.root / cq.WAIVERS).read_text(encoding="utf-8")
        fx.write(self.root, cq.WAIVERS, whole + waiver.format("pyproject.toml"))
        self.assertEqual(self.found(), [])
        fx.write(self.root, cq.WAIVERS, whole + waiver.format("other/pyproject.toml"))
        self.assertFound("has no waiver", "matches nothing any more")
        self.assertEqual(len(self.found()), 2)

    def test_the_waivers_file_is_there_and_reads(self) -> None:
        whole = (self.root / cq.WAIVERS).read_text(encoding="utf-8")
        (self.root / cq.WAIVERS).unlink()
        self.assertEqual(len(self.found()), 1)
        self.assertFound(f"{cq.WAIVERS}: [waivers] missing")
        fx.write(self.root, cq.WAIVERS, whole + "= 3\n")
        self.assertFound(f"{cq.WAIVERS}: [waivers] not valid TOML")

    def test_dependabot_watches_the_actions(self) -> None:
        rel = ".github/dependabot.yml"
        self.edit(rel, "package-ecosystem: github-actions", "package-ecosystem: docker")
        self.assertFound(f"{rel}: [dependabot] no github-actions ecosystem")

    def test_a_pin_says_its_version_and_an_ignore_its_reason(self) -> None:
        sha = "a" * 40
        rel = ".github/workflows/own.yml"
        job = (
            'name: Own\non: push\npermissions: {{}}\njobs:\n  a:\n    name: "🔧 A"\n'
            "    runs-on: ubuntu-latest\n    timeout-minutes: 5\n    steps:\n{}"
        )
        for steps, needle in (
            (f"      - uses: o/a@{sha} # v1\n", ""),
            (f"      - uses: o/a@{sha}\n", "carries the version it pins in a comment"),
            (f"      - uses: o/a@{sha} #\n", "carries the version it pins in a comment"),
            (f"      - uses: o/a@{sha[:39]} # v1\n", "is not pinned by a full commit SHA"),
            ("      - uses: './x'\n      - uses: docker://x\n", ""),
            ("      # why\n      - run: x # zizmor: ignore[a]\n", ""),
            (
                "      - run: x # zizmor: ignore[a]\n",
                "has its reason in a comment on the line above",
            ),
        ):
            with self.subTest(steps=steps):
                fx.write(self.root, rel, fx.header() + job.format(steps))
                found = self.found()
                self.assertEqual(len(found), 1 if needle else 0, found)
                if needle:
                    self.assertIn(needle, found[0])

    def test_dependabot_ignores_the_kit_and_covers_every_manifest(self) -> None:
        self.edit(".github/dependabot.yml", '      - dependency-name: "kleidos-dev/.github*"\n', "")
        fx.write(self.root, "site/package.json", "{}\n")
        self.assertFound('github-actions must ignore "kleidos-dev/.github*"', "npm:/site weakens")

    # --- CI conventions and the kit workflows --------------------------------

    def test_ci_jobs_follow_the_conventions(self) -> None:
        fx.write(
            self.root,
            ".github/workflows/extra.yml",
            fx.header()
            + "name: Extra\non: push\njobs:\n  build:\n    name: Build\n"
            + "    runs-on: ubuntu-latest\n"
            + "    continue-on-error: true\n    steps:\n      - uses: actions/checkout@v7\n",
        )
        self.assertFound(
            "starts with an emoji",
            "needs a timeout-minutes",
            "actions/checkout@v7 is not pinned by a full commit SHA",
            "continue-on-error:.github/workflows/extra.yml:build weakens",
        )

    def test_every_kit_workflow_is_called(self) -> None:
        self.edit(".github/workflows/check.yml", "reusable-mypy.yml", "reusable-nothing.yml")
        self.assertFound("no workflow calls the kit's reusable-mypy.yml")
        fx.write(self.root, "sonar-project.properties", "# x\n")
        self.edit(".github/workflows/check.yml", "reusable-sonarcloud.yml", "reusable-none.yml")
        self.assertFound("no workflow calls the kit's reusable-sonarcloud.yml")

    def test_a_missing_profile_is_reported(self) -> None:
        fx.write(self.root, "web/app.ts", "// x\nexport const a = 1;\n")
        self.assertFound("the tree holds ts files but the ts profile is not adopted")

    def test_a_kit_call_that_may_not_run_is_caught(self) -> None:
        wf = ".github/workflows/check.yml"
        original = (self.root / wf).read_text(encoding="utf-8")
        gated = original.replace(
            "\n    uses: kleidos-dev/.github/.github/workflows/reusable-lint.yml",
            "\n    if: false\n    uses: kleidos-dev/.github/.github/workflows/reusable-lint.yml",
        )
        self.assertNotEqual(gated, original)
        (self.root / wf).write_text(gated, encoding="utf-8")
        self.assertFound("calls reusable-lint.yml but it carries the condition `if: false`")
        # A job that needs the gated one cannot run either.
        self.assertFound("calls reusable-mypy.yml but the job it needs, lint,")
        for triggers, why in (
            ("on:\n  workflow_dispatch:\n", "does not run on pull_request"),
            ("on:\n  push:\n    branches: [main]\n", "does not run on pull_request"),
            ("on:\n  pull_request:\n", "does not run on push"),
            (
                "on:\n  pull_request:\n    paths: [docs/**]\n  push:\n",
                "pull_request trigger has a paths filter",
            ),
            (
                "on:\n  pull_request:\n    branches: [dev]\n  push:\n",
                "trigger does not include main",
            ),
            (
                "on:\n  pull_request:\n    types: [opened]\n  push:\n",
                "leaves out synchronize, reopened",
            ),
            ("on:\n  pull_request:\n  push:\n    tags: ['*']\n", "runs on tags only"),
            (
                "on:\n  pull_request:\n  push:\n    branches: ['**', '!main']\n",
                "push trigger does not include main",
            ),
        ):
            head, _, rest = original.partition("\non:\n")
            body = rest[rest.index("\npermissions:") :]
            (self.root / wf).write_text(head + "\n" + triggers + body, encoding="utf-8")
            self.assertFound(why)
        (self.root / wf).write_text(original, encoding="utf-8")
        self.assertEqual(self.found(), [])

    def test_the_drift_caller_may_not_skip_the_schedule(self) -> None:
        wf = self.root / ".github/workflows/quality-drift.yml"
        text = wf.read_text(encoding="utf-8")
        at = text.index("    uses: kleidos-dev")
        wf.write_text(text[:at] + "    if: github.event_name != 'schedule'\n" + text[at:])
        self.assertFound("calls reusable-quality-drift.yml but it carries the condition")

    def test_the_lint_caller_skips_only_hooks_of_its_own(self) -> None:
        wf = self.root / ".github/workflows/check.yml"
        text = wf.read_text(encoding="utf-8")
        marker = "reusable-lint.yml@"
        at = text.index("\n", text.index(marker))
        wf.write_text(text[:at] + "\n    with:\n      skip: my-hook,ruff-check" + text[at:])
        self.assertFound("skip names the kit hook ruff-check")
        self.assertFalse(any("my-hook" in f for f in self.found()))

    def test_lint_skip_is_refused_from_the_kit_itself(self) -> None:
        kit = cq.DirKit(fx.CENTRAL)
        self.assertIn("ruff-check", cq.kit_block_hook_ids(kit))
        self.assertIn("gitleaks-mac", cq.kit_block_hook_ids(kit))
        self.assertEqual(
            cq.refused_skips("mine, gitleaks ,x", cq.kit_block_hook_ids(kit)), ["gitleaks"]
        )

    def test_pre_commit_globals_cannot_switch_the_kit_hooks_off(self) -> None:
        self.edit(".pre-commit-config.yaml", "repos:\n", "exclude: '^pkg/'\nrepos:\n")
        self.assertFound("exclude:^pkg/ weakens a kit rule")
        self.edit(".pre-commit-config.yaml", "exclude: '^pkg/'\n", "files: '^$'\n")
        self.assertFound("files:^$ weakens a kit rule")
        self.edit(".pre-commit-config.yaml", "files: '^$'\n", "default_stages: [manual]\n")
        self.assertFound("default_stages without pre-commit")
        self.edit(
            ".pre-commit-config.yaml",
            "default_stages: [manual]\n",
            "default_stages: [pre-commit, manual]\n",
        )
        self.assertEqual(self.found(), [])

    def test_only_kit_copies_live_in_the_kit_folder(self) -> None:
        fx.write(
            self.root,
            ".github/quality/osv-scanner.toml",
            "# x\n[[IgnoredVulns]]\nid = 'GHSA-0000-0000-0000'\n",
        )
        fx.write(self.root, ".github/quality/parked.py", "import os\nimport sys\n")
        self.assertFound(
            ".github/quality/osv-scanner.toml: [kit-dir]",
            ".github/quality/parked.py: [kit-dir]",
            "IgnoredVulns[0] GHSA-0000-0000-0000: [osv] needs a reason",
            ".github/quality/parked.py: [mypy] not checked by mypy",
        )

    def test_a_manifest_cannot_hide_a_file(self) -> None:
        import json

        fx.write(self.root, "other/hidden.py", "import os\n")
        path = self.root / cq.SOURCE_JSON
        record = json.loads(path.read_text(encoding="utf-8"))
        record["files"].append({"path": "other/hidden.py", "source_path": "x", "sha256": "0"})
        path.write_text(json.dumps(record), encoding="utf-8")
        self.assertFound(
            "records other/hidden.py, which is not a path the kit copies to",
            "other/hidden.py: [mypy] not checked by mypy",
        )
        record["files"].pop()
        path.write_text(json.dumps(record), encoding="utf-8")
        fx.write(
            self.root,
            cq.COMMIT_CHECK_SOURCE,
            json.dumps({"files": [{"path": "other/hidden.py"}]}),
        )
        self.assertFound(
            "records other/hidden.py: the commit-check manifest lists only",
            "other/hidden.py: [mypy] not checked by mypy",
        )

    def test_kit_copies_match_the_manifest(self) -> None:
        manifest = cq.DirKit(fx.CENTRAL).manifest()
        copies = {
            str(c["target"]): str(c["source"]) for c in manifest["copy"] if not c.get("requires")
        }
        self.assertEqual(copies, cq.KIT_COPIES)
        test_copy = [c for c in manifest["copy"] if c.get("requires")]
        self.assertEqual(
            [(c["target"].rsplit("/", 1)[1], c["source"]) for c in test_copy],
            [cq.KIT_TEST_COPY],
        )

    def test_python_version_and_dependabot_cooldown_are_required(self) -> None:
        (self.root / ".python-version").unlink()
        self.edit(".github/dependabot.yml", "    cooldown:\n      default-days: 7\n", "")
        self.assertFound(
            ".python-version: [python] missing",
            "github-actions /: needs a cooldown",
        )

    def test_a_license_sidecar_needs_a_waiver(self) -> None:
        fx.write(self.root, "logo.svg.license", "x\n")
        self.assertFound("sidecar:logo.svg.license weakens a kit rule")

    def test_cpp_runs_clang_tidy_in_a_job_of_its_own(self) -> None:
        fx.write(self.root, "src/a.cpp", "// x\nint a;\n")
        sync.write(self.root, commit=fx.FAKE_COMMIT)
        self.assertFound("the cpp profile runs clang-tidy")
        fx.write(
            self.root,
            ".github/workflows/tidy.yml",
            fx.header()
            + "name: Tidy\non:\n  pull_request:\njobs:\n  tidy:\n"
            + '    name: "🔎 clang-tidy"\n    runs-on: ubuntu-latest\n'
            + "    timeout-minutes: 5\n    steps:\n      - run: clang-tidy -p build src/a.cpp\n",
        )
        self.assertFalse(any("the cpp profile runs clang-tidy" in f for f in self.found()))
        self.edit(
            ".github/workflows/tidy.yml",
            "      - run: clang-tidy",
            "      - if: false\n        run: clang-tidy",
        )
        self.assertFound("the cpp profile runs clang-tidy")

    # --- suppressions in other languages -------------------------------------

    def test_nolint_and_eslint_disable_name_their_rule_and_reason(self) -> None:
        fx.write(self.root, "src/a.cpp", "int a; // NOLINT\nint b; // NOLINT(misc-x)\n")
        fx.write(self.root, "web/a.js", "// eslint-disable-next-line\nlet a;\n")
        self.assertFound(
            "a NOLINT names the check",
            "a NOLINT carries its reason",
            "an eslint-disable names its rule",
        )

    def test_a_copy_recorded_from_another_kit_file_is_caught(self) -> None:
        import json

        path = self.root / cq.SOURCE_JSON
        record = json.loads(path.read_text(encoding="utf-8"))
        for entry in record["files"]:
            if entry["path"] == ".github/quality/ruff.toml":
                entry["source_path"] = "quality/markdownlint/base.jsonc"
                data = (fx.CENTRAL / entry["source_path"]).read_bytes()
                (self.root / entry["path"]).write_bytes(data)
                entry["sha256"] = cq.sha256(data)
        path.write_text(json.dumps(record), encoding="utf-8")
        self.assertFound("but the kit copies quality/ruff/ruff.toml there")


class TypeScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fx.consumer(Path(self._tmp.name) / "repo")
        fx.write(self.root, "web/app.ts", "// x\nexport const a = 1;\n")
        wf = self.root / ".github/workflows/check.yml"
        wf.write_text(
            wf.read_text(encoding="utf-8")
            + "\n  eslint:\n"
            + '    name: "🔎 ESLint and tsc"\n'
            + "    needs: [lint, reuse]\n"
            + "    uses: kleidos-dev/.github/.github/workflows/reusable-eslint.yml@0 # q\n"
            + "    with:\n      working-directory: web\n"
            + "    permissions:\n      contents: read\n",
            encoding="utf-8",
        )
        sync.write(self.root, commit=fx.FAKE_COMMIT)
        fx.write(
            self.root,
            "web/eslint.config.js",
            "// x\nimport { kleidosTypeScript } from '../.github/quality/eslint.base.mjs';\n"
            "export default [];\n",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def found(self) -> list[str]:
        report = cq.run(self.root, kit=cq.DirKit(fx.CENTRAL), today=TODAY)
        return [f"{p.where}: [{p.rule}] {p.message}" for p in report.problems]

    def test_the_extends_chain_must_reach_the_kit_base(self) -> None:
        fx.write(self.root, "web/config/base.json", "{}\n")
        fx.write(self.root, "web/tsconfig.json", '{"extends": "./config/base.json"}\n')
        self.assertTrue(any("extends neither" in f for f in self.found()))
        fx.write(
            self.root,
            "web/config/base.json",
            '{"extends": "../../.github/quality/tsconfig.base.json"}\n',
        )
        self.assertFalse(any("extends neither" in f for f in self.found()))

    def test_a_flag_strict_turns_on_cannot_be_turned_off_silently(self) -> None:
        fx.write(
            self.root,
            "web/tsconfig.json",
            '{"extends": "../.github/quality/tsconfig.base.json",'
            ' "compilerOptions": {"strictNullChecks": false}}\n',
        )
        self.assertTrue(any("strictNullChecks weakens" in f for f in self.found()))

    def test_a_quoted_off_rule_is_a_weakening(self) -> None:
        fx.write(
            self.root, "web/tsconfig.json", '{"extends": "../.github/quality/tsconfig.base.json"}\n'
        )
        self.append_eslint('"no-console": "off", "eqeqeq": ["warn"], "max-len": 0,\n')
        found = self.found()
        for rule in ("no-console", "eqeqeq", "max-len"):
            self.assertTrue(any(f"{rule} weakens" in f for f in found), (rule, found))

    def test_the_ts_profile_calls_the_eslint_workflow(self) -> None:
        wf = self.root / ".github/workflows/check.yml"
        wf.write_text(
            wf.read_text(encoding="utf-8").replace("reusable-eslint.yml", "reusable-x.yml"),
            encoding="utf-8",
        )
        self.assertTrue(any("reusable-eslint.yml" in f for f in self.found()))

    def test_type_checking_off_and_ignored_sources_are_weakenings(self) -> None:
        fx.write(
            self.root, "web/tsconfig.json", '{"extends": "../.github/quality/tsconfig.base.json"}\n'
        )
        path = self.root / "web/eslint.config.js"
        path.write_text(
            path.read_text(encoding="utf-8")
            + "export const x = [{ ignores: ['dist/**', 'src/legacy/**'] },"
            + " tseslint.configs.disableTypeChecked];\n",
            encoding="utf-8",
        )
        found = self.found()
        self.assertTrue(any("disableTypeChecked weakens" in f for f in found), found)
        self.assertTrue(any("ignores:src/legacy/** weakens" in f for f in found), found)
        self.assertFalse(any("ignores:dist/**" in f for f in found), found)

    def append_eslint(self, text: str) -> None:
        path = self.root / "web/eslint.config.js"
        path.write_text(path.read_text(encoding="utf-8") + "// " + text, encoding="utf-8")


class HelpersTest(unittest.TestCase):
    def test_jsonc_reads_comments_and_trailing_commas(self) -> None:
        text = '{\n  // a comment\n  "a": "http://x", /* block */\n  "b": [1, 2,],\n}\n'
        self.assertEqual(cq.load_jsonc(text), {"a": "http://x", "b": [1, 2]})

    def test_a_block_that_opens_twice_is_an_error(self) -> None:
        text = "# >>> kleidos-quality x\n# >>> kleidos-quality x\n# <<< kleidos-quality x\n"
        with self.assertRaises(ValueError):
            cq.find_block(text, "x")

    def test_the_emoji_test_reads_the_first_character(self) -> None:
        self.assertTrue(cq.first_is_emoji("🧹 Lint"))
        self.assertFalse(cq.first_is_emoji("Lint"))


if __name__ == "__main__":
    unittest.main()
