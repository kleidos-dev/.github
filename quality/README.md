<!--
SPDX-FileCopyrightText: 2026 José M. Requena Plens
SPDX-License-Identifier: MIT
-->

# The Kleidos quality kit

The shared rules and analysis-tool configuration of every Kleidos repository. Read [`docs/quality.md`](../docs/quality.md): every rule and why, how a repository adopts the kit, overrides a rule and takes a new release, and how the kit itself changes.

| Path | What it is |
| --- | --- |
| [`kit.toml`](kit.toml) | The manifest: what each profile copies, which managed blocks it writes, what it seeds once, and the consuming repositories. |
| [`sync.py`](sync.py) | `--write REPO` brings a repository to this checkout of the kit (a release tag on `main`); `--check REPO` compares it; `--preview` measures a change on throwaway clones; `--release-check` and `--drift` keep releases and the drift notice honest. |
| [`check_quality.py`](check_quality.py) | The checker every repository copies: copies, blocks, kit workflow references, conformance, waivers; `--plant-mac` proves the MAC rules. |
| [`spdx_headers.py`](spdx_headers.py) | The licensing header rule: check, and `--write` to add or repair the lines. |
| [`md_nowrap.py`](md_nowrap.py) | Markdown prose is never hard-wrapped. |
| [`agent_docs.py`](agent_docs.py) | The agent-docs guard: `AGENTS.md` and `CLAUDE.md` keep [`docs/agent-docs.md`](../docs/agent-docs.md) (the import, sizes, paths, links, the organization-rules block). |
| [`mypy_groups.py`](mypy_groups.py) | The mypy runner the python profile copies: one run per group of folders a repository declares, or one bare `mypy`; the mypy hook and `reusable-mypy.yml` run it. |
| [`fetch_tool.py`](fetch_tool.py), [`tools.lock`](tools.lock) | The release binaries (OSV-Scanner, gitleaks) pinned by SHA-256. |
| [`latest_releases.py`](latest_releases.py) | The weekly report: every kit pin (Python, actions, hook revs, PyPI tools, binaries) against its newest upstream stable release. |
| [`requirements-tools.in`](requirements-tools.in), [`requirements-tools.txt`](requirements-tools.txt) | The PyPI tools, compiled with hashes; the workflows install them from the kit, and no repository copies them. |
| `ruff/`, `mypy/`, `typos/`, `gitleaks/`, `markdownlint/`, `shellcheck/`, `zizmor/`, `eslint/`, `tsconfig/`, `clang-tidy/` | The tool configs and managed-block sources. |
| [`agents/block.md`](agents/block.md) | The organization rules: the Markdown block every repository's `AGENTS.md` carries. |
| [`templates/`](templates/) | Files seeded once into a repository, the drift test, and the model CI callers. |
| [`tests/`](tests/) | The kit's tests (`python3 -m unittest discover -s quality/tests`). |
| [`VERSION`](VERSION), [`CHANGELOG.md`](CHANGELOG.md) | The kit's version and what each release changes. |
