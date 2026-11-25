<!--
SPDX-FileCopyrightText: 2026 José M. Requena Plens
SPDX-License-Identifier: GPL-3.0-or-later
-->

# The ecosystem report

One report says what is behind, what is broken and what nobody declared across the Kleidos repositories: [`tools/ecosystem.py`](../tools/ecosystem.py), which compares what it reads with one declared list, [`tools/ecosystem.toml`](../tools/ecosystem.toml). Being behind is a line in it, never a red check anywhere (owner, 2026-11-24).

## Contents

- [The two halves](#the-two-halves)
- [The states](#the-states)
- [What it reads](#what-it-reads)
- [The declared list](#the-declared-list)
- [The local report](#the-local-report)
- [Previewing a kit change](#previewing-a-kit-change)
- [Refreshing a copy](#refreshing-a-copy)
- [Landing a pull request](#landing-a-pull-request)
- [Landing the bot's pull requests](#landing-the-bots-pull-requests)

## The two halves

| | Public | Local |
| --- | --- | --- |
| Command | `python tools/ecosystem.py report` | `python tools/ecosystem.py report --all` |
| Runs | Weekly in [`ecosystem.yml`](../.github/workflows/ecosystem.yml), on demand, and as a trial on a pull request that changes it | Weekly from a timer on the owner's machine ([The local report](#the-local-report)) |
| Reads as | A token that reads this repository and what is public | The caller's own `gh` session, read-only |
| Covers | The public repositories | Every one, and the settings |
| Goes to | The job summary, and the badge on the organization's profile | A dated file and a notification; it is never posted |

The public half cannot leak what it cannot read, and does not name it either: it asks nothing about a repository the list does not call public, withholds any line that names one, and refuses to print if one is left. `--all` refuses to run in CI.

## The states

| State | When | The run |
| --- | --- | --- |
| Red | A copy edited in place, or whose source is gone; a bot's pull request with a failing check; `v<major>` not on `main`, or a tag named like a branch; a dead banner or link. Local only: a setting that is not what the list declares, an undeclared repository, an App that can write what it should not, a deployed Worker that has not been `main`'s tree for longer than its limit, the public report's schedule off | Fails |
| Late | A copy that follows its source and has differed for longer than its limit; a bot's pull request that has waited longer than its own | Passes; listed right after red |
| Amber | A copy that differs, a base configuration of any age, a repository on an older kit, a hook revision behind, a kit pin with a newer release | Passes |
| Frozen | A copy that is as old as the thing made from it, with its reason; no limit | Passes |
| Note | What could not be compared, and why | Passes |
| Green | Digests equal to the source's `main`, however many commits behind | Passes |

## What it reads

- **Copies.** The edges between repositories are not declared: the report finds them by reading every record of copies in the trees ([`quality.md`, "The base configurations"](quality.md#the-base-configurations), and the older dialects still in use). Digests decide; a copy's age is its `taken` date, else the day its record last changed.
- **The kit.** Which name each repository calls it by, the `rev` of its hooks against the newest release, whether the names are sound, and the kit's own pins against upstream.
- **Pull requests.** The open ones of bots.
- **Links.** Every link and banner of the public READMEs; and in every README it reads (the private ones too in the local run), a link to a repository that moves out (`folds_into`) or a banner served from it, which is red.
- **SonarCloud's quality gate** on `main` of each public repository with a project: red unless it passes. The kit's `📊 SonarCloud` job proves only that SonarCloud accepted the analysis; the gate is what SonarCloud's GitHub App reports on the commit, and no ruleset requires it, so a red gate on `main` is seen here.
- **Settings** (local): rulesets and who may bypass them, required checks, the App each comes from and whether they can be bypassed, whom the CLA serves, deploy keys, Apps, immutable releases, Dependabot's entries, whether each SonarQube Cloud project exists, the deployed Workers' `/version`.

## The declared list

A change of a setting is a change of [`ecosystem.toml`](../tools/ecosystem.toml) first. It holds what cannot be found by reading: the repositories and which are public, the limits in days, the required checks with their App, the rules of a protected branch, whom the CLA should serve, the SonarQube Cloud projects, the Workers, and `hold`, the repositories `land` leaves alone. A repository with `folds_into` is moving into another and will be deleted, so nothing is expected of its settings, and the report is red (`leaving`) while the README of any other repository it reads still links to it or shows a banner served from it; its entry goes with the deletion.

Which Apps may write, and what, is declared too but not published: `~/.config/kleidos/ecosystem.local.toml` on the machine of the local report, a table `[apps]` with the list of write permissions of each App (`--local` names another file). Without it the report says so in a note and compares no App.

## The local report

On the machine that has the `gh` session, from a checkout kept for it with its `.venv` ([`AGENTS.md`](../AGENTS.md), "Commands"):

```sh
# macOS
sed -e "s|@CHECKOUT@|$PWD|g" -e "s|@HOME@|$HOME|g" tools/timer/dev.kleidos.ecosystem.plist > ~/Library/LaunchAgents/dev.kleidos.ecosystem.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/dev.kleidos.ecosystem.plist

# Linux
mkdir -p ~/.config/systemd/user
sed "s|@CHECKOUT@|$PWD|g" tools/timer/kleidos-ecosystem.service > ~/.config/systemd/user/kleidos-ecosystem.service
cp tools/timer/kleidos-ecosystem.timer ~/.config/systemd/user/
systemctl --user enable --now kleidos-ecosystem.timer
```

Each run writes `~/kleidos-ecosystem/ecosystem-<date>.md` and raises a notification with the counts. The first line says how old the public report is. The weekly pass reads that file, runs `land`, and then the lessons inbox.

## Previewing a kit change

`python tools/ecosystem.py preview` clones each public repository (with `--all`, the private ones too, locally), applies the kit of this checkout and counts what it finds: the 2.x copies brought to it and judged as they are, what the drift notice would say, and the run form after the mechanical switch; a repository that has switched is judged as it stands. It changes nothing. The kit's CI runs the public half on every pull request and writes the table to the job summary; it informs, it does not gate.

## Refreshing a copy

In the repository that holds the copy, with a clean checkout of its source beside it (or `--from`):

```sh
python ../.github/tools/ecosystem.py refresh vendor/boards/SOURCE.json
python ../.github/tools/ecosystem.py refresh .github/quality/SOURCE.json   # the base configurations, from that checkout
```

It copies the bytes, rewrites the digests, the date and the commit it notes, and refuses a frozen copy and a generator's output, which are made again instead, a path under `.git/` or through a symbolic link, and a record or a file under `.github/` or at `.pre-commit-config.yaml`: workflows, actions, Dependabot's settings and the hook list are what GitHub and the hooks run, with the repository's token, and they change by a person's own edit. A path is compared as a file system that folds case and Unicode compatibility forms reads it (APFS opens `.github/workflowſ/` as `.github/workflows/`), and by what the file system resolves it to. The consumer pulls; no script writes into another repository's checkout.

## Landing a pull request

`python tools/ecosystem.py land OWNER/NAME#N` says what it would do with one pull request, and `--merge` does it, the way [`quality.md`, "Merging"](quality.md#merging) states: never a merge button, a push of signed commits, and never a forced one. It runs with the caller's own `gh` and git, whose identity has to be the owner's, in a clone of its own.

| The pull request | What happens |
| --- | --- |
| The owner's, from a branch of the repository | Judged (on top of `main`; every commit signed and verified, and the owner's where it says it is, by [`hooks/commit_identity.py`](../hooks/commit_identity.py); no merge commit; what has to be read was), waited for until nothing that runs on its head is left, judged again, pushed to `main` as it is, and confirmed: GitHub says it is merged |
| A person's, from a fork or a branch here, signed and on top of `main` | Judged (its checks green on its head, the CLA among them where it is required; its messages within the rules; no merge commit; no commit that says it is the owner's and is not), judged again, pushed to `main` as it is, with its author, committer and signature, and confirmed |
| A person's, not signed or behind `main` | Judged the same, then taken: each commit on today's `main` with its author, committed and signed by the owner, on `land/pr-N` with a pull request of its own |
| Dependabot's | The guards below, then taken as one commit of the owner's, and landed |

- `--read SHA` says that the part of the diff a green gate proves nothing about (`.github/`, `.pre-commit-config.yaml`) was read line by line at that head. Of an update of Dependabot's it says the whole diff was read: the update is taken, whatever it changes, and its own pull request lands by name.
- The push is a plain one, so GitHub refuses it if `main` moved in the last second.
- A pull request that was taken stays open when its own does not land; the branch `land/pr-N` is never written twice.
- A person's pull request whose checks are not green yet is left, not waited for.
- A branch that is exempt from the identity of its commits, and a repository on `hold`, are never landed on; this repository's own pull requests land by name, and its bot's by hand.
- What it cannot do: a repository whose jobs GitHub does not start, which lands by hand.

[`tools/fast_forward.py`](../tools/fast_forward.py) is the code of it.

## Landing the bot's pull requests

`python tools/ecosystem.py land` says which of Dependabot's pull requests it would land, and `--merge` lands them, one at a time. It puts third-party code under the owner's key with nobody reading the diff, so it holds no standing credential, runs only by hand, and every guard must hold:

- opened by Dependabot from a branch of the same repository; every push to that branch Dependabot's or the caller's, on GitHub's own record of them; every commit authored by Dependabot and signed by GitHub, but for merges of `main` by the caller;
- nothing under `.github/`, whoever changed it: a pull request brings its own workflows, so `✅ Check` proves nothing there ([`quality.md`, "Merging"](quality.md#merging));
- only `requirements*.txt` and `.in`, `pyproject.toml`, `package.json` and `package-lock.json` changed, read line by line, every block of every hunk: each new line is its old one but for the version, a range, the checksum, or the version in an address of `registry.npmjs.org`. A version is masked only where it is a package's, after the package's name and one of pip's operators, and in each further bound a comma adds to that requirement, so a number after a bare `=` or after a quote is compared whole (Poetry's `python = "<4,>=3.12"` among them). In `package.json`, a changed line that names a version names a package one of Dependabot's commits says it updates (the name read without the quotes Dependabot puts around a scoped one, `"@types/node"`), so no engine, whatever its name (`vscode`, `deno`), and not the project's own `version`. A package that was not there, another license, host, option or script is left to a person, and so is the hook list (Dependabot's commits for it do not say what each update is, and it read a sub-crate's tag as a typos release once);
- no floor and no index moves: a changed line naming a coverage threshold (`fail_under`, `--cov-fail-under`), the oldest Python (`requires-python`, `python_requires`, Poetry's `python`) or uv (`required-version`), a package index or source (`--index-url`, `-i`, `--extra-index-url`, `--find-links`, `--trusted-host`, `-c`, a `[[tool.uv.index]]`-like table), or, in `package.json`, an engine (`node`, `npm`, `pnpm`, `yarn`, `bun`), `engines`, `registry` or `packageManager`, is left to a person (a lock's engines of its dependencies move with their versions);
- no major version, as each of Dependabot's commits states each update;
- never in this repository (a bump here is a kit release, by hand), nor in one on hold;
- taken as a signed commit of the owner's on today's `main`, in a pull request of its own that changes no more than the bot's by the same reading, everything that runs on that green, and the gate, `✅ Check` of GitHub Actions, among it (a repository that has not switched has none, so nothing lands there).

[`tools/landing.py`](../tools/landing.py) is the code of the guards.
