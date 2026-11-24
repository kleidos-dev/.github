<!--
SPDX-FileCopyrightText: 2026 José M. Requena Plens
SPDX-License-Identifier: GPL-3.0-or-later
-->

<!-- BEGIN GENERATED: banner (kleidos-dev/brand, social/tools/sync_readme_banners.py); do not edit by hand -->

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/kleidos-dev/brand/main/social/svg/readme/dot-github/banner-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/kleidos-dev/brand/main/social/svg/readme/dot-github/banner-light.svg">
  <img src="https://raw.githubusercontent.com/kleidos-dev/brand/main/social/svg/readme/dot-github/banner-light.svg" width="100%" alt="Kleidos Community: The organization's profile, contributing guide, security policy and templates.">
</picture>

<!-- END GENERATED: banner -->

# kleidos-dev/.github

This repository holds the kleidos-dev organization's profile, its community defaults, and its Discussions. It contains no firmware; its only code is the commit-message gate and the tools that write and check the metadata of the profile's images.

| Path | What it is |
| --- | --- |
| [`profile/README.md`](profile/README.md) | The organization's public landing page on GitHub. |
| [`profile/assets/`](profile/assets/) | The profile banners (dark and light) and `assets.json`, the record of what each banner says about itself and its SHA-256. |
| [`.github/FUNDING.yml`](.github/FUNDING.yml) | The two donation routes, used by every repository that has no funding file of its own and has Sponsorships turned on. |
| [`SECURITY.md`](SECURITY.md) | How to report a vulnerability privately; the default for every repository without its own policy. |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Where to ask, how a new board gets added, and the license of contributions; the default for every repository without its own guide. |
| [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) | The Contributor Covenant 2.1, for every repository and for Discussions. |
| [`SUPPORT.md`](SUPPORT.md) | Where questions, board requests, and vulnerabilities go. |
| [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/) | The default issue form, with questions sent to Discussions and vulnerabilities to the security policy. |
| [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) | The default pull request description. |
| [`.github/VULNERABILITY_REPORT.yml`](.github/VULNERABILITY_REPORT.yml) | The default form for a private vulnerability report. |
| [`.github/DISCUSSION_TEMPLATE/new-board-requests.yml`](.github/DISCUSSION_TEMPLATE/new-board-requests.yml) | The form behind the New board requests category. |
| [`docs/discussion-categories.md`](docs/discussion-categories.md) | The Discussions categories and the pinned welcome post. |
| [`docs/sonarcloud.md`](docs/sonarcloud.md) | What is set by hand in the SonarQube Cloud organization and its projects, and how to add a project. |
| [`docs/quality.md`](docs/quality.md) | The quality kit: the rules every kleidos-dev repository meets, why, how a repository runs the kit and overrides a rule, and how the kit is released. |
| [`docs/ecosystem.md`](docs/ecosystem.md) | The report of what is behind or broken across the repositories, the preview of a kit change, and the tools beside it. |
| [`docs/agent-docs.md`](docs/agent-docs.md) | The standard for every repository's `AGENTS.md` and `CLAUDE.md`, the organization rules they share and the guard that checks them. |
| [`docs/quality-firmware-adoption.md`](docs/quality-firmware-adoption.md) | The plan for bringing the firmware repository onto the kit. |
| [`quality/`](quality/) | The kit itself: the checkers every repository runs, the shared tool configs, the model CI, their tests, and the tool versions. |
| [`hooks/`](hooks/), [`.pre-commit-hooks.yaml`](.pre-commit-hooks.yaml) | The kit's pre-commit hooks, which other repositories name at a release tag, the commit-message checker among them. |
| [`tools/`](tools/) | The tools that look across the repositories: the ecosystem report and its declared list (`ecosystem.toml`), the switch to the run form, and the weekly timers. |
| [`scripts/`](scripts/), [`tests/`](tests/) | The media metadata tools (`media_meta.py`, `stamp_media_meta.py`, `check_metadata.py`) and their tests. |
| [`.github/workflows/`](.github/workflows/) | The kit's entry workflows (`quick.yml`, `check.yml`, `sonar.yml`), which every repository's CI calls, the `reusable-*.yml` jobs they call, this repository's own CI (`ci.yml`) and the weekly ecosystem report (`ecosystem.yml`). |
| [`.github/quality/`](.github/quality/) | This repository's own held copies of the kit's checkers, `SOURCE.json` and its waivers. |
| [`.github/dependabot.yml`](.github/dependabot.yml) | Weekly updates of the pinned GitHub Actions, of the CI's Python tools (`requirements.txt`) and of the kit's tool versions (`quality/requirements-tools.txt`, the pre-commit hooks). |
| [`.coderabbit.yaml`](.coderabbit.yaml), [`.greptile/`](.greptile/) | The review bots' configuration: inline reviews and suggestions only. |
| [`sonar-project.properties`](sonar-project.properties), [`.coveragerc`](.coveragerc) | The SonarCloud project and the coverage report its analysis reads. |
| [`AGENTS.md`](AGENTS.md), [`CLAUDE.md`](CLAUDE.md) | The rules for coding agents working here (`CLAUDE.md` imports `AGENTS.md` for Claude Code). Each kleidos-dev repository keeps its own. |
| [`REUSE.toml`](REUSE.toml), [`LICENSES/`](LICENSES/) | The license and copyright of every file, in the [REUSE](https://reuse.software/) format, and the license texts. |

Kleidos itself is described at <https://kleidos.dev>.

## Media metadata

Every image this repository publishes carries metadata that says what it is, who made it and under which license, for readers and for search engines: a descriptive `<title>` and `<desc>`, and a Dublin Core and ccREL `<metadata>` block with the creator, the rights line, the license URL, the file's URL, keywords and the IPTC digital source type. The block sits between `REUSE-IgnoreStart` and `REUSE-IgnoreEnd` comments, so the REUSE tool takes the license and holders from `REUSE.toml` alone. This is the profile `kleidos-media-meta/1` that every kleidos-dev repository follows.

Nobody writes that metadata by hand. Each file's record in [`profile/assets/assets.json`](profile/assets/assets.json) holds its title, description, keywords and source type; the license and holders come from `REUSE.toml`. After changing a banner or its record:

```sh
python3 scripts/stamp_media_meta.py --write   # writes the metadata and records the SHA-256
python3 scripts/check_metadata.py             # checks the profile, REUSE and the privacy deny-list
python3 -m unittest discover -s tests         # the tools' own tests
```

The stamp rewrites only the root `<svg>`'s `role`, `aria-labelledby` and `lang` and the title, description and metadata that follow it; the drawing is never touched. The checker refuses any e-mail address, local path, host name, machine time or tool name in the metadata, and identity patterns kept out of the repository (the `KLEIDOS_DENY_EXTRA` secret in CI, or an untracked `scripts/deny-local.txt`). The pre-commit hooks run the same commands, in the `CI` workflow too (`ci.yml`, the lint job).

## Review bots and analysis

Pull requests are reviewed by [CodeRabbit](https://coderabbit.ai) (`.coderabbit.yaml`) and [Greptile](https://www.greptile.com) (`.greptile/`), configured to post inline reviews and suggestions only: they never touch a pull request's title or description, post no summary of it, and commit nothing to it. Both review against the rules in this README and in [`CONTRIBUTING.md`](CONTRIBUTING.md). The `CI` workflow runs on every push to `main` and every pull request against `main`: it runs the quality kit's checks (`docs/quality.md`), measures the tools' tests with coverage.py and then runs the SonarCloud job (the kit's `sonar.yml`), which is mandatory: it fails when the analysis cannot run or when SonarCloud does not accept it. The one required check is `✅ Check`, which needs every other job.

SonarCloud analysis is secretless and runs only from CI (Automatic Analysis is off): the job trades its GitHub OIDC token for a short-lived project token through `SonarSource/sonarqube-auth-action`, so the repository holds no `SONAR_TOKEN`. A pull request that GitHub gives no OIDC token (from a fork, or from Dependabot) skips the analysis with a notice, and the change is analyzed once it is on `main`. Every setting a file can carry (sources, tests, coverage, Python version, links) is in `sonar-project.properties`; the new code period (30 days), the quality gate and profiles (the organization's defaults, the gate being `Kleidos (agentic AI level)`) and the rest of what a file cannot hold are set by hand in the SonarQube Cloud organization `kleidos-dev`, as [`docs/sonarcloud.md`](docs/sonarcloud.md) records.

## License

The text and the banners in this repository are licensed under the [GNU General Public License, version 3 or later](https://www.gnu.org/licenses/gpl-3.0.html) (GPL-3.0-or-later), except [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md), which is adapted from the [Contributor Covenant](https://www.contributor-covenant.org/) 2.1 (CC BY 4.0). The tooling (the quality kit with its hooks, the ecosystem tools, the media metadata tools, their tests, the CI configuration and the configuration of the review bots and of SonarCloud) is under the MIT License, so the other kleidos-dev repositories can share it. Every file that can carry a comment states its copyright and license in its first lines, [`REUSE.toml`](REUSE.toml) states them for the rest, and the texts are in [`LICENSES/`](LICENSES/); the full text of the GPL is also in [`LICENSE`](LICENSE). Every other Kleidos repository states its own license in its `LICENSE` file.
