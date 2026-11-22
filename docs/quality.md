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

Everything a repository took from the kit is recorded in `.github/quality/SOURCE.json`: the kit version, the kit commit, the profiles, and the SHA-256 of every copy and every block. Every call to a kit workflow names that same commit, so a repository is at exactly one kit version for configs and CI alike. kleidos-dev/agents' commit-check copies and their digest test are the model this follows.

Profiles say what applies: `base` (every repository), `python`, `actions`, `shell`, `ts`, `cpp`. They are detected from the tree, and the checker fails when the tree holds a language whose profile is not adopted.

| Profile | Copies | Blocks | Seeded once |
| --- | --- | --- | --- |
| base | `check_quality.py`, `md_nowrap.py`, `spdx_headers.py`, `requirements-tools.txt`, `markdownlint.jsonc` (all in `.github/quality/`), `.gitleaks-mac.toml` | `pre-commit-base`, `typos` | `.gitleaks.toml`, `.github/quality/waivers.toml`, `.markdownlint-cli2.jsonc`, `quality-drift.yml`, the two commit-check callers |
| python | `.github/quality/ruff.toml` | `pre-commit-python`, `mypy` | |
| actions | `.github/zizmor.yml` | `pre-commit-actions` | |
| shell | `.shellcheckrc` | `pre-commit-shell` | |
| ts | `.github/quality/eslint.base.mjs`, `.github/quality/tsconfig.base.json` | | |
| cpp | `.clang-tidy` (the root one) | | |

A seeded file is written once, when the repository has none, and is the repository's own from then on, held to the conformance rules. The two commit-check callers also replace a repository's copies of kleidos-dev/agents' `commit-check.yml` and `commit-check-comment.yml`.

## Adopting the kit in a repository

