<!--
SPDX-FileCopyrightText: 2026 José M. Requena Plens
SPDX-License-Identifier: MIT
-->

# Quality kit changelog

One entry per release; each says what can turn a green repository red. The rules, and how a repository takes a release, are in [`docs/quality.md`](../docs/quality.md).

## 1.1.0 (2026-11-23)

mypy groups, for a repository whose scripts sit in plain folders that repeat file names (a `score.py` in each video's folder), where one mypy run stops at "Duplicate module named". Nothing turns a green repository red: without groups every repository runs the same bare `mypy` as before, and the new duplicate-module check reports only what that run already fails on (the impact preview found nothing in boards, brand, social, cla, qa, agents and posts).

- A repository may declare `[[tool.kleidos-quality.mypy-groups]]` in its `pyproject.toml`: each group a `name` and the `files` (folders, files, or globs such as `music/*.py`) of one mypy run. A group sets nothing else, so every run reads the same `[tool.mypy]` and the kit's strict block; with groups, `[tool.mypy]` sets no `files`.
- `quality/mypy_groups.py`, copied by the python profile to `.github/quality/mypy_groups.py`, runs mypy once per group, each with a cache of its own, and every group even after one fails; without groups it runs a bare `mypy`. The mypy hook of the `pre-commit-python` block now runs it (`python3 .github/quality/mypy_groups.py`).
- `reusable-mypy.yml` runs it with `--github`: a fold per group in the log, an error annotation per failing group, and a table of every group in the job summary.
- `check_quality.py` holds every tracked Python file to exactly one group (or, without groups, to `files` as before), refuses a group key other than `name` and `files`, a bad name or path, `files` beside groups and any other `[tool.kleidos-quality]` key (no waiver), reports a group folder that holds no Python file, and reports two files of one mypy run that mypy would name the same module.

## 1.0.0 (2026-11-23)

The first release, tagged `quality-v1.0.0` at its merge commit on `main`: `sync.py --write` records only a release tag on `main`. A repository that adopts it gets:

- ruff with the kit's bug-finding rule set and `ruff format`; mypy strict (phonometry's floor) over every Python file, with every error fixed and no baseline.
- actionlint, zizmor (every `uses:` pinned by SHA, the `self-repository` audit off while actionlint rejects `$/`), shellcheck at warning severity, and the CI conventions checked.
- typos (US English), gitleaks over the tree and the history with the default rules and the MAC rules, OSV-Scanner as a gate, Dependabot coverage.
- `reuse lint` and the licensing header rule: both REUSE lines, copyright first, with the year of the file's first commit and no e-mail, in every file that can carry a comment.
- The Markdown no-wrap rule and markdownlint's broken-table rules.
- ESLint and tsconfig bases for TypeScript, a clang-tidy base for C++.
- Reusable workflows for lint, licensing, types, Python tests, OSV, secrets, SonarCloud, the commit-message gate and its comment, and the weekly drift notice.
- `check_quality.py`, which checks the copies, the blocks, the kit workflow references and the conformance of the repository's own configs, with waivers for the weakenings it allows. A kit workflow counts as called only from a job that runs on every pull request and push to `main`; the lint caller's `skip` may not name a kit hook; `.github/quality/` holds only the kit's copies; `[tool.mypy]` takes an allowlist; a `.python-version` (python), a Dependabot `cooldown`, the ESLint workflow (ts) and a local clang-tidy job (cpp) are required.
- The header rule held at the top of each file, with an owner line, the first-commit year in UTC or the year before (squash merges across the new year), Astro headers in the front matter, and every text file of an unknown format named in `REUSE.toml`.
- The commit-message checker the CI runs recorded against kleidos-dev/agents (`.github/commit-check/SOURCE.json` and its digest test); the tool pins are not copied into repositories.
