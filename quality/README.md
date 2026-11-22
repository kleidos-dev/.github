<!--
SPDX-FileCopyrightText: 2026 José M. Requena Plens
SPDX-License-Identifier: MIT
-->

# The Kleidos quality kit

The shared rules and analysis-tool configuration of every Kleidos repository. Read [`docs/quality.md`](../docs/quality.md): every rule and why, how a repository adopts the kit, overrides a rule and takes a new release, and how the kit itself changes.

| Path | What it is |
| --- | --- |
| [`kit.toml`](kit.toml) | The manifest: what each profile copies, which managed blocks it writes, what it seeds once, and the consuming repositories. |
| [`sync.py`](sync.py) | `--write REPO` brings a repository to this checkout of the kit; `--check REPO` compares it; `--preview` measures a change on throwaway clones. |
| [`check_quality.py`](check_quality.py) | The checker every repository copies: copies, blocks, kit workflow references, conformance, waivers; `--plant-mac` proves the MAC rules. |
| [`spdx_headers.py`](spdx_headers.py) | The licensing header rule: check, and `--write` to add or repair the lines. |
| [`md_nowrap.py`](md_nowrap.py) | Markdown prose is never hard-wrapped. |
| [`fetch_tool.py`](fetch_tool.py), [`tools.lock`](tools.lock) | The release binaries (OSV-Scanner, gitleaks) pinned by SHA-256. |
| [`requirements-tools.in`](requirements-tools.in), [`requirements-tools.txt`](requirements-tools.txt) | The PyPI tools, compiled with hashes. |
| `ruff/`, `mypy/`, `typos/`, `gitleaks/`, `markdownlint/`, `shellcheck/`, `zizmor/`, `eslint/`, `tsconfig/`, `clang-tidy/` | The tool configs and managed-block sources. |
| [`templates/`](templates/) | Files seeded once into a repository, the drift test, and the model CI callers. |
| [`tests/`](tests/) | The kit's tests (`python3 -m unittest discover -s quality/tests`). |
| [`VERSION`](VERSION), [`CHANGELOG.md`](CHANGELOG.md) | The kit's version and what each release changes. |
