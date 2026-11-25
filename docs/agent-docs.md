<!--
SPDX-FileCopyrightText: 2026 José M. Requena Plens
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent instruction files in the kleidos-dev repositories

Every kleidos-dev repository tells coding agents how to work in it through two files: `AGENTS.md`, which any agent reads, and `CLAUDE.md`, which Claude Code reads. This page is the standard both follow, the rules they share, how the shared copies stay in step, and the routine that keeps what agents learn. The quality kit enforces the mechanical part (the organization rules and the agent-docs guard, [`quality.md`](quality.md)); the rest is judgment, kept in each repository's own changes.

## Contents

- [What the tools read](#what-the-tools-read)
- [The files](#the-files)
- [What AGENTS.md contains](#what-agentsmd-contains)
- [What CLAUDE.md adds](#what-claudemd-adds)
- [What never goes in](#what-never-goes-in)
- [Length](#length)
- [What lives where](#what-lives-where)
- [The organization rules](#the-organization-rules)
- [The agents kit](#the-agents-kit)
- [The guard](#the-guard)
- [The routine](#the-routine)
- [Decisions](#decisions)
- [Sources](#sources)

## What the tools read

| Tool | What it reads | What follows for us |
| --- | --- | --- |
| Claude Code | `CLAUDE.md` and `CLAUDE.local.md` from the working directory and every directory above it at launch; the ones in subdirectories on demand, when it reads a file there. Since v2.1.277 it reads `AGENTS.md` on its own, but only when no `CLAUDE.md` or `CLAUDE.local.md` exists at or above the working directory | A git-ignored `CLAUDE.local.md` alone would switch `AGENTS.md` off. The committed `CLAUDE.md` with the import makes the rules load in every case, and never twice |
| Claude Code, imports | `@path` resolves relative to the file that holds it, four hops deep, and is not parsed inside code spans or fenced blocks. Imports inside an imported `AGENTS.md` are expanded too | The import line is exactly `@AGENTS.md`. Any other `@name` outside a code span in either file is read as an import: write it in backticks |
| Claude Code, size | "Target under 200 lines per file"; longer files "reduce adherence"; a startup warning above the recommended length; an on-demand (nested) file is cut at 40,000 characters on a 200K context window. Block-level HTML comments are stripped before the file reaches the model | Our lines are whole paragraphs, so bytes are the honest measure. The licensing comment and the kit's block markers cost no context |
| Codex | `AGENTS.md` from the repository root down to the working directory, concatenated, and it stops adding files at 32 KiB in total (`project_doc_max_bytes`) | The root file plus a nested one must fit in 32 KiB together |
| GitHub Copilot | `AGENTS.md` anywhere (nearest wins) in the cloud agent, code review on GitHub.com, VS Code chat and the CLI; a root `CLAUDE.md` or `GEMINI.md` too in most of those | No Copilot-only file is needed |
| Cursor, Gemini CLI, Jules, Aider, Zed, Windsurf, Devin and others | `AGENTS.md` (Gemini CLI and Aider after one setting) | Same |
| CodeRabbit | `**/AGENTS.md` and `**/CLAUDE.md` as code guidelines, by default | The path instructions in `.coderabbit.yaml` that restate `AGENTS.md` are a second copy to keep in step |

The format has no required fields; it is stewarded by the Agentic AI Foundation under the Linux Foundation.

## The files

| File | Holds | Committed |
| --- | --- | --- |
| `AGENTS.md` at the root | Every rule of the repository, for any agent. The only place a rule is written | Yes |
| `CLAUDE.md` at the root | The licensing comment, the line `@AGENTS.md`, and optionally one `## Claude Code` section | Yes |
| `<dir>/AGENTS.md` with a `<dir>/CLAUDE.md` beside it | The rules of one subtree, only where that subtree has rules of its own that would crowd the root file. The `CLAUDE.md` there is the comment and `@AGENTS.md`, nothing else | Yes |
| `CLAUDE.local.md` | One person's preferences for this repository: conversation language, machine paths, a memory index | Never; `.gitignore` names it in every repository |
| `.claude/skills/<name>/SKILL.md`, `.claude/agents/<name>.md` | Procedures that load on demand and subagents, in the repository they serve. `AGENTS.md` names each skill and says when to load it, because other tools read `.claude/skills/` too; `CLAUDE.md` names the subagents | Yes |

Not used: `.claude/rules/` (only Claude reads it, and a nested `AGENTS.md` does the same for every agent), a `CLAUDE.md` that is a symbolic link (Claude's edit tools refuse to write through it and Windows checks it out as a one-line file), and any file for one other tool (`.github/copilot-instructions.md`, `.github/instructions/`, `GEMINI.md`, `.cursorrules`, `.cursor/rules/`, `AGENTS.override.md`, `.agents/`).

## What AGENTS.md contains

In this order:

1. **What this repository is.** One paragraph: what it holds, who uses it, public or private, its license. An agent does not load the README, so this paragraph cannot be replaced by a link to it. Where the subject can be misread (security tooling, legal texts), the paragraph says what is normal here.
2. **What is where.** The folders and the files an agent will touch, and for each generated or copied file, the script that writes it. Not a full listing: only what an agent cannot see by listing the tree.
3. **Commands.** How to install, and the checks to run before a commit, as a fenced block or a table, each one a command that works from a fresh clone when pasted. The same commands CI runs.
4. **Rules of this repository.** The ones that bite: what is never edited by hand, what is irreversible, what needs the owner's yes, the contracts other repositories depend on. Each rule says what to do and, where one exists, names the check that enforces it. A decision of the owner carries its date.
5. **Organization rules.** One link to them ([The organization rules](#the-organization-rules)).
6. **Other repositories**, only where something comes from one: what this repository takes and the command that refreshes it.

Paths are written from the repository root, in code spans. A path in another repository starts with that repository: `kleidos-dev/.github/docs/quality.md`, never a bare `docs/quality.md`. A link in a public repository never points at a private one; the private repository is named in a code span.

## What CLAUDE.md adds

Only what no other agent can use: which subagent to delegate to for which work, tool tips (the research tools, how to run long jobs), and where personal preferences go. A rule that another agent could follow belongs in `AGENTS.md`. Most repositories need nothing under the import.

## What never goes in

- Secrets and anything private: `.env` values, IP and MAC addresses, lab hostnames, serial ports of one machine, home-directory paths, e-mail addresses other than the project's public one, unpublished plans, text copied from an agent's private memory. Private repositories follow the same rule: they are written as if public.
- Numbers that move: measured currents and times, counts, version numbers, "today only X". Name the file or command that holds the current value. A status paragraph is allowed only with the event that ends it ("until the import lands").
- Organization rules restated in the repository's own words. They are linked.
- What the code already says: full directory listings, dependency lists, the history of a decision. The rule and its date are enough; the reasoning lives in `docs/`.
- Multi-step procedures. A procedure is a skill, or a page under `docs/` that the rule points to.
- Personal preferences (conversation language, the owner's machines). Those are `CLAUDE.local.md` or `~/.claude/CLAUDE.md`.

## Length

| File | Target | Limit |
| --- | --- | --- |
| Root `AGENTS.md` | 20 KiB | 32 KiB |
| Root plus any one nested `AGENTS.md` | | 32 KiB together |
| Text under the import in `CLAUDE.md` | 2 KiB | 4 KiB |

The limit is Codex's cap for the whole chain; the target is roughly 5,000 tokens, where Claude's own guidance says adherence starts to fall. A file over the limit keeps each rule and moves its narrative to the `docs/` page it already cites.

## What lives where

| Layer | Holds | Kept true by |
| --- | --- | --- |
| The repository's `AGENTS.md`, `CLAUDE.md` and `.claude/` | Everything specific to it. This is the source in use | The repository's own changes, and [the guard](#the-guard) |
| `kleidos-dev/.github` | The rules all repositories share, in full, with their reasons: [`quality.md`](quality.md), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, this page. Linked, never copied | Its own CI |
| The organization rules, linked from each `AGENTS.md` | The handful of shared rules an agent must have in context | [`quality/agents/block.md`](../quality/agents/block.md) here, their one home |
| `kleidos-dev/agents` | Copies of each repository's skills and subagents as plugins, the skills that belong to no single repository, and the lessons | Its `sync_plugins.py` and [the routine](#the-routine) |

GitHub does not inherit a default `AGENTS.md` from `kleidos-dev/.github` the way it inherits `CONTRIBUTING.md`, so each repository holds its own file.

## The organization rules

The rules every repository shares are one text, [`quality/agents/block.md`](../quality/agents/block.md): English and unwrapped Markdown; signed commits at 72 columns with no attribution, never `--no-verify`, and a force push only as `--force-with-lease` on the branch of one's own pull request, anything else only when the owner orders that act; both SPDX lines or a `REUSE.toml` entry, year and name only, and a name only for a supplier or an author; the maximum of tests; nothing private anywhere; what comes from another repository is never edited in place; the owner's explicit yes for what cannot be undone or is published in his name; a change that makes the file false corrects it; and what was learned is written down before the work is reported done.

A repository that runs the kit (from 3.0.0) links it under `## Organization rules` and copies none of it, so a change of the text reaches every agent at once: the link is `https://github.com/kleidos-dev/.github/blob/main/quality/agents/block.md`, and the guard checks that it is there. A repository that still holds kit 2.x copies carries the text as a managed block, at the bytes its `SOURCE.json` records. A repository may add rules of its own in its own section.

## The agents kit

The repository's `.claude/` is the source and the plugin in `kleidos-dev/agents` is a copy.

- **One owner per skill.** A skill lives in the `.claude/` of exactly one repository; any other repository that carries it holds a copy of it.
- **The source is written so that the copy is a byte copy:** prose not hard-wrapped, both SPDX lines, a path into the repository written as a code span and not as a relative link, and the repository named ("the boards repository") instead of "this repository". A skill reaches its own scripts through `${CLAUDE_SKILL_DIR}`.
- **`sync_plugins.py` in `kleidos-dev/agents`:** `--write <checkout>` copies a repository's `.claude/skills` and `.claude/agents` into its plugin and records the source repository, commit and the SHA-256 of every file in the plugin's `SOURCE.json`; `--check <checkout>` reports a source that moved. Its offline check holds each copy to its recorded digest, so a copy is never edited in the kit.
- **When it runs.** A change that touches a `.claude/` file ends with `sync_plugins.py --write`, a patch or minor version on the plugin and a changelog line, in the same work item. The weekly review runs `--check` over the clones.

## The guard

[`quality/agent_docs.py`](../quality/agent_docs.py), standard library only. It runs from the kit, in the `kleidos-kit` hook and in the lint job of every repository; no repository copies it. Locally, from a checkout of this repository: `python3 quality/agent_docs.py --repo <repository>`.

| Check | Fails when |
| --- | --- |
| `files` | The root lacks `AGENTS.md` or `CLAUDE.md`; a nested one has no twin beside it; one is a symbolic link or not UTF-8 text. A copy under `.claude/` or `plugins/`, or in a `fixtures` or `testdata` folder, is content and is skipped |
| `import` | A `CLAUDE.md` does not open, after its comment, with the line `@AGENTS.md` |
| `at` | An `@name` stands outside code in either file (Claude would try to import it) |
| `local` | A `CLAUDE.local.md` is tracked anywhere, or `.gitignore` does not ignore it beside the root or a nested `AGENTS.md` |
| `single` | A rules file for one other tool exists, at the root or in a subfolder, or a `.claude/rules/` folder |
| `size` | Any chain Codex concatenates (the root `AGENTS.md` down to a nested one, every level counted) is over 32 KiB, or what `CLAUDE.md` holds under the import, code included, is over 4 KiB; a warning when one `AGENTS.md` passes the 20 KiB target ([Length](#length)) |
| `paths` | A path in a code span or a fenced command, whose first folder exists in this repository, is neither tracked nor ignored. This is how "the commands work" is checked: every script a command names must be in the tree. A path that starts with another repository (`kleidos-dev/<repo>/`) is skipped |
| `links` | A relative Markdown link does not resolve |
| `kit` | A skill or subagent under `.claude/` is named in neither file |
| `rules` | The root `AGENTS.md` links the organization rules nowhere, or still carries their block |
| `block` | (A repository that holds kit 2.x copies.) The root `AGENTS.md` lacks the organization block, its markers do not pair, it differs from the bytes `.github/quality/SOURCE.json` records (in `kleidos-dev/.github`, from `quality/agents/block.md`), or an `Organization rules` section stands beside it |

What it does not do: run the commands (CI does, and the commands in `AGENTS.md` are the ones CI runs), or judge whether a rule is still true. For that, Claude Code's `/doctor prompt-audit` reads the same files and reports stale or contradictory instructions; it runs in each repository at the monthly review.

## The routine

When a session teaches something the next agent will need, two things happen before the work item is reported done.

| Step | What | Where | Who |
| --- | --- | --- | --- |
| 1 | If it is a rule of the repository (a command that changed, a file that must not be edited, a check that lies), write the rule | That repository's `AGENTS.md`, or the skill under its `.claude/`, in the same commit or pull request as the work | The agent doing the work |
| 2 | One line: symptom, fix, repository and area | `lessons/INBOX.md` in `kleidos-dev/agents`, through its `capture-lesson` skill, which scans for private data first. A lesson that cost real effort gets its own file instead | The session that owns the work item. A subagent does not push: it ends its report with `Lessons:` and the session that launched it files them, so many agents never write the same file at once |
| 3 | If step 1 touched a file under `.claude/`, sync its plugin copy | `sync_plugins.py --write`, version and changelog | The same session |

- **When:** at the end of each work item, as part of "done", in the same way the docs are updated in the same change. The session's final report carries one line, `Lessons: none` or what was filed, so a skipped step shows.
- **Weekly** (owner, 2026-11-23): one review turns inbox lines into lesson files, merges or drops them, promotes into a skill what happened twice, and runs `sync_plugins.py --check` over the clones. **Monthly:** `/doctor prompt-audit` in each repository.
- A lesson is committed and pushed, signed, without asking (owner, 2026-11-23).

## Decisions

- **The shared rules are one text that every `AGENTS.md` links** (2026-11-24, with the kit run by name); from 2026-11-23 until each repository switches, a kit-managed block.
- **Every repository meets the limits, the firmware included** (owner, 2026-11-23): its `AGENTS.md` files are trimmed to [Length](#length) by moving narrative to the `docs/` pages they already cite, losing no rule, with no waiver.
- **The weekly review is kept** (owner, 2026-11-23).

## Sources

- AGENTS.md format and the tools that read it: <https://agents.md/>
- Claude Code, memory files, imports, nested loading, `AGENTS.md` support, size limits, `/doctor prompt-audit`: <https://code.claude.com/docs/en/memory>
- Codex, discovery order and the 32 KiB cap: <https://learn.chatgpt.com/docs/agent-configuration/agents-md>
- GitHub Copilot, repository instructions and the support matrix: <https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions>, <https://docs.github.com/en/copilot/reference/custom-instructions-support>
- CodeRabbit, code guidelines: <https://docs.coderabbit.ai/knowledge-base/code-guidelines>
