<!--
SPDX-FileCopyrightText: 2026 José M. Requena Plens
SPDX-License-Identifier: MIT
-->

# Quality kit changelog

One entry per release; each says what can turn a green repository red. The rules, and how a repository takes a release, are in [`docs/quality.md`](../docs/quality.md).

## 1.0.0 (2026-11-22)

The first release. A repository that adopts it gets:

- ruff with the kit's bug-finding rule set and `ruff format`; mypy strict (phonometry's floor) over every Python file, with every error fixed and no baseline.
- actionlint, zizmor (every `uses:` pinned by SHA, the `self-repository` audit off while actionlint rejects `$/`), shellcheck at warning severity, and the CI conventions checked.
- typos (US English), gitleaks over the tree and the history with the default rules and the MAC rules, OSV-Scanner as a gate, Dependabot coverage.
- `reuse lint` and the licensing header rule: both REUSE lines, copyright first, with the year of the file's first commit and no e-mail, in every file that can carry a comment.
- The Markdown no-wrap rule and markdownlint's broken-table rules.
- ESLint and tsconfig bases for TypeScript, a clang-tidy base for C++.
- Reusable workflows for lint, licensing, types, Python tests, OSV, secrets, SonarCloud, the commit-message gate and its comment, and the weekly drift notice.
- `check_quality.py`, which checks the copies, the blocks, the kit workflow references and the conformance of the repository's own configs, with waivers for the weakenings it allows.
