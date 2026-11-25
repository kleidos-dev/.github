# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT
"""agent_docs.py: each planted defect in AGENTS.md or CLAUDE.md is a finding."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import kit_fixtures as fx
from kit_fixtures import agent_docs as ad

BLOCK = (fx.CENTRAL / "quality/agents/block.md").read_text(encoding="utf-8")
START = (
    "<!-- >>> kleidos-quality organization-rules (synced from kleidos-dev/.github"
    " quality/agents/block.md; do not edit) -->\n"
)
END = "<!-- <<< kleidos-quality organization-rules -->\n"


class AgentDocsTest(unittest.TestCase):
    """A repository that keeps the standard, then one defect at a time."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = fx.init(Path(self._tmp.name) / "repo")
        fx.write(self.root, "scripts/check.py", fx.header())
        self.agents(
            "## Commands\n\n```sh\npython3 scripts/check.py\n```\n\n"
            "See [the check](scripts/check.py) and `scripts/`.\n"
        )
        fx.write(self.root, "CLAUDE.md", fx.md_header() + "@AGENTS.md\n")
        fx.write(self.root, ".gitignore", fx.header() + "\nCLAUDE.local.md\n")
        self.record(BLOCK)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def agents(self, body: str, block: str = BLOCK, rel: str = "AGENTS.md") -> None:
        fx.write(
            self.root,
            rel,
            fx.md_header() + "# AGENTS.md\n\n" + body + "\n" + START + block + END,
        )

    def record(self, block: str) -> None:
        """SOURCE.json as the sync writes it, with the block's digest."""
        entry = {"id": "organization-rules", "path": "AGENTS.md", "sha256": ad.sha256(block)}
        fx.write(
            self.root,
            ".github/quality/SOURCE.json",
            json.dumps({"commit": fx.FAKE_COMMIT, "blocks": [entry]}),
        )

    def findings(self, check: str | None = None) -> list[str]:
        fx.commit(self.root)
        found = ad.check(ad.Repo(self.root))
        return [str(f) for f in found if check is None or f.check == check]

    def assert_finding(self, check: str, needle: str) -> None:
        found = self.findings(check)
        self.assertTrue(any(needle in f for f in found), found)

    # -- the clean case --------------------------------------------------------

    def test_a_repository_that_keeps_the_standard_passes(self) -> None:
        self.assertEqual(self.findings(), [])

    def test_the_command_line_exits_zero_and_one(self) -> None:
        fx.commit(self.root)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ad.main(["--repo", str(self.root)]), 0)
        self.assertIn("0 error(s)", out.getvalue())
        (self.root / "CLAUDE.md").unlink()
        fx.commit(self.root)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ad.main(["--repo", str(self.root), "--github"]), 1)
        self.assertIn("::error file=CLAUDE.md,title=Agent docs (files)::", out.getvalue())

    def test_a_directory_outside_git_is_a_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ad.main(["--repo", tmp]), 2)

    # -- files -----------------------------------------------------------------

    def test_a_missing_root_file_is_found(self) -> None:
        (self.root / "CLAUDE.md").unlink()
        self.assert_finding("files", "CLAUDE.md: [files] missing at the root")

    def test_a_nested_agents_md_needs_its_claude_md(self) -> None:
        fx.write(self.root, "src/AGENTS.md", fx.md_header() + "# src\n\nRules.\n")
        self.assert_finding("files", "src/AGENTS.md: [files] has no CLAUDE.md beside it")
        fx.write(self.root, "src/CLAUDE.md", fx.md_header() + "@AGENTS.md\n")
        self.assertEqual(self.findings(), [])

    def test_a_symbolic_link_or_an_unreadable_file_is_found(self) -> None:
        (self.root / "CLAUDE.md").unlink()
        (self.root / "CLAUDE.md").symlink_to("AGENTS.md")
        self.assert_finding("files", "CLAUDE.md: [files] is a symbolic link")
        (self.root / "CLAUDE.md").unlink()
        (self.root / "CLAUDE.md").write_bytes(b"\xff\xfe@AGENTS.md\n")
        self.assert_finding("files", "CLAUDE.md: [files] cannot be read as UTF-8 text")

    def test_a_plugin_or_fixture_copy_is_content_not_rules(self) -> None:
        fx.write(self.root, "plugins/x/AGENTS.md", "# A template\n")
        fx.write(self.root, "tests/fixtures/CLAUDE.md", "No import here.\n")
        self.assertEqual(self.findings(), [])

    # -- import ----------------------------------------------------------------

    def test_claude_md_opens_with_the_import(self) -> None:
        fx.write(self.root, "CLAUDE.md", fx.md_header() + "# Claude\n\n@AGENTS.md\n")
        self.assert_finding("import", "CLAUDE.md: [import] does not open with the line @AGENTS.md")

    def test_an_import_in_a_code_span_is_not_the_import(self) -> None:
        fx.write(self.root, "CLAUDE.md", fx.md_header() + "`@AGENTS.md`\n")
        self.assert_finding("import", "does not open with the line @AGENTS.md")

    def test_a_short_claude_section_under_the_import_is_allowed(self) -> None:
        fx.write(
            self.root,
            "CLAUDE.md",
            fx.md_header() + "@AGENTS.md\n\n## Claude Code\n\nDelegate tests to `test-writer`.\n",
        )
        self.assertEqual(self.findings(), [])

    # -- at --------------------------------------------------------------------

    def test_a_bare_at_name_outside_code_is_found(self) -> None:
        self.agents("Ask @owner before a release.\n")
        self.assert_finding("at", "AGENTS.md:8: [at] @owner outside code")

    def test_an_at_name_in_code_or_an_address_is_not(self) -> None:
        self.agents(
            "Write `@types/node` in code, mail mail@kleidos.dev.\n\n```\n@AGENTS.md\n```\n"
            "<!-- @hidden in a comment -->\n"
        )
        self.assertEqual(self.findings(), [])

    def test_a_second_import_line_in_claude_md_is_found(self) -> None:
        fx.write(self.root, "CLAUDE.md", fx.md_header() + "@AGENTS.md\n\n@docs/more.md\n")
        self.assert_finding("at", "CLAUDE.md:8: [at] @docs/more.md outside code")

    # -- local and single --------------------------------------------------------

    def test_claude_local_md_must_be_ignored(self) -> None:
        fx.write(self.root, ".gitignore", fx.header() + "\n.venv/\n")
        self.assert_finding("local", ".gitignore: [local] does not ignore CLAUDE.local.md")

    def test_claude_local_md_must_not_be_tracked(self) -> None:
        fx.write(self.root, "CLAUDE.local.md", "Mine.\n")
        fx.git(self.root, "add", "-f", "CLAUDE.local.md")
        self.assert_finding("local", "CLAUDE.local.md: [local] is tracked")

    def test_a_nested_claude_local_md_is_tracked_or_not_ignored(self) -> None:
        fx.write(self.root, "src/AGENTS.md", fx.md_header() + "# src\n\nRules.\n")
        fx.write(self.root, "src/CLAUDE.md", fx.md_header() + "@AGENTS.md\n")
        fx.write(self.root, ".gitignore", fx.header() + "\n/CLAUDE.local.md\n")
        self.assert_finding("local", ".gitignore: [local] does not ignore src/CLAUDE.local.md")
        fx.write(self.root, "src/CLAUDE.local.md", "Mine.\n")
        fx.git(self.root, "add", "-f", "src/CLAUDE.local.md")
        self.assert_finding("local", "src/CLAUDE.local.md: [local] is tracked")

    def test_a_nested_rules_file_for_one_tool_is_found(self) -> None:
        fx.write(self.root, "src/AGENTS.override.md", "Rules.\n")
        fx.write(self.root, "web/.cursor/rules/a.mdc", "Rules.\n")
        fx.write(self.root, ".claude/rules/b.md", "Rules.\n")
        found = self.findings("single")
        for where in ("src/AGENTS.override.md:", "web/.cursor/rules/:", ".claude/rules/:"):
            self.assertTrue(any(f.startswith(where) for f in found), (where, found))

    def test_a_rules_file_for_one_tool_is_found(self) -> None:
        fx.write(self.root, "GEMINI.md", "Rules.\n")
        fx.write(self.root, ".cursor/rules/a.mdc", "Rules.\n")
        found = self.findings("single")
        self.assertTrue(any(f.startswith("GEMINI.md:") for f in found), found)
        self.assertTrue(any(f.startswith(".cursor/rules/:") for f in found), found)

    # -- size --------------------------------------------------------------------

    def test_a_root_file_over_the_target_warns_and_still_passes(self) -> None:
        self.agents("- " + "x" * (ad.TARGET_BYTES + 100) + "\n")
        fx.commit(self.root)
        found = ad.check(ad.Repo(self.root))
        self.assertEqual([f.check for f in found], ["size"])
        self.assertTrue(found[0].warning)

    def test_a_root_file_over_the_limit_fails(self) -> None:
        self.agents("- " + "x" * (ad.HARD_BYTES + 100) + "\n")
        self.assert_finding("size", "AGENTS.md: [size] is ")

    def test_the_root_and_a_nested_file_share_the_limit(self) -> None:
        self.agents("- " + "x" * (ad.TARGET_BYTES - 2000) + "\n")
        fx.write(
            self.root, "src/AGENTS.md", fx.md_header() + "- " + "y" * (ad.HARD_BYTES // 2) + "\n"
        )
        fx.write(self.root, "src/CLAUDE.md", fx.md_header() + "@AGENTS.md\n")
        self.assert_finding("size", "src/AGENTS.md: [size] with AGENTS.md is ")

    def test_every_level_of_a_nested_chain_counts(self) -> None:
        third = ad.HARD_BYTES // 3 + 200
        self.agents("- " + "x" * (third - 2000) + "\n")
        for folder in ("src", "src/cli"):
            fx.write(self.root, f"{folder}/AGENTS.md", fx.md_header() + "- " + "y" * third + "\n")
            fx.write(self.root, f"{folder}/CLAUDE.md", fx.md_header() + "@AGENTS.md\n")
        found = self.findings("size")
        self.assertEqual(len(found), 1, found)
        self.assertIn("src/cli/AGENTS.md: [size] with AGENTS.md, src/AGENTS.md is ", found[0])

    def test_code_under_the_import_counts_toward_its_size(self) -> None:
        fence = "```sh\n" + "\n".join(f"run step {n} " + "z" * 60 for n in range(80)) + "\n```\n"
        fx.write(self.root, "CLAUDE.md", fx.md_header() + "@AGENTS.md\n\n" + fence)
        self.assert_finding("size", "CLAUDE.md: [size] holds ")

    def test_claude_md_holds_little_of_its_own(self) -> None:
        own = "\n".join(f"- Claude only, line {n}: " + "z" * 60 for n in range(80))
        fx.write(self.root, "CLAUDE.md", fx.md_header() + "@AGENTS.md\n\n" + own + "\n")
        self.assert_finding("size", "CLAUDE.md: [size] holds ")

    # -- paths -------------------------------------------------------------------

    def test_a_named_script_that_does_not_exist_is_found(self) -> None:
        self.agents("```sh\npython3 scripts/gone.py --write\n```\n")
        self.assert_finding("paths", "names `scripts/gone.py`, which is not in the tree")

    def test_a_path_in_a_code_span_that_does_not_exist_is_found(self) -> None:
        self.agents("Edit `scripts/missing/` first.\n")
        self.assert_finding("paths", "names `scripts/missing/`")

    def test_other_repositories_unknown_folders_and_ignored_paths_are_skipped(self) -> None:
        fx.write(self.root, ".gitignore", fx.header() + "\nCLAUDE.local.md\nscripts/local.txt\n")
        self.agents(
            "`kleidos-dev/.github/docs/quality.md`, `elsewhere/thing.py`, "
            "`scripts/local.txt`, `./scripts/check.py`, 3/4 of `a/b`.\n"
        )
        self.assertEqual(self.findings(), [])

    def test_a_nested_file_resolves_paths_from_its_own_folder(self) -> None:
        fx.write(self.root, "src/tool/run.py", fx.header())
        fx.write(self.root, "src/AGENTS.md", fx.md_header() + "Run `tool/run.py`.\n")
        fx.write(self.root, "src/CLAUDE.md", fx.md_header() + "@AGENTS.md\n")
        self.assertEqual(self.findings(), [])

    # -- links -------------------------------------------------------------------

    def test_a_relative_link_that_does_not_resolve_is_found(self) -> None:
        self.agents("See [the guide](docs/guide.md#start).\n")
        self.assert_finding("links", "links to docs/guide.md, which does not exist")

    def test_urls_anchors_and_resolving_links_pass(self) -> None:
        self.agents(
            "See <https://kleidos.dev>, [the site](https://kleidos.dev), [here](#commands)"
            " and [the check](./scripts/check.py).\n"
        )
        self.assertEqual(self.findings(), [])

    # -- kit ---------------------------------------------------------------------

    def test_an_unnamed_skill_or_subagent_is_found(self) -> None:
        fx.write(self.root, ".claude/skills/board-specs/SKILL.md", "---\nname: x\n---\n")
        fx.write(self.root, ".claude/agents/reviewer.md", "---\nname: y\n---\n")
        found = self.findings("kit")
        self.assertTrue(any("the skill `board-specs`" in f for f in found), found)
        self.assertTrue(any("the subagent `reviewer`" in f for f in found), found)
        self.agents("Load `board-specs` for boards; `reviewer` reviews.\n")
        self.assertEqual(self.findings(), [])

    # -- rules: a repository that runs the kit links the organization rules ------

    def run_form(self, body: str) -> None:
        fx.write(self.root, "AGENTS.md", fx.md_header() + "# AGENTS.md\n\n" + body)
        fx.write(self.root, ".github/quality/SOURCE.json", '{"schema": "kleidos.vendored-copy/1"}')

    def test_the_link_is_enough(self) -> None:
        self.run_form(f"## Organization rules\n\nSee [them]({ad.RULES_URL}).\n")
        self.assertEqual(self.findings(), [])
        self.assertTrue(ad.runs_the_kit(ad.Repo(self.root)))

    def test_without_the_link_it_is_found(self) -> None:
        for body in ("Nothing.\n", f"`{ad.RULES_URL}`\n", f"<!-- [x]({ad.RULES_URL}) -->\n"):
            self.run_form(body)
            self.assert_finding("rules", "links the organization rules nowhere")

    def test_a_block_left_behind_is_found(self) -> None:
        self.run_form(f"[them]({ad.RULES_URL})\n\n{START}x\n{END}")
        self.assert_finding("rules", "AGENTS.md:10: [rules] the organization rules are a link now")
        self.run_form(f"[them]({ad.RULES_URL})\n\n{START.replace('organization-rules', 'own')}x\n")
        self.assertEqual(self.findings("rules"), [])

    def test_the_form_is_read_from_the_record(self) -> None:
        for body in ("[]", "{", '{"commit": "self"}'):
            fx.write(self.root, ".github/quality/SOURCE.json", body)
            self.assertFalse(ad.runs_the_kit(ad.Repo(self.root)), body)
        (self.root / ".github/quality/SOURCE.json").unlink()
        self.assertFalse(ad.runs_the_kit(ad.Repo(self.root)))

    # -- block -------------------------------------------------------------------

    def test_a_missing_block_is_found(self) -> None:
        fx.write(self.root, "AGENTS.md", fx.md_header() + "# AGENTS.md\n\nRules.\n")
        self.assert_finding("block", "AGENTS.md: [block] holds no organization-rules block")

    def test_an_edited_block_is_found(self) -> None:
        edited = BLOCK.replace("Never `--no-verify`", "Rarely `--no-verify`")
        self.assertNotEqual(edited, BLOCK)
        self.agents("Rules.\n", block=edited)
        self.assert_finding("block", "the organization-rules block differs from the kit's")

    def test_a_hand_written_section_beside_the_block_is_found(self) -> None:
        self.agents("## Organization rules\n\nAn old copy.\n")
        self.assert_finding("block", "AGENTS.md:8: [block] an Organization rules section outside")

    def test_a_numbered_hand_written_section_is_found_too(self) -> None:
        self.agents("## 5. Organization rules\n\nAn old copy.\n")
        self.assert_finding("block", "an Organization rules section outside the managed block")

    def test_markers_that_do_not_pair_are_found(self) -> None:
        fx.write(self.root, "AGENTS.md", fx.md_header() + "# AGENTS.md\n\n" + START + BLOCK + START)
        self.assert_finding("block", "the organization-rules markers do not pair")

    def test_in_the_kit_home_the_block_is_the_kit_source(self) -> None:
        fx.write(self.root, ".github/quality/SOURCE.json", json.dumps({"commit": "self"}))
        fx.write(self.root, "quality/agents/block.md", BLOCK)
        self.assertEqual(self.findings(), [])
        fx.write(self.root, "quality/agents/block.md", BLOCK + "- A new rule.\n")
        self.assert_finding("block", "differs from the kit's")

    def test_what_is_no_work_tree_is_said(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for path in (Path(tmp), Path(tmp) / "none"):
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    self.assertEqual(ad.main(["--repo", str(path)]), 2)
                self.assertEqual(err.getvalue(), f"agent-docs: {path} is not a git work tree\n")

    def test_the_kit_home_passes(self) -> None:
        self.assertEqual(ad.check(ad.Repo(fx.CENTRAL)), [])


if __name__ == "__main__":
    unittest.main()
