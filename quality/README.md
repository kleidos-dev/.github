<!--
SPDX-FileCopyrightText: 2026 José M. Requena Plens
SPDX-License-Identifier: MIT
-->

# The Kleidos quality kit

The shared rules and analysis-tool configuration of every Kleidos repository. Read [`docs/quality.md`](../docs/quality.md): every rule and why, how a repository runs the kit and overrides a rule, and how the kit itself changes.

| Path | What it is |
| --- | --- |
| [`policy.py`](policy.py) | Every policy check on one repository: what the `kleidos-kit` hook and the lint and licensing jobs run. |
| [`check_quality.py`](check_quality.py) | The kit check: conformance of a repository's own configurations, pins, waivers; `--plant-mac` proves the MAC rules. |
| [`run_form.py`](run_form.py) | The kit check of a repository that calls the kit by name: the record, the workflows, the gate, the hooks. |
| [`spdx_headers.py`](spdx_headers.py) | The licensing header rule and the owner's statement: check, and `--write` to add or repair the lines. |
| [`md_nowrap.py`](md_nowrap.py) | Markdown prose is never hard-wrapped. |
| [`agent_docs.py`](agent_docs.py) | The agent-docs guard: `AGENTS.md` and `CLAUDE.md` keep [`docs/agent-docs.md`](../docs/agent-docs.md). |
| [`suite_rules.py`](suite_rules.py), with [`js_text.py`](js_text.py), what is code in a JavaScript or TypeScript file | The tests check: no test runs alone, a skip says why, no coverage threshold falls unsaid ([`docs/testing.md`](../docs/testing.md)). |
| [`mypy_groups.py`](mypy_groups.py) | The mypy runner: one run per group of folders a repository declares, or one bare `mypy`. |
| [`templates/run/`](templates/run/) | The model CI of a repository, its gate job included, and the comment caller. |
| [`config-digests.json`](config-digests.json) | The released bytes of each base configuration. |
| [`coverage_floor.py`](coverage_floor.py) | Every file of the kit keeps the share of coverage it has reached. |
| [`fetch_tool.py`](fetch_tool.py), [`tools.lock`](tools.lock) | The release binaries (OSV-Scanner, gitleaks) pinned by SHA-256. |
| [`latest_releases.py`](latest_releases.py) | Every kit pin (Python, actions, hook revs, PyPI tools, binaries) against its newest upstream stable release, for the ecosystem report. |
| [`requirements-tools.in`](requirements-tools.in), [`requirements-tools.txt`](requirements-tools.txt) | The PyPI tools, compiled with hashes; the workflows install them from the kit. |
| `ruff/`, `mypy/`, `typos/`, `gitleaks/`, `markdownlint/`, `shellcheck/`, `zizmor/`, `eslint/`, `tsconfig/`, `clang-tidy/` | The base configurations, and the block sources of the held form. |
| [`agents/block.md`](agents/block.md) | The organization rules, which every repository's `AGENTS.md` links. |
| [`sync.py`](sync.py), [`kit.toml`](kit.toml), the rest of [`templates/`](templates/) | The held form (kit 2.x): copies, blocks and seeded files, and the release check. |
| [`tests/`](tests/) | The kit's tests (`python3 -m unittest discover -s quality/tests`). |
| [`VERSION`](VERSION), [`CHANGELOG.md`](CHANGELOG.md) | The kit's version and what each release changes. |
