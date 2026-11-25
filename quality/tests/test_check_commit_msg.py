# SPDX-FileCopyrightText: 2026 José M. Requena Plens
# SPDX-License-Identifier: MIT

"""Offline tests for check_commit_msg.py: every rule, the exemptions, the
hook and range modes, the comment rendering and the sticky-comment decision.

They need git on PATH for the hook and range tests, use no network, and
ignore the user's git config. Run: python3 -m unittest discover -s <this dir>.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

import kit_fixtures as fx
from kit_fixtures import check_commit_msg as ccm

ENV = dict(
    os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_NOSYSTEM="1"
)
LONG = "word " * 15  # 75 columns
GOOD = (
    "Add the board index\n\n"
    "The index lists every board with its folder and the date it was\n"
    "last measured.\n"
)


def rules(text: str) -> list[str]:
    return [p["rule"] for p in ccm.check_message(text)]


def errors(text: str) -> list[str]:
    return [p["rule"] for p in ccm.check_message(text) if p["severity"] == ccm.ERROR]


class SubjectRulesTest(unittest.TestCase):
    def test_good_message_passes(self) -> None:
        self.assertEqual(rules(GOOD), [])

    def test_empty_subject(self) -> None:
        self.assertEqual(errors(""), ["subject-empty"])
        self.assertEqual(errors("   \n\nbody"), ["subject-empty"])

    def test_subject_over_72_is_an_error(self) -> None:
        subject = "Add " + "x" * 69  # 73 columns
        self.assertIn("subject-max-length", errors(subject))

    def test_subject_of_72_passes_with_a_warning(self) -> None:
        subject = "Add " + "x" * 68  # 72 columns
        self.assertEqual(errors(subject), [])
        self.assertEqual(rules(subject), ["subject-soft-length"])

    def test_subject_of_50_has_no_warning(self) -> None:
        self.assertEqual(rules("Add " + "x" * 46), [])

    def test_trailing_period(self) -> None:
        self.assertEqual(errors("Add the board index."), ["subject-trailing-period"])

    def test_ellipsis_is_not_a_period(self) -> None:
        self.assertEqual(errors("Add the board index..."), [])

    def test_not_imperative(self) -> None:
        for subject in (
            "Added the index",
            "Adds the index",
            "Fixed a typo",
            "fixes a typo",
            "Updating docs",
            "Bumped the pin",
        ):
            self.assertIn("subject-imperative", errors(subject), subject)

    def test_a_merge_subject_is_gits_own(self) -> None:
        long = "x" * 80
        whats = ["branch", "branches", "remote-tracking branch", "pull request", "tag", "commit"]
        for what in whats:
            self.assertEqual(rules(f"Merge {what} {long}."), [], what)
            self.assertNotEqual(rules(f"Merge {what}{long}."), [], what)
        self.assertNotEqual(rules(f"Re-Merge branch {long}."), [])
        self.assertNotEqual(rules(f"Merge it {long}"), [])
        self.assertEqual(rules(f'Revert "{long}"'), [])
        self.assertNotEqual(rules(f'Re-Revert "{long}"'), [])

    def test_what_each_rule_says_to_do(self) -> None:
        hints = {
            "subject-empty": "write a one-line summary of the change",
            "subject-max-length": "shorten the subject to 72 columns or fewer",
            "subject-soft-length": "aim for 50 columns or fewer",
            "subject-trailing-period": "drop the final period",
            "subject-imperative": "start with an imperative verb: Add, Fix, Update, Remove",
            "body-leading-blank": "leave line 2 empty",
            "body-max-length": "wrap the body at 72 columns",
            "attribution": "remove the attribution line",
        }
        self.assertEqual(hints, ccm.HINTS)

    def test_every_verb_of_the_rule_in_every_form(self) -> None:
        bases = "add fix update remove change implement refactor move rename create delete"
        for base in [*bases.split(), "improve", "bump"]:
            stem = base.removesuffix("e")
            past = f"{stem}ed"
            third = f"{base}es" if base == "fix" else f"{base}s"
            for verb in (past, third, f"{stem}ing"):
                for subject in (f"{verb} it", f"{verb.title()} it", f"amend! fixup! {verb} it"):
                    self.assertIn("subject-imperative", errors(subject), subject)
                self.assertEqual(errors(f"{verb.title()}x it"), [])
            self.assertEqual(errors(f"{base.title()} it"), [])

    def test_imperative_passes(self) -> None:
        for subject in ("Add the index", "Fix a typo", "Update the docs", "Fixate the clock"):
            self.assertEqual(errors(subject), [], subject)

    def test_autosquash_prefix_is_ignored(self) -> None:
        self.assertEqual(errors("fixup! Add the board index"), [])
        self.assertIn("subject-imperative", errors("squash! Added the board index"))

    def test_autosquash_prefix_does_not_count_toward_the_length(self) -> None:
        target = "Add " + "x" * 66  # 70 columns
        self.assertEqual(errors("fixup! " + target), [])
        self.assertEqual(errors("amend! squash! " + target), [])
        self.assertIn("subject-max-length", errors("fixup! " + target + "xxx"))

    def test_revert_subject_has_no_length_limit(self) -> None:
        self.assertEqual(rules('Revert "' + "Add " + "x" * 70 + '"'), [])

    def test_merge_commit_message_is_skipped(self) -> None:
        self.assertEqual(
            rules(
                "Merge pull request #12 from example/branch-with-a-long-name-that-goes-on-and-on."
            ),
            [],
        )


class BodyRulesTest(unittest.TestCase):
    def test_line_two_must_be_blank(self) -> None:
        self.assertEqual(errors("Add the index\nbody right below"), ["body-leading-blank"])

    def test_body_line_over_72(self) -> None:
        probs = ccm.check_message("Add the index\n\nshort line\n" + LONG + "\n")
        self.assertEqual([(p["rule"], p["line"]) for p in probs], [("body-max-length", 4)])
        self.assertIn("75 columns", probs[0]["message"])

    def test_body_line_of_72_passes(self) -> None:
        self.assertEqual(rules("Add the index\n\n" + "a " * 35 + "bc"), [])

    def test_one_line_paragraph_fails(self) -> None:
        para = (
            "This paragraph was written one line per paragraph, as Markdown files are,"
            " and it runs well past the limit."
        )
        self.assertEqual(errors("Add the index\n\n" + para), ["body-max-length"])

    def test_url_line_is_exempt(self) -> None:
        self.assertEqual(
            rules(
                "Add the index\n\nSee https://example.com/"
                + "a" * 80
                + " for the rest of the story."
            ),
            [],
        )

    def test_indented_line_is_exempt(self) -> None:
        self.assertEqual(rules("Add the index\n\n    " + LONG + "\n\t" + LONG), [])

    def test_fenced_block_is_exempt(self) -> None:
        msg = "Add the index\n\n```\n" + LONG + "\n```\n\n~~~sh\n" + LONG + "\n~~~\n"
        self.assertEqual(rules(msg), [])

    def test_line_after_a_fence_is_checked_again(self) -> None:
        msg = "Add the index\n\n```\n" + LONG + "\n```\n" + LONG
        self.assertEqual(errors(msg), ["body-max-length"])

    def test_table_line_is_exempt(self) -> None:
        self.assertEqual(rules("Add the index\n\n| a | " + LONG + " |"), [])

    def test_one_long_word_is_exempt(self) -> None:
        self.assertEqual(rules("Add the index\n\nsrc/" + "very_long_path/" * 6 + "file.cpp"), [])

    def test_trailers_at_the_end_are_exempt(self) -> None:
        msg = (
            "Add the index\n\nBody.\n\nReviewed-by: Example Person <person@example.com> "
            + "x" * 60
            + "\nRefs: #12"
        )
        self.assertEqual(rules(msg), [])

    def test_trailer_continuation_line_is_exempt(self) -> None:
        msg = "Add the index\n\nBody.\n\nNote-to-self: first\n  " + LONG
        self.assertEqual(rules(msg), [])

    def test_trailer_like_line_inside_the_body_is_checked(self) -> None:
        msg = "Add the index\n\nKey: " + LONG + "\n\nLast paragraph is prose."
        self.assertEqual(errors(msg), ["body-max-length"])

    def test_mixed_last_paragraph_is_not_a_trailer_block(self) -> None:
        msg = "Add the index\n\nBody.\n\nSigned-off-by: A <a@example.com>\n" + LONG
        self.assertEqual(errors(msg), ["body-max-length"])


class AttributionTest(unittest.TestCase):
    def test_assistant_co_author(self) -> None:
        msg = "Add the index\n\nBody.\n\nCo-Authored-By: Claude <noreply@example.com>"
        probs = [p for p in ccm.check_message(msg) if p["rule"] == "attribution"]
        self.assertEqual(len(probs), 1)
        self.assertEqual(probs[0]["line"], 5)

    def test_generated_with_footer(self) -> None:
        self.assertIn("attribution", errors("Add the index\n\nGenerated with Claude Code"))
        self.assertIn("attribution", errors("Add the index\n\nGenerated by an AI model"))

    def test_who_is_named_as_an_author_or_a_maker(self) -> None:
        for name in [
            "claude",
            "anthropic",
            "copilot",
            "chatgpt",
            "openai",
            "gemini",
            "cursor",
            "assistant",
            "bot",
        ]:
            line = f"Co-authored-by: Some {name.title()} <x@example.org>"
            self.assertIn("attribution", errors(f"Add it\n\nText.\n{line}"), line)
            line = f"Co-authored-by: Some {name}x <x@example.org>"
            self.assertNotIn("attribution", errors(f"Add it\n\nText.\n{line}"), line)
        for name in ("claude", "copilot", "chatgpt", "ai", "assistant"):
            for word in ("with", "by"):
                self.assertIn("attribution", errors(f"Add it\n\nGenerated {word} {name}."), name)
                line = f"Generated {word} an {name}x and a x{name}"
                self.assertNotIn("attribution", errors(f"Add it\n\n{line}"), line)
        for link in ("claude.ai/code/session_1", "chatgpt.com/share/1", "chat.openai.com/chat"):
            self.assertIn("attribution", errors(f"Add it\n\nhttps://{link}"), link)
            self.assertNotIn("attribution", errors(f"Add it\n\nhttps://x{link}"), link)
            self.assertNotIn("attribution", errors(f"Add it\n\n{link}"), link)
        self.assertNotIn("attribution", errors("Add it\n\nhttps://claude.ai/docs"))

    def test_generated_by_a_tool_is_not_attribution(self) -> None:
        for line in (
            "Generated with data from Dubai and Shanghai",
            "Generated by the board script",
        ):
            self.assertNotIn("attribution", errors("Add the index\n\n" + line), line)

    def test_robot_emoji(self) -> None:
        self.assertIn("attribution", errors("Add the index\n\n\U0001f916 made this"))

    def test_human_co_author_is_allowed(self) -> None:
        self.assertEqual(
            rules("Add the index\n\nCo-authored-by: Example Person <person@example.com>"), []
        )


class CleanMessageTest(unittest.TestCase):
    def test_comments_and_scissors_are_dropped(self) -> None:
        raw = (
            "\n# leading comment\nAdd the index\n\nBody.\n# Please enter the message\n"
            "# ------------------------ >8 ------------------------\ndiff --git a b\n" + LONG
        )
        self.assertEqual(ccm.clean_message(raw), "Add the index\n\nBody.")

    def test_custom_comment_char(self) -> None:
        self.assertEqual(
            ccm.clean_message("Add the index\n; comment\n# kept", ";"), "Add the index\n# kept"
        )

    def test_crlf(self) -> None:
        self.assertEqual(
            ccm.clean_message("Add the index\r\n\r\nBody.\r\n"), "Add the index\n\nBody."
        )


class FormatTest(unittest.TestCase):
    def test_stable_line_format(self) -> None:
        p = ccm.check_message("Add the index\n\n" + LONG)[0]
        self.assertEqual(
            ccm.format_problem("abc123", p),
            "abc123:3: error: body-max-length: line is 75 columns; the limit is 72"
            " -- wrap the body at 72 columns",
        )


@unittest.skipIf(shutil.which("git") is None, "git is not installed")
class GitModesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        self._env = dict(os.environ)
        os.environ.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
        self.git("init", "-q", "-b", "main")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "user.name", "Example Maintainer")
        self.git("config", "user.email", "maintainer@example.com")
        self.commit("Add the first file")
        self.base = self.rev("HEAD")

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)
        self.tmp.cleanup()

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.repo, env=ENV, check=True, capture_output=True, text=True
        ).stdout

    def rev(self, name: str) -> str:
        return self.git("rev-parse", name).strip()

    def commit(self, message: str, name: str = "f.txt") -> None:
        with open(os.path.join(self.repo, name), "a", encoding="utf-8") as fh:
            fh.write(message + "\n")
        self.git("add", name)
        self.git("commit", "-q", "--cleanup=verbatim", "-m", message)

    def run_main(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ccm.main(["-C", self.repo, *args])
        return code, out.getvalue(), err.getvalue()

    def test_hook_mode_passes_and_fails(self) -> None:
        path = os.path.join(self.repo, "MSG")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(GOOD + "# Please enter the commit message\n")
        self.assertEqual(self.run_main(path)[0], 0)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("Added the index.\n\n" + LONG + "\n")
        code, out, err = self.run_main(path)
        self.assertEqual(code, 1)
        self.assertEqual(len(out.strip().split("\n")), 3, out)
        self.assertIn(f"{path}:3: error: body-max-length", out)
        self.assertIn("git commit -e -F", err)

    def test_hook_mode_warning_only_exits_zero(self) -> None:
        path = os.path.join(self.repo, "MSG")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("Add " + "x" * 60 + "\n")
        code, out, _ = self.run_main(path)
        self.assertEqual(code, 0)
        self.assertIn("warning: subject-soft-length", out)

    def test_hook_mode_empty_message_is_left_to_git(self) -> None:
        path = os.path.join(self.repo, "MSG")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# only a comment\n")
        self.assertEqual(self.run_main(path)[0], 0)

    def test_range_mode_checks_commits_and_skips_merges(self) -> None:
        self.git("checkout", "-q", "-b", "topic")
        self.commit("Add the second file\n\n" + LONG, "g.txt")
        bad = self.rev("HEAD")
        self.git("checkout", "-q", "main")
        self.commit("Add the third file", "h.txt")
        self.git("checkout", "-q", "topic")
        long_merge = (
            "Merge branch 'main' into topic, and this merge subject is far longer"
            " than seventy-two columns."
        )
        self.git("merge", "-q", "--no-ff", "-m", long_merge, "main")
        self.commit("Fix the second file", "g.txt")
        out_json = os.path.join(self.repo, "result.json")
        code, out, err = self.run_main(
            "--range",
            self.base + "..HEAD",
            "--json",
            out_json,
            "--pr",
            "7",
            "--head-sha",
            self.rev("HEAD"),
        )
        self.assertEqual(code, 1)
        with open(out_json, encoding="utf-8") as fh:
            result = json.load(fh)
        self.assertEqual(result["checked"], 3)
        self.assertEqual(result["skipped_merges"], 1)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["pr"], 7)
        self.assertEqual([c["sha"] for c in result["commits"]], [bad])
        self.assertEqual(
            out.strip(),
            f"{bad[:12]}:3: error: body-max-length: line is 75 columns; the limit is 72"
            " -- wrap the body at 72 columns",
        )
        self.assertIn("3 commit(s) checked, 1 merge(s) skipped", err)

    def test_range_mode_clean(self) -> None:
        self.commit("Add the second file")
        code, out, _ = self.run_main("--range", self.base + "..HEAD", "--json", "-")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["errors"], 0)

    def test_range_mode_bad_revision(self) -> None:
        self.assertEqual(self.run_main("--range", "nosuchref..HEAD")[0], 2)


def result_with(
    problems: bool = True,
    pr: int | None = 7,
    head: str = "a" * 40,
    subject: str = "Added the index.",
) -> ccm.Result:
    commits: list[dict[str, Any]] = []
    errors_ = 0
    if problems:
        probs = ccm.check_message(subject + "\n\n" + LONG)
        errors_ = sum(1 for p in probs if p["severity"] == ccm.ERROR)
        commits.append({"sha": "b" * 40, "subject": subject, "problems": probs})
    return {
        "range": "x..y",
        "checked": 1,
        "skipped_merges": 0,
        "errors": errors_,
        "warnings": 0,
        "commits": commits,
        "pr": pr,
        "head_sha": head,
    }


class RenderTest(unittest.TestCase):
    def test_failure_table(self) -> None:
        body = ccm.render(result_with())
        self.assertTrue(body.startswith(ccm.MARKER + "\n"))
        self.assertIn("### Commit messages: 3 problems in 1 commit", body)
        self.assertIn("| Commit | Subject | Line | Rule | Fix |", body)
        self.assertIn(
            "| `bbbbbbb` | `Added the index.` | 3 | `body-max-length` |"
            " Line is 75 columns; the limit is 72. Wrap the body at 72 columns. |",
            body,
        )
        self.assertIn("`subject-imperative`", body)
        self.assertIn("git rebase -i", body)
        self.assertIn("git push --force-with-lease", body)
        self.assertIn("on the branch of your own pull request and nowhere else", body)
        self.assertIn("plain `--force` never is", body)

    def test_warnings_stay_out_of_the_table(self) -> None:
        res = result_with(subject="Add " + "x" * 60)
        self.assertEqual(ccm.render(res).count("subject-soft-length"), 0)

    def test_resolved_note(self) -> None:
        body = ccm.render(result_with(problems=False))
        self.assertTrue(body.startswith(ccm.MARKER))
        self.assertIn("all pass", body)
        self.assertIn("`aaaaaaa`", body)

    def test_untrusted_subject_is_neutralized(self) -> None:
        res = result_with(subject="Added @someone | <img src=x> `tick`\nsecond line")
        body = ccm.render(res)
        row = [ln for ln in body.split("\n") if ln.startswith("| `bbbbbbb`")][0]
        self.assertNotIn("`tick`", row)
        self.assertIn("\\|", row)
        self.assertEqual(row.count("|") - row.count("\\|"), 6)  # five cells, no extra column
        self.assertIn("second line", row)  # one cell, no line break

    def test_untrusted_message_text_is_escaped(self) -> None:
        res = result_with()
        res["commits"][0]["problems"][0]["message"] = "hi @someone <script>x</script> | y"
        body = ccm.render(res)
        self.assertNotIn("<script>", body)
        self.assertNotIn("@someone", body)
        self.assertIn("@\u200bsomeone", body)

    def test_untrusted_links_are_neutralized(self) -> None:
        res = result_with()
        res["commits"][0]["problems"][0]["message"] = (
            "see [the fix](https://evil.example/x) or https://evil.example/y"
        )
        res["commits"][0]["problems"][0]["rule"] = "made-up-rule"
        res["commits"][0]["problems"][0]["hint"] = "open [this](https://evil.example/z)"
        body = ccm.render(res)
        self.assertNotIn("](https://", body)
        self.assertNotIn("https://evil", body)
        self.assertNotIn("evil.example/z", body)  # the fix never comes from the artifact

    def test_rows_are_capped(self) -> None:
        res = result_with()
        res["commits"] = [dict(res["commits"][0], sha=f"{i:040x}") for i in range(ccm.MAX_ROWS)]
        res["errors"] = 3 * ccm.MAX_ROWS
        body = ccm.render(res)
        self.assertEqual(sum(1 for ln in body.split("\n") if ln.startswith("| `")), ccm.MAX_ROWS)
        self.assertIn(f"And {2 * ccm.MAX_ROWS} more", body)

    def test_malformed_results_are_rejected(self) -> None:
        bad = [
            [],
            {"commits": "x"},
            {"commits": [{"sha": "not-hex", "problems": []}]},
            {
                "commits": [
                    {
                        "sha": "b" * 40,
                        "problems": [{"line": "3", "rule": "body-max-length", "severity": "error"}],
                    }
                ]
            },
            {
                "commits": [
                    {
                        "sha": "b" * 40,
                        "problems": [{"line": 3, "rule": "Bad Rule|x", "severity": "error"}],
                    }
                ]
            },
            {
                "commits": [
                    {
                        "sha": "b" * 40,
                        "problems": [{"line": 3, "rule": "body-max-length", "severity": "fatal"}],
                    }
                ]
            },
        ]
        for data in bad:
            with self.assertRaises(ValueError, msg=data):
                ccm.valid_result(data)
        good = result_with()
        self.assertIs(ccm.valid_result(good), good)


class DecideTest(unittest.TestCase):
    def test_failure_without_comment_creates(self) -> None:
        action, body = ccm.decide(None, result_with())
        self.assertEqual(action, "create")
        assert body is not None
        self.assertIn(ccm.MARKER, body)

    def test_failure_with_a_different_comment_updates(self) -> None:
        self.assertEqual(ccm.decide(ccm.MARKER + "\nold", result_with())[0], "update")

    def test_same_failure_changes_nothing(self) -> None:
        res = result_with()
        self.assertEqual(ccm.decide(ccm.render(res), res)[0], "none")

    def test_pass_without_comment_does_nothing(self) -> None:
        self.assertEqual(ccm.decide(None, result_with(problems=False)), ("none", None))

    def test_pass_with_comment_updates_to_resolved(self) -> None:
        action, body = ccm.decide(ccm.render(result_with()), result_with(problems=False))
        self.assertEqual(action, "update")
        assert body is not None
        self.assertIn("all pass", body)

    def test_pass_with_resolved_comment_changes_nothing(self) -> None:
        res = result_with(problems=False)
        self.assertEqual(ccm.decide(ccm.render(res), res)[0], "none")

    def test_pass_with_comment_deletes_when_asked(self) -> None:
        self.assertEqual(
            ccm.decide(ccm.render(result_with()), result_with(problems=False), resolved="delete"),
            ("delete", None),
        )


class FakeGitHub:
    def __init__(self, head_sha: str, comments: list[dict[str, Any]] | None = None) -> None:
        self.head_sha = head_sha
        self.comments = list(comments or [])
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        self.calls.append((method, path, body))
        if method == "GET" and "/pulls/" in path:
            return {"head": {"sha": self.head_sha}}
        if method == "GET" and "/comments" in path:
            page = int(path.rsplit("page=", 1)[1])
            return self.comments[(page - 1) * 100 : page * 100]
        return {}


BOT = "github-actions[bot]"


class SyncCommentTest(unittest.TestCase):
    def sync(self, api: FakeGitHub, res: ccm.Result, head: str = "a" * 40, **kw: Any) -> str:
        return ccm.sync_comment(api, "kleidos-dev/example", res, head, log=lambda *_: None, **kw)

    def writes(self, api: FakeGitHub) -> list[tuple[str, str]]:
        return [(m, p) for m, p, _ in api.calls if m != "GET"]

    def test_creates_on_first_failure(self) -> None:
        api = FakeGitHub("a" * 40)
        self.assertEqual(self.sync(api, result_with()), "create")
        self.assertEqual(
            self.writes(api), [("POST", "/repos/kleidos-dev/example/issues/7/comments")]
        )

    def test_updates_its_own_comment_found_on_a_later_page(self) -> None:
        others = [{"id": i, "user": {"login": "someone"}, "body": "hello"} for i in range(100)]
        ours = {"id": 999, "user": {"login": BOT}, "body": ccm.MARKER + "\nold"}
        api = FakeGitHub("a" * 40, others + [ours])
        self.assertEqual(self.sync(api, result_with()), "update")
        self.assertEqual(
            self.writes(api), [("PATCH", "/repos/kleidos-dev/example/issues/comments/999")]
        )

    def test_ignores_a_marker_written_by_someone_else(self) -> None:
        api = FakeGitHub("a" * 40, [{"id": 5, "user": {"login": "someone"}, "body": ccm.MARKER}])
        self.assertEqual(self.sync(api, result_with()), "create")

    def test_deletes_when_fixed_and_asked(self) -> None:
        api = FakeGitHub(
            "a" * 40, [{"id": 5, "user": {"login": BOT}, "body": ccm.render(result_with())}]
        )
        self.assertEqual(self.sync(api, result_with(problems=False), resolved="delete"), "delete")
        self.assertEqual(
            self.writes(api), [("DELETE", "/repos/kleidos-dev/example/issues/comments/5")]
        )

    def test_stale_result_is_left_alone(self) -> None:
        api = FakeGitHub("c" * 40)
        self.assertEqual(self.sync(api, result_with()), "stale")
        self.assertEqual(self.writes(api), [])

    def test_result_for_another_head_is_left_alone(self) -> None:
        api = FakeGitHub("a" * 40)
        self.assertEqual(self.sync(api, result_with(head="d" * 40)), "stale")

    def test_result_without_a_pull_request_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.sync(FakeGitHub("a" * 40), result_with(pr=None))

    def test_the_api_url_must_be_https(self) -> None:
        with self.assertRaises(ValueError):
            ccm.GitHub("token", "http://api.example.com")
        with self.assertRaises(ValueError):
            ccm.GitHub("token", "file:///etc/passwd")
        api = ccm.GitHub("token", "https://api.example.com/")
        self.assertEqual(api.api_url, "https://api.example.com")


class RenderCliTest(unittest.TestCase):
    def test_render_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "result.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(result_with(), fh)
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(ccm.main(["--render", path]), 0)
            self.assertIn(ccm.MARKER, out.getvalue())
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{}")
            with redirect_stderr(io.StringIO()):
                self.assertEqual(ccm.main(["--render", path]), 2)


class CommandTest(unittest.TestCase):
    """The command line's other ends, with git, the network and the files failing."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.result = os.path.join(self._tmp.name, "result.json")
        with open(self.result, "w", encoding="utf-8") as fh:
            json.dump(result_with(), fh)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def main(self, *argv: str) -> tuple[int, str, str]:
        with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            try:
                status = ccm.main(list(argv))
            except SystemExit as stop:
                status = int(stop.code or 0)
        return status, out.getvalue(), err.getvalue()

    def test_exactly_one_mode(self) -> None:
        for argv in ((), ("MSG", "--range", "a..b"), ("--render", "x", "--comment", "y")):
            status, _out, err = self.main(*argv)
            self.assertEqual(status, 2, argv)
            self.assertIn("give exactly one of", err)

    def test_a_message_file_that_is_not_there(self) -> None:
        status, _out, err = self.main(os.path.join(self._tmp.name, "none"))
        self.assertEqual(status, 2)
        self.assertIn("check_commit_msg:", err)

    def test_the_comment_needs_its_three_names(self) -> None:
        whole = ["--comment", self.result, "--repo", "o/r", "--head-sha", "a" * 40]
        with mock.patch.dict(os.environ):
            os.environ.pop("GITHUB_TOKEN", None)
            self.assertIn("--comment needs", self.main(*whole)[2])
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t"}):
            for argv in (whole[:2] + whole[4:], whole[:4]):
                self.assertIn("--comment needs", self.main(*argv)[2])

    def test_the_comment_is_synced_with_the_environments_api(self) -> None:
        env = {"GITHUB_TOKEN": "t", "GITHUB_API_URL": "https://api.example.com"}
        argv = ["--comment", self.result, "--repo", "o/r", "--head-sha", "a" * 40]
        with (
            mock.patch.dict(os.environ, env),
            mock.patch.object(ccm, "sync_comment", return_value="create") as sync,
        ):
            status, _out, _err = self.main(*argv, "--resolved", "delete", "--bot-login", "b")
        self.assertEqual(status, 0)
        api, repo, result, head, resolved, login = sync.call_args.args
        self.assertEqual(api.api_url, "https://api.example.com")
        self.assertEqual((repo, head, resolved, login), ("o/r", "a" * 40, "delete", "b"))
        self.assertEqual(result["pr"], 7)

    def test_a_network_that_fails_is_said(self) -> None:
        argv = ["--comment", self.result, "--repo", "o/r", "--head-sha", "a" * 40]
        with (
            mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t"}),
            mock.patch.object(ccm, "sync_comment", side_effect=urllib.error.URLError("down")),
        ):
            status, _out, err = self.main(*argv)
        self.assertEqual(status, 2)
        self.assertIn("down", err)

    def test_a_range_can_be_written_to_standard_output(self) -> None:
        result = {**result_with(problems=False), "skipped_merges": 0}
        with mock.patch.object(ccm, "check_range", return_value=result):
            status, out, _err = self.main("--range", "a..b", "--json", "-", "--pr", "9")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out)["pr"], 9)

    def test_a_range_alone_writes_no_file(self) -> None:
        with mock.patch.object(
            ccm, "check_range", return_value={**result_with(), "skipped_merges": 0}
        ):
            status, out, _err = self.main("--range", "a..b")
        self.assertEqual(status, 1)
        self.assertTrue(out)

    def test_gits_comment_character(self) -> None:
        for said, char in ((";\n", ";"), ("auto\n", "#"), ("\n", "#")):
            with mock.patch.object(ccm, "git", return_value=said):
                self.assertEqual(ccm.comment_char(), char)
        with mock.patch.object(ccm, "git", side_effect=RuntimeError("unset")):
            self.assertEqual(ccm.comment_char(), "#")

    def test_long_text_is_cut(self) -> None:
        self.assertEqual(ccm.plain("x" * 161), "x" * 159 + "…")
        self.assertEqual(ccm.plain("x" * 160), "x" * 160)
        self.assertEqual(ccm.code_cell("x" * 61), "`" + "x" * 59 + "…`")
        self.assertEqual(ccm.code_cell("x" * 60), "`" + "x" * 60 + "`")
        self.assertEqual(ccm.code_cell(" "), "")

    def test_a_count_that_is_no_number_is_refused(self) -> None:
        for key in ("errors", "warnings", "checked"):
            with self.assertRaisesRegex(ValueError, f"{key} is not a number"):
                ccm.valid_result({**result_with(), key: "1"})


