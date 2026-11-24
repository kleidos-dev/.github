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
- **Links.** Every link and banner of the public READMEs.
- **Settings** (local): rulesets and who may bypass them, required checks and the App each comes from, whom the CLA serves, deploy keys, Apps, immutable releases, Dependabot's entries, the SonarQube Cloud projects, the deployed Workers' `/version`.

## The declared list

A change of a setting is a change of [`ecosystem.toml`](../tools/ecosystem.toml) first. It holds what cannot be found by reading: the repositories and which are public, the limits in days, the required checks with their App, the rules of a protected branch, the Apps that may write, whom the CLA should serve, the SonarQube Cloud projects, the Workers, and `hold`, the repositories `land` leaves alone. A repository with `folds_into` is moving into another and will be deleted, so nothing is expected of its settings.

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

It copies the bytes, rewrites the digests, the date and the commit it notes, and refuses a frozen copy and a generator's output, which are made again instead. The consumer pulls; no script writes into another repository's checkout.

## Landing the bot's pull requests

`python tools/ecosystem.py land` says which of Dependabot's pull requests it would merge, and `--merge` merges them, one at a time. It merges third-party code under the caller's credential with nobody reading the diff, so it holds no standing credential, runs only by hand, and every guard must hold:

- opened by Dependabot from a branch of the same repository; every commit authored by Dependabot and signed by GitHub, but for the merges of `main` this command's own update made;
- only manifests, lock files, `uses:` lines of workflows and `rev:` lines of the hook list changed;
- no major version, as Dependabot's own commit states each update;
- never in this repository (a bump here is a kit release, by hand), nor in one on hold;
- its branch updated to today's `main`, a run on that, and everything that ran on it green.

[`tools/landing.py`](../tools/landing.py) is the code of it.
