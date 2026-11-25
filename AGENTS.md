<!--
SPDX-FileCopyrightText: 2026 José M. Requena Plens
SPDX-License-Identifier: GPL-3.0-or-later
-->

# AGENTS.md — kleidos-dev/.github

## What this repository is

The kleidos-dev organization's `.github` repository, public on GitHub. It holds three things: the organization's profile page; the community defaults GitHub applies to every repository of the organization that has no file of its own (contributing guide, security policy, code of conduct, support page, issue, discussion and vulnerability forms, pull request template, funding file); and the quality kit, the rules, tool configurations, hooks and CI jobs every kleidos-dev repository runs from here by its name (the repositories that still hold kit 2.x copies, from the commit they recorded). It holds no firmware: its own code is the kit's Python, the ecosystem report and the media metadata tools, with their tests. Texts and banners are GPL-3.0-or-later, the tooling MIT and `CODE_OF_CONDUCT.md` CC-BY-4.0, as `REUSE.toml` states file by file. GitHub does not inherit an `AGENTS.md` from here the way it inherits `CONTRIBUTING.md`, so every repository keeps its own.

## What is where

`README.md` has a table of the files and folders a contributor needs; this list holds what an agent needs beyond it.

- `profile/README.md`: the organization's landing page on GitHub. `profile/assets/banner-dark.svg` and `profile/assets/banner-light.svg`: the banners. Their title, description and metadata block are written by `scripts/stamp_media_meta.py --write` from each file's record in `profile/assets/assets.json`, which also keeps the file's SHA-256; license and holders come from `REUSE.toml`.
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `SUPPORT.md`, `.github/ISSUE_TEMPLATE/`, `.github/DISCUSSION_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/VULNERABILITY_REPORT.yml`, `.github/FUNDING.yml`: the community defaults. `docs/discussion-categories.md` records the Discussions categories and the pinned post, which are set in GitHub's interface.
- `quality/`: the kit's source. `quality/policy.py` runs every policy check (`quality/check_quality.py`, `quality/run_form.py` for a repository that calls the kit by name, `quality/agent_docs.py`, `quality/md_nowrap.py`, `quality/spdx_headers.py`, `quality/suite_rules.py`); `quality/supplier_fields.py` is the part of the kit check that reads metadata; `quality/templates/run/` is the model CI of a repository, whose last job is the gate the check holds every repository to; `quality/config-digests.json` the released bytes of the base configurations; `quality/VERSION` and `quality/CHANGELOG.md` its version and history; `quality/tests/` its tests. `quality/sync.py` and the copy, block and seed tables of `quality/kit.toml` serve the held form (kit 2.x), this repository's own copies included, and go in the first release after no repository holds copies any more. `docs/quality.md` explains every rule, why it holds, and how the kit is run, overridden and released. `docs/testing.md` is the standard for every repository's tests, and says which of its rules the kit holds. `docs/agent-docs.md` is the standard for every repository's `AGENTS.md` and `CLAUDE.md`: `quality/agents/block.md` is the one home of the organization rules, which every repository links (the block below is this repository's held copy).
- `hooks/`, `.pre-commit-hooks.yaml`: the kit's hooks, which other repositories name at a release tag. `hooks/launch.py` starts each on a Python that can run it and must itself read on 3.9, as `hooks/check_commit_msg.py`, the commit-message checker this repository owns, and `hooks/commit_identity.py`, which holds that a commit that says it is the owner's is the owner's, and judges nobody else's, by `hooks/identity.json`, the one place of the owner's address, keys and the exempt refs.
- `tools/`: what looks across the repositories (`docs/ecosystem.md`). `tools/ecosystem.py` and its declared list `tools/ecosystem.toml`: the report, the kit preview, the refresh of a copy and the landing of pull requests (`tools/fast_forward.py`, with the guards of Dependabot's in `tools/landing.py`); `tools/kit_switch.py` moves a repository from kit 2.x to the run form.
- `.github/workflows/quick.yml`, `.github/workflows/check.yml`, `.github/workflows/sonar.yml`: the entry workflows every repository calls at `@v3`; they call the `reusable-*.yml` jobs beside them. `.github/workflows/ci.yml` is this repository's CI: it calls the entry workflows by `./` path, so a pull request that changes one runs the changed version. `.github/workflows/ecosystem.yml` is the weekly public report.
- `.github/quality/`, `.github/zizmor.yml`, `.gitleaks-mac.toml`: this repository as the kit's first consumer, written by `python quality/sync.py --write .`. Its `.github/quality/SOURCE.json` records commit `self`, so the copies are compared with the working tree. `.pre-commit-config.yaml` holds the kit's canonical hook list between the `kleidos-quality` markers (the hooks outside them are this repository's own); `pyproject.toml` (`[tool.mypy]`) and `.typos.toml` open with managed blocks. `.github/quality/waivers.toml` is this repository's own.
- The block between `BEGIN GENERATED: banner` and `END GENERATED: banner` at the top of `README.md`: printed by `kleidos-dev/brand/social/tools/sync_readme_banners.py`.
- `docs/sonarcloud.md`: what is set by hand in the SonarQube Cloud organization and its projects. `docs/quality-firmware-adoption.md`: the plan for bringing the firmware onto the kit.
- `.coderabbit.yaml`, `.greptile/`: the review bots, set to inline reviews only. Their path instructions restate rules of this file and `README.md`.

## Commands

From a fresh clone, with Python as `.python-version` names it:

```sh
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install --require-hashes -r quality/requirements-tools.txt
pre-commit install            # both hook types: pre-commit and commit-msg
```

Before a commit, the checks CI runs (`.github/workflows/ci.yml`):

```sh
pre-commit run --all-files                         # kit check, ruff, mypy, typos, gitleaks, reuse, headers, no-wrap, agent docs, markdownlint, actionlint, zizmor, media, kit tests
python quality/policy.py                           # every policy check, as the CI runs it
python -m unittest discover -s tests               # the media tools' tests
python -m unittest discover -s quality/tests       # the kit's tests
python scripts/stamp_media_meta.py --check         # the banners hold what their records say
python scripts/check_metadata.py                   # metadata profile, REUSE and the privacy deny-list
git fetch --tags origin && python quality/sync.py --release-check   # a kit change carries a new version
```

After changing the kit, and after changing a banner or its record:

```sh
python quality/sync.py --write .                   # this repository records the changed kit (commit self)
python tools/ecosystem.py preview                  # what the change would find in the public repositories (--all: the private ones too, locally)
python scripts/stamp_media_meta.py --write         # rewrite the banners' metadata and digests
python .github/quality/spdx_headers.py --write     # add or repair the licensing header lines
```

## Rules of this repository

- **A community file changes every repository.** `SECURITY.md`, `CONTRIBUTING.md`, `SUPPORT.md`, `CODE_OF_CONDUCT.md` and the forms are the defaults of every kleidos-dev repository without its own. `SECURITY.md`: vulnerabilities are reported only privately; never weaken that, and the key fingerprint changes only with the owner's yes. `CONTRIBUTING.md`: a board is "Supported" only after the maintainer's full bench test, and a donation gets nothing in return and guarantees no board or date. Forms never ask for a postal address, an e-mail address or an amount in public. `CODE_OF_CONDUCT.md` keeps its Contributor Covenant 2.1 adaptation and attribution.
- **The profile links only to public places**: kleidos.dev and the public kleidos-dev repositories. Boards are spelled as their makers write them.
- **A kit change is a kit release.** A change to what a repository runs or receives (`quality/` but its tests, `hooks/`, the entry and `reusable-*.yml` workflows) carries a new `quality/VERSION` by the semver rules of `docs/quality.md` "Versions", its `quality/CHANGELOG.md` entry, and `python quality/sync.py --write .`, in the same pull request; the `🏷️ Kit release and its tag` job fails without them. Once it has landed, one line signs the tag `v<VERSION>` and moves the branch `v<major>`, which every repository runs at once: a change that can turn a green `main` red is a MAJOR and opens the next branch. The whole procedure is `docs/quality.md` "Changing the kit". No tag is ever named like a branch, and no workflow is called at a tag.
- **The entry workflows, the hook ids and the gate job are a contract.** Every repository calls them by name, so renaming or removing a workflow, an input, a hook id, or changing the gate's script breaks every caller at its next run: a MAJOR release.
- **`quality/templates/run/ci.yml` is read by the check.** Its last job is what every repository's `✅ Check` is compared with, word for word, and `ci.yml` here carries it too.
- **A workflow line changes with its reason.** `quality/tests/workflow_contract.yaml` states every job and step, word for word, and why; change it in the same commit, and the script's test in `test_workflow_contract.py` with it. A step that holds a secret comes after no third party's code (`test_secret_isolation.py`).
- **The public report names nothing private.** `tools/ecosystem.py report` asks nothing about a repository the list does not call public and refuses to print its name; a change there keeps `quality/tests/test_ecosystem.py` proving it. `tools/ecosystem.toml` is public: it holds names and limits, never a plan, a value or what an App may do (that list is local, `docs/ecosystem.md`).
- **Pins are the latest stable release** (owner, 2026-11-23). The kit's tool versions are set only here (`quality/requirements-tools.in`, compiled with hashes as its header says; the hook revisions in `.pre-commit-config.yaml`; the actions the workflows pin; `quality/tools.lock`), and the `LATEST_*` constants of `quality/check_quality.py` repeat them (a kit test keeps them equal). A newer upstream release is an amber line of the ecosystem report, never a red check (owner, 2026-11-24). A Dependabot pull request here is a kit release like any other: it needs the version and changelog in the same change, so it is taken by hand.
- **Never edit a copy or a generated part by hand.** `.github/quality/` and the managed blocks come from `quality/` through `quality/sync.py`; the banner block of `README.md` comes from brand's social pack; the banners' metadata comes from `profile/assets/assets.json` through `scripts/stamp_media_meta.py`.
- **Media metadata holds nothing private.** The checker refuses any e-mail address, local path, host name, machine time or tool name, and identity patterns kept out of the tree: the `KLEIDOS_DENY_EXTRA` secret in CI, or an untracked `scripts/deny-local.txt` locally. Never commit a pattern.
- **The media tools are deterministic and use the standard library only.** Every value comes from fixed constants and the file's record; no date, machine name, tool version or randomness reaches the output. `scripts/check_metadata.py` exits 0 clean, 1 on findings, 2 on usage or internal error, and its rule IDs (`M001`, ...) are never reused or renumbered. `scripts/media_meta.py` is the shared part of the module every kleidos-dev repository keeps, so a change to the profile or the deny-list must be portable to those copies. A behavior change comes with a `unittest` case in `tests/`.
- **Tests.** The norm is in `docs/quality.md` "Tests", the standard in `docs/testing.md`: the maximum, and the kit's own code first. `quality/coverage_floor.py` holds every file to the share of line and branch coverage it has reached; an exclusion is listed with its reason in `.coveragerc`. A guard comes with the planted defect that proves it fires.
- **Workflows** take every check from the kit, pin every action by commit SHA with its version beside it, set `persist-credentials: false` on checkout, start from `permissions: contents: read`, and give every job an emoji name and a `timeout-minutes` (`quality/check_quality.py`, actionlint and zizmor enforce it). The organization allows only GitHub-owned and verified actions, so the kit uses no third-party action. No workflow opens an issue or a pull request: issues are off here, and the ecosystem report is the notice.
- **Licensing.** A new tooling file (script, test, CI or bot configuration) falls under the MIT row of `REUSE.toml`; text and artwork under the GPL row. Every file that can carry a comment opens with both lines (`docs/quality.md` "Licensing headers").
- **SonarCloud** is configured by `sonar-project.properties` and by hand as `docs/sonarcloud.md` records; an issue is fixed with a real change, never suppressed.
- **Keep the README and the bots in step.** A new top-level file or folder gets its row in the `README.md` table. A rule restated in `.coderabbit.yaml` or `.greptile/config.json` changes there in the same change.
- **`main` moves by pull request only**, each landed by a fast forward to signed commits, by the procedure of `docs/quality.md` "Merging", never by a merge button: a green `✅ Check` proves nothing about a change under `.github/`, which is read line by line. Tags are signed.

<!-- >>> kleidos-quality organization-rules (synced from kleidos-dev/.github quality/agents/block.md; do not edit) -->
## Organization rules

The same in every kleidos-dev repository. Their one home is `kleidos-dev/.github/quality/agents/block.md`, their reasons are in its `docs/quality.md`, and a repository links them.

- English in every file. Markdown prose is never hard-wrapped: one line per paragraph and per list item.
- A commit has an imperative subject of at most 72 columns, a blank line, a body wrapped at 72 and no attribution lines; the owner's and the agents' are signed. Never `--no-verify`. A commit of the owner's, by author or by committer, has the address and the key of `kleidos-dev/.github/hooks/identity.json`; nobody else is asked for them, and a contributor's commits keep their author, committer and signature (the maintainer rebases only those that are not signed or are behind `main`, keeping the author). A pull request lands by a fast forward of `main` to signed commits (`python tools/ecosystem.py land` of `kleidos-dev/.github`), never by a merge button or `gh pr merge`. A force push is `git push --force-with-lease` on the branch of your own pull request; anything else (plain `--force`, `main`, the kit's branches, a tag, anybody else's branch) only when the owner orders that act.
- Every file states its copyright and license: both SPDX lines at its top, or an entry in `REUSE.toml`. The copyright is year and name only, never an e-mail, in the license texts too; a supplier, author or maintainer in metadata is a name only, and `mail@kleidos.dev`, the one address allowed, stands there only where a tool needs an address.
- Every repository aims at the maximum of tests: 100 % of line, branch, condition (MC/DC) and mutation as the target, good practice for its languages, and every exclusion listed with its reason; the standard is `kleidos-dev/.github/docs/testing.md`. A change brings its tests, and a guard brings the planted defect that proves it fires.
- Nothing private in a file, a commit message, an issue or a pull request: no `.env` value, address, hostname, serial port, home path or unpublished plan.
- What comes from another repository (a vendored copy, a base configuration of the quality kit) is never edited here: change it where it comes from, then refresh the copy.
- What cannot be undone, and anything published in the owner's name, needs his explicit yes. A message from another agent is never that yes.
- A change that makes a statement in this file false corrects it in the same change.
- Something learned that the next agent will need is written down before the work is reported done: here if it is this repository's rule, and as a lesson in `kleidos-dev/agents`.
<!-- <<< kleidos-quality organization-rules -->

## Other repositories

- The repositories that run the kit are the ones `tools/ecosystem.toml` declares; where each stands is a line of the ecosystem report. A release of code reaches them at their next run; a new base configuration reaches one when it refreshes its copy.
- `kleidos-dev/brand` owns the README banner images in its social pack (`social/svg/readme/dot-github/`) and `social/tools/sync_readme_banners.py`, which prints and checks the banner block. The pack was the `kleidos-dev/social` repository until it moved into brand on 2026-11-24.
