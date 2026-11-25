<!--
SPDX-FileCopyrightText: 2026 José M. Requena Plens
SPDX-License-Identifier: GPL-3.0-or-later
-->

# The Kleidos quality kit

One place holds the rules every Kleidos repository meets, the configuration of every analysis tool that enforces them, and the CI jobs that run those tools: this repository, in [`quality/`](../quality/), [`hooks/`](../hooks/) and [`.github/workflows/`](../.github/workflows/). Every repository runs it the same way, may add rules of its own, and cannot weaken a shared rule without writing down why. A rule change is one pull request here.

From 3.0.0 the kit is **run, not held**: a repository calls it by its name, `@v3`, and holds none of its code ([How a repository runs the kit](#how-a-repository-runs-the-kit)). The repositories that still hold kit 2.x copies keep working as they are, at the commit they recorded, until each one switches ([Switching from kit 2.x](#switching-from-kit-2x)); being behind is never red (owner, 2026-11-24).

The kit uses free tools only (owner, 2026-11-22). SonarCloud stays on every public repository; the kit runs its analysis job but never touches a project's settings.

The agent instruction files every repository keeps, `AGENTS.md` and `CLAUDE.md`, have a standard of their own, [`agent-docs.md`](agent-docs.md); the kit carries its two mechanical parts, the organization rules and the guard that checks the files. What is behind or broken across the repositories is one report, [`ecosystem.md`](ecosystem.md).

## Contents

- [How a repository runs the kit](#how-a-repository-runs-the-kit)
- [Switching from kit 2.x](#switching-from-kit-2x)
- [Held copies (kit 2.x)](#held-copies-kit-2x)
- [The rules](#the-rules)
- [Tests](#tests)
- [Licensing headers](#licensing-headers)
- [Reusable workflows](#reusable-workflows)
- [Overrides](#overrides)
- [Versions](#versions)
- [Changing the kit](#changing-the-kit)
- [Merging](#merging)
- [Proof from another repository](#proof-from-another-repository)
- [Outside the kit: Socket, CodeQL, SonarCloud](#outside-the-kit-socket-codeql-sonarcloud)

## How a repository runs the kit

Four things, and nothing else of the kit is in the tree:

| What | What the repository holds | Who moves it |
| --- | --- | --- |
| CI | The calls to the entry workflows, at the branch `v3`, and the `✅ Check` job | The kit's release moves the branch; a new major is a hand pull request |
| Hooks | One entry in `.pre-commit-config.yaml`, at a release tag, beside the third-party hooks | Dependabot |
| Base configurations | The files a tool reads from the disk, with their record in `.github/quality/SOURCE.json` | `tools/ecosystem.py refresh`, whenever; an old one is a line of the report |
| Waivers | `.github/quality/waivers.toml` | The repository |

### The entry workflows

The model is [`quality/templates/run/ci.yml`](../quality/templates/run/ci.yml).

| Workflow | Jobs | Inputs | The caller grants |
| --- | --- | --- | --- |
| [`quick.yml`](../.github/workflows/quick.yml) | Lint (every policy check, every hook, zizmor online), licensing, the secrets scan, the commit check (the messages of a pull request's commits, and whether what it or a push to `main` adds as the owner's is the owner's), and where `deny-hooks` names some, the repository's own hooks that read the deny-list, in a job of their own | `skip`, `deny-hooks`; the secret `deny` | `contents: read` |
| [`check.yml`](../.github/workflows/check.yml) | The tests, mypy, ESLint and `tsc`, OSV-Scanner | `python` (what pip installs) or `install` (a command), `tests`, `coverage-report`, `coverage-artifact`, `timeout-minutes`, `types`, `types-install`, `python-version-file`, `node-directory`, `node-projects`, `node-version` | `contents: read` |
| [`sonar.yml`](../.github/workflows/sonar.yml) | The SonarQube Cloud analysis (public repositories) | `coverage-artifact` | `contents: read`, `id-token: write` |

Each calls the `reusable-*.yml` workflows beside it ([Reusable workflows](#reusable-workflows)), which a repository may also call itself, at `@v3`, for what the entry workflows do not say (a second test job). The comment caller, [`quality/templates/run/commit-check-comment.yml`](../quality/templates/run/commit-check-comment.yml), is the second and last kit file of a repository.

- **The reference is the branch, `@v3`, exactly.** Third-party actions stay pinned by the commit SHA of their latest release (owner, 2026-11-23); our own kit is called by name because the question a SHA answers is who can move the reference, and only the organization's admin can move `v3` (a ruleset on `main`, on `v[0-9]*` and on every tag). zizmor's policy would accept any name there, `@main` included, so the kit's check holds it to the one.
- **Never an annotated or signed tag.** A workflow called at one cannot call the workflows beside it: the run fails before its first job, with no log (tried on 2026-11-24; a branch, a lightweight tag and a commit all work). The release tags are signed, and they are for the hooks and the history.
- **The kit that runs is the kit that checks.** Each job fetches `kleidos-dev/.github` at the commit of the workflow it is in (`job.workflow_sha`, read as `fromJSON(toJSON(job)).workflow_sha` while actionlint 1.7.12 does not know the key; the round trip needs no configuration file and leaves every other key of `job` checked, which an ignore would not) and writes `kit v3.x.y (<commit>)` in the job summary.
- **The secret.** Only `quick.yml` takes one, by name, `deny: ${{ secrets.KLEIDOS_DENY_EXTRA }}`, never `secrets: inherit`, and gives it to one job, [`reusable-deny.yml`](../.github/workflows/reusable-deny.yml), whose last step is the only one that sees it. Before that step the job runs GitHub's own actions, the kit and its hashed tools, and no hook, no dependency and no code of a third party; the hooks it runs then are the repository's own local ones, in a language that installs nothing ([`deny_hooks.py`](../quality/deny_hooks.py) refuses any other). Taking the secret out of the environment of a hook that runs in the same job is not enough, since what ran before may have left something behind for the step that has it. The repository's own code and what the job's own commit changed still run with it: whoever can push a branch can read it. [`test_secret_isolation.py`](../quality/tests/test_secret_isolation.py) holds every job with something to lose by what its steps do, not by their names: what each action is told (a checkout leaves no credential and fetches no other ref or repository, `setup-python` restores no cache), the job on GitHub's `ubuntu-latest` with no matrix and no job key but its listed ones, each script step given only its listed environment (no `PYTHONPATH`, `BASH_ENV` or `PIP_INDEX_URL`), the secret in the last step only, the kit's folder only from the step that fetched it, and the conditions that decide what runs evaluated case by case.

### The gate

The last job of the file is the repository's own and the one required check: named `✅ Check`, it needs every other job of the file, carries `if: always()`, and fails unless each of them succeeded. GitHub counts a required check that was *skipped* as passed, so a job whose own condition may skip it (an expensive build that runs only when its inputs changed, the analysis on a schedule) is named in `MAY_SKIP`; any other skip fails. The kit's check holds the job to the model, word for word, refuses a second job with that name, and refuses any workflow whose token can write checks or commit statuses, since a job with one could post a passing `✅ Check` on any commit. Nothing around the step steers it: its shell reads no start-up file (`-p --noprofile --norc`), it sets its own `PATH` and `HOME`, both of its inputs are always set in the step, and the check refuses `env` and `defaults` on its workflow, a matrix or a soft failure on a kit caller, and an expression in what a caller skips. A `MAY_SKIP` job whose condition is never true is the one thing it cannot tell from a build that had nothing to do: the caller of a kit workflow may be named there only where the check says so, and the rest is read by a person.

**What no fix removes.** A pull request brings its own workflow files, and GitHub runs those. Whatever the check says about `.github/` it says after the workflow under check has run, from inside it. So a green `✅ Check` proves something about a change of the code and nothing about a change under `.github/` ([Merging](#merging)).

### The hooks

```yaml
  - repo: https://github.com/kleidos-dev/.github
    rev: v3.0.0
    hooks:
      - id: kleidos-kit          # every policy check: conformance, agent docs, Markdown, licensing lines, tests
      - id: kleidos-commit-msg   # the commit-message rules
      - id: kleidos-mypy         # mypy, where there is Python
```

They are `language: script` hooks ([`.pre-commit-hooks.yaml`](../.pre-commit-hooks.yaml)): nothing is installed. [`hooks/launch.py`](../hooks/launch.py) reads on Python 3.9, the oldest `python3` the machines have (macOS's), and runs each hook on a Python that can: the commit-message check in the one it started on, the others on 3.14 or newer, with PyYAML for `kleidos-kit` and mypy from the repository's environment for `kleidos-mypy`. Where a Python has no PyYAML the line it prints makes an environment of the kit's own (`~/.local/share/kleidos-kit`, which it looks for last): Homebrew's and Debian's Pythons refuse pip outside one. Where there is no Python it says so in one line and fails; the CI is the gate, so an outside contributor need not run the hooks. Every hook names its stages, because pre-commit runs a hook that names none at every installed hook type.

The third-party hooks are the repository's own text, held to the kit's canonical list (the blocks of this repository's [`.pre-commit-config.yaml`](../.pre-commit-config.yaml)): a missing one, a changed `entry` or `language` is a problem, and different arguments or file filters are a weakening. CI runs the branch and the hooks a release, so for up to a week a pull request can meet a rule its author's hooks do not have yet; a failing policy job prints the kit it ran and the `rev` it found.

### The base configurations

`.github/quality/ruff.toml`, `.github/quality/markdownlint.jsonc`, `.gitleaks-mac.toml`, `.github/zizmor.yml`, `.shellcheckrc`, `.github/quality/eslint.base.mjs`, `.github/quality/tsconfig.base.json` and `.clang-tidy`, as the profiles call for them. `.github/quality/SOURCE.json` is a record of schema `kleidos.vendored-copy/1`, the one every copy between repositories uses:

| Field | Says |
| --- | --- |
| `upstream.repo`, `upstream.path` | Where the files come from |
| `upstream.commit` | The commit they were taken at: a note, never a gate (the digests are the pin) |
| `mode` | `follow`, with an optional `max_age_days`, or `frozen`, with a one-sentence `reason` |
| `taken` | The date of the copy |
| `files` | Each file with its SHA-256, named from the record's folder, or from the top with `"root": "."` |
| `sources` | Where a file's name differs from its source's |
| `kit` | In the kit's own record: the version and the profiles |

The check holds every such record of the tree to its bytes, offline ("edited in place"), and the kit's own to bytes some kit release holds ([`quality/config-digests.json`](../quality/config-digests.json)). It never compares them with the newest: a repository sits on an old configuration, green, for as long as nobody refreshes it, and the report says so.

Profiles say what applies: `base` (every repository), `python`, `actions`, `shell`, `ts`, `cpp`. They are detected from the tree, and the checker fails when the tree holds a language whose profile is not adopted.

### What else the repository holds to

- `.github/dependabot.yml`: every manifest directory has its ecosystem; every update has a `cooldown` (`default-days: 7`); `github-actions` ignores `kleidos-dev/.github*` (Dependabot reads a branch named like a version as a pin and would propose `@v4` the week that branch exists); the `pre-commit` ecosystem runs and ignores `version-update:semver-major` of `https://github.com/kleidos-dev/.github`.
- `pyproject.toml`: `[tool.ruff]` with `extend = ".github/quality/ruff.toml"` and `target-version`; `[tool.mypy]` with `strict = true`, `enable_error_code = ["ignore-without-code"]`, `python_version` and `files` naming every Python root (or [mypy groups](#mypy-groups)). `.typos.toml`: `[default] locale = "en-us"`.
- `AGENTS.md` links the [organization rules](../quality/agents/block.md) and copies none of them.
- A repository with the `python` profile has a `.python-version`. TypeScript: `tsconfig.json` extends the base and `eslint.config.js` imports `kleidosTypeScript` from it. C++: the root `.clang-tidy` is the kit's, and a job of the repository's own runs clang-tidy on every pull request (it needs the repository's build).

## Switching from kit 2.x

One pull request (or signed push) per repository, after `v3` exists:

1. `python tools/kit_switch.py --write <repository>` from an up-to-date checkout of this repository at `v3`. It removes the kit's scripts, the drift caller, the commit-check folder and the kit test, rewrites the gate workflow (the repository's own jobs kept, `✅ Check` last), the comment caller, the hook list and Dependabot's entry, drops the block markers, links the organization rules, and records the base configurations. It refuses a tree with uncommitted changes, and prints what is left.
2. By hand: the comments of the gate workflow that named the old jobs, the needs of the repository's own jobs, the docs that name the copies, the sync or the drift job, the `pins` waivers (an old pin is a note in the run form), and the license lines (below).
3. `python quality/policy.py --repo <repository>` from the same checkout: clean. `pre-commit run --all-files` in the repository: clean.
4. The exit check: CI green on the pull request and on `main`; no 40-hex reference to `kleidos-dev/.github` in the tree; nothing under `.github/quality/` but the base configurations, their record and the waivers.

`tools/ecosystem.py preview --all` shows what each repository would meet. The one rule 3.0.0 adds that a repository meets at the switch and not before is the owner's copyright line in the license texts ([Licensing headers](#licensing-headers)).

## Held copies (kit 2.x)

A repository that has not switched carries byte copies of kit files, managed blocks of kit text between `kleidos-quality` markers, and calls to the `reusable-*.yml` workflows at one kit commit, all recorded in `.github/quality/SOURCE.json`. It stays exactly as it is: its CI calls the commit it recorded, which the tag `quality-v<VERSION>` names, and its weekly drift job, which runs this repository's newest [`sync.py`](../quality/sync.py), answers "not behind" for any 2.x commit. No release after 2.3.0 is taken by a sync: `sync.py --write` refuses a repository that is not this one. The tags `quality-v*` stay until the last one has switched. [`quality/kit.toml`](../quality/kit.toml) lists the copies and blocks; `check_quality.py` still checks them where it meets them. All of it goes with the first release after the last 2.x caller is gone, and not before: their drift job runs this repository's newest `sync.py`, through the newest [`reusable-quality-drift.yml`](../.github/workflows/reusable-quality-drift.yml), so removing either turns each of them red.

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
| zizmor, offline in the hook and online in the lint job | hook `zizmor`, [`reusable-lint.yml`](../.github/workflows/reusable-lint.yml), [`quality/zizmor/zizmor.yml`](../quality/zizmor/zizmor.yml) | Workflow security: template injection, credentials left by checkout, cache poisoning, excessive permissions. Every `uses:` is pinned by commit SHA, GitHub's own actions included (the trivy-action tag rewrite of 2026-03-19 is the risk), but the kit's own, which are called at `@v3`. The `self-repository` audit is off kit-wide: it asks for `uses: $/...`, which actionlint 1.7.12 rejects. |
| A zizmor finding is accepted only inline: `# zizmor: ignore[<rule>]` with the reason on the line above | `check_quality.py` | The repository's `zizmor.yml` is the kit's copy, so there is no ignore list to grow. |
| CI conventions: an emoji first in every job name, a `timeout-minutes` on every job that runs steps, every third-party `uses:` pinned by a 40-hex SHA with its version in a comment, no `continue-on-error: true` on a job or on a step | `check_quality.py` (a weakening, `tool = "ci"`, named `continue-on-error:<file>:<job>` or `...:<job>:<step id, name or index>`; an expression there is refused) | The owner's conventions, now checked. A job with `continue-on-error` is green whatever it finds, and so is a step, in every workflow of the tree, a local reusable one included. |
| actionlint reads the kit's rules: every `ignore` of `.github/actionlint.yaml` is a weakening | `check_quality.py` (`tool = "actionlint"`, `ignore:<glob>:<pattern>`) | An ignore of `.*` switches it off for the files its glob names. |
| zizmor reads the kit's configuration and no other | `check_quality.py`, no waiver: a `zizmor.yml`, `zizmor.yaml`, `.zizmor.yml` or `.github/zizmor.yaml` beside `.github/zizmor.yml` is refused | zizmor would read it instead of the kit's copy. |
| Every check comes from the kit, and runs | [`run_form.py`](../quality/run_form.py), no waiver: the entry workflows called at `@v3` in a workflow that runs on `pull_request` and on `push` to `main` with no `paths` filter, by jobs that neither carry nor need an `if:` other than `github.event_name != 'schedule'`; `types` not false where there is Python, `node-directory` named where there is TypeScript; the sonar call where `sonar-project.properties` exists; with `cpp`, a job of the repository's own whose `run:` calls clang-tidy | One definition of each check, so a fix reaches every repository. The workflows are parsed, not searched: a caller with `if: false`, a check run only by hand, or one the pushes to `main` never run is reported. |
| The kit's reference, grants and secrets | `run_form.py`, no waiver | `@v3` and nothing else ([The entry workflows](#the-entry-workflows)); a caller grants what the table there says and no more. |
| The gate | `run_form.py`, no waiver | [The gate](#the-gate). |
| No workflow can write checks or commit statuses | `run_form.py`, no waiver (`checks: write`, `statuses: write`, `write-all`) | A job with either can post a passing `✅ Check`: the App behind it is the same GitHub Actions the required check is pinned to. |
| The quick caller skips only the repository's own hooks | `run_form.py`, and the lint job itself against the kit that runs, no waiver | `skip` and `deny-hooks` exist for hooks that cannot run in CI or that need the deny-list; a kit hook named there would switch a shared rule off. |
| Nothing above the hooks switches them off | `check_quality.py` | A top-level `exclude:` or `files:` in `.pre-commit-config.yaml` narrows every hook, the kit's included: a weakening that needs a waiver (`tool = "pre-commit"`). A `default_stages` without `pre-commit` stops them running at all: refused, no waiver. |
| shellcheck at warning severity | hook `shellcheck`, [`quality/shellcheck/shellcheckrc`](../quality/shellcheck/shellcheckrc) | Quoting and word-splitting bugs; notes and style stay out. |

### Every repository (profile `base`)

| Rule | Enforced by | Why |
| --- | --- | --- |
| Spelling, US English | hook `typos` (report only: a spelling "fix" in code is a bug), the typos block (`locale = "en-us"`) | The estate's prose and identifiers use US spelling; typos also catches misspelled identifiers. |
| typos reads `.typos.toml` and checks every file | `check_quality.py`, each a weakening (`tool = "typos"`): another configuration it would read first or for a folder (`typos.toml` or `_typos.toml` anywhere, a `.typos.toml` below the top, `[tool.typos]` in a `pyproject.toml`, `typos` metadata in a `Cargo.toml`), a typos table in a `pyproject.toml` or `Cargo.toml` however the TOML spells it, an `extend-exclude` that covers every file with an extension (`*`, `**`, `/`, `*.*`, and with globset's classes and alternates `[!_]*`, `{*,.*}`), `check-file` or `check-filename` set false, an `extend-ignore-re` pattern that leaves no two letters together in any word it skips (`.`, `[a-z]`, `[A-Za-z]+`), an `extend-ignore-identifiers-re` or `extend-ignore-words-re` pattern found in every word (`[a-z]`); the check fails closed, so a pattern or glob the kit cannot read as typos does (`\p`, a POSIX class `[[:alpha:]]`, the flags `U` and `-u`, one Python refuses or warns about) counts as covering everything, and a `pyproject.toml` or `Cargo.toml` that tomllib cannot read (TOML 1.1 before Python 3.15) holds a typos table wherever its text names typos | Each switches it off for some files or all (typos 1.52.2 checks a type made `binary` all the same, and reads a file that starts with a byte order mark). An `extend-exclude` of named paths and the words in `extend-words` are facts; a later release will judge the paths. |
| Secrets: every default gitleaks rule, over the tree and the whole history | hooks `gitleaks`, [`reusable-secrets.yml`](../.github/workflows/reusable-secrets.yml) | Private repositories get no GitHub secret scanning on the Free plan. |
| MAC addresses: the kit's MAC rules | hook `gitleaks-mac`, `.gitleaks-mac.toml` (a copy of [`quality/gitleaks/mac.toml`](../quality/gitleaks/mac.toml)), the plant test | The bench's board MACs are private. The MAC config extends nothing, so the default allowlist (images, fonts, lockfiles) never hides a MAC; the plant test proves the rules still fire on real shapes and spare the fakes. |
| `.gitleaks.toml`, every key read without regard to case as gitleaks reads it (`[[Rules]]`, `DisabledRules`, `Paths`; one key spelled twice is refused), one table alone as an array of one and one string as a list of one: `useDefault = true`, no `disabledRules`, no global `[allowlist]`, every `[[allowlists]]` with a `description` and `targetRules` and no `paths` or `regexes` pattern that finds every file with an extension or every secret (`.*`, `\.`, an empty one); a rule of the tree only under an id of its own (`kleidos-…`), never a default rule's, and no `paths` or `regexes` of its allowlists that find everything; no pattern the kit cannot read as gitleaks (Go's RE2) does (`\p`, a POSIX class, the flags `U` and `-u`, one Python refuses or warns about); every `.gitleaksignore` fingerprint with a comment above it; scans run with `--ignore-gitleaks-allow` | `check_quality.py`, no waiver | An allowlist that reaches every rule hides the next real secret, and one that reaches every file turns its rules off as `disabledRules` would. gitleaks 8.30.1 merges a rule of the tree into the default rule of the same id, so its `entropy`, `path` or allowlist switches that rule off. |
| Known vulnerabilities fail the build | [`reusable-osv.yml`](../.github/workflows/reusable-osv.yml) (OSV-Scanner over every manifest and lockfile, also weekly) | Advisory-only scanning was ignored. An accepted one goes in `osv-scanner.toml` with a `reason` and an `ignoreUntil` at most 90 days ahead (`check_quality.py`). |
| Dependabot covers every manifest, each update with a cooldown | `check_quality.py` | A directory without its ecosystem never gets a security update; a week's cooldown gives a compromised or yanked release time to be noticed. |
| Licensing: `reuse lint`, the header lines, and the owner's statement with no e-mail | [`reusable-reuse.yml`](../.github/workflows/reusable-reuse.yml), hooks `reuse` and `kleidos-kit`, `check_quality.py` (a `.license` sidecar is a weakening, `tool = "reuse"`) | See [Licensing headers](#licensing-headers). |
| No e-mail address in a supplier, author or maintainer field | `check_quality.py` ([`supplier_fields.py`](../quality/supplier_fields.py)); `mail@kleidos.dev` is a weakening (`tool = "supplier"`, `what = "address:<field>"`), any other address has no waiver | Owner, 2026-11-25. See [Supplier fields](#supplier-fields). |
| Markdown prose is never hard-wrapped | hook `kleidos-kit` and the lint job ([`quality/md_nowrap.py`](../quality/md_nowrap.py)) | Owner, 2026-11-16: one line per paragraph and per list item. |
| Agent instruction files keep the standard: `AGENTS.md` and `CLAUDE.md` at the root, `CLAUDE.md` importing `AGENTS.md` first, `CLAUDE.local.md` ignored, the size limits, every named path and link real, every skill and subagent named, the organization rules linked | hook `kleidos-kit` and the lint job ([`quality/agent_docs.py`](../quality/agent_docs.py)) | Every agent reads `AGENTS.md`; a path that moved or a rule restated by hand misleads the next one. See [`agent-docs.md`](agent-docs.md). |
| Markdown tables render: MD055, MD056, MD058 only | hook `markdownlint-cli2`, [`quality/markdownlint/base.jsonc`](../quality/markdownlint/base.jsonc) | Broken tables are the findings that matter; the rest of markdownlint's defaults measured as noise. |
| markdownlint reads the kit's configuration | `check_quality.py`: a `.markdownlint*` or `.markdownlint-cli2.*` in a folder, or a `.markdownlint-cli2` other than the `.jsonc` at the top, is a weakening (`tool = "markdownlint"`, `config:<path>`) | markdownlint-cli2 reads a configuration in every folder, for that folder. |
| Copies are the bytes their record names, and no kit code is held | hook `kleidos-kit`, the lint job (`run_form.py`) | [The base configurations](#the-base-configurations). A kit script, a managed-block marker, the drift caller or the commit-check folder left in the tree is reported. |
| Python repositories name their Python | `check_quality.py` (`.python-version`) | The kit's mypy and test workflows read it; without it the first CI run fails in setup-python. |
| Every pin at the latest stable release | Dependabot in each repository, the report's ages, and here [`quality/latest_releases.py`](../quality/latest_releases.py); an image by digest with its tag, a hook with its tag, are problems | Owner, 2026-11-23. See [Pins at the latest release](#pins-at-the-latest-release). |
| Commit messages | [`reusable-commit-check.yml`](../.github/workflows/reusable-commit-check.yml), the `kleidos-commit-msg` hook | 72 columns, imperative, no AI attribution: [The commit-message gate](#the-commit-message-gate). |
| A commit that says it is the owner's, by author or by committer, has the owner's address and the owner's key; nobody else's is judged | [`reusable-commit-check.yml`](../.github/workflows/reusable-commit-check.yml) ([`commit_identity.py`](../hooks/commit_identity.py)), no waiver: the exemptions are the kit's own list | Owner, 2026-11-25: the owner's commits are told from anybody else's, and a contributor's stay the contributor's. See [The identity of a commit](#the-identity-of-a-commit). |

### The commit-message gate

The kit owns the checker, [`hooks/check_commit_msg.py`](../hooks/check_commit_msg.py) (until 3.0.0 `kleidos-dev/agents` did, and every repository held a copy). The hook runs it on the message git is about to commit; `quick.yml` runs it on a pull request's commits, with the kit that is called, and in this repository with the base branch's, so a change to it does not judge its own pull request; the result is a table in the job summary and one comment on the pull request. Its rules are in its docstring. A pull request opened by Dependabot or Renovate is not checked.

### The identity of a commit

Owner, 2026-11-25. A commit that says it is the owner's is the owner's: one address, and one PGP key, which is public. **It applies to the owner alone.** Nobody else is asked for that address, that committer or that key, wherever the branch is: a contributor's commit, with the contributor's author, committer and key, or with no signature, is not judged here and never fails here. [`hooks/identity.json`](../hooks/identity.json) holds who the owner is: the login, the address, the fingerprints of the keys, the exempt refs, each with its reason, and the moment the rule starts. It is the organization's, and the same for every repository that calls this kit; a fork of the kit for another owner is that file with another content.

[`hooks/commit_identity.py`](../hooks/commit_identity.py), in the same job as the messages and so part of `✅ Check`, asks GitHub about each commit a pull request adds and each commit a push adds to the default branch. A commit's author, or its committer, is the owner when GitHub gives the owner's login for it, or when it holds the owner's address, whoever wrote it there.

| The commit | What is judged |
| --- | --- |
| (a) Its author is the owner | Author address, committer and signature are the owner's: a merge button, the web editor, another machine, and somebody who writes the owner's address, are refused |
| (b) Its author is somebody else, its committer the owner, who landed it | Committer address and signature are the owner's; the author is untouched |
| (c) Neither is the owner | Nothing: the log counts it |
| (d) GitHub knows no account of its author or of its committer | Nothing; on a pull request the owner opened from a branch of the repository, a warning where neither is the owner, since it may be the owner's other machine. Never a failure, and never of what the owner landed, (b), whose author is not the owner's to change |
| (e) A bot's (Dependabot, the CLA's) | Nothing |

| Rule | Refused |
| --- | --- |
| `identity-author` | An author who is the owner, with another address |
| `identity-committer` | A committer of one of these commits with any address but the owner's |
| `identity-signature` | On one of these commits: no signature; one GitHub does not report valid; one GitHub made itself; one made with a key whose id, as GitHub gives it, is not the owner's |
| `identity-unknown` | Nothing: it is the warning of (d) |

- **That a commit of `main` is signed by somebody is another rule, and GitHub's**: the required signatures of each `main`'s ruleset refuse an unsigned push, whoever made the commit, and say nothing of who. This check says nothing of whether a contributor's commit is signed.
- **The owner's other addresses are private**, so none is listed anywhere: the owner with another address is told by the login GitHub gives. What is printed names a login, never an address.
- **Nothing of a contributor's commit turns the job red.** Where GitHub has not decided on a signature, or could not verify it, the job waits for the owner's and for nobody else's: three times, and then it fails rather than pass a commit that may be forged. What GitHub does not answer at all is asked three times too, since whose a commit is cannot be told without it; an outage longer than that fails the job of anybody, and running it again is all there is to do.
- **Only what is added is judged**, never history, nor what the default branch already holds. A pull request against another branch is judged as far as the default one goes, since no push judged that branch, and turning the pull request to `main` starts no run: so a commit of the owner's that does not comply is refused there too, whoever opened it. A push that came before `since` is not judged, by GitHub's own record of when it came (a committer date is the committer's to write), so a run started again finds in an old push what it found then. A push that wrote `main` anew is judged whole.
- **No code of a pull request runs beside the token**, which can only read: the checker is the kit's that runs, and in this repository the base branch's. So a fork's pull request is judged like any other, and what it can be refused for is a commit that says it is the owner's.
- **The exempt refs** are the list in `identity.json` and no other: the branch of `kleidos-dev/cla` the CLA bot writes, whose commits are the evidence of who signed, and, while work that still squash-merges ends there, the `main` of `kleidos-dev/meter`.
- **What it does not see**: the owner's name with somebody else's address, since a name is nobody's; the owner with an address of no GitHub account, but for the warning; a push whose run was cancelled by the next one (the pull request it came from was judged); and whatever a pull request's own change of `.github/` makes of the job ([The gate](#the-gate)). GitHub does not enforce the e-mail patterns a ruleset may hold on this plan (tried, 2026-11-25), so this is held here.

To repair a branch of the owner's: the owner's `user.email` and `user.signingkey` in git, `git rebase --force-rebase --gpg-sign origin/main`, and `git push --force-with-lease`. A contributor whose branch holds a commit that says it is the owner's drops that commit, or sets their own name and address on what they wrote.

### Pins at the latest release

Owner, 2026-11-23: every pinned version is the latest stable release, and whatever cannot move has its blocker fixed; only what truly cannot move stays lower, with its reason beside the pin, on its line or in the comment lines right above it, after the marker `below-latest:`:

```yaml
      - uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0 # v7.1.0
        with:
          # below-latest: the skills' scripts run on the python3 macOS ships (3.9)
          python-version: "3.9"
```

Owner, 2026-11-24: being behind is never red. So in a repository that runs the kit:

- Dependabot moves third-party actions, hook revisions and packages, in grouped weekly pull requests with a seven-day cooldown (the kit's own release is exempt), and `tools/ecosystem.py land` lands the ones that pass its guards, each as a signed commit of the owner's.
- The check notes a Python, an action, a hook or an image that is below the newest release this kit knows and has no `below-latest:` reason; the note fails nothing.
- What a pin must *say* stays a problem: a third-party `uses:` is a full commit SHA with its version in a comment; a hook of the canonical list is a commit with `# frozen: vX.Y.Z` or a tag; a container image the kit knows is pinned by digest with its tag in a comment, `image: kicad/kicad@sha256:3f4a0178…3714ddc34 # 10.0.8`, and the newest tag with another digest is refused (Dependabot's `docker` ecosystem reads no workflow's `container:`).

This repository's own pins (its Python, the actions, the hook revisions, the images, the PyPI tools of [`requirements-tools.in`](../quality/requirements-tools.in), the binaries of [`tools.lock`](../quality/tools.lock)) are compared with upstream by the weekly [ecosystem report](ecosystem.md), as an amber line; moving one is a kit release. A kit 2.x repository still has the older rule, at the commit it recorded: a pin below its kit's is a finding there, waivable as `tool = "pins"` with the reason beside it.

The kit's own Python is 3.15: its scripts are formatted for it (PEP 758 `except` clauses without parentheses need 3.14 or newer), but [`hooks/`](../hooks/), which keeps to 3.9 ([The hooks](#the-hooks)). SonarQube Cloud lists Python up to 3.14, so `sonar.python.version` stays 3.14 with its reason beside it ([`sonarcloud.md`](sonarcloud.md)).

### TypeScript and C++ (profiles `ts`, `cpp`)

| Rule | Enforced by | Why |
| --- | --- | --- |
| ESLint `strictTypeChecked` plus `no-deprecated` and `switch-exhaustiveness-check`, and `tsc` on every project | [`quality/eslint/base.mjs`](../quality/eslint/base.mjs), [`reusable-eslint.yml`](../.github/workflows/reusable-eslint.yml) (`npm ci`, `eslint --max-warnings 0 .`, `tsc --noEmit -p` per project), `check_quality.py` (a base rule set to `off` or `warn` locally, `disableTypeChecked`, and an `ignores:` entry other than build output such as `dist/**`, `node_modules/**`, `.wrangler/**` are weakenings) | Type-aware bugs Sonar does not see. ESLint and its plugins stay the repository's dependencies. |
| `tsc` strict flags: `strict`, `noUncheckedIndexedAccess`, `noImplicitOverride`, `noFallthroughCasesInSwitch`, `noImplicitReturns`, `exactOptionalPropertyTypes`; no `baseUrl` | [`quality/tsconfig/base.json`](../quality/tsconfig/base.json), `check_quality.py` | `baseUrl` stops working in TypeScript 7 (TS5101). |
| clang-tidy base with `clang-analyzer-*`, `concurrency-mt-unsafe`, `misc-no-recursion`, `WarningsAsErrors: '*'` | [`quality/clang-tidy/base.yaml`](../quality/clang-tidy/base.yaml), `check_quality.py` (a local `-<check>` is a weakening; a pull-request job of the repository's own must run clang-tidy) | The path-sensitive analyzer never ran in either C++ repository. clang-tidy needs the repository's build (its compile database), so the job stays local; naming prefixes and header filters stay local too. |
| `NOLINT(<check>): <why>`, `eslint-disable-next-line <rule> -- <why>` | `check_quality.py` | A suppression names what it silences and why. |

clang-format is not in the kit yet: meter and the firmware use different styles.

## Tests

Owner, 2026-11-24. Every repository aims at the maximum of tests: 100 % of line, branch, condition (MC/DC) and mutation is the target, with good practice for each language, and every exclusion is listed with its reason where the tool reads it. A change brings its tests; a guard brings the planted defect that proves it fires. The share a file has reached is held, so it only rises.

The long standard, language by language, is [`testing.md`](testing.md), from a pilot in `kleidos-dev/cla`. It also says which of its rules the kit holds in every repository that calls it (the `tests` check of [`policy.py`](../quality/policy.py), below), which each repository holds by itself, and which nothing holds yet.

| Rule | Enforced by | Why |
| --- | --- | --- |
| No test is marked to run alone (`it.only` and the like) | [`suite_rules.py`](../quality/suite_rules.py), no waiver | Every other test of its file stops running, and the suite passes. |
| A test that is skipped, left to do or expected to fail says why, in the marker or in a comment `skip: <why>` on its line or in the comment right above | `suite_rules.py`, no waiver: the reason is written where the skip is | A skip with no reason is nobody's decision. |
| coverage.py's threshold is in its configuration, never on a command line | `suite_rules.py`, no waiver | The command line wins over the place a person looks. |
| A coverage threshold the tools would use never falls or goes, against the base of the change, unless the change adds its `[[lowered]]` entry to `.github/quality/waivers.toml` ([`testing.md`, "What the kit holds"](testing.md#what-the-kit-holds)) | `suite_rules.py`, in the lint job against the pull request's base or what `main` was before the push, in the hook against where the branch left `origin/main` | The number is the pull request's own text. |

The kit's own code is the first to meet it. [`quality/tests/workflow_contract.yaml`](../quality/tests/workflow_contract.yaml) states every job and step of every workflow with its reason, and the tests run each script with its tools replaced, so no line of a workflow changes without saying why. The `check` job measures line and branch coverage of every root ([`.coveragerc`](../.coveragerc), whose exclusions carry their reasons) and [`quality/coverage_floor.py`](../quality/coverage_floor.py) holds each file to the share it has reached: a file that is not listed is held to 100 %.

## Licensing headers

Owner, 2026-11-22. Every file that can carry a comment starts with both REUSE lines, in its comment syntax, copyright first:

<!-- REUSE-IgnoreStart -->

```text
SPDX-FileCopyrightText: <year> José M. Requena Plens
SPDX-License-Identifier: <the repository's license for the file>
```

<!-- REUSE-IgnoreEnd -->

- `<year>` is the year of the file's first commit, as `git log --diff-filter=A --format=%ad --date=format:%Y -- <file>` gives it (read in UTC), and the current year for a file not committed yet. The check also accepts the year before: a file added in a pull request written in December can come to `main` in January with a commit made then (a commit taken as the owner's keeps its author's date, but one of Dependabot's is made anew, and until 3.4.0 the public repositories merged by squash), and its header, written in December, must not turn `main` red. A pull request that crosses the new year needs nothing else; the writer always sets the first-commit year.
- At least one copyright line names José M. Requena Plens. A third-party file is stated in `REUSE.toml` with `precedence = "override"` instead.
- **Year and name only** (owner, 2026-11-24): no e-mail address, in a file, in `REUSE.toml` or in a license text; a `SPDX-FileContributor` line beside the two holds a name only as well. The owner's line of a `LICENSE` or of a text under `LICENSES/` is `Copyright (c) <year> José M. Requena Plens`, with `All rights reserved.` after it where that is the license; a third party's line is never touched. A statement anywhere in the tree that puts an e-mail beside the owner's name is found too, a `mailto:` link included. A header may add in parentheses which part it covers, `(Spanish translation)`. In a repository that still holds kit 2.x copies the license texts are a note until it switches.
- The license stays the one each repository already declares (MIT, GPL-3.0-or-later, ...).
- A file that cannot carry a comment (images, JSON, binaries, lockfiles, generated data) gets both lines through a `REUSE.toml` annotation (`SPDX-FileCopyrightText` and `SPDX-License-Identifier`), never a `.license` sidecar unless `REUSE.toml` cannot express it. So does a file `REUSE.toml` covers with `precedence = "override"`: third-party text, the kit's managed-block sources, and the pull request template, whose text GitHub copies into every pull request.
- The lines sit in a comment at the top of the file: in Markdown and HTML an HTML comment at the top (after any front matter, XML declaration or doctype); in CSS and linker scripts a block comment; in an Astro component `//` lines at the top of its front matter (an HTML comment in its template would reach every page that renders it; the writer opens a front matter where there is none); elsewhere line comments, after a shebang or an encoding line. Lines further down, or inside a docstring, do not count.
- A text file in a format the check has no comment syntax for (JSON, SVG, a KiCad file, a TSV, a `.python-version`) is named in a `REUSE.toml` annotation of its own, by path or by format (`**/*.json`), not only by the catch-all `**`: the check lists every such file, so a new format is a decision, either its syntax added to [`spdx_headers.py`](../quality/spdx_headers.py) or an annotation. A file with a shebang is a script and takes `#` lines whatever its name. Formats that take comments include ESP-IDF's `sdkconfig*`, `Kconfig*`, partition tables (`partitions*.csv`) and linker fragments (`.lf`), `Doxyfile` and `.dox`, `.supp`, `.S`, `.ld`, `.cppcheck-suppress` and `.git-blame-ignore-revs`.

`reuse lint` proves that every file states both, in the file or in `REUSE.toml`; [`quality/spdx_headers.py`](../quality/spdx_headers.py) proves that every file that can carry a comment states them itself, in order, with the right year and no e-mail, and holds the license texts. Both run in [`reusable-reuse.yml`](../.github/workflows/reusable-reuse.yml), which fetches the whole history for the years, and as hooks. The base configurations keep the kit's year and are checked for presence only; in a shallow clone only presence is checked.

To add or repair the lines, with the year from git and the license from the file's own line, else its `REUSE.toml` annotation, else `--license`, from a checkout of this repository:

```bash
python3 quality/spdx_headers.py --repo <repository> --write            # every file
python3 quality/spdx_headers.py --repo <repository> --write 'src/**'   # some
```
 A template or generator that emits files (a skill's file template, a script that writes a `REUSE.toml` annotation) writes both lines.

### Supplier fields

Metadata that says who a thing comes from holds a name and no e-mail address, as a copyright does (owner, 2026-11-25). The one address that may stand there is `mail@kleidos.dev`, and only where the tool that reads the field needs an address: it is a weakening, and its waiver's reason names that tool. Any other address is refused, with no waiver.

```toml
[[waiver]]
tool = "supplier"
what = "address:project.authors.email"   # as check_quality.py names it
where = "pyproject.toml"
reason = "Which tool refuses the field without an address, and how it says so"
decided = "owner 2026-11-25"
```

- The files and their fields are one list, `METADATA` of [`supplier_fields.py`](../quality/supplier_fields.py): `REUSE.toml` (`SPDX-PackageSupplier`, `SPDX-PackageOriginator`, `SPDX-FileContributor`), `package.json`, `composer.json` and their like, `pyproject.toml` and `Cargo.toml`, `CITATION.cff`, `codemeta.json` and `.zenodo.json`, ESP-IDF's and PlatformIO's component manifests, the plugin manifests of `.claude-plugin/`, `action.yml`, `manifest.json`, the software bills of materials (SPDX, CycloneDX), the older package formats (`setup.cfg`, `debian/control`, ...) and, at the root and in `.github/`, the lists of people (`AUTHORS`, `CODEOWNERS`, `.mailmap`, ...). A new kind of metadata is a row there. A `SPDX-FileContributor` line of a file's header is held by the [header check](#licensing-headers).
- A field holds everything below it, and nothing else of the file counts, but a text with a `mailto:` link, which is read wherever it is: a `description` that names an address otherwise is not a supplier. A file whose format has no fields in the list (`setup.cfg`, `AUTHORS`) is searched whole, `setup.py` by its strings; so is one that cannot be read as its format says. YAML is read with its aliases, merges and `!!binary` texts.
- An address is searched for in the text as a person reads it: with no character that does not show, with HTML entities, percent-encoding, `\x40` escapes and compatibility forms (a fullwidth `@`, an ideographic full stop) decoded. It is found in capitals, in a `mailto:` link, with spaces around the `@`, with a quoted name or an address literal (`[192.0.2.1]`), with the marks in brackets or in words (`user [at] host [.] tld`, `user[@]host.tld`, `user at host dot tld`, `user_at_host_dot_tld`), and with a plain `at` inside brackets, `(user at host.tld)`. `mail@kleidos.dev` is the allowed one only when it is written as it is.
- Not an address: the user of a URL (`https`, `ssh`, `git+ssh`, ...; a `mailto://` is no such URL), a clone address (`git@host:path`), a version (`name@1.2.3-rc.1`), an image (`logo@2x.png`), and, in a file searched whole, a handle of the fediverse (`@user@host`). In a list of people in Markdown and below a folder of tests or fixtures, nor is one at a domain reserved for examples (`example.org`, `.invalid`, `.test`).
- Of a software bill of materials the document's own people are read (`metadata`, `creationInfo`, the packages it says it describes, or every one where it does not say), not those of the packages it lists, which are other people's.
- A file `REUSE.toml` states is a third party's is not ours to correct: an annotation of its own, not the catch-all, whose copyright names neither the owner nor Kleidos. `REUSE.toml` itself is never a third party's. A nested `REUSE.toml` or a header inside the file says nothing here: the root's `REUSE.toml` states it.
- A key that holds an address is printed as `*`: a log is read by anybody.
- What the rule does not read, so a reviewer does: a comment beside a field, a name with no domain (`user@host` outside angle brackets), a plain `user at host.tld` with no brackets around it, an address in pieces that are put together when the file is run, spelled backwards or in another language's words, a compressed file, and the metadata no row names (`pom.xml`, `Dockerfile` labels, `.npmrc`, `PKG-INFO`, a skill's front matter, SPDX as RDF). A document and the contact of a page are no metadata. A repository that still holds kit 2.x copies is not read.

## Reusable workflows

Every check a repository runs is a job of the kit, one workflow per concern, which the [entry workflows](#the-entry-workflows) call; a repository calls one itself, at `@v3`, only for what they do not say. Its own steps that cannot be shared stay local jobs.

| Workflow | Job | Inputs | Caller permissions |
| --- | --- | --- | --- |
| [`reusable-lint.yml`](../.github/workflows/reusable-lint.yml) | Every policy check ([`policy.py`](../quality/policy.py), from the kit that is called), on the whole history, which says what the coverage thresholds were; every pre-commit hook on every file (mypy, reuse and the header lines excepted: they have their own workflows), zizmor's online audits | `skip`, `deny-hooks` (the repository's own hook ids; a kit hook fails the check), `python-version` | `contents: read` |
| [`reusable-deny.yml`](../.github/workflows/reusable-deny.yml) | The repository's own hooks that read the deny-list, alone with it ([The entry workflows](#the-entry-workflows)) | `hooks` (required); the secret `deny` | `contents: read` |
| [`reusable-reuse.yml`](../.github/workflows/reusable-reuse.yml) | `reuse lint`, then the header lines, on the whole history | | `contents: read` |
| [`reusable-mypy.yml`](../.github/workflows/reusable-mypy.yml) | mypy with the repository's dependencies installed, through the kit's `mypy_groups.py`: one run per [mypy group](#mypy-groups), each folded in the log, an error annotation per failing group and a table of every group in the job summary (a bare `mypy` without groups) | `install`, `python-version-file`, `python-version` | `contents: read` |
| [`reusable-python-tests.yml`](../.github/workflows/reusable-python-tests.yml) | The repository's tests, and `coverage.xml` as the `coverage` artifact for SonarCloud | `run` (required), `install`, `python-version`, `python-version-file`, `coverage-report`, `coverage-artifact`, `timeout-minutes` | `contents: read` |
| [`reusable-eslint.yml`](../.github/workflows/reusable-eslint.yml) | `npm ci`, ESLint with no warning allowed, and `tsc --noEmit` on each project | `working-directory`, `projects`, `node-version` | `contents: read` |
| [`reusable-osv.yml`](../.github/workflows/reusable-osv.yml) | OSV-Scanner, failing on any known vulnerability | | `contents: read` |
| [`reusable-secrets.yml`](../.github/workflows/reusable-secrets.yml) | gitleaks over the history and the tree with both configs, and the MAC plant test | | `contents: read` |
| [`reusable-sonarcloud.yml`](../.github/workflows/reusable-sonarcloud.yml) | The secretless SonarCloud analysis, moved unchanged from the public repositories: OIDC token exchange (`SonarSource/sonarqube-auth-action`), scan (`SonarSource/sonarqube-scan-action`), and a wait until SonarCloud accepted the analysis; a pull request with no OIDC token (a fork, Dependabot) ends green with a notice | `coverage-artifact` (`coverage`; empty for none) | `contents: read`, `id-token: write` |
| [`reusable-commit-check.yml`](../.github/workflows/reusable-commit-check.yml) | The commit-message gate, on a pull request, and the identity of the owner's commits that a pull request or a push adds | | `contents: read` |
| [`reusable-commit-check-comment.yml`](../.github/workflows/reusable-commit-check-comment.yml) | The one commit-check comment, from a `workflow_run` caller that follows the gate workflow | | `actions: read`, `pull-requests: write` |
| [`reusable-quality-drift.yml`](../.github/workflows/reusable-quality-drift.yml) | Kit 2.x only: the weekly drift notice, which always answers "not behind" now; it stays while a 2.x caller remains | | `contents: read` |

The org's Actions policy allows only GitHub-owned and verified actions, so the kit uses no third-party action: tools come from PyPI with hashes ([`quality/requirements-tools.txt`](../quality/requirements-tools.txt)), from pre-commit hook repositories, or as release binaries pinned by SHA-256 in [`quality/tools.lock`](../quality/tools.lock) and installed by [`quality/fetch_tool.py`](../quality/fetch_tool.py). Each called job's name shows on GitHub as `<caller job> / <called job>`. A job's working directory is the repository's tree, so every `python -m` and `python -c` of a kit job runs with `-I`: Python would otherwise import a `pip.py` or a `json.py` of the tree in place of the module named (a script named by its path reads its own folder, the kit's, first); `test_entry_workflows.py` holds it.

A notice is a line of the [ecosystem report](ecosystem.md), not an issue: issues are off in most kleidos-dev repositories, and no workflow here may open a pull request (`GITHUB_TOKEN` pull requests run no CI, and a PAT or App token is not used). GitHub disables the scheduled workflows of a public repository after 60 days without activity in it; the local report says when the public one has stopped, and a repository that has been quiet that long gets its `CI` workflow re-enabled (`gh workflow enable`) whenever it is next touched.

## Overrides

1. **Adding is free.** A repository may add rules, checks, hooks, stricter flags and wider scopes without asking: `extend-select`, more clang-tidy checks, a mypy flag the block does not set, an ESLint plugin, a CI job.
2. **Weakening needs a recorded reason.** Anything that makes a tool report less than the kit on the same code is a weakening: a rule off or down to a warning, an ignore or per-file ignore, an excluded path, a `-check`, a relaxed tsconfig or ESLint setting, a markdownlint rule turned off, a manifest directory Dependabot does not cover, a job with `continue-on-error`. Each is an entry in the repository's `.github/quality/waivers.toml`:

   ```toml
   [[waiver]]
   tool = "ruff"                # ruff, eslint, tsconfig, clang-tidy, markdownlint, ci, dependabot, pre-commit, reuse, pins, typos, actionlint, supplier
   what = "ignore:E501"         # the weakening, as check_quality.py names it
   where = "pyproject.toml"     # optional: the file, when the same weakening is in two
   reason = "Why the rule is wrong for this code, with the sites read"
   decided = "owner 2026-11-22" # or "agent, reviewed in PR #<n>"
   expires = 2027-05-22         # optional
   ```

   `check_quality.py` fails on a weakening with no waiver, on a waiver with no `reason` or `decided`, on a waiver that matches nothing any more, and on an expired one. A coverage threshold that falls is said in the same file, in a `[[lowered]]` entry that counts in the change that adds it ([Tests](#tests)). The lint job's summary lists every waiver in effect and counts the inline suppressions.
3. **Some things cannot be waived:** a mypy suppression beyond missing types (owner: every error fixed, no baseline), a gitleaks global allowlist or `disabledRules`, an inline suppression without its code, an edited copy, the kit's reference, the gate, and any SonarCloud suppression (owner: an issue is fixed with a real change or left open).
4. **Inline suppressions** carry their code and a reason: `# noqa: S603  <why>`, `# type: ignore[arg-type]  # <why>`, `# zizmor: ignore[<rule>]` with the reason on the line above, `// NOLINT(<check>): <why>`, `// eslint-disable-next-line <rule> -- <why>`. `RUF100` and mypy's `warn_unused_ignores` remove dead ones.
5. **A weakening every repository needs moves into the kit**, in one pull request here, with its reason in the kit file (as `S603`, `S607` and `self-repository` are).
6. **Facts are not weakenings**: `python_version`, `target-version`, `files`, `mypy_path` and the mypy groups (while coverage holds), `HeaderFilterRegex`, naming conventions, `known-first-party`, tsconfig `types` and `include`, typos exceptions for words that are right.

## Versions

- [`quality/VERSION`](../quality/VERSION) is the kit's semver, with an entry per release in [`quality/CHANGELOG.md`](../quality/CHANGELOG.md). MAJOR: anything that can turn a green repository red (a rule on, a stricter setting, a tool bump with new findings, a new conformance rule some repository fails). MINOR: a new opt-in profile or tool, or a rule every repository already passes. PATCH: docs, or a checker fix that cannot add findings.
- **The branch `v<major>`** is the kit's name. A MINOR or PATCH release moves it, fast forward, to its commit on `main`, and every repository runs it at its next run ([How often it moves](#how-often-v3-moves)). A MAJOR opens the next branch, and each repository moves its line in the pull request that carries its fixes; the old branch keeps working, frozen. No tag may ever be named like a branch: GitHub resolves the tag first, so the tag ruleset exists before the branch, and the report turns red on one.
- **The tag `v<VERSION>`** is signed and is the hooks' `rev`. No workflow is called at it ([The entry workflows](#the-entry-workflows)). Releases before 3.0.0 are the tags `quality-v<VERSION>`.
- Tool versions are set here only: [`quality/requirements-tools.in`](../quality/requirements-tools.in) compiled with hashes into `requirements-tools.txt` (the command is in its header), the actions the workflows pin, and `tools.lock`; `check_quality.py`'s `LATEST_PYTHON`, `LATEST_ACTIONS` and `LATEST_HOOKS` repeat the Python, action and canonical hook versions, and a kit test keeps them equal; `LATEST_IMAGES` names the container images repositories run. Dependabot bumps the first two and the hook revisions here; a repository's own hook revisions are moved by its own Dependabot.
- A Dependabot pull request here is a kit release like any other, and `land` leaves it to a person: its change goes into a branch of the maintainer's (`git merge --squash` of its head, then a signed commit), with the new `quality/VERSION` (MINOR for a tool bump that finds nothing new in the impact preview, MAJOR if it finds more) and its `quality/CHANGELOG.md` entry (the `🏷️ Kit release and its tag` job fails until then; a pip bump of `requirements-tools.txt` also needs its header put back on top, as the file says), then the tag once it has landed. Dependabot's pre-commit updater reads crate-ci/typos' sub-crate tags (`varcon-core-v5.0.7`) as typos versions, so `dependabot.yml` ignores typos `>= 2` (closed PR #10).

### How often `v3` moves

The rule is at most once a week. `v3` runs in every repository at once, so a release is proved by the repositories' own runs, and a week between two of them is what lets a bad one be seen, and told from the one before, before the next hides it; it also keeps the CI no further than a week ahead of the hooks, which Dependabot moves weekly.

It has not been kept yet: 3.0.0 made the branch on 2026-11-24, and 3.1.0, 3.1.1, 3.1.2, 3.2.0 and 3.3.0 moved it five times on that day and the next. Two exceptions say when that is right:

- **A security fix** moves it at once. 3.1.0 and 3.1.1 were that.
- **A decision of the owner that has to hold everywhere from a date**, while the organization is being built: the repositories are few, nobody outside depends on them, and each release re-ran every one's CI. 3.2.0, 3.3.0 and 3.4.0 are that. It is not a habit to keep: once the firmware is public and somebody else's work meets the gate, only the first exception is left.

A release that moves the branch within the week says in its changelog which of the two it is. In either case the impact preview over every repository comes first (`tools/ecosystem.py preview --all`), and the CI of every repository is run again right after the move: a repository that is not pushed to would show a red days later, as nobody's.

## Changing the kit

1. One pull request here: the change, `quality/VERSION`, `quality/CHANGELOG.md`, the new digest in `quality/config-digests.json` when a base configuration changed (its old ones stay: a repository may hold them), and `python quality/sync.py --write .`, so this repository records it (its `SOURCE.json` records commit `self` and is compared with the working tree).
2. CI runs the entry workflows on this repository, by `./` path, so the pull request runs its own version of them; the kit's tests; the release check (`sync.py --release-check --online`: a change to what repositories run, without a new `quality/VERSION` newer than the newest tag and its `CHANGELOG.md` entry, fails; so does a release tag that is lightweight, carries no signature or is one GitHub does not verify, and any tag named like a branch, `v3` or `main`); and an impact preview, `tools/ecosystem.py preview`, which applies the changed kit to throwaway clones of the public repositories and writes their counts to the job summary. Before a release, `tools/ecosystem.py preview --all` does the same locally with the private ones.
3. Land it ([Merging](#merging)), then release from what is on the remote, never from a local `main`, in the one line that also moves the branch: `git fetch origin && git tag -s vX.Y.Z -m 'Quality kit X.Y.Z' origin/main && git push origin vX.Y.Z refs/remotes/origin/main:refs/heads/vX`, then `gh release create vX.Y.Z --verify-tag --notes-file <the changelog entry>`. Until the tag exists and the branch is at its commit, the release job of that push to `main` is red; re-run it once both are pushed.

A bad release is red everywhere at once. The repair is a revert on `main`, a new PATCH and the same line again; then each repository that went red needs **Re-run all jobs**, since "Re-run failed jobs" keeps the workflow files the first attempt read.

**Never delete or move a `vX.Y.Z`** once the first repository has switched: it is the hooks' `rev` in every repository, and the commit a held record may note. The same for the `quality-v*` tags while a 2.x caller remains.

## Merging

A pull request lands by a fast forward of `main` to its own head: the commits that were reviewed and checked are the ones that land, with the signatures they have. Nobody presses a merge button and nobody runs `gh pr merge` (owner, 2026-11-25): what they make of the owner's work is committed and signed by GitHub, which [the identity of a commit](#the-identity-of-a-commit) refuses, and what they make of a contributor's would lose the contributor's own commits. GitHub marks a pull request whose head reached `main` as merged.

Every pull request of a repository in the run form, the owner's and the agents' alike:

1. `gh pr diff <n> --name-only`. If a path starts with `.github/`, or is `.pre-commit-config.yaml`, read that part of the diff line by line before anything else: `✅ Check` is the pull request's own workflow there and is not proof.
2. Rebase the branch on `main` locally and push it: `git rebase --gpg-sign origin/main`, `git push --force-with-lease`. The required checks are attached to the head commit, so they run again on this one, and they are the ones that count.
3. `python tools/ecosystem.py land kleidos-dev/<repository>#<n>` says whether it would land and why not; with `--merge` it waits for the checks, lands it and confirms it. Where step 1 found something, `--read <head>` says that it was read, at that head and no other.

What the tool does can be done by hand: every commit signed and verified, every check green on that exact head, `✅ Check` of GitHub Actions (App 15368) among them, `main` still where the branch starts, `git push origin <head>:main` with no force, and the pull request then says merged. It is how a repository lands whose jobs GitHub does not start (private minutes): the same gates, run locally, are pasted in the pull request.

What [`tools/ecosystem.py land`](ecosystem.md#landing-a-pull-request) refuses is tested: a draft, an owner's branch that is not on top of `main`, a commit that says it is the owner's and is not, one nobody signed, a merge commit, a part of the diff that has to be read and was not, a check that is red, missing or still running after an hour, a head or a `main` that moved meanwhile, a signature GitHub has not decided on.

What it judges is what it pushes: the commits are asked for by the SHAs of `main` and of the head, not as the pull request's own list, which is of whatever its head is at that instant; whether `.github/` or the hook list changed is asked of git, in the clone the push is made from; and the checks of the head are asked once more right before the push, after everything else.

**A contributor's work** lands with the contributor as its author, and the maintainer runs the same command on it once the contributor has signed the CLA and the pull request is green:

- **As it is**, when every commit is signed and GitHub verifies it, and the branch is on top of `main`: the contributor's own commits are pushed to `main`, with the contributor's author, committer and signature, whoever's key it is, and GitHub shows the pull request as merged.
- **Rebased by the maintainer**, when a commit is not signed or `main` has moved: the commits go on today's `main` one by one, with their author and message as they are, on a branch `land/pr-<n>` with a pull request of its own, which lands as above. Only there are the committer and the signature the owner's, because the owner makes those commits. The contributor's pull request is then closed with the commit it landed as, since GitHub shows as merged only a pull request whose own commits reach `main`.

Nobody has to sign to contribute, and somebody who wants the signature kept rebases on `main` and signs. A merge commit, a message that breaks the rules, a commit that says it is the owner's, or a conflict with `main` goes back to the contributor. Nothing of a pull request runs on the maintainer's machine, and nobody else's commits are ever made the owner's.

**An update of Dependabot's** lands as one commit of the owner's, since a bot has no authorship to keep, the same way; `land` on its own walks those that pass [its guards](ecosystem.md#landing-the-bots-pull-requests). One the guards leave to a person (an action, a hook, a major version) is taken by name, with `--read <head>` once its diff was read whole.

A force push is `git push --force-with-lease` on the branch of one's own pull request; anything else (plain `--force`, `main`, `v3` and the other kit branches, a tag, anybody else's branch) only when the owner orders that act (owner, 2026-11-25). A rebase or a reworded commit so needs no new pull request.

The required checks are a ruleset of their own on `main`, with an empty bypass list, so nobody lands past a red one; the rest of `main`'s rules are another, which an organization admin may bypass, and a required check there would be bypassed with it. That bypass is what lets the owner push to a `main` that moves by pull request only. The signature is to be required with an empty bypass list too: GitHub then refuses the buttons that cannot sign, where squash and merge commits are off, and takes a push of commits somebody signed (tried, 2026-11-25). That is the one rule every commit of `main` meets, a contributor's too; whose the owner's are is [another](#the-identity-of-a-commit). A squash of the whole history before a repository goes public needs the first one disabled for that push, and enabled again right after.

## Proof from another repository

A `./` call of this repository proves everything but one thing: that the call works from *another* repository. Before any repository switches, and again for each new major, two throwaway branches prove it, one private and one public; neither is ever merged.

1. **Private, on a push: `kleidos-dev/qa`.** In a fresh clone, on a branch `kit-proof`: `python <this checkout>/tools/kit_switch.py --write .`, correct what `python <this checkout>/quality/policy.py --repo .` then lists (the paths `AGENTS.md` still names), add `kit-proof` to the gate workflow's `push: branches`, commit, push the branch. Expected: the run is green (or red only for a reason of `qa`'s own, read), `✅ Check` is there under its bare name, every kit job's summary says `kit v3.0.0 (<the commit v3 names>)`, and `gh api repos/kleidos-dev/qa/actions/runs/<id> --jq .referenced_workflows` lists `quick.yml@v3` with `"ref": "refs/heads/v3"` and that commit.
2. **Public, on a pull request: `kleidos-dev/boards`.** The same switch on a branch, as a draft pull request. Expected, besides the above: the commit-message job ran (it only does on a pull request), `sonar` was given its OIDC token from the named reference and SonarQube Cloud accepted the analysis, and a commit whose subject breaks a rule turns `quick` red and leaves its result for the comment (which is posted once the caller is on `main`, not before: `workflow_run` runs the default branch's file).
3. In either clone, `pre-commit run --all-files` with `PRE_COMMIT_HOME` at an empty folder: the kit's hooks install from the tag and run.
4. Close the pull request, delete both branches.

## Outside the kit: Socket, CodeQL, SonarCloud

- **Socket** (owner: public repositories only) is a GitHub App, so installing it is the owner's click: <https://github.com/apps/socket-security/installations/new>, account `kleidos-dev`, "Only select repositories": `.github`, `boards`, `brand`, `cla`. Free plan; it reads the pip and npm manifests and comments on pull requests that change them. Check the permissions page before accepting (contents and metadata read, checks and pull-request write expected). No `socket.yml` is needed for its defaults.
- **CodeQL** runs as GitHub's default setup on every public repository (a repository setting, no workflow): `actions` and `python` on `.github`, boards and brand; `actions`, JavaScript/TypeScript and `python` on cla. No repository runs a CodeQL workflow, so the kit has none: default setup and an advanced-setup workflow are exclusive. Its license forbids it on private code.
- **SonarCloud** settings live in each `sonar-project.properties` and in [`sonarcloud.md`](sonarcloud.md); the kit only runs the analysis job. That job is green once SonarCloud has accepted the analysis, whatever the quality gate says: the gate is SonarCloud's GitHub App's check on the commit, which no ruleset requires, so the ecosystem report reads the gate of every public `main` and is red while one fails ([`ecosystem.md`](ecosystem.md), "What it reads"): this repository's `main` was red there through 3.0.0 and 3.1.0 while the job was green. What the scan runs and where it sends the result is the kit's: the check refuses `sonar.scanner.*` (but `autoconfig.enabled=false`), `sonar.host.url`, `sonar.region`, `sonar.nodejs.executable` and `sonar.working.directory` in the file, since a program of the tree named there would run in the step that holds the token. It also refuses, with no waiver ([Overrides](#overrides)), a suppression (`sonar.issue.ignore.*`, `sonar.issue.enforce.*`) and an exclusion of every file in `sonar.exclusions`, `sonar.test.exclusions`, `sonar.coverage.exclusions` or `sonar.cpd.exclusions` (`**`, `**/*`, and `**/*.*`, since Sonar reads a file by its extension). Reading the mypy and ruff reports into SonarCloud (`sonar.python.mypy.reportPaths`, `sonar.python.ruff.reportPaths`) is a later minor release.