1. Clone kleidos-dev/.github beside the repository and check out the kit commit to record (normally `main`): `sync.py` records `HEAD` and refuses a dirty tree.
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
4. Replace the CI with thin callers. [`quality/templates/workflows/check.yml`](../quality/templates/workflows/check.yml) is the model: lint and licensing first, then types, tests, OSV and the history scan side by side, then SonarCloud (public repositories). Keep the repository's own jobs (a model build, a firmware build, a picture check) beside them. Every job keeps the CI conventions: an emoji name, `timeout-minutes` (a caller job's comes from the called workflow), staged `needs:`, least `permissions`. Re-run `sync.py --write .` after editing, so the new calls name the recorded commit.
5. `.github/dependabot.yml`: every manifest directory has its ecosystem; `github-actions` ignores `kleidos-dev/.github*` (the sync moves those references); no `pre-commit` ecosystem (hook versions come with the sync); nothing under `.github/quality/`. Turn on Dependabot security updates: `gh api -X PUT repos/<owner>/<repo>/automated-security-fixes`.
6. Fix everything the tools report, in the same pull request: `pre-commit run --all-files`, `mypy`, `python3 .github/quality/spdx_headers.py --write` for the licensing headers, `reuse lint`. A waiver only where [Overrides](#overrides) allows one. A first `ruff format` of the whole tree is its own commit, listed in `.git-blame-ignore-revs`.
7. Install the hooks (`pre-commit install --hook-type pre-commit --hook-type commit-msg`), commit signed, and merge once CI is green.

The checker, offline, is the pre-commit hook `kleidos-quality`; with the kit beside it, `python3 ../.github/quality/sync.py --check .` compares the copies with the kit's working tree.

## The rules

Each rule below is enforced by the tool named, with the kit's configuration; the reason is why the estate holds it.

### Python (profile `python`)

| Rule | Enforced by | Why |
| --- | --- | --- |
| ruff with the kit's rule set: `E`, `F`, `W`, `I`, `B`, `UP`, `SIM`, `PLE`, `PLW`, `BLE001`, `DTZ`, `ASYNC`, `RUF012`, `RUF100`, `C4`, `PIE`, `RET`, `PERF`, `S`, `PGH003`, `PGH004`; line length 100; `S101`, `S105`, `S106` allowed in tests | `ruff check` (hook and lint job), [`quality/ruff/ruff.toml`](../quality/ruff/ruff.toml) | The bug-finding sets of the analyzer proposal (subprocess calls without `check=`, overwritten loop variables, naive datetimes, bare `except Exception`, Python syntax newer than the declared floor). `S603` and `S607` are off kit-wide: they flag every argument-list subprocess call and every call by program name, so they cannot tell a safe call from an unsafe one; the shell forms stay on. |
| One formatting: `ruff format` | hook `ruff-format` | No style review; diffs show only changes. |
| A local `select` is refused | `check_quality.py` | It would replace the kit's list instead of adding to it; use `extend-select`. |
| mypy strict, `ignore-without-code` | mypy block, [`reusable-mypy.yml`](../.github/workflows/reusable-mypy.yml) | Owner, 2026-11-22: mypy, as in phonometry, with every error fixed and no baseline. The block is phonometry's floor: `strict = true`, `enable_error_code = ["ignore-without-code"]`. |
| mypy checks every tracked Python file | `check_quality.py` (`files` minus `exclude` must cover every `*.py`) | A checker that skips a directory reports nothing about it, and that silence reads as green. |
| No mypy suppression beyond missing types | `check_quality.py`, no waiver | `ignore_errors`, `disable_error_code`, `follow_imports = skip`, `allow_*`, any strict flag set false, an inline `# mypy:` configuration and an override that sets anything but `ignore_missing_imports` are refused. |
| An inline `# type: ignore[code]  # reason` | `check_quality.py`, mypy's `warn_unused_ignores` | Names what it silences, says why, and dies when it silences nothing. |

### Workflows and shell (profiles `actions`, `shell`)

| Rule | Enforced by | Why |
| --- | --- | --- |
| actionlint | hook `actionlint` | Syntax, expressions, and shellcheck inside every `run:`. |
| zizmor, offline in the hook and online in the lint job | hook `zizmor`, [`reusable-lint.yml`](../.github/workflows/reusable-lint.yml), [`quality/zizmor/zizmor.yml`](../quality/zizmor/zizmor.yml) | Workflow security: template injection, credentials left by checkout, cache poisoning, excessive permissions. Every `uses:` is pinned by commit SHA, GitHub's own actions included (the trivy-action tag rewrite of 2026-03-19 is the risk). The `self-repository` audit is off kit-wide: it asks for `uses: $/...`, which actionlint 1.7.12 rejects. |
| A zizmor finding is accepted only inline: `# zizmor: ignore[<rule>]` with the reason on the line above | `check_quality.py` | The repository's `zizmor.yml` is the kit's copy, so there is no ignore list to grow. |
| CI conventions: an emoji first in every job name, a `timeout-minutes` on every job that runs steps, every `uses:` pinned by a 40-hex SHA with its version in a comment, no `continue-on-error: true` on a job | `check_quality.py` | The owner's conventions, now checked. A job with `continue-on-error` is green whatever it finds. |
| Every check comes from the kit | `check_quality.py` (the base profile's kit workflows, `reusable-mypy.yml` with the python profile, `reusable-sonarcloud.yml` where `sonar-project.properties` exists) | One definition of each check, so a fix reaches every repository. |
| shellcheck at warning severity | hook `shellcheck`, [`quality/shellcheck/shellcheckrc`](../quality/shellcheck/shellcheckrc) | Quoting and word-splitting bugs; notes and style stay out. |

### Every repository (profile `base`)

| Rule | Enforced by | Why |
| --- | --- | --- |
| Spelling, US English | hook `typos` (report only: a spelling "fix" in code is a bug), the typos block (`locale = "en-us"`) | The estate's prose and identifiers use US spelling; typos also catches misspelled identifiers. |
| Secrets: every default gitleaks rule, over the tree and the whole history | hooks `gitleaks`, [`reusable-secrets.yml`](../.github/workflows/reusable-secrets.yml) | Private repositories get no GitHub secret scanning on the Free plan. |
| MAC addresses: the kit's MAC rules | hook `gitleaks-mac`, `.gitleaks-mac.toml` (a copy of [`quality/gitleaks/mac.toml`](../quality/gitleaks/mac.toml)), the plant test | The bench's board MACs are private. The MAC config extends nothing, so the default allowlist (images, fonts, lockfiles) never hides a MAC; the plant test proves the rules still fire on real shapes and spare the fakes. |
| `.gitleaks.toml`: `useDefault = true`, no `disabledRules`, no global `[allowlist]`, every `[[allowlists]]` with a `description` and `targetRules`; every `.gitleaksignore` fingerprint with a comment above it; scans run with `--ignore-gitleaks-allow` | `check_quality.py`, no waiver | An allowlist that reaches every rule hides the next real secret. |
| Known vulnerabilities fail the build | [`reusable-osv.yml`](../.github/workflows/reusable-osv.yml) (OSV-Scanner over every manifest and lockfile, also weekly) | Advisory-only scanning was ignored. An accepted one goes in `osv-scanner.toml` with a `reason` and an `ignoreUntil` at most 90 days ahead (`check_quality.py`). |
| Dependabot covers every manifest | `check_quality.py` | A directory without its ecosystem never gets a security update. |
| Licensing: `reuse lint`, and the header lines | [`reusable-reuse.yml`](../.github/workflows/reusable-reuse.yml), hooks `reuse` and `kleidos-spdx-headers` | See [Licensing headers](#licensing-headers). |
| Markdown prose is never hard-wrapped | hook `kleidos-md-nowrap` ([`quality/md_nowrap.py`](../quality/md_nowrap.py)) | Owner, 2026-11-16: one line per paragraph and per list item. |
| Markdown tables render: MD055, MD056, MD058 only | hook `markdownlint-cli2`, [`quality/markdownlint/base.jsonc`](../quality/markdownlint/base.jsonc) | Broken tables are the findings that matter; the rest of markdownlint's defaults measured as noise. |
| The kit is intact | hook `kleidos-quality`, the lint job | Every copy and block is the bytes `SOURCE.json` records and, in CI, the bytes the kit holds at that commit (the CI fetches the checker from the kit, so an edited local checker cannot pass itself). |
| Commit messages | [`reusable-commit-check.yml`](../.github/workflows/reusable-commit-check.yml), the `kleidos-commit-msg` hook | kleidos-dev/agents' gate: 72 columns, imperative, no AI attribution. |

### TypeScript and C++ (profiles `ts`, `cpp`)

| Rule | Enforced by | Why |
| --- | --- | --- |
| ESLint `strictTypeChecked` plus `no-deprecated` and `switch-exhaustiveness-check` | [`quality/eslint/base.mjs`](../quality/eslint/base.mjs), `check_quality.py` (a base rule set to `off` or `warn` locally is a weakening) | Type-aware bugs Sonar does not see. ESLint and its plugins stay the repository's dependencies. |
| `tsc` strict flags: `strict`, `noUncheckedIndexedAccess`, `noImplicitOverride`, `noFallthroughCasesInSwitch`, `noImplicitReturns`, `exactOptionalPropertyTypes`; no `baseUrl` | [`quality/tsconfig/base.json`](../quality/tsconfig/base.json), `check_quality.py` | `baseUrl` stops working in TypeScript 7 (TS5101). |
| clang-tidy base with `clang-analyzer-*`, `concurrency-mt-unsafe`, `misc-no-recursion`, `WarningsAsErrors: '*'` | [`quality/clang-tidy/base.yaml`](../quality/clang-tidy/base.yaml), `check_quality.py` (a local `-<check>` is a weakening) | The path-sensitive analyzer never ran in either C++ repository. Naming prefixes and header filters stay local. |
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

- `<year>` is the year of the file's first commit, as `git log --diff-filter=A --format=%ad --date=format:%Y -- <file>` gives it, and the current year for a file not committed yet.
- No e-mail address, in a file or in `REUSE.toml`.
- The license stays the one each repository already declares (MIT, GPL-3.0-or-later, ...).
- A file that cannot carry a comment (images, JSON, binaries, lockfiles, generated data) gets both lines through a `REUSE.toml` annotation (`SPDX-FileCopyrightText` and `SPDX-License-Identifier`), never a `.license` sidecar unless `REUSE.toml` cannot express it. So does a file `REUSE.toml` covers with `precedence = "override"`: third-party text, the kit's managed-block sources, and the pull request template, whose text GitHub copies into every pull request.
- In Markdown the lines sit in an HTML comment at the top (after any front matter); in CSS in a block comment; elsewhere in line comments, after a shebang or an encoding line.

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
| [`reusable-lint.yml`](../.github/workflows/reusable-lint.yml) | The kit check (from the kit at the recorded commit), every pre-commit hook on every file (mypy, reuse and the header lines excepted: they have their own workflows), zizmor's online audits | `skip` (hook ids that need a secret), `python-version` | `contents: read` |
| [`reusable-reuse.yml`](../.github/workflows/reusable-reuse.yml) | `reuse lint`, then the header lines, on the whole history | | `contents: read` |
| [`reusable-mypy.yml`](../.github/workflows/reusable-mypy.yml) | A bare `mypy` with the repository's dependencies installed | `install`, `python-version-file`, `python-version` | `contents: read` |
| [`reusable-python-tests.yml`](../.github/workflows/reusable-python-tests.yml) | The repository's tests, and `coverage.xml` as the `coverage` artifact for SonarCloud | `run` (required), `install`, `python-version-file`, `coverage-report`, `coverage-artifact`, `timeout-minutes` | `contents: read` |
| [`reusable-osv.yml`](../.github/workflows/reusable-osv.yml) | OSV-Scanner, failing on any known vulnerability | | `contents: read` |
| [`reusable-secrets.yml`](../.github/workflows/reusable-secrets.yml) | gitleaks over the history and the tree with both configs, and the MAC plant test | | `contents: read` |
| [`reusable-sonarcloud.yml`](../.github/workflows/reusable-sonarcloud.yml) | The secretless SonarCloud analysis, moved unchanged from the public repositories: OIDC token exchange (`SonarSource/sonarqube-auth-action`), scan (`SonarSource/sonarqube-scan-action`), and a wait until SonarCloud accepted the analysis; a pull request with no OIDC token (a fork, Dependabot) ends green with a notice | `coverage-artifact` (`coverage`; empty for none) | `contents: read`, `id-token: write` |
| [`reusable-commit-check.yml`](../.github/workflows/reusable-commit-check.yml) | The commit-message gate, with the checker the base branch names | | `contents: read` |
| [`reusable-commit-check-comment.yml`](../.github/workflows/reusable-commit-check-comment.yml) | The one commit-check comment, from a `workflow_run` caller | | `actions: read`, `contents: read`, `pull-requests: write` |
| [`reusable-quality-drift.yml`](../.github/workflows/reusable-quality-drift.yml) | Weekly: is the recorded kit behind `main`? A dry run of the new kit, written to the job summary, and a red run as the notice | | `contents: read` |

The commit-check callers keep the workflow name `Commit check` (the comment workflow follows it by name) and the drift caller is `.github/workflows/quality-drift.yml`; the sync seeds all three. The org's Actions policy allows only GitHub-owned and verified actions, so the kit uses no third-party action: tools come from PyPI with hashes ([`quality/requirements-tools.txt`](../quality/requirements-tools.txt)), from pre-commit hook repositories, or as release binaries pinned by SHA-256 in [`quality/tools.lock`](../quality/tools.lock) and installed by [`quality/fetch_tool.py`](../quality/fetch_tool.py). Each called job's name shows on GitHub as `<caller job> / <called job>`.

A notice is a red scheduled run, not an issue: issues are off in most kleidos-dev repositories, and no workflow here may open a pull request (`GITHUB_TOKEN` pull requests run no CI, and a PAT or App token is not used).

## Overrides

1. **Adding is free.** A repository may add rules, checks, hooks, stricter flags and wider scopes without asking: `extend-select`, more clang-tidy checks, a mypy flag the block does not set, an ESLint plugin, a CI job.
2. **Weakening needs a recorded reason.** Anything that makes a tool report less than the kit on the same code is a weakening: a rule off or down to a warning, an ignore or per-file ignore, an excluded path, a `-check`, a relaxed tsconfig or ESLint setting, a markdownlint rule turned off, a manifest directory Dependabot does not cover, a job with `continue-on-error`. Each is an entry in the repository's `.github/quality/waivers.toml`:

   ```toml
   [[waiver]]
   tool = "ruff"                # ruff, eslint, tsconfig, clang-tidy, markdownlint, ci, dependabot
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
6. **Facts are not weakenings**: `python_version`, `target-version`, `files` and `mypy_path` (while coverage holds), `HeaderFilterRegex`, naming conventions, `known-first-party`, tsconfig `types` and `include`, typos exceptions for words that are right.

## Versions

- [`quality/VERSION`](../quality/VERSION) is the kit's semver, with an entry per release in [`quality/CHANGELOG.md`](../quality/CHANGELOG.md). MAJOR: anything that can turn a green repository red (a rule on, a stricter setting, a tool bump with new findings, a new conformance rule some repository fails). MINOR: a new opt-in profile or tool, or a rule every repository already passes. PATCH: docs, or a checker fix that cannot add findings.
- Tool versions are set here only: [`quality/requirements-tools.in`](../quality/requirements-tools.in) compiled with hashes into `requirements-tools.txt` (the command is in its header), the hook revisions in this repository's [`.pre-commit-config.yaml`](../.pre-commit-config.yaml) (each a commit SHA with its tag), the actions the reusable workflows pin, and `tools.lock`. Dependabot bumps the first three here (pip, pre-commit and github-actions ecosystems); the weekly `📦 Pinned release binaries current` job turns red when a `tools.lock` binary has a newer release. A bump reaches the other repositories through the sync, never through their own Dependabot.

## Taking a new kit release

When a repository's weekly `Quality kit drift` run turns red, its summary says which release is out, how many problems a dry run found, and which files a sync would change. The sync is one pull request: check out kleidos-dev/.github `main` beside the repository, run `python3 ../.github/quality/sync.py --write .`, fix every new finding in the same pull request (a waiver only where [Overrides](#overrides) allows it), and merge once CI is green (squash on the public repositories; a signed push to `main` on the private ones, which cannot have rulesets on the Free plan). The drift test (`test_quality_kit.py`, copied by `--test-dir`) makes the repository's own test suite fail on drift too.

## Changing the kit

1. One pull request here: the change, `quality/VERSION`, `quality/CHANGELOG.md`, and `sync.py --write .` so this repository, the kit's first consumer, records it (its `SOURCE.json` records commit `self` and is compared with the working tree).
2. CI runs the kit's tests ([`quality/tests/`](../quality/tests/), also the `kleidos-quality-kit-tests` hook), this repository against itself, and an impact preview: `sync.py --preview --tools @public` applies the changed kit to throwaway clones of the public repositories and writes their finding counts to the job summary. Private repositories are previewed locally with `sync.py --preview <path>`.
3. Merge, tag `quality-vX.Y.Z`, and sync each repository.

[`quality/kit.toml`](../quality/kit.toml) lists every copy, block and seed by profile, and the repositories that consume the kit.

## Outside the kit: Socket, CodeQL, SonarCloud

- **Socket** (owner: public repositories only) is a GitHub App, so installing it is the owner's click: <https://github.com/apps/socket-security/installations/new>, account `kleidos-dev`, "Only select repositories": `.github`, `boards`, `brand`, `social`, `cla`. Free plan; it reads the pip and npm manifests and comments on pull requests that change them. Check the permissions page before accepting (contents and metadata read, checks and pull-request write expected). No `socket.yml` is needed for its defaults.
- **CodeQL** runs as GitHub's default setup on every public repository (a repository setting, no workflow): `actions` and `python` on `.github`, boards and brand; `actions` only on social (add `python` with `gh api -X PATCH repos/kleidos-dev/social/code-scanning/default-setup -f state=configured -F 'languages[]=actions' -F 'languages[]=python'`); `actions`, JavaScript/TypeScript and `python` on cla. No repository runs a CodeQL workflow, so the kit has none: default setup and an advanced-setup workflow are exclusive. Its license forbids it on private code.
- **SonarCloud** settings live in each `sonar-project.properties` and in [`sonarcloud.md`](sonarcloud.md); the kit only runs the analysis job. Reading the mypy and ruff reports into SonarCloud (`sonar.python.mypy.reportPaths`, `sonar.python.ruff.reportPaths`) is a later minor release.

## Where each repository stands

| Repository | Visibility | Profiles | State |
| --- | --- | --- | --- |
| kleidos-dev/.github | public | base, python, actions | The kit's home and first consumer (commit `self`) |
| kleidos-dev/boards, brand, social | public | base, python, actions | Wave 1: one sync pull request each |
| kleidos-dev/cla | public | base, python, actions, ts | Wave 2, coordinated with its own build |
| kleidos-dev/qa, meter, videos, agents, posts | private | by tree (meter: cpp, shell; videos: shell) | Wave 3: a signed push to `main` each |
| jmrplens/kleidos (the firmware) | private | all | Not yet: [`quality-firmware-adoption.md`](quality-firmware-adoption.md) |