class UntrustedTest(unittest.TestCase):
    """The artifact is data from an untrusted run: every escape of the comment path."""

    def test_every_character_that_means_something_is_neutralized(self) -> None:
        for raw, safe in (
            ("a & b", "a &amp; b"),
            ("<b>", "&lt;b&gt;"),
            ("<", "&lt;"),
            (">", "&gt;"),
            ("&lt;", "&amp;lt;"),
            ("a|b", "a\\|b"),
            ("a\\b", "a\\\\b"),
            ("a`b", "a'b"),
            ("[x](y)", "\\[x\\](y)"),
            ("https://x.y", "https:\\/\\/x.y"),
            ("@someone", "@\u200bsomeone"),
            ("a\nb", "a b"),
            ("a\r\n\tb   c", "a b c"),
            ("  a  ", "a"),
            (7, "7"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(ccm.plain(raw), safe)
        self.assertEqual(ccm.code_cell("a\n b`c|d"), "`a b'c\\|d`")

    def test_a_row_is_one_line_whatever_the_artifact_says(self) -> None:
        hostile = "x\n| forged | row |\n<script> [a](b) @someone https://e.example `c`"
        result = result_with()
        result["commits"][0]["subject"] = hostile
        problem = result["commits"][0]["problems"][0]
        problem.update(message=hostile, fix=hostile, hint=hostile)
        body = ccm.render(result)
        rows = [line for line in body.splitlines() if line.startswith("| `")]
        self.assertEqual(len(rows), result["errors"], body)
        for planted in ("<script>", "[a](b)", "@someone", "https://e.example"):
            self.assertNotIn(planted, rows[0].replace(ccm.code_cell(hostile), ""))
        self.assertNotIn("| forged | row |", body.splitlines())

    def test_the_fix_is_the_checkers_own_whatever_the_artifact_says(self) -> None:
        result = result_with()
        problem = result["commits"][0]["problems"][0]
        problem.update(fix="run this command", hint="run this command")
        body = ccm.render(result)
        self.assertNotIn("run this command", body)
        self.assertIn(ccm.sentence(ccm.HINTS[problem["rule"]]), body)
        problem["rule"] = "no-such-rule"
        self.assertIn("See the job log.", ccm.render(result))
        self.assertNotIn("run this command", ccm.render(result))

    def test_only_the_bots_own_marked_comment_is_edited(self) -> None:
        for comment, action in (
            ({"id": 5, "user": {"login": BOT}, "body": "another bot comment"}, "create"),
            ({"id": 5, "user": {"login": BOT}, "body": None}, "create"),
            ({"id": 5, "user": None, "body": ccm.MARKER}, "create"),
            ({"id": 5, "user": {"login": "someone"}, "body": ccm.MARKER}, "create"),
            ({"id": 5, "user": {"login": BOT}, "body": ccm.MARKER + " old"}, "update"),
        ):
            with self.subTest(comment=comment):
                api = FakeGitHub("a" * 40, [comment])
                said = ccm.sync_comment(api, "o/r", result_with(), "a" * 40, log=lambda *_: None)
                self.assertEqual(said, action)

    def test_a_number_that_is_no_pull_request_is_refused(self) -> None:
        for number in (0, -1, None, "7", 7.0):
            result = {**result_with(), "pr": number}
            with self.assertRaisesRegex(ValueError, "names no pull request"):
                ccm.sync_comment(FakeGitHub("a" * 40), "o/r", result, "a" * 40)


class ReadFileTest(unittest.TestCase):
    """What the hook reads is git's, the repository's or a temporary file."""

    def test_where_a_file_may_be(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            repo = fx.init(home / "repo")
            for rel in ("repo/in.txt", "repo/.git/MSG", "temp/t", "runner/r", "out/o", "repo2/x"):
                (home / rel).parent.mkdir(exist_ok=True)
                (home / rel).write_text(rel, encoding="utf-8")
            (repo / "link").symlink_to(home / "out/o")
            with (
                mock.patch.object(tempfile, "gettempdir", return_value=str(home / "temp")),
                mock.patch.dict(os.environ, {"RUNNER_TEMP": str(home / "runner")}),
                contextlib.chdir(home),
            ):
                for rel in ("repo/in.txt", "repo/.git/MSG", "temp/t", "runner/r"):
                    self.assertEqual(ccm.read_file(rel, "repo"), rel)
                for rel in ("out/o", "repo2/x", "repo/link", "repo/../out/o", "repo", "none"):
                    with self.assertRaises(OSError, msg=rel):
                        ccm.read_file(rel, "repo")
                with mock.patch.object(ccm, "check_range", return_value=result_with()):
                    argv = ["--range", "a..b", "-C", "repo", "--json"]
                    quiet = contextlib.redirect_stdout(io.StringIO())
                    with quiet, contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(ccm.main([*argv, "repo/new.json"]), 1)
                        self.assertTrue((repo / "new.json").is_file())
                        self.assertEqual(ccm.main([*argv, "out/new.json"]), 2)
                self.assertFalse((home / "out/new.json").exists())
                os.environ["RUNNER_TEMP"] = ""
                with self.assertRaisesRegex(OSError, "runner/r is neither in this repository"):
                    ccm.read_file("runner/r", "repo")
                self.assertEqual(ccm.read_file("out/o"), "out/o")  # the folder it runs in
                fx.git(repo, "commit", "-q", "--allow-empty", "-m", "x")
                fx.git(repo, "worktree", "add", "-q", str(home / "tree"))
                message = home / "repo/.git/worktrees/tree/COMMIT_EDITMSG"
                message.write_text("m", encoding="utf-8")
                self.assertEqual(ccm.read_file(str(message), "tree"), "m")
                bare = home / "bare"
                bare.mkdir()
                (bare / "x").write_text("b", encoding="utf-8")
                self.assertEqual(ccm.read_file("bare/x", "bare"), "b")  # no repository at all


class RevisionTest(unittest.TestCase):
    def test_a_range_is_never_an_option_of_gits(self) -> None:
        for rev in ("--output=x", "-n1", "", "a b", "a;b", "$(x)"):
            with self.assertRaisesRegex(RuntimeError, "is not a revision range"):
                ccm.read_range(rev)
        with mock.patch.object(ccm, "git", return_value="") as git:
            for rev in (
                "main..HEAD",
                "a" * 40 + ".." + "b" * 40,
                "HEAD~3..",
                "^main",
                "v1.0-rc.1",
                "x",
            ):
                self.assertEqual(ccm.read_range(rev), [])
                self.assertEqual(git.call_args.args[0][-2:], [rev, "--"])


class GitHubTest(unittest.TestCase):
    """The real client, its one request."""

    def request(self, answer: bytes, *args: Any) -> tuple[Any, Any]:
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = answer
            got = ccm.GitHub("tok", "https://api.example.com").request(*args)
        self.assertEqual(urlopen.call_args.kwargs, {"timeout": 30})
        return got, urlopen.call_args.args[0]

    def test_a_read(self) -> None:
        got, sent = self.request(b'{"a": 1}', "GET", "/x")
        self.assertEqual(got, {"a": 1})
        self.assertEqual((sent.full_url, sent.get_method()), ("https://api.example.com/x", "GET"))
        self.assertIsNone(sent.data)
        self.assertEqual(sent.get_header("Authorization"), "Bearer tok")
        self.assertIsNone(sent.get_header("Content-type"))

    def test_a_write(self) -> None:
        got, sent = self.request(b"", "POST", "/x", {"body": "é"})
        self.assertIsNone(got)
        self.assertEqual(json.loads(sent.data), {"body": "é"})
        self.assertEqual(sent.get_header("Content-type"), "application/json")

    def test_a_kept_comment_is_not_written(self) -> None:
        body = ccm.render(result_with())
        api = FakeGitHub("a" * 40, [{"id": 5, "user": {"login": BOT}, "body": body}])
        said: list[object] = []
        action = ccm.sync_comment(api, "o/r", result_with(), "a" * 40, log=said.append)
        self.assertEqual(action, "none")
        self.assertEqual([m for m, _p, _b in api.calls if m != "GET"], [])
        self.assertEqual(said, ["pull request #7: kept the commit-check comment"])


if __name__ == "__main__":
    unittest.main()
