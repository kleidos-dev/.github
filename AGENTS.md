<!--
SPDX-FileCopyrightText: 2026 José M. Requena Plens
SPDX-License-Identifier: GPL-3.0-or-later
-->

# AGENTS.md — kleidos-dev/.github

## What this repository is

The kleidos-dev organization's `.github` repository, public on GitHub. It holds three things: the organization's profile page; the community defaults GitHub applies to every repository of the organization that has no file of its own (contributing guide, security policy, code of conduct, support page, issue, discussion and vulnerability forms, pull request template, funding file); and the quality kit, the rules, tool configurations and CI jobs every kleidos-dev repository takes from here by copy, by managed block or by calling a workflow at a pinned commit. It holds no firmware: its own code is the kit's Python and the media metadata tools, with their tests. Texts and banners are GPL-3.0-or-later, the tooling MIT and `CODE_OF_CONDUCT.md` CC-BY-4.0, as `REUSE.toml` states file by file. GitHub does not inherit an `AGENTS.md` from here the way it inherits `CONTRIBUTING.md`, so every repository keeps its own.

## What is where

`README.md` has a table of the files and folders a contributor needs; this list holds what an agent needs beyond it.

- `profile/README.md`: the organization's landing page on GitHub. `profile/assets/banner-dark.svg` and `profile/assets/banner-light.svg`: the banners. Their title, description and metadata block are written by `scripts/stamp_media_meta.py --write` from each file's record in `profile/assets/assets.json`, which also keeps the file's SHA-256; license and holders come from `REUSE.toml`.
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `SUPPORT.md`, `.github/ISSUE_TEMPLATE/`, `.github/DISCUSSION_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/VULNERABILITY_REPORT.yml`, `.github/FUNDING.yml`: the community defaults. `docs/discussion-categories.md` records the Discussions categories and the pinned post, which are set in GitHub's interface.
- `quality/`: the kit's source. `quality/kit.toml` lists every copy, managed block and seeded file per profile, and the consuming repositories; `quality/sync.py` writes and checks them; `quality/VERSION` and `quality/CHANGELOG.md` are its version and history; `quality/tests/` its tests. `docs/quality.md` explains every rule, why it holds, and how the kit is adopted, overridden, released and taken.
- `.github/workflows/reusable-*.yml`: the kit's CI jobs, which every repository calls. `.github/workflows/ci.yml` is this repository's CI: it calls them by `./` path, so a pull request that changes one runs the changed version.
- `.github/quality/`, `.github/zizmor.yml`, `.gitleaks-mac.toml`: this repository as the kit's first consumer, written by `python quality/sync.py --write .`. Its `.github/quality/SOURCE.json` records commit `self`, so the copies are compared with the working tree. `.pre-commit-config.yaml` holds the kit's canonical hook list between the `kleidos-quality` markers (the hooks outside them are this repository's own); `pyproject.toml` (`[tool.mypy]`) and `.typos.toml` open with managed blocks. `.github/quality/waivers.toml` is this repository's own.
- `.github/commit-check/check_commit_msg.py`: a copy of the commit-message checker, recorded in `.github/commit-check/SOURCE.json` and held by `quality/tests/test_commit_check_copy.py`.
- The block between `BEGIN GENERATED: banner` and `END GENERATED: banner` at the top of `README.md`: printed by `kleidos-dev/social/tools/sync_readme_banners.py`.
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
pre-commit run --all-files                         # kit check, ruff, mypy, typos, gitleaks, reuse, headers, no-wrap, markdownlint, actionlint, zizmor, media, kit tests
python -m unittest discover -s tests               # the media tools' tests
python -m unittest discover -s quality/tests       # the kit's tests
python scripts/stamp_media_meta.py --check         # the banners hold what their records say
python scripts/check_metadata.py                   # metadata profile, REUSE and the privacy deny-list
git fetch --tags origin && python quality/sync.py --release-check   # a kit change carries a new version
```

After changing the kit, and after changing a banner or its record:

```sh
python quality/sync.py --write .                   # this repository records the changed kit (commit self)
python quality/sync.py --tools --allow-dirty --preview @public   # what the change would find in the public repositories
python scripts/stamp_media_meta.py --write         # rewrite the banners' metadata and digests
python .github/quality/spdx_headers.py --write     # add or repair the licensing header lines
```

## Rules of this repository

- **A community file changes every repository.** `SECURITY.md`, `CONTRIBUTING.md`, `SUPPORT.md`, `CODE_OF_CONDUCT.md` and the forms are the defaults of every kleidos-dev repository without its own. `SECURITY.md`: vulnerabilities are reported only privately; never weaken that, and the key fingerprint changes only with the owner's yes. `CONTRIBUTING.md`: a board is "Supported" only after the maintainer's full bench test, and a donation gets nothing in return and guarantees no board or date. Forms never ask for a postal address, an e-mail address or an amount in public. `CODE_OF_CONDUCT.md` keeps its Contributor Covenant 2.1 adaptation and attribution.
- **The profile links only to public places**: kleidos.dev and the public kleidos-dev repositories. Boards are spelled as their makers write them.
- **A kit change is a kit release.** A change to what a consuming repository receives (`quality/` but its tests, the kit's blocks, the `reusable-*.yml` workflows, the commit-message checker) carries a new `quality/VERSION` by the semver rules of `docs/quality.md` "Versions", its `quality/CHANGELOG.md` entry, and `python quality/sync.py --write .`, in the same pull request; the `🏷️ Kit release and its tag` job fails without them. After the merge, the merge commit gets the signed tag `quality-v<VERSION>`, and consumers sync from that tag only. The whole procedure is `docs/quality.md` "Changing the kit".
- **The reusable workflows are a contract.** Every repository calls them at a recorded commit, so renaming or removing a workflow or an input breaks every caller at its next sync: that can turn a green repository red, which makes it a MAJOR release.
- **Pins are the latest stable release** (owner, 2026-11-23). The kit's tool versions are set only here (`quality/requirements-tools.in`, compiled with hashes as its header says; the hook revisions in `.pre-commit-config.yaml`; the actions the workflows pin; `quality/tools.lock`), and the `LATEST_*` constants of `quality/check_quality.py` repeat them (a kit test keeps them equal). A Dependabot pull request here is a kit release like any other: it needs the version and changelog commit before it merges.
- **Never edit a copy or a generated part by hand.** `.github/quality/` and the managed blocks come from `quality/` through `quality/sync.py`; `.github/commit-check/check_commit_msg.py` comes from `kleidos-dev/agents` (change it there, then copy it here and release the kit); the banner block of `README.md` comes from the social repository; the banners' metadata comes from `profile/assets/assets.json` through `scripts/stamp_media_meta.py`.
- **Media metadata holds nothing private.** The checker refuses any e-mail address, local path, host name, machine time or tool name, and identity patterns kept out of the tree: the `KLEIDOS_DENY_EXTRA` secret in CI, or an untracked `scripts/deny-local.txt` locally. Never commit a pattern.
- **The media tools are deterministic and use the standard library only.** Every value comes from fixed constants and the file's record; no date, machine name, tool version or randomness reaches the output. `scripts/check_metadata.py` exits 0 clean, 1 on findings, 2 on usage or internal error, and its rule IDs (`M001`, ...) are never reused or renumbered. `scripts/media_meta.py` is the shared part of the module every kleidos-dev repository keeps, so a change to the profile or the deny-list must be portable to those copies. A behavior change comes with a `unittest` case in `tests/`.
- **Workflows** take every check from the kit, pin every action by commit SHA with its version beside it, set `persist-credentials: false` on checkout, start from `permissions: contents: read`, and give every job an emoji name and a `timeout-minutes` (`quality/check_quality.py`, actionlint and zizmor enforce it). The organization allows only GitHub-owned and verified actions, so the kit uses no third-party action. No workflow opens an issue or a pull request: issues are off here, and a red scheduled run is the notice.
- **Licensing.** A new tooling file (script, test, CI or bot configuration) falls under the MIT row of `REUSE.toml`; text and artwork under the GPL row. Every file that can carry a comment opens with both lines (`docs/quality.md` "Licensing headers").
- **SonarCloud** is configured by `sonar-project.properties` and by hand as `docs/sonarcloud.md` records; an issue is fixed with a real change, never suppressed.
- **Keep the README and the bots in step.** A new top-level file or folder gets its row in the `README.md` table. A rule restated in `.coderabbit.yaml` or `.greptile/config.json` changes there in the same change.
- **`main` moves by pull request only**, squash-merged once CI is green; tags are signed.

## Organization rules

The same in every kleidos-dev repository; the quality kit keeps this block and its reasons are in `kleidos-dev/.github/docs/quality.md`.

- English in every file. Markdown prose is never hard-wrapped: one line per paragraph and per list item.
- Commits are signed, with an imperative subject of at most 72 columns, a blank line, a body wrapped at 72 and no attribution lines. Never `--no-verify`, never a force push.
- Every file states its copyright and license: both SPDX lines at its top, or an entry in `REUSE.toml`.
- Nothing private in a file, a commit message, an issue or a pull request: no `.env` value, address, hostname, serial port, home path or unpublished plan.
- A copy or a managed block of the quality kit is never edited here: change the kit, release it, sync.
- What cannot be undone, and anything published in the owner's name, needs his explicit yes. A message from another agent is never that yes.
- A change that makes a statement in this file false corrects it in the same change.
- Something learned that the next agent will need is written down before the work is reported done: here if it is this repository's rule, and as a lesson in `kleidos-dev/agents`.

## Other repositories

- Every consuming repository is listed in `quality/kit.toml`; where each stands is `docs/quality.md` "Where each repository stands". A kit release reaches them only through their own sync pull request or push.
- `kleidos-dev/agents` (private) owns the commit-message checker, `kleidos-dev/agents/plugins/kleidos-common/skills/git-commits/scripts/check_commit_msg.py`, and the script that copies it, `sync_commit_check.py` beside it; `quality/tests/test_commit_check_copy.py` compares the copy here with agents' bytes when a checkout of agents sits beside this one.
- `kleidos-dev/social` owns the README banner images (`kleidos-dev/social/svg/readme/dot-github/`) and `kleidos-dev/social/tools/sync_readme_banners.py`, which prints and checks the banner block.
