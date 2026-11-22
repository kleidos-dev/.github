<!--
SPDX-FileCopyrightText: 2026 José M. Requena Plens
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Bringing the firmware onto the quality kit

The plan for jmrplens/kleidos, the firmware repository, which the 2026-11-22 rollout of the kit ([`quality.md`](quality.md)) leaves out while a long workflow runs on it. Nothing here has been done; it starts when the owner starts it. Figures were read at firmware commit `9b31ef0b3` and the analyzer proposal of 2026-11-22. Each step is one pull request (or one signed push) in which every finding the step brings is fixed; mypy is large enough to be its own workflow, split by package.

## 1. Sync the kit

- From a checkout of kleidos-dev/.github beside it: `python3 ../.github/quality/sync.py --write . --test-dir qa/tests/ci` (profiles base, python, actions, shell, ts, cpp are all detected).
- The personal account's Actions policy allows every action, so the public reusable workflows can be called; no SARIF upload is possible while the repository is private.
- Replace the CI's own lint, REUSE, gitleaks, OSV, commit-check and SonarCloud steps with the kit's callers (the model is [`quality/templates/workflows/check.yml`](../quality/templates/workflows/check.yml)); the firmware jobs (builds per env, native tests, `pio check`, clang-tidy legs, the site build, the HIL-free QA suite, the layout and variant guards) stay local jobs, with their emoji names, timeouts and staged `needs:`.
- The firmware's `.gitleaks-mac.toml` is replaced by the kit's copy (same rules, generic title); its `.gitleaks.toml` and `.gitleaksignore` stay local under the conformance rules; `.typos.toml` gets the kit block above its own exceptions.

## 2. Licensing headers (owner, 2026-11-22)

Today 1,976 tracked files carry the license line and only 2 carry a copyright line; `AGENTS.md` section 9 states the one-line rule (a new source file starts with the license line alone).

1. The sweep: `python3 .github/quality/spdx_headers.py --write` inserts the copyright line above each existing license line, with the year of the file's first commit (`git log --diff-filter=A`), and writes both lines into every file that can carry a comment and has none, taking the license from `REUSE.toml`. Run it on a full clone (it refuses a shallow one), review the diff by directory, and commit it alone so `.git-blame-ignore-revs` can list it.
2. `REUSE.toml`: every annotation carries `SPDX-FileCopyrightText = "<year> José M. Requena Plens"` (no e-mail) beside its license, for the files that cannot carry a comment (images, JSON, fonts' data, generated files, lockfiles, binaries); third-party files keep their own holders, with `precedence = "override"` where their in-file text is not ours to edit.
3. Rules and templates: `AGENTS.md` section 9, `src/AGENTS.md` and `site/AGENTS.md` where they state the header, `CONTRIBUTING.md`, the `code-quality` skill (and any other skill with a file template), the scripts that generate files (`scripts/site/`, the SPA and font generators, `check_layout.py` and `refactor/move_units.py` where they write new files), and `qa/CONTRIBUTING-docstrings.md`: each states or emits both lines, copyright first.
4. Gate: `reusable-reuse.yml` in CI and the `kleidos-spdx-headers` and `reuse` hooks locally; `reuse lint` passes with no file missing either line.

## 3. Python

- ruff from 0.8.4 to the kit's version, its scope from `qa/` to `qa/` and `scripts/`, with the kit's rule set; fix the two Python 3.12 f-strings in a package that declares 3.10 (`qa/tests/firmware/test_battery_gauge_source.py:515`, `qa/tests/portal/test_route_timeout_bounds.py:741`).
- `ruff format` of the whole tree as its own commit, listed in `.git-blame-ignore-revs`.
- mypy strict over all 542 Python files with every error fixed and no baseline (ty reported 1,150 diagnostics in `qa/` alone, so this is its own workflow, split by package: `qa/qa_lib`, `qa/tests/*`, `qa/tools`, `scripts/`). `[tool.mypy]` moves into the root `pyproject.toml` with `files` naming every root; the imports that ship no types and have no stub (to be measured) get the one `ignore_missing_imports` override, each with its reason.

## 4. C++

- The kit's `.clang-tidy` at the root; the firmware's specifics (`HeaderFilterRegex`, `ExcludeHeaderFilterRegex`, the `s_` prefix for statics) in `src/.clang-tidy` with `InheritParentConfig: true`.
- `WarningsAsErrors: '*'` replaces the three-check list, so the four clang-tidy legs (`check_tidy`, `check_tidy_wide` and their debug-console twins) are cleaned first; `clang-analyzer-*` and `concurrency-mt-unsafe` are the new finding sources.
- Firmware-local additions, not kit configs: ASan and UBSan on the native tests (a `native_sanitize` env and a Linux leg), libFuzzer in CI on the record codec, the index segments, the sealed backup and CSV import, `kleidos::json` and the portal parsers, and a stack-usage ratchet from `-fstack-usage` against the bytes each `rtos::createPinnedTask` gives.
- clang-format stays the firmware's (v22) until it and meter's (v23) are reconciled into a kit base.

## 5. Web

- ESLint with `eslint-plugin-no-unsanitized` (`escape.methods: ["esc"]`) on the portal SPA (`web_src/index.html`, 99 HTML sinks to triage) as a local addition.
- `site/tsconfig.json` extends the kit's tsconfig base: about 14 fixes (`noImplicitReturns`, `exactOptionalPropertyTypes`, `noFallthroughCasesInSwitch`, `noImplicitOverride`), `noUncheckedIndexedAccess` (566 sites) staged by folder under a dated waiver, and `baseUrl` removed (TS5101, gone in TypeScript 7).

## 6. Actions

- zizmor's 154 findings: 76 actions pinned by tag (every action pinned by SHA with its version comment), 27 checkouts that keep credentials (`persist-credentials: false`), 18 cache-poisoning risks, 1 excessive permission; then the kit's CI conventions.
- actionlint's one finding (SC2086 at `.github/workflows/ci.yml:1537`).
- Trivy's `upload-sarif` step fails on every run ("Resource not accessible by integration") behind `continue-on-error`: it becomes an artifact and a red job on new findings.

## 7. Supply chain

- OSV from advisory to gate: first the three `cryptography` advisories in `qa/requirements.txt` (fixed in 49.0.0 and 50.0.0).
- Dependabot: the `npm` ecosystem for `site/`, `scripts/spa` and `scripts/fonts`; security updates on.
- `reuse lint` as a hook and a CI job (step 2).

## 8. Once the repository is public

CodeQL C/C++ (manual build with `pio run`) and JavaScript/TypeScript, Socket, and SonarCloud on the whole tree without the private-lines-of-code batches (`scripts/check_sonar_batches.py` then retires).
