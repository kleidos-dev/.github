<!--
SPDX-FileCopyrightText: 2026 José M. Requena Plens
SPDX-License-Identifier: GPL-3.0-or-later
-->

# SonarQube Cloud settings

What is set in the SonarQube Cloud web UI for the organization `kleidos-dev` (<https://sonarcloud.io/organizations/kleidos-dev>) and its projects, as audited and configured on 2026-11-22, so it can be redone by hand. Only what a `sonar-project.properties` file cannot carry lives here; everything else belongs in each repository's file (listed at the end), so a project can be rebuilt from its repository alone.

The projects are `kleidos-dev_boards`, `kleidos-dev_brand`, `kleidos-dev_social` and `kleidos-dev_.github`, all public, each bound to its repository `kleidos-dev/<repo>` and analyzed only from that repository's CI (GitHub Actions, secretless), on every push to `main` and every pull request against `main`.

The plan is **OSS (SonarQube for OSS)** since 2026-11-22: free, public projects only (no private lines of code), unlimited members, unlimited branch and pull request analysis, custom quality gates and quality profiles per project, webhooks, the Projects Management page and GitHub member synchronization. It does not include AI Code Assurance or AI CodeFix (see "AI Code Assurance").

Until 2026-11-22 the organization was on the **Free** plan, which cannot attach any quality gate other than `Sonar way` to a project and analyses no branch other than `main`. A Free organization cannot be moved to OSS (it is chosen only when an organization is created), so on 2026-11-22, with the owner's approval, the Free organization `kleidos-dev` was deleted and a new one was created on the OSS plan from the GitHub organization (Create organization > the already installed `Kleidos` GitHub organization > "Start SonarQube for OSS" > Create OSS organization, which reused the installed SonarQube Cloud GitHub App and asked for no new permission or terms), with the same key, name and project keys. The analysis history before that day was lost with the old organization; every project's history starts on 2026-11-22.

## Organization

| Setting | Value | Where in the UI | Why |
| --- | --- | --- | --- |
| Name | `Kleidos` | Administration > Organization settings > General | Matches the GitHub organization. |
| Key | `kleidos-dev` | same page, "Edit organization key" | Matches the GitHub login; every `sonar.organization` and project key uses it. Never change it. |
| Avatar | the GitHub organization's avatar | same page | Filled in by the binding. |
| Description | `Open-source hardware password manager for ESP32 boards. Code quality of the public Kleidos repositories, analyzed from CI on every push to main and every pull request.` | same page | The first sentence is the GitHub organization's description; the second says what the Sonar organization is for and how it is fed. |
| URL | `https://kleidos.dev` | same page | The GitHub organization's homepage. |
| Mask detected secret values in source code (`sonar.security.secretSourceRedaction.enabled`) | **on** | Organization settings > Security | Every project is public, so its source views are public: if a secret is ever committed, Sonar does not republish it in its own pages and API while it is being rotated. |
| Organization privacy | public | Organization settings > Privacy | All the projects are public repositories; a private organization would make every project private. |
| Automatic analysis | on for newly imported projects; not settable at organization level | Organization settings > Analysis | Informational: SonarQube Cloud turns Automatic Analysis on for every newly imported project, so it is turned off **per project** (see Projects). |
| Secretless analysis for GitHub Actions | **on** (since 2026-11-22) | Organization settings > Analysis | GitHub Actions authenticate through OIDC (`SonarSource/sonarqube-auth-action`), so no `SONAR_TOKEN` secret exists in any kleidos-dev repository. |
| In-code issue resolution (`sonar.issues.issueResolution.global.enabled`, `sonar.issues.issueResolution.enabled`) | off (default) | Organization settings > Issues | Left off on purpose: it lets a `SONAR-RESOLVE` comment in the code close an issue, and the Kleidos rule is that an issue is fixed with a real change or left open. |
| Plan | SonarQube for OSS | Billing and usage | See above. Billing and usage offers only an upgrade to Team; nothing is paid. |
| Organization binding | bound to the GitHub organization `kleidos-dev` | Organization settings > Organization binding | Done at creation (the organization is imported from GitHub) and not reversible. Gives the project import and the pull request decoration. |
| Automatically import new GitHub repositories | **off** | Organization settings > Organization binding | On, every new repository the Sonar GitHub App can see would be imported with Automatic Analysis on, which conflicts with the CI analysis (a CI scan fails while Automatic Analysis is on) and would also pick up the private repositories, which the OSS plan cannot analyze. Repositories are added one by one, by hand (see "Adding a project"). |
| Security contact | `mail@kleidos.dev` | Organization settings > Security contact | Receives Sonar's platform security advisories and incident notices (not scan results). It is the address in the organization's `SECURITY.md`. |
| Default new code definition | **Number of days: 30** | Administration > New code | Kleidos pushes to `main` with no releases and no `sonar.projectVersion`, so "Previous version" (the default) never moves and every change since a project's first analysis would count as new code forever. 30 days is Sonar's recommendation for continuous delivery: a new issue stays in the new-code gate for a month, then joins the overall code. Pull requests always compare with `main`. Applies only to projects created after the change, so each project is also set (see Projects). |
| Quality gate settings: Ignore duplication and coverage on small changes | on (default) | Administration > Quality gate settings | Coverage and duplication conditions are skipped until a change has 20 new lines, so a one-line fix does not fail on a percentage. |
| Default quality gate | `Kleidos (agentic AI level)` (custom); every project follows the organization default, none has a gate or profile of its own | Policies > Quality gates | The conditions of the built-in `Sonar way for Agentic AI` gate (which the OSS plan does not list) on the current, non-deprecated metrics, plus those of `Sonar way`; see "Quality gate". The built-in `Sonar way` stays available but is no longer the default. |
| Default quality profiles | `Sonar way core` (built-in) for every language (Python 303 rules, GitHub Actions 32, secrets 357) | Policies > Quality profiles | See "Stricter options". |
| Webhooks | none | Webhooks | Available on OSS but not needed: the CI job checks the analysis itself, and the pull request decoration comes from the binding. |
| Members, groups, permissions, permission templates | one member (the owner, Admin); groups `Members` and `Owners`; the default template only | Members, Groups, Permissions, Permission templates | Not changed. |
| AI capabilities | disabled | AI capabilities | A paid feature. |

## Projects

| Setting | Value (every project) | Where in the UI | Why |
| --- | --- | --- | --- |
| Analysis method: Automatic analysis (`sonar.autoscan.enabled`) | **off** | Project > Administration > Analysis method | Analysis runs only from CI. |
| Repository binding | `kleidos-dev/<repo>` | Administration > General settings > Repository binding | Gives the pull request decoration. |
| Main branch | `main` | Project > Branches (from the binding) | The CI analyses `main` and pull requests against it. The OSS plan would also analyze other branches, but no workflow runs the scan on them. |
| Long-lived branch pattern (`sonar.branch.longLivedBranches.regex`) | `(branch\|release)-.*` (inherited default) | General settings | No other branch is analyzed today; left at default. |
| Pull request summary comment (`sonar.pullrequest.github.summary_comment`) | on (inherited default) | General settings > Pull Requests | Sonar posts its summary in the pull request's conversation. |
| Pull request issue annotations (`sonar.enableIssueAnnotation`) | on (inherited default) | General settings > Pull Requests | Issues show as annotations on the GitHub check run. |
| New code | **Number of days: 30** | Administration > New code | Projects imported before 2026-11-22 copied "Previous version" from the organization default; same reasoning as the organization row. |
| Enable automatic configuration (`sonar.scanner.autoconfig.enabled`) | reset (no UI override; the inherited value is false) | Administration > General settings > General > Miscellaneous | The import flow sets it to true. It lets the scanner guess sources, tests and exclusions from the build system; every file names its scope explicitly and also says `sonar.scanner.autoconfig.enabled=false`, so a re-import cannot change the scope silently. |
| Quality gate | `Kleidos (agentic AI level)`, attached explicitly | Project > Policies > Quality gate | See "Quality gate". |
| Quality profiles | organization defaults (`Sonar way core`) | Project > Policies > Quality profiles | See "Stricter options". |
| Sensor cache (`sonar.sensor.cache.project.enable`) | on (default) | General settings > General | Speeds up pull request analyses. |
| Analysis scope, languages, SCM, external analyzers, links | nothing set in the UI | General settings, Administration > Links | Everything lives in the file. |
| Visibility | public | Administration > Permissions | Public repositories. |
| Notifications | the owner's choice | My account > Notifications (per user) | Personal e-mail settings, not the organization's. Worth ticking: "Background tasks fail on my administered projects", and each project under "Project Notifications" with "New quality gate status". |

## Adding a project

1. Keep "Automatically import new GitHub repositories" **off** (the import page ticks it by default; untick it there too). Import the repository from the `+` menu > Analyze new project, in the organization `kleidos-dev`; if the import page does not list it, first grant the Sonar GitHub App access to that repository.
2. Project > Administration > Analysis method: turn **Automatic analysis off** before the first CI run.
3. Project > Administration > New code: confirm **Number of days, 30**.
4. Project > Administration > General settings > General: if "Enable automatic configuration" shows a Reset button, reset it.
5. Project > Policies > Quality gate: leave **Use the organization's default quality gate** selected, and Project > Policies > Quality profiles on the organization defaults. Every project uses the organization's gate and profiles; none sets its own.
6. Add `sonar-project.properties` (below) and the CI job: `permissions: contents: read, id-token: write`; `actions/checkout` with `fetch-depth: 0` and `persist-credentials: false`; `SonarSource/sonarqube-auth-action@b372e2c2930aadfcc4f4399446da1e12772709ad # v1.2` right before `SonarSource/sonarqube-scan-action@59202af334b4ba7b5db01b701b8e79f8b3bef0f4 # v8.5.0`; no `SONAR_TOKEN` secret; run only on a push to `main` or a pull request against `main`; on a pull request from a fork (GitHub gives it no OIDC token) skip every step with a `::notice` so the job ends green. The CI of `boards`, `brand`, `social` and this repository is the model to copy.

## Quality gate

`Kleidos (agentic AI level)` is a custom gate created on 2026-11-22 from the conditions of the built-in `Sonar way for Agentic AI` gate as the owner's personal organization `jmrplens` (Team plan) shows them, since the OSS plan does not list that built-in gate. The same day the three severity conditions that the UI marks "Deprecated" (bugs, vulnerabilities and code smells severity, of the old issue types) were replaced by their Multi-Quality Rule counterparts with the same thresholds, and "Review and update" added the four conditions Sonar recommends on new code. The UI now reads "This quality gate has all of the conditions recommended by Sonar". It is the organization default, and every project follows it ("Use the organization's default quality gate"; owner's rule of 2026-11-22: all projects use the organization's gate and quality profiles). All its conditions are on new code (pull requests and the last 30 days of `main`); a pull request or analysis fails when any of them is met:

| Condition (UI) | Metric and API value | Fails when |
| --- | --- | --- |
| Reliability severity is greater than or equal to Low | `new_reliability_issue_severity` `GT 9` | a new reliability issue of severity Low or higher (was bugs severity ≥ Minor) |
| Security severity is greater than or equal to Low | `new_security_issue_severity` `GT 9` | a new security issue of severity Low or higher (was vulnerabilities severity ≥ Minor) |
| Maintainability severity is greater than or equal to Medium | `new_maintainability_issue_severity` `GT 14` | a new maintainability issue of severity Medium or higher (was code smells severity ≥ Major) |
| Reliability Rating is worse than A | `new_reliability_rating` `GT 1` | the reliability rating of new code is below A |
| Security Rating is worse than A | `new_security_rating` `GT 1` | the security rating of new code is below A |
| Maintainability Rating is worse than A | `new_maintainability_rating` `GT 1` | the maintainability rating of new code is below A |
| Security hotspots reviewed is less than 100 % | `new_security_hotspots_reviewed` `LT 100` | a security hotspot in new code is not reviewed |
| Coverage is less than 80 % | `new_coverage` `LT 80` | coverage on new code below 80 % |
| Duplicated Lines (%) is greater than 3 % | `new_duplicated_lines_density` `GT 3` | duplicated lines on new code above 3 % |
| Dependency risk severity is greater than or equal to Low | `new_sca_severity_any_issue` `GT 9` | a new dependency risk of severity Low or higher |

Notes:

- The severity scale of the current metrics is Info, Low, Medium, High, Blocker; Low and Medium take the API values of the old Minor and Major (`9` and `14`), so the replacements fail on exactly what the deprecated conditions failed on.
- The four conditions "Review and update" added (the three A ratings and 100 % of security hotspots reviewed) are those of the built-in `Sonar way`; with them this gate is the agentic gate plus `Sonar way`, never weaker than either.
- The dependency-risk condition belongs to SonarQube Advanced Security (dependency analysis), a paid add-on: the UI shows it with the paid-feature mark. Without the add-on the metric is not computed, so the condition is not expected to fail. It is kept so the gate stays a superset of the built-in agentic one.
- "Ignore duplication and coverage on small changes" (organization default, on) still skips the coverage and duplication conditions for changes under 20 new lines.

## AI Code Assurance

Not available to this organization, on either plan it has had (checked on 2026-11-22). Sonar's subscription-plans page lists AI Code Assurance and the `Sonar way for agentic AI` gate as included in Free, Team and Enterprise, but the product offers neither on the Free or the OSS plan:

| Place | What it shows on OSS |
| --- | --- |
| Project > Administration | No "AI code assurance" entry; `/project/ai_generated_code?id=<key>` answers "The page you were looking for does not exist" (the same URL opens the page on a Team-plan project). |
| Policies > Quality gates | Only `Sonar way` among the built-in gates; `Sonar way for Agentic AI` is not listed. |
| Billing and usage | "SonarQube for OSS"; the only offer is an upgrade to Team. |

The owner's personal organization `jmrplens`, on the paid **Team** plan, has it: Project > Administration > AI code assurance, "This project contains AI-generated code" on, with the built-in gate `Sonar way for Agentic AI` (used by `phonometry`, `ghchronicle`, `gitlab-mcp-server` and others). Getting the feature here would need the Team plan (paid, $34/month for 100k private lines of code) or Enterprise; the custom gate above gives the same pass/fail conditions without the AI Code Assurance label.

## Stricter options (not applied)

- **Quality gate.** The OSS plan lets the gate be made stricter (conditions on overall code, coverage of at least 90 % on new code, zero new issues of any severity). That would fail analyses that pass today, which the "fix it, never ignore it" rule would then require fixing; it is the owner's call.
- **Quality profile.** The OSS plan allows custom profiles per project, or switching the organization's default per language to another built-in profile: `Sonar way extended` (Python 346 rules, GitHub Actions 33) or `Sonar way comprehensive` (Python 492, GitHub Actions 45). That would raise new issues on every project at the next analysis; it is the owner's call.

## What each `sonar-project.properties` carries

Everything a file can hold goes in the file:

| Property | Value |
| --- | --- |
| `sonar.organization` | `kleidos-dev` |
| `sonar.projectKey` | `kleidos-dev_<repo>` |
| `sonar.projectName` | the repository's name |
| `sonar.projectDescription` | the GitHub repository's description |
| `sonar.links.homepage` | `https://kleidos.dev` |
| `sonar.links.scm` | `https://github.com/kleidos-dev/<repo>` |
| `sonar.links.issue` | `https://github.com/kleidos-dev/<repo>/issues` (this repository has issues off, so it points at the organization's Discussions) |
| `sonar.links.ci` | `https://github.com/kleidos-dev/<repo>/actions` |
| `sonar.sources`, `sonar.tests` | the code roots, named explicitly so artwork, data and generated files never count as code |
| `sonar.exclusions` | only what sits inside a source root but is not the repository's code (today only in `boards`) |
| `sonar.test.inclusions` | only where `tests/` holds files that are not tests (today only in this repository) |
| `sonar.sourceEncoding` | `UTF-8` |
| `sonar.scanner.autoconfig.enabled` | `false` |
| `sonar.python.version` | `3.14`, the newest version SonarQube Cloud lists as supported; raised when the docs list a newer one |
| `sonar.python.coverage.reportPaths` | `coverage.xml`, written by the tests job with relative paths (`.coveragerc`) and handed to the Sonar job as an artifact |

Deliberately absent: `sonar.issue.ignore.multicriteria`, `sonar.cpd.exclusions` and `sonar.coverage.exclusions`. An issue is fixed with a real change or left open, and coverage is raised with tests.
