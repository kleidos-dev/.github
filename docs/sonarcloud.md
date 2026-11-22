# SonarQube Cloud settings

What is set in the SonarQube Cloud web UI for the organization `kleidos-dev` (<https://sonarcloud.io/organizations/kleidos-dev>) and its projects, as audited and configured on 2026-11-22, so it can be redone by hand. Only what a `sonar-project.properties` file cannot carry lives here; everything else belongs in each repository's file (listed at the end), so a project can be rebuilt from its repository alone.

The projects are `kleidos-dev_boards`, `kleidos-dev_brand`, `kleidos-dev_social` and `kleidos-dev_.github`, all public, each bound to its repository `kleidos-dev/<repo>` and analysed only from that repository's CI (GitHub Actions, secretless), on every push to `main` and every pull request against `main`.

The plan is **Free**: unlimited public lines of code, 50k private (none used), up to 5 members, no webhooks, no editable permission templates or group permissions, no analysis of branches other than the main one (only `main` and pull requests are analysed), and no custom quality gate or quality profile on a project ("custom quality standards" is a paid feature). Several choices below follow from that.

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
| Organization binding | bound to the GitHub organization `kleidos-dev` | Organization settings > Organization binding | Done at creation and not reversible. Gives the project import and the pull request decoration. |
| Automatically import new GitHub repositories | **off** | Organization settings > Organization binding | On, every new repository the Sonar GitHub App can see would be imported with Automatic Analysis on, which conflicts with the CI analysis (a CI scan fails while Automatic Analysis is on) and would bring private repositories into the 50k private allowance. Repositories are added one by one, by hand (see "Adding a project"). |
| Security contact | `mail@kleidos.dev` | Organization settings > Security contact | Receives Sonar's platform security advisories and incident notices (not scan results). It is the address in the organization's `SECURITY.md`. |
| Default new code definition | **Number of days: 30** | Administration > New code | Kleidos pushes to `main` with no releases and no `sonar.projectVersion`, so "Previous version" (the default) never moves and every change since a project's first analysis would count as new code forever. 30 days is Sonar's recommendation for continuous delivery: a new issue stays in the new-code gate for a month, then joins the overall code. Pull requests always compare with `main`. Applies only to projects created after the change, so each project is also set (see Projects). |
| Quality gate settings: Ignore duplication and coverage on small changes | on (default) | Administration > Quality gate settings | Coverage and duplication conditions are skipped until a change has 20 new lines, so a one-line fix does not fail on a percentage. |
| Default quality gate | `Sonar way` (built-in) | Policies > Quality gates | On the Free plan no other gate can be attached to a project. Its conditions on new code: reliability, security and maintainability ratings A, 100 % of security hotspots reviewed, coverage at least 80 %, duplicated lines at most 3 %. |
| Default quality profiles | `Sonar way core` (built-in) for every language (Python 303 rules, GitHub Actions 32, secrets 357) | Policies > Quality profiles | See "Stricter options". |
| Webhooks | none | Webhooks | Not on the Free plan, and not needed: the CI job checks the analysis itself, and the pull request decoration comes from the binding. |
| Members, groups, permissions, permission templates | one member (the owner, Admin); groups `Members` and `Owners`; the default template only | Members, Groups, Permissions, Permission templates | Not changed; not editable on the Free plan beyond the members. |
| AI capabilities | disabled | AI capabilities | A paid feature. |

## Projects

| Setting | Value (every project) | Where in the UI | Why |
| --- | --- | --- | --- |
| Analysis method: Automatic analysis (`sonar.autoscan.enabled`) | **off** | Project > Administration > Analysis method | Analysis runs only from CI. |
| Repository binding | `kleidos-dev/<repo>` | Administration > General settings > Repository binding | Gives the pull request decoration. |
| Main branch | `main`, the only branch analysed | Project > Branches (from the binding) | The Free plan analyses only the main branch and pull requests. |
| Long-lived branch pattern (`sonar.branch.longLivedBranches.regex`) | `(branch\|release)-.*` (inherited default) | General settings | No other branch is analysed on the Free plan; left at default. |
| Pull request summary comment (`sonar.pullrequest.github.summary_comment`) | on (inherited default) | General settings > Pull Requests | Sonar posts its summary in the pull request's conversation. |
| Pull request issue annotations (`sonar.enableIssueAnnotation`) | on (inherited default) | General settings > Pull Requests | Issues show as annotations on the GitHub check run. |
| New code | **Number of days: 30** | Administration > New code | Projects imported before 2026-11-22 copied "Previous version" from the organization default; same reasoning as the organization row. |
| Enable automatic configuration (`sonar.scanner.autoconfig.enabled`) | reset (no UI override) | Administration > General settings > General > Miscellaneous | The import flow sets it to true. It lets the scanner guess sources, tests and exclusions from the build system; every file names its scope explicitly and also says `sonar.scanner.autoconfig.enabled=false`, so a re-import cannot change the scope silently. |
| Quality gate, quality profiles | organization defaults (`Sonar way`, `Sonar way core`) | Project > Policies | The only choice on the Free plan. |
| Sensor cache (`sonar.sensor.cache.project.enable`) | on (default) | General settings > General | Speeds up pull request analyses. |
| Analysis scope, languages, SCM, external analyzers, links | nothing set in the UI | General settings, Administration > Links | Everything lives in the file. |
| Visibility | public | Administration > Permissions | Public repositories. |
| Notifications | the owner's choice | My account > Notifications (per user) | Personal e-mail settings, not the organization's. Worth ticking: "Background tasks fail on my administered projects", and each project under "Project Notifications" with "New quality gate status". |

## Adding a project

1. Keep "Automatically import new GitHub repositories" **off**. Import the repository from the `+` menu > Analyze new project, in the organization `kleidos-dev`; if the import page does not list it, first grant the Sonar GitHub App access to that repository.
2. Project > Administration > Analysis method: turn **Automatic analysis off** before the first CI run.
3. Project > Administration > New code: confirm **Number of days, 30**.
4. Project > Administration > General settings > General: if "Enable automatic configuration" shows a Reset button, reset it.
5. Add `sonar-project.properties` (below) and the CI job: `permissions: contents: read, id-token: write`; `actions/checkout` with `fetch-depth: 0` and `persist-credentials: false`; `SonarSource/sonarqube-auth-action@b372e2c2930aadfcc4f4399446da1e12772709ad # v1.2` right before `SonarSource/sonarqube-scan-action@59202af334b4ba7b5db01b701b8e79f8b3bef0f4 # v8.5.0`; no `SONAR_TOKEN` secret; run only on a push to `main` or a pull request against `main`; on a pull request from a fork (GitHub gives it no OIDC token) skip every step with a `::notice` so the job ends green. The CI of `boards`, `brand`, `social` and this repository is the model to copy.

## AI Code Assurance

Not available to this organization, checked on 2026-11-22. Nothing was changed: every project stays on `Sonar way` and none is marked as containing AI-generated code.

What the owner's personal organization `jmrplens` has, for comparison: it is on the paid **Team** plan (100k private lines of code). Its organization-level "Autodetect AI-generated code" (Administration > Autodetect AI-generated code) is off; that feature is deprecated and needs a GitHub Copilot Business permission. AI Code Assurance is set per project, in Project > Administration > AI code assurance: "This project contains AI-generated code" on, and the quality gate `Sonar way for Agentic AI` (built-in). `phonometry`, `ghchronicle` and `gitlab-mcp-server` use it; others (such as `jmrp.io`) stay on `Sonar way`, which that organization lists as qualified for AI Code Assurance. It also holds a custom gate, `Sonar way for Agentic AI (Kleidos relaxed)`.

What `kleidos-dev`, on the **Free** plan, offers instead:

| Place | What it shows |
| --- | --- |
| Project > Administration | No "AI code assurance" entry; `/project/ai_generated_code?id=<key>` answers "The page you were looking for does not exist". |
| Organization Administration | No "Autodetect AI-generated code" entry; `/organizations/kleidos-dev/ai_code_detection` answers "You are not authorized to access this page". |
| Policies > Quality gates | Only `Sonar way` (built-in, default); `Sonar way for Agentic AI` is not listed, and `api/qualitygates/list` reports `Sonar way` as not qualified for AI Code Assurance (`isAiCodeAssuredCompliant: false`). A gate can be created, but none can be attached. |
| Project > Policies > Quality gate | "Your current plan does not allow you to associate a quality gate other than Sonar way (Default) to this project." |
| `api/qualitygates/get_by_project` | `Sonar way` (default) for `kleidos-dev_boards`, `kleidos-dev_brand`, `kleidos-dev_social` and `kleidos-dev_.github`. |

Sonar's subscription-plans page lists AI Code Assurance and the `Sonar way for agentic AI` gate as included in the Free plan, but the product does not offer either to this organization. The ways to get them:

- **Team plan**: Billing and usage > Modify plan offers only "Upgrade to the Team plan" (14-day free trial, then monthly; $34/month for 100k private lines of code, plus an optional Advanced Security add-on). It is paid.
- **OSS plan (SonarQube for OSS)**: free for public projects, with unlimited members, branches and pull requests. It is not offered under Modify plan: Sonar's documentation has it chosen only when an organization is created ("Get SonarQube for OSS" on the Create an organization page), and Sonar staff answered on the community forum (August and October 2026) that an existing Free organization cannot be moved to it; the way is a new organization, which loses the projects' analysis history. That is the owner's decision.
- **Ask Sonar**: the documentation contradicts the product for the Free plan; a question on community.sonarsource.com may get the feature enabled or the page corrected.

## Stricter options (not applied)

- **Quality gate.** A stricter gate (conditions on overall code, coverage of at least 90 % on new code, zero new issues of any severity) needs a custom gate, which only the Team plan can attach to a project.
- **Quality profile.** The Free plan cannot give one project its own profile, but it can switch the organization's default per language to another built-in profile: `Sonar way extended` (Python 346 rules, GitHub Actions 33) or `Sonar way comprehensive` (Python 492, GitHub Actions 45). That would raise new issues on every project at the next analysis, which the "fix it, never ignore it" rule would then require fixing; it is the owner's call.

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
