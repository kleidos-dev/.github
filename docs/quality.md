<!--
SPDX-FileCopyrightText: 2026 José M. Requena Plens
SPDX-License-Identifier: GPL-3.0-or-later
-->

# The Kleidos quality kit

One place holds the rules every Kleidos repository meets, the configuration of every analysis tool that enforces them, and the CI jobs that run those tools: this repository, in [`quality/`](../quality/) and the `reusable-*.yml` workflows of [`.github/workflows/`](../.github/workflows/). Every repository consumes it the same way, may add rules of its own, and cannot weaken a shared rule without writing down why. A rule change is one pull request here and one sync pull request in each repository.

The kit uses free tools only (owner, 2026-11-22). SonarCloud stays on every public repository; the kit runs its analysis job but never touches a project's settings.

## Contents

- [How a repository consumes the kit](#how-a-repository-consumes-the-kit)
- [Adopting the kit in a repository](#adopting-the-kit-in-a-repository)
- [The rules](#the-rules)
- [Licensing headers](#licensing-headers)
- [Reusable workflows](#reusable-workflows)
- [Overrides](#overrides)
- [Versions](#versions)
- [Taking a new kit release](#taking-a-new-kit-release)
- [Changing the kit](#changing-the-kit)
- [Outside the kit: Socket, CodeQL, SonarCloud](#outside-the-kit-socket-codeql-sonarcloud)
- [Where each repository stands](#where-each-repository-stands)

## How a repository consumes the kit

Four mechanisms, chosen per tool by what the tool can do:

| Mechanism | What the repository holds | Used for |
| --- | --- | --- |
| Copy | The kit's file, byte for byte, recorded by SHA-256 | Tools that can point at another file (`ruff` `extend`, ESLint import, `tsconfig` `extends`, markdownlint `extends`, gitleaks `--config`, clang-tidy's parent config) and the kit's own scripts |
| Managed block | A region of kit text inside a file the repository owns, between `# >>> kleidos-quality <id>` and `# <<< kleidos-quality <id>` | Tools that read one file and have no include: mypy (`[tool.mypy]` in `pyproject.toml`), typos (`[default]` in `.typos.toml`), pre-commit (the hook list) |
| Reusable workflow | A thin caller job: `uses: kleidos-dev/.github/.github/workflows/reusable-<x>.yml@<kit commit>` | Every CI check |
| Conformance rule | Nothing: `check_quality.py` reads the repository's own configs | Weakenings no copy or block can prevent (a local `select`, an ignore, a `-check`, a `continue-on-error`) |

Everything a repository took from the kit is recorded in `.github/quality/SOURCE.json`: the kit version, the kit commit, the profiles, and the SHA-256 of every copy and every block. Every call to a kit workflow names that same commit, so a repository is at exactly one kit version for configs and CI alike. That commit is always a release: the merge commit on `main` that the tag `quality-v<VERSION>` names, the only commit `sync.py --write` records (zizmor's online `ref-version-mismatch` audit checks every `# quality-v<VERSION>` comment beside a kit SHA against that tag). kleidos-dev/agents' commit-check copies and their digest test are the model this follows.

`.github/quality/` holds the kit's copies, `SOURCE.json` and `waivers.toml`, and nothing else: any other file there, a `SOURCE.json` entry that is not one of the kit's copy targets, and a `.github/commit-check/SOURCE.json` entry other than the commit-message checker and its two workflows are reported, so no file escapes the checks by being parked or listed there.

Profiles say what applies: `base` (every repository), `python`, `actions`, `shell`, `ts`, `cpp`. They are detected from the tree, and the checker fails when the tree holds a language whose profile is not adopted.

| Profile | Copies | Blocks | Seeded once |
| --- | --- | --- | --- |
| base | `check_quality.py`, `md_nowrap.py`, `spdx_headers.py`, `markdownlint.jsonc` (all in `.github/quality/`), `.gitleaks-mac.toml` | `pre-commit-base`, `typos` | `.gitleaks.toml`, `.github/quality/waivers.toml`, `.markdownlint-cli2.jsonc`, `quality-drift.yml`, the two commit-check callers |
| python | `.github/quality/ruff.toml`, `.github/quality/mypy_groups.py` | `pre-commit-python`, `mypy` | |
| actions | `.github/zizmor.yml` | `pre-commit-actions` | |
| shell | `.shellcheckrc` | `pre-commit-shell` | |
| ts | `.github/quality/eslint.base.mjs`, `.github/quality/tsconfig.base.json` | | |
| cpp | `.clang-tidy` (the root one) | | |

A seeded file is written once, when the repository has none, and is the repository's own from then on, held to the conformance rules. The two commit-check callers also replace a repository's copies of kleidos-dev/agents' `commit-check.yml` and `commit-check-comment.yml` (see [The commit-message gate](#the-commit-message-gate)).

The kit's tool pins, [`quality/requirements-tools.txt`](../quality/requirements-tools.txt), are not copied: every kit workflow installs them from the kit at the recorded commit, and a copy would only have put about 30 pinned packages into every repository's dependency graph, where one advisory against a tool's dependency would turn every repository's OSV gate red at once. Locally, install them from a kit checkout beside the repository: `pip install --require-hashes -r ../.github/quality/requirements-tools.txt`. A sync removes a copy the kit no longer makes.

### The commit-message gate

One owner per file. kleidos-dev/agents owns the checker, `check_commit_msg.py`, and the `kleidos-commit-msg` hook entry: its `sync_commit_check.py` copies the checker into each repository's `.github/commit-check/`, recorded in that repository's `.github/commit-check/SOURCE.json`, for the commit-msg hook. The kit owns the CI side: the two workflows are seeded thin callers of [`reusable-commit-check.yml`](../.github/workflows/reusable-commit-check.yml) and [`reusable-commit-check-comment.yml`](../.github/workflows/reusable-commit-check-comment.yml), which run the checker kleidos-dev/.github carries at the recorded kit commit. This repository's copy is recorded in its own [`.github/commit-check/SOURCE.json`](../.github/commit-check/SOURCE.json) (agents' commit and the SHA-256) and held there by [`quality/tests/test_commit_check_copy.py`](../quality/tests/test_commit_check_copy.py), which also reads agents' bytes at that commit when agents is checked out beside it, so the CI's checker and every hook's checker are the same file. A checker change is an agents change, then a copy here and a kit release.

## Adopting the kit in a repository

1. Clone kleidos-dev/.github beside the repository and check out the newest release: `git fetch --tags origin && git checkout quality-v$(cat quality/VERSION)` on an up-to-date `main` (or the newest `quality-v*` tag). `sync.py --write` records `HEAD`, refuses a dirty tree, and refuses any commit that is not exactly the tag `quality-v<quality/VERSION>` on `origin/main` (`--allow-untagged` exists for throwaway trees only).
2. Run the sync, naming any profile detection would miss and, if the repository has a test suite, where the drift test goes:

   ```bash
   python3 ../.github/quality/sync.py --write . --test-dir tests
   ```

   It writes the copies, the blocks and the seeded files, points every call to a kit workflow at the commit, records it all in `.github/quality/SOURCE.json`, and then runs the check. A key the repository set in a table the block now opens (say `strict = false` under `[tool.mypy]`) is moved out and listed, so a kit setting can never be overridden by a duplicate key.
3. Point the tools at the copies, in the repository's own files:
   - `pyproject.toml`: `[tool.ruff]` with `extend = ".github/quality/ruff.toml"` and `target-version`; `[tool.mypy]` (which now opens with the kit block) with `python_version`, `files` naming every Python root, `mypy_path` where needed, and an `[[tool.mypy.overrides]]` with `ignore_missing_imports = true` only for packages that ship no types and have no `types-*` stub, each with a comment above saying so.
   - A `.markdownlint.json` that exists for the review bots says `"extends": ".github/quality/markdownlint.jsonc"` too (markdownlint-cli2 lets it override `.markdownlint-cli2.jsonc`).
   - TypeScript: `tsconfig.json` extends `.github/quality/tsconfig.base.json`; `eslint.config.js` imports `kleidosTypeScript` from `.github/quality/eslint.base.mjs` and passes it its own `js` and `tseslint`.
   - C++: the root `.clang-tidy` is the kit's; repository specifics go in a subdirectory's `.clang-tidy` with `InheritParentConfig: true`.
4. Replace the CI with thin callers. [`quality/templates/workflows/check.yml`](../quality/templates/workflows/check.yml) is the model: lint and licensing first, then types, tests, OSV and the history scan side by side, then SonarCloud (public repositories). A `ts` repository adds the [`reusable-eslint.yml`](../.github/workflows/reusable-eslint.yml) caller (its `working-directory` and tsconfig `projects`); a `cpp` repository keeps a job of its own that runs clang-tidy with the kit's `.clang-tidy` on every pull request, because clang-tidy needs the repository's build (meter's static-analysis job already does). Keep the repository's own jobs (a model build, a firmware build, a picture check) beside them. Each caller of a kit workflow sits in a workflow that runs on `pull_request` and `push` to `main` (with no `paths` filter), carries no `if:` but the model's `github.event_name != 'schedule'`, and needs no job that does; the commit-check, comment and drift callers keep their seeded triggers. Every job keeps the CI conventions: an emoji name, `timeout-minutes` (a caller job's comes from the called workflow), staged `needs:`, least `permissions`. Re-run `sync.py --write .` after editing, so the new calls name the recorded commit.
5. `.github/dependabot.yml`: every manifest directory has its ecosystem; every update has a `cooldown` (`default-days: 7`, which zizmor's `dependabot-cooldown` audit also asks for); `github-actions` ignores `kleidos-dev/.github*` (the sync moves those references); no `pre-commit` ecosystem (hook versions come with the sync); nothing under `.github/quality/`. Turn on Dependabot security updates: `gh api -X PUT repos/<owner>/<repo>/automated-security-fixes`.
6. A repository with the `python` profile has a `.python-version` (the kit's mypy and test workflows read it; the checker reports its absence), naming the latest stable Python ([Pins at the latest release](#pins-at-the-latest-release)).
7. The commit-message gate: where the sync replaced kleidos-dev/agents' two workflow copies, it also drops them from `.github/commit-check/SOURCE.json` and says so; edit the repository's own digest test (`tests/ci/test_commit_check_copy.py` in qa and meter) so its path set is the checker alone, in the same pull request. kleidos-dev/agents' `sync_commit_check.py` then copies only the checker (its `FILES` reduced to `check_commit_msg.py`, and its `--check` no longer reporting the two workflows): that change lands in agents' own sync, which goes first in wave 3, before qa's and meter's ([The commit-message gate](#the-commit-message-gate)).
8. Fix everything the tools report, in the same pull request: `pre-commit run --all-files`, `python3 .github/quality/mypy_groups.py` (mypy, per group where the repository declares [mypy groups](#mypy-groups)), `python3 .github/quality/spdx_headers.py --write` for the licensing headers, `reuse lint`. A waiver only where [Overrides](#overrides) allows one. A first `ruff format` of the whole tree is its own commit, listed in `.git-blame-ignore-revs`.
9. Install the hooks (`pre-commit install --hook-type pre-commit --hook-type commit-msg`), commit signed, and merge once CI is green.

The checker, offline, is the pre-commit hook `kleidos-quality`; with the kit beside it, `python3 ../.github/quality/sync.py --check .` compares the copies with the kit's working tree.

## The rules

Each rule below is enforced by the tool named, with the kit's configuration; the reason is why the estate holds it.

### Python (profile `python`)

| Rule | Enforced by | Why |
| --- | --- | --- |
| ruff with the kit's rule set: `E`, `F`, `W`, `I`, `B`, `UP`, `SIM`, `PLE`, `PLW`, `BLE001`, `DTZ`, `ASYNC`, `RUF012`, `RUF100`, `C4`, `PIE`, `RET`, `PERF`, `S`, `PGH003`, `PGH004`; line length 100; `S101`, `S105`, `S106` allowed in tests | `ruff check` (hook and lint job), [`quality/ruff/ruff.toml`](../quality/ruff/ruff.toml) | The bug-finding sets of the analyzer proposal (subprocess calls without `check=`, overwritten loop variables, naive datetimes, bare `except Exception`, Python syntax newer than the declared floor). `S603` and `S607` are off kit-wide: they flag every argument-list subprocess call and every call by program name, so they cannot tell a safe call from an unsafe one; the shell forms stay on. |
| One formatting: `ruff format` | hook `ruff-format` | No style review; diffs show only changes. |
| A local `select` is refused; a local `include` needs a waiver | `check_quality.py` | `select` would replace the kit's list instead of adding to it (use `extend-select`); `include` replaces ruff's file list and can narrow it to nothing. |
| mypy strict, `ignore-without-code` | mypy block, [`reusable-mypy.yml`](../.github/workflows/reusable-mypy.yml) | Owner, 2026-11-22: mypy, as in phonometry, with every error fixed and no baseline. The block is phonometry's floor: `strict = true`, `enable_error_code = ["ignore-without-code"]`. |
| mypy checks every tracked Python file | `check_quality.py` (`files` minus `exclude`, or the [mypy groups](#mypy-groups), must cover every `*.py`) | A checker that skips a directory reports nothing about it, and that silence reads as green. |
| One mypy run never holds a module name twice | `check_quality.py` (the name mypy gives each file: its packages, then its stem) | mypy stops at "Duplicate module named" and checks nothing more, so two loose `score.py` in one run hide every error of the run. The fix is [mypy groups](#mypy-groups). |
| No mypy suppression beyond missing types | `check_quality.py`, no waiver | `[tool.mypy]` takes an allowlist: the facts about the repository (`python_version`, `platform`, `files`, `mypy_path`, `exclude`, `plugins`, `namespace_packages`, `explicit_package_bases`, `python_executable`, extra `enable_error_code`, `overrides`), the settings that only change how mypy reports (`pretty`, `show_*`, `cache_dir`, ...), stricter flags set true (`strict_*`, `warn_*`, `disallow_*`, `check_untyped_defs`, `no_implicit_*`, `extra_checks`, `local_partial_types`), `implicit_reexport`, `implicit_optional` and `follow_untyped_imports` set false, and `follow_imports` as `normal` or `error`. Anything else is refused: `ignore_errors`, `disable_error_code`, `always_false` and `always_true` (they hide whole branches), `untyped_calls_exclude`, `follow_imports = skip`, `allow_*`, a strict flag set false. So are an inline `# mypy:` configuration and an override that sets anything but `ignore_missing_imports`. |
| An inline `# type: ignore[code]  # reason` | `check_quality.py`, mypy's `warn_unused_ignores` | Names what it silences, says why, and dies when it silences nothing. |

#### mypy groups

mypy names a file in a folder with no `__init__.py` after the file alone, so a repository of loose scripts whose folders repeat file names (a `score.py` per video) cannot pass one mypy run over the tree. It declares groups instead, in `pyproject.toml` beside its `[tool.mypy]`, and each group is one mypy run:

```toml
[[tool.kleidos-quality.mypy-groups]]
name = "video-01"
files = ["youtube/video-01/source"]

[[tool.kleidos-quality.mypy-groups]]
name = "keys"
files = ["youtube/music-styles/keys/*.py"]   # the folder's files, not its test-cue/ subfolder

[[tool.kleidos-quality.mypy-groups]]
name = "keys-cue"
files = ["youtube/music-styles/keys/test-cue"]
```

- A group is a `name` (`[a-z0-9][a-z0-9._-]*`, unique) and its `files`: folders, files, or globs as mypy's own `files` reads them. It sets nothing else, so every run reads the same `[tool.mypy]`, the kit's strict block included, and no group can weaken it; `[tool.mypy]` sets no `files` beside groups. `check_quality.py` refuses any other key, in a group or in `[tool.kleidos-quality]`, with no waiver.
- Every tracked Python file is in exactly one group, after `[tool.mypy] exclude`: a file in none, or in two, is reported, and so is a group folder or glob that holds no Python file. Within a group no two files may be the same module.
- [`mypy_groups.py`](../quality/mypy_groups.py) runs them: one mypy per group, in its own cache directory (`<cache_dir>/<group>`, as two groups may each hold a `score`), every group even after one fails, passing mypy the group's paths and nothing else. Without groups it runs a bare `mypy`. Locally the `mypy` hook runs it; `python3 .github/quality/mypy_groups.py --group video-01` runs one group. Exit status 1 when mypy found errors, 2 for a bad declaration, mypy missing, or a run mypy could not finish.

### Workflows and shell (profiles `actions`, `shell`)

| Rule | Enforced by | Why |
| --- | --- | --- |
| actionlint | hook `actionlint` | Syntax, expressions, and shellcheck inside every `run:`. |
| zizmor, offline in the hook and online in the lint job | hook `zizmor`, [`reusable-lint.yml`](../.github/workflows/reusable-lint.yml), [`quality/zizmor/zizmor.yml`](../quality/zizmor/zizmor.yml) | Workflow security: template injection, credentials left by checkout, cache poisoning, excessive permissions. Every `uses:` is pinned by commit SHA, GitHub's own actions included (the trivy-action tag rewrite of 2026-03-19 is the risk). The `self-repository` audit is off kit-wide: it asks for `uses: $/...`, which actionlint 1.7.12 rejects. |
| A zizmor finding is accepted only inline: `# zizmor: ignore[<rule>]` with the reason on the line above | `check_quality.py` | The repository's `zizmor.yml` is the kit's copy, so there is no ignore list to grow. |
| CI conventions: an emoji first in every job name, a `timeout-minutes` on every job that runs steps, every `uses:` pinned by a 40-hex SHA with its version in a comment, no `continue-on-error: true` on a job | `check_quality.py` | The owner's conventions, now checked. A job with `continue-on-error` is green whatever it finds. |
| Every check comes from the kit, and runs | `check_quality.py`, no waiver (the base profile's kit workflows, `reusable-mypy.yml` with `python`, `reusable-eslint.yml` with `ts`, `reusable-sonarcloud.yml` where `sonar-project.properties` exists; with `cpp`, a job of the repository's own whose `run:` calls clang-tidy) | One definition of each check, so a fix reaches every repository. The workflows are parsed, not searched: a caller counts only in a workflow that runs on `pull_request` and on `push` to `main` with no `paths` filter, and only if neither it nor a job it needs carries an `if:` other than `github.event_name != 'schedule'` (the commit-check, comment and drift callers keep their seeded `pull_request`, `workflow_run` and `schedule` triggers). A caller with `if: false`, a check run only by hand, or one the pushes to `main` never run is reported. |
| The lint caller skips only the repository's own hooks | `check_quality.py` and [`reusable-lint.yml`](../.github/workflows/reusable-lint.yml) itself (`--lint-skip`, read against the kit's blocks at the recorded commit), no waiver | `skip` exists for a repository hook that needs a secret; a kit hook named there would switch a shared rule off. |
| Nothing above the hooks switches them off | `check_quality.py` | A top-level `exclude:` or `files:` in `.pre-commit-config.yaml` narrows every hook, the kit's included: a weakening that needs a waiver (`tool = "pre-commit"`). A `default_stages` without `pre-commit` stops them running at all: refused, no waiver. |
| shellcheck at warning severity | hook `shellcheck`, [`quality/shellcheck/shellcheckrc`](../quality/shellcheck/shellcheckrc) | Quoting and word-splitting bugs; notes and style stay out. |

### Every repository (profile `base`)

| Rule | Enforced by | Why |
| --- | --- | --- |
| Spelling, US English | hook `typos` (report only: a spelling "fix" in code is a bug), the typos block (`locale = "en-us"`) | The estate's prose and identifiers use US spelling; typos also catches misspelled identifiers. |
| Secrets: every default gitleaks rule, over the tree and the whole history | hooks `gitleaks`, [`reusable-secrets.yml`](../.github/workflows/reusable-secrets.yml) | Private repositories get no GitHub secret scanning on the Free plan. |
| MAC addresses: the kit's MAC rules | hook `gitleaks-mac`, `.gitleaks-mac.toml` (a copy of [`quality/gitleaks/mac.toml`](../quality/gitleaks/mac.toml)), the plant test | The bench's board MACs are private. The MAC config extends nothing, so the default allowlist (images, fonts, lockfiles) never hides a MAC; the plant test proves the rules still fire on real shapes and spare the fakes. |
| `.gitleaks.toml`: `useDefault = true`, no `disabledRules`, no global `[allowlist]`, every `[[allowlists]]` with a `description` and `targetRules`; every `.gitleaksignore` fingerprint with a comment above it; scans run with `--ignore-gitleaks-allow` | `check_quality.py`, no waiver | An allowlist that reaches every rule hides the next real secret. |
| Known vulnerabilities fail the build | [`reusable-osv.yml`](../.github/workflows/reusable-osv.yml) (OSV-Scanner over every manifest and lockfile, also weekly) | Advisory-only scanning was ignored. An accepted one goes in `osv-scanner.toml` with a `reason` and an `ignoreUntil` at most 90 days ahead (`check_quality.py`). |
| Dependabot covers every manifest, each update with a cooldown | `check_quality.py` | A directory without its ecosystem never gets a security update; a week's cooldown gives a compromised or yanked release time to be noticed. |
| Licensing: `reuse lint`, and the header lines | [`reusable-reuse.yml`](../.github/workflows/reusable-reuse.yml), hooks `reuse` and `kleidos-spdx-headers`, `check_quality.py` (a `.license` sidecar is a weakening, `tool = "reuse"`) | See [Licensing headers](#licensing-headers). |
| Markdown prose is never hard-wrapped | hook `kleidos-md-nowrap` ([`quality/md_nowrap.py`](../quality/md_nowrap.py)) | Owner, 2026-11-16: one line per paragraph and per list item. |
| Markdown tables render: MD055, MD056, MD058 only | hook `markdownlint-cli2`, [`quality/markdownlint/base.jsonc`](../quality/markdownlint/base.jsonc) | Broken tables are the findings that matter; the rest of markdownlint's defaults measured as noise. |
| The kit is intact | hook `kleidos-quality`, the lint job | Every copy and block is the bytes `SOURCE.json` records and, in CI, the bytes the kit holds at that commit (the CI fetches the checker from the kit, so an edited local checker cannot pass itself). `.github/quality/` holds nothing else, and `SOURCE.json` records only the kit's copy targets, each from its own source, offline too. |
| Python repositories name their Python | `check_quality.py` (`.python-version`) | The kit's mypy and test workflows read it; without it the first CI run fails in setup-python. |
| Every pin at the latest stable release | `check_quality.py` (the pin rule), waivable as `tool = "pins"` only with a reason beside the pin; the kit's weekly `📦 Pinned versions current` job ([`quality/latest_releases.py`](../quality/latest_releases.py)) | Owner, 2026-11-23. See [Pins at the latest release](#pins-at-the-latest-release). |
| Commit messages | [`reusable-commit-check.yml`](../.github/workflows/reusable-commit-check.yml), the `kleidos-commit-msg` hook | kleidos-dev/agents' gate: 72 columns, imperative, no AI attribution. |

### Pins at the latest release

Owner, 2026-11-23: every pinned version is the latest stable release, and whatever cannot move has its blocker fixed; only what truly cannot move stays lower, with its reason beside the pin. `check_quality.py` holds every repository to the newest releases this kit release knows, the kit's own pins (a kit test keeps them equal):

- **Python** (`LATEST_PYTHON`, 3.15): the first version line of every `.python-version`; `target-version`, `python_version` and `requires-python` (its lower bound) in `pyproject.toml`, `ruff.toml` and `.ruff.toml`; every `python-version:` in a workflow, inline or as a block list, and the matrix key a `python-version: ${{ matrix.<key> }}` reads, in that job only (its inline list, block list or `include:` entries).
- **Actions** (`LATEST_ACTIONS`): every `uses:` of an action the kit itself pins, by the version in its comment (`# v7.0.1`); an action the kit does not use is left to Dependabot.
- **Hook revisions** (`LATEST_HOOKS`): every `rev:` of a hook repository the kit's blocks use, by its `# frozen: vX.Y.Z` comment (or the rev, when it is a tag); a bare commit SHA with no tag beside it is reported, since nothing says which release it is.
- **Pins a submodule supplies**: a requirements or constraints file (`requirements*.txt`, `*.in`, or one under a `requirements/` folder) that includes a file of a git submodule (`-r brand/requirements.txt`, `-c`) takes that file's pins at the commit the submodule is recorded at, so that commit is a pin too. With the kit (`--kit`, as the CI runs it) the checker fetches the submodule's upstream (`.gitmodules`' `url`, its `branch` or else the default branch) and reads the included file, and every file it includes in turn, at the recorded commit and at the branch tip; a pin the tip adds, drops or moves is a finding until the submodule moves to the tip (`what = "submodule:<path>@<short commit>"`, the reason on the include line or right above it). A pin under an environment marker (`foo==1 ; sys_platform == 'win32'`) is compared per marker. A submodule at the tip, or a tip that changes no pin, is clean; an upstream that cannot be fetched, or a `branch` that is not a plain branch name, is a finding (the URL and branch come from the checked tree, so neither reaches `git fetch` as an option). Offline (the pre-commit hook) it fetches nothing and says so in a note.

A pin below them is a finding. When it truly cannot move, write the reason beside it, on its line or in the comment lines right above it (for a hook, above its `- repo:` line too), after the marker `below-latest:`:

```yaml
      - uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
        with:
          # below-latest: the skills' scripts run on the python3 macOS ships (3.9)
          python-version: "3.9"
```

and it becomes a weakening that also needs its waiver, `tool = "pins"`, `what = "python:3.9"` (or `action:<owner>/<repo>@<version>`, `hook:<url>@<version>`, `submodule:<path>@<short commit>`, as the finding names it). A reason without the marker, or a marker without a waiver, does not pass. A `.python-version` takes the comment on the line above its version (pyenv, uv and setup-python skip `#` lines).

The kit's weekly `📦 Pinned versions current` job ([`quality/latest_releases.py`](../quality/latest_releases.py)) compares the kit's pins with upstream: the newest stable CPython setup-python serves, each action's and hook repository's latest release (its newest version tag when it publishes no release), each PyPI tool of `requirements-tools.in`, and each `tools.lock` binary. A newer one turns the job red; moving it is a kit release that bumps the pin, its `LATEST_*` entry, `quality/VERSION` and the changelog, and the sync carries it to every repository. Dependabot's seven-day cooldown still paces its own pull requests; the job reports a release as soon as it is out.

The kit's own Python is 3.15 as well: its scripts are formatted for it (PEP 758 `except` clauses without parentheses need 3.14 or newer), so a repository that takes a 2.x release runs its CI and hooks on 3.15, as the pin rule asks anyway. SonarQube Cloud lists Python up to 3.14, so `sonar.python.version` stays 3.14 with its reason beside it ([`sonarcloud.md`](sonarcloud.md)).

### TypeScript and C++ (profiles `ts`, `cpp`)

| Rule | Enforced by | Why |
| --- | --- | --- |
| ESLint `strictTypeChecked` plus `no-deprecated` and `switch-exhaustiveness-check`, and `tsc` on every project | [`quality/eslint/base.mjs`](../quality/eslint/base.mjs), [`reusable-eslint.yml`](../.github/workflows/reusable-eslint.yml) (`npm ci`, `eslint --max-warnings 0 .`, `tsc --noEmit -p` per project), `check_quality.py` (a base rule set to `off` or `warn` locally, `disableTypeChecked`, and an `ignores:` entry other than build output such as `dist/**`, `node_modules/**`, `.wrangler/**` are weakenings) | Type-aware bugs Sonar does not see. ESLint and its plugins stay the repository's dependencies. |
| `tsc` strict flags: `strict`, `noUncheckedIndexedAccess`, `noImplicitOverride`, `noFallthroughCasesInSwitch`, `noImplicitReturns`, `exactOptionalPropertyTypes`; no `baseUrl` | [`quality/tsconfig/base.json`](../quality/tsconfig/base.json), `check_quality.py` | `baseUrl` stops working in TypeScript 7 (TS5101). |
| clang-tidy base with `clang-analyzer-*`, `concurrency-mt-unsafe`, `misc-no-recursion`, `WarningsAsErrors: '*'` | [`quality/clang-tidy/base.yaml`](../quality/clang-tidy/base.yaml), `check_quality.py` (a local `-<check>` is a weakening; a pull-request job of the repository's own must run clang-tidy) | The path-sensitive analyzer never ran in either C++ repository. clang-tidy needs the repository's build (its compile database), so the job stays local; naming prefixes and header filters stay local too. |
| `NOLINT(<check>): <why>`, `eslint-disable-next-line <rule> -- <why>` | `check_quality.py` | A suppression names what it silences and why. |

clang-format is not in the kit yet: meter and the firmware use different styles.

## Licensing headers

Owner, 2026-11-22. Every file that can carry a comment starts with both REUSE lines, in its comment syntax, copyright first:

<!-- REUSE-IgnoreStart -->

```text
SPDX-FileCopyrightText: <year> José M. Requena Plens
SPDX-License-Identifier: <the repository's license for the file>
```

<!-- REUSE-IgnoreEnd -->

- `<year>` is the year of the file's first commit, as `git log --diff-filter=A --format=%ad --date=format:%Y -- <file>` gives it (read in UTC), and the current year for a file not committed yet. The check also accepts the year before: the public repositories merge by squash, so a file added in a pull request written in December and merged in January lands on `main` with a January commit, and its header, written in December, must not turn `main` red. A pull request that crosses the new year needs nothing else; the writer always sets the first-commit year.
- At least one copyright line names José M. Requena Plens. A third-party file is stated in `REUSE.toml` with `precedence = "override"` instead.
- No e-mail address, in a file or in `REUSE.toml`.
- The license stays the one each repository already declares (MIT, GPL-3.0-or-later, ...).
- A file that cannot carry a comment (images, JSON, binaries, lockfiles, generated data) gets both lines through a `REUSE.toml` annotation (`SPDX-FileCopyrightText` and `SPDX-License-Identifier`), never a `.license` sidecar unless `REUSE.toml` cannot express it. So does a file `REUSE.toml` covers with `precedence = "override"`: third-party text, the kit's managed-block sources, and the pull request template, whose text GitHub copies into every pull request.
- The lines sit in a comment at the top of the file: in Markdown and HTML an HTML comment at the top (after any front matter, XML declaration or doctype); in CSS and linker scripts a block comment; in an Astro component `//` lines at the top of its front matter (an HTML comment in its template would reach every page that renders it; the writer opens a front matter where there is none); elsewhere line comments, after a shebang or an encoding line. Lines further down, or inside a docstring, do not count.
- A text file in a format the check has no comment syntax for (JSON, SVG, a KiCad file, a TSV, a `.python-version`) is named in a `REUSE.toml` annotation of its own, by path or by format (`**/*.json`), not only by the catch-all `**`: the check lists every such file, so a new format is a decision, either its syntax added to [`spdx_headers.py`](../quality/spdx_headers.py) or an annotation. A file with a shebang is a script and takes `#` lines whatever its name. Formats that take comments include ESP-IDF's `sdkconfig*`, `Kconfig*`, partition tables (`partitions*.csv`) and linker fragments (`.lf`), `Doxyfile` and `.dox`, `.supp`, `.S`, `.ld`, `.cppcheck-suppress` and `.git-blame-ignore-revs`.

`reuse lint` proves that every file states both, in the file or in `REUSE.toml`; [`quality/spdx_headers.py`](../quality/spdx_headers.py) proves that every file that can carry a comment states them itself, in order, with the right year and no e-mail. Both run in [`reusable-reuse.yml`](../.github/workflows/reusable-reuse.yml), which fetches the whole history for the years, and as hooks. Kit copies keep the kit's year and are checked for presence only; in a shallow clone only presence is checked.

To add or repair the lines, with the year from git and the license from the file's own line, else its `REUSE.toml` annotation, else `--license`:

```bash
python3 .github/quality/spdx_headers.py --write            # every file
python3 .github/quality/spdx_headers.py --write 'src/**'   # some
```

The sync writes seeded files with the current year. A template or generator that emits files (a skill's file template, a script that writes a `REUSE.toml` annotation) writes both lines.

## Reusable workflows

Every check a repository runs is a job of the kit, one workflow per concern, in the style of jmrplens/gitlab-mcp-server (whose release workflow calls separate files). A repository keeps only thin callers; its own steps that cannot be shared stay local jobs.

| Workflow | Job | Inputs | Caller permissions |
| --- | --- | --- | --- |
| [`reusable-lint.yml`](../.github/workflows/reusable-lint.yml) | The kit check (from the kit at the recorded commit), every pre-commit hook on every file (mypy, reuse and the header lines excepted: they have their own workflows), zizmor's online audits | `skip` (the repository's own hook ids that need a secret; a kit hook id fails the kit check), `python-version` | `contents: read` |
| [`reusable-reuse.yml`](../.github/workflows/reusable-reuse.yml) | `reuse lint`, then the header lines, on the whole history | | `contents: read` |
| [`reusable-mypy.yml`](../.github/workflows/reusable-mypy.yml) | mypy with the repository's dependencies installed, through the kit's `mypy_groups.py`: one run per [mypy group](#mypy-groups), each folded in the log, an error annotation per failing group and a table of every group in the job summary (a bare `mypy` without groups) | `install`, `python-version-file`, `python-version` | `contents: read` |
| [`reusable-python-tests.yml`](../.github/workflows/reusable-python-tests.yml) | The repository's tests, and `coverage.xml` as the `coverage` artifact for SonarCloud | `run` (required), `install`, `python-version`, `python-version-file`, `coverage-report`, `coverage-artifact`, `timeout-minutes` | `contents: read` |
| [`reusable-eslint.yml`](../.github/workflows/reusable-eslint.yml) | `npm ci`, ESLint with no warning allowed, and `tsc --noEmit` on each project | `working-directory`, `projects`, `node-version` | `contents: read` |
| [`reusable-osv.yml`](../.github/workflows/reusable-osv.yml) | OSV-Scanner, failing on any known vulnerability | | `contents: read` |
| [`reusable-secrets.yml`](../.github/workflows/reusable-secrets.yml) | gitleaks over the history and the tree with both configs, and the MAC plant test | | `contents: read` |
| [`reusable-sonarcloud.yml`](../.github/workflows/reusable-sonarcloud.yml) | The secretless SonarCloud analysis, moved unchanged from the public repositories: OIDC token exchange (`SonarSource/sonarqube-auth-action`), scan (`SonarSource/sonarqube-scan-action`), and a wait until SonarCloud accepted the analysis; a pull request with no OIDC token (a fork, Dependabot) ends green with a notice | `coverage-artifact` (`coverage`; empty for none) | `contents: read`, `id-token: write` |
| [`reusable-commit-check.yml`](../.github/workflows/reusable-commit-check.yml) | The commit-message gate, with the checker the base branch names | | `contents: read` |
| [`reusable-commit-check-comment.yml`](../.github/workflows/reusable-commit-check-comment.yml) | The one commit-check comment, from a `workflow_run` caller | | `actions: read`, `contents: read`, `pull-requests: write` |
| [`reusable-quality-drift.yml`](../.github/workflows/reusable-quality-drift.yml) | Weekly: is the recorded kit behind the newest release (the newest `quality-v*` tag)? Only what a repository receives counts (quality/ but its tests, the kit's blocks, the `reusable-*.yml` workflows, the commit-message checker), so a merge to `main` that changes none of it, or is not yet released, raises nothing. A dry run of that release, written to the job summary, and a red run as the notice | | `contents: read` |

The commit-check callers keep the workflow name `Commit check` (the comment workflow follows it by name) and the drift caller is `.github/workflows/quality-drift.yml`; the sync seeds all three. The org's Actions policy allows only GitHub-owned and verified actions, so the kit uses no third-party action: tools come from PyPI with hashes ([`quality/requirements-tools.txt`](../quality/requirements-tools.txt)), from pre-commit hook repositories, or as release binaries pinned by SHA-256 in [`quality/tools.lock`](../quality/tools.lock) and installed by [`quality/fetch_tool.py`](../quality/fetch_tool.py). Each called job's name shows on GitHub as `<caller job> / <called job>`.

A notice is a red scheduled run, not an issue: issues are off in most kleidos-dev repositories, and no workflow here may open a pull request (`GITHUB_TOKEN` pull requests run no CI, and a PAT or App token is not used). GitHub disables the scheduled workflows of a public repository after 60 days without activity in it (its documented behavior, not yet seen here), and the drift notice and the weekly OSV scan stop with them; a repository that has been quiet that long gets its `Quality kit drift` and `CI` workflows re-enabled (`gh workflow enable`) whenever it is next touched, and each kit release is followed by a look at which repositories have not synced.

## Overrides

1. **Adding is free.** A repository may add rules, checks, hooks, stricter flags and wider scopes without asking: `extend-select`, more clang-tidy checks, a mypy flag the block does not set, an ESLint plugin, a CI job.
2. **Weakening needs a recorded reason.** Anything that makes a tool report less than the kit on the same code is a weakening: a rule off or down to a warning, an ignore or per-file ignore, an excluded path, a `-check`, a relaxed tsconfig or ESLint setting, a markdownlint rule turned off, a manifest directory Dependabot does not cover, a job with `continue-on-error`. Each is an entry in the repository's `.github/quality/waivers.toml`:

   ```toml
   [[waiver]]
   tool = "ruff"                # ruff, eslint, tsconfig, clang-tidy, markdownlint, ci, dependabot, pre-commit, reuse, pins
   what = "ignore:E501"         # the weakening, as check_quality.py names it
   where = "pyproject.toml"     # optional: the file, when the same weakening is in two
   reason = "Why the rule is wrong for this code, with the sites read"
   decided = "owner 2026-11-22" # or "agent, reviewed in PR #<n>"
   expires = 2027-05-22         # optional
   ```

   `check_quality.py` fails on a weakening with no waiver, on a waiver with no `reason` or `decided`, on a waiver that matches nothing any more, and on an expired one. The lint job's summary lists every waiver in effect and counts the inline suppressions.
3. **Some things cannot be waived:** a mypy suppression beyond missing types (owner: every error fixed, no baseline), a gitleaks global allowlist or `disabledRules`, an inline suppression without its code, an edited copy or managed block, and any SonarCloud suppression (owner: an issue is fixed with a real change or left open).
4. **Inline suppressions** carry their code and a reason: `# noqa: S603  <why>`, `# type: ignore[arg-type]  # <why>`, `# zizmor: ignore[<rule>]` with the reason on the line above, `// NOLINT(<check>): <why>`, `// eslint-disable-next-line <rule> -- <why>`. `RUF100` and mypy's `warn_unused_ignores` remove dead ones.
5. **A weakening every repository needs moves into the kit**, in one pull request here, with its reason in the kit file (as `S603`, `S607` and `self-repository` are).
6. **Facts are not weakenings**: `python_version`, `target-version`, `files`, `mypy_path` and the mypy groups (while coverage holds), `HeaderFilterRegex`, naming conventions, `known-first-party`, tsconfig `types` and `include`, typos exceptions for words that are right.

## Versions

- [`quality/VERSION`](../quality/VERSION) is the kit's semver, with an entry per release in [`quality/CHANGELOG.md`](../quality/CHANGELOG.md). MAJOR: anything that can turn a green repository red (a rule on, a stricter setting, a tool bump with new findings, a new conformance rule some repository fails). MINOR: a new opt-in profile or tool, or a rule every repository already passes. PATCH: docs, or a checker fix that cannot add findings.
- Tool versions are set here only: [`quality/requirements-tools.in`](../quality/requirements-tools.in) compiled with hashes into `requirements-tools.txt` (the command is in its header), the hook revisions in this repository's [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) (each a commit SHA with its tag), the actions the reusable workflows pin, and `tools.lock`; `check_quality.py`'s `LATEST_PYTHON`, `LATEST_ACTIONS` and `LATEST_HOOKS` repeat the Python, action and hook versions, and a kit test keeps them equal. Dependabot bumps the first three here (pip, pre-commit and github-actions ecosystems); the weekly `📦 Pinned versions current` job turns red when any kit pin has a newer stable release ([Pins at the latest release](#pins-at-the-latest-release)). A bump reaches the other repositories through the sync, never through their own Dependabot.
- A Dependabot pull request here is a kit release like any other. This repository records commit `self`, so its own lint job compares its copies and blocks with its working tree, not with `SOURCE.json`'s digests, and a hook or action bump passes it unattended. What it still needs before it merges: a signed commit on its branch with the new `quality/VERSION` (MINOR for a tool bump that finds nothing new in the impact preview, MAJOR if it finds more) and its `quality/CHANGELOG.md` entry (the `🏷️ Kit release and its tag` job fails until then; a pip bump of `requirements-tools.txt` also needs its header put back on top, as the file says), then the tag after the merge. Dependabot's pre-commit updater reads crate-ci/typos' sub-crate tags (`varcon-core-v5.0.7`) as typos versions, so `dependabot.yml` ignores typos `>= 2` (closed PR #10).

## Taking a new kit release

When a repository's weekly `Quality kit drift` run turns red, its summary says which release is out, how many problems a dry run found, and which files a sync would change. The sync is one pull request: check out that release (`git checkout quality-vX.Y.Z`) in a clone of kleidos-dev/.github beside the repository, run `python3 ../.github/quality/sync.py --write .`, fix every new finding in the same pull request (a waiver only where [Overrides](#overrides) allows it), and merge once CI is green (squash on the public repositories; a signed push to `main` on the private ones, which cannot have rulesets on the Free plan). The drift test (`test_quality_kit.py`, copied by `--test-dir`) makes the repository's own test suite fail on drift too.

## Changing the kit

1. One pull request here: the change, `quality/VERSION`, `quality/CHANGELOG.md`, and `sync.py --write .` so this repository, the kit's first consumer, records it (its `SOURCE.json` records commit `self` and is compared with the working tree).
2. CI runs the kit's tests ([`quality/tests/`](../quality/tests/), also the `kleidos-quality-kit-tests` hook), this repository against itself, the release check (`sync.py --release-check`: a pull request that changes what a repository receives, without a new `quality/VERSION` newer than the newest tag and its `CHANGELOG.md` entry, fails), and an impact preview: `sync.py --preview --tools @public` applies the changed kit to throwaway clones of the public repositories and writes their finding counts to the job summary (`ruff format` counted from its JSON report). Private repositories are previewed locally with `sync.py --preview <path>`.
3. Merge (squash), then tag the merge commit on `main`, signed: `git tag -s quality-vX.Y.Z -m 'Quality kit X.Y.Z' <merge commit> && git push origin quality-vX.Y.Z`. Until the tag exists, the release job of that push to `main` is red; re-run it once the tag is pushed. Then sync each repository from that tag.

[`quality/kit.toml`](../quality/kit.toml) lists every copy, block and seed by profile, and the repositories that consume the kit.

## Outside the kit: Socket, CodeQL, SonarCloud

- **Socket** (owner: public repositories only) is a GitHub App, so installing it is the owner's click: <https://github.com/apps/socket-security/installations/new>, account `kleidos-dev`, "Only select repositories": `.github`, `boards`, `brand`, `social`, `cla`. Free plan; it reads the pip and npm manifests and comments on pull requests that change them. Check the permissions page before accepting (contents and metadata read, checks and pull-request write expected). No `socket.yml` is needed for its defaults.
- **CodeQL** runs as GitHub's default setup on every public repository (a repository setting, no workflow): `actions` and `python` on `.github`, boards and brand; `actions` only on social (add `python` with `gh api -X PATCH repos/kleidos-dev/social/code-scanning/default-setup -f state=configured -F 'languages[]=actions' -F 'languages[]=python'`); `actions`, JavaScript/TypeScript and `python` on cla. No repository runs a CodeQL workflow, so the kit has none: default setup and an advanced-setup workflow are exclusive. Its license forbids it on private code.
- **SonarCloud** settings live in each `sonar-project.properties` and in [`sonarcloud.md`](sonarcloud.md); the kit only runs the analysis job. Reading the mypy and ruff reports into SonarCloud (`sonar.python.mypy.reportPaths`, `sonar.python.ruff.reportPaths`) is a later minor release.

## Where each repository stands

| Repository | Visibility | Profiles | State |
| --- | --- | --- | --- |
| kleidos-dev/.github | public | base, python, actions | The kit's home and first consumer (commit `self`) |
| kleidos-dev/boards, brand, social | public | base, python, actions | Wave 1: one sync pull request each, from the tag `quality-v1.0.0` |
| kleidos-dev/cla | public | base, python, actions, ts | Wave 2, coordinated with its own build; its ESLint and tsc jobs become the `reusable-eslint.yml` caller (`working-directory: worker`, `projects: tsconfig.json ../scripts/tsconfig.json`) |
| kleidos-dev/agents | private | by tree | Wave 3, first: its `sync_commit_check.py` copies only the checker from then on ([The commit-message gate](#the-commit-message-gate)) |
| kleidos-dev/qa, meter, videos, posts | private | by tree (meter: cpp, shell, with its static-analysis job as the local clang-tidy job; videos: shell) | Wave 3, after agents: a signed push to `main` each; qa and meter edit their commit-check digest test |
| jmrplens/kleidos (the firmware) | private | all | Not yet: [`quality-firmware-adoption.md`](quality-firmware-adoption.md) |
