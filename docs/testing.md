<!--
SPDX-FileCopyrightText: 2026 José M. Requena Plens
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Testing standard

Owner, 2026-11-24. Every kleidos-dev repository tries to reach the maximum of tests: 100 % of lines, branches, conditions (MC/DC) and mutants, with the good practice of its languages. This page says what that means, language by language. It comes from a pilot in [`kleidos-dev/cla`](https://github.com/kleidos-dev/cla): the measurement of that repository, the tools tried on it, and the review of its gates, which found six ways a pull request could lose checking and stay green, each closed and planted again. Where a sentence says "on cla", it was seen there.

A tool marked *candidate* was not run in the pilot. A repository adopts a tool only after trying it on its own code and writing down what it saw.

It is a standard to reach, not a state: each repository gets there in a round of its own, and [What the kit holds](#what-the-kit-holds) says which part is enforced today wherever the kit is called, what each repository holds by itself, and what nothing holds yet.

## Contents

- [What a number means](#what-a-number-means)
- [The gate is a ratchet](#the-gate-is-a-ratchet)
- [Exclusions](#exclusions)
- [Practices in every language](#practices-in-every-language)
- [Per language](#per-language)
- [Where each measure runs](#where-each-measure-runs)
- [What the kit holds](#what-the-kit-holds)

## What a number means

- A measure counts what a test **checked**. A line run by a test that asserts nothing, a snapshot nobody read, a status code with no look at what was written, or an excluded line adds nothing. Mutants are the measure that tells these apart, so no area is "at 100 %" on lines alone.
- Five measures, cheapest first: lines and functions; branches; conditions and MC/DC (each atomic condition shown to change its decision alone; the masking form for short-circuit languages, as LLVM defines it); mutants killed; properties holding on generated input. MC/DC and the two forced mutants of each condition are both required, because each overstates without the other: on cla, 21 of 382 conditions had both forced mutants killed without MC/DC, and 37 the reverse.
- The target of each is 100 %, less a listed set. What these tests protect comes first: the code that decides (who must sign, whether a record is valid, when data is erased, what a hostile input can do) reaches every measure before glue code reaches the first.

## The gate is a ratchet

- Each repository commits its floors, one file per area, `tests/floors/<area>.toml`. A floor stores **misses, not percentages**: uncovered lines, branches without both outcomes, conditions without MC/DC, surviving mutants, entries of each exclusion list.
- The gate fails when a count is above its floor, and also when it is below: the same change lowers the floor. So a count only falls, new code arrives fully tested, and at zero the entry is replaced by the tool's own threshold of 100.
- The ratchet check compares each file with the base branch. A raised count fails unless the same change adds a dated line with its reason to that file's `raised` table, which a maintainer reviews.
- **A dated line is not enough on its own.** On cla, a pull request that deleted a test file, lowered vitest's thresholds to 99 and listed the newly uncovered checks of the link sanitizer, with its own dated lines, was green everywhere. So a second check, of its own and red on purpose, names every floor raised, every measure or test count lowered, every new list entry and every threshold lowered, dated or not, as warnings on the run's page; a maintainer merges such a change knowingly, never on a quiet green. The numeric thresholds (vitest's, `fail_under`, Node's `--test-coverage-*`) are compared with the base too, and none falls without its `[[lowered]]` entry in the same change: they are the pull request's own text. The kit does that part in every repository that calls it, which the firmware does not yet ([What the kit holds](#what-the-kit-holds)).
- **Every area's files are found, not listed by pattern.** The check that each source file is in exactly one area walks the source roots at any depth (a new subfolder, a second `.py`, a `.mjs` beside the `.ts` files) and also fails on a file of an area that one of its tools cannot reach as configured (the coverage include, the mutator's globs, the MC/DC instrumenter's filter, the files a workflow hands the mutator, `sonar.sources`). On cla a back door in `worker/src/rules/login.ts`, wired in by one line, passed every gate before this: no tool ever looked at the folder.

## Exclusions

- One list per area, `tests/exclusions/<area>.toml`, keyed by file, function and source text, never by line number. The gate fails on a miss that is not listed, on an entry that is now covered or killed, and on an entry whose text no longer exists. The length of each list is a floor.
- Every list has a floor, the lists of suites that judge their own entries (workflows, pages) included: a list with no floor grows with no line at all.
- Valid reasons, a closed set: (1) unreachable by construction, with the argument, after trying to delete the code or narrow the type; (2) an equivalent mutant, with the argument why no input tells it apart; (3) the boundary to a real service or device (a socket, an eFuse, a radio), naming the test at another level that runs it; (4) a mutant the tool builds wrongly, naming the hand-written test that replaces it.
- Not reasons: hard to test, trivial, defensive, only logging, needs a mock, no time.
- Inline pragmas are banned (`# pragma: no cover`, `istanbul ignore`, `Stryker disable`, `LCOV_EXCL`, `NOSONAR`) and a guard greps for them; SonarCloud gets no coverage exclusion. Generated and vendored files are out of scope by path, stated in the tool's configuration, and tested where they are made.
- Dead code is deleted, not listed.

## Practices in every language

- **Arrange, act, assert**, visibly, and one reason to fail per test. A table of cases is one named case per row.
- **The name states the rule** as a sentence ("an expired session cannot sign"), not the function under test.
- **Values and effects, not status.** Assert what was returned, what was written, what was *not* written or called, and the order; a refusal is asserted by its reason, never by its exception type alone.
- **Strict fakes.** A fake of an outside service refuses what the real one refuses (method, headers, credentials), fails on a call the test did not expect, and records its calls for the assert.
- **Parsers and validators** (anything that reads bytes or text it did not write) get property tests (round trip, idempotence, raises only its declared errors, agrees with a second implementation) and a hostile corpus: empty, huge, wrong type, duplicate keys, bytes that are not UTF-8, Unicode letters that look like another and digits, control characters, numeric edges. Two implementations of one rule (two languages, firmware and host) read one shared vector file.
- **Tests are counted.** Each suite's floors hold how many tests every test file runs, as the runner reports them (unittest through a small result class, vitest's JSON reporter, a `node --test` reporter), and the run fails on more or fewer, a file gone, no test at all, and any test skipped, left to do or expected to fail. Coverage cannot see a lost test: the lines it ran are run by another one. On cla, `describe.skip` on 16 tests, seven deleted test files (111 tests, the end-to-end flows) and `raise SkipTest` over every property of the register were all green before. A lint or grep hook refuses `skip`, `todo`, `skipIf`, `runIf`, `only`, `fails`, `unittest.skip`, `SkipTest` and `expectedFailure` in the test trees, with each allowed exception named and counted. A test that cannot run everywhere (it needs a board, a browser, a tool the machine lacks) is the exception with a reason, and it runs somewhere: the CI job that has what it needs fails instead of skipping.
- **A planted defect for every guard.** A check, lint rule, CI gate or validator is tested by handing it the bad thing and seeing it fail (`--selftest`). The measuring tools too: a planted uncovered condition and a planted surviving mutant must be reported.
- **Determinism.** No sleep, wall clock, network or real randomness; no dependence on test order, locale, time zone or host. Time and randomness are injected. A property test in a pull request runs derandomized; the weekly run prints its seed, and a counterexample becomes a named example.
- **No timing assertions**: they measure the machine. Count calls or steps, or inject the clock.
- **Flakes.** A test that fails without a code change is a defect: no retry in CI and no "known flaky" mark; it is fixed at its cause or deleted within the week. The weekly run executes each suite in random order to find them first.
- **A real defect found while testing** gets its failing test first and its fix in a commit of its own.
- Tests are code: linted, typed, reviewed, with made-up data only (no real name, address, id or token).

## Per language

### Python

- **Measured:** lines and branches with coverage.py (`branch = true`, `patch = ["subprocess"]` so a command run as a child counts); conditions and MC/DC with an AST instrumenter (cla's `tests/tools/py/mcdc.py`; coverage.py has no condition measure: its arcs are pairs of lines); mutants with a runner of ours (cla's `tests/tools/py/mutate.py`), which mutates module level too (the regexes that decide live there), has the forced-condition and regex operators, and runs only the tests that reach the statement; properties with hypothesis; types with mypy strict.
- **Gate:** `fail_under = 100` when reached, the floors before.
- **Valid exclusion:** almost none. An abstract method becomes a `Protocol`; a `__main__` block is run by a child-process test.
- **Not worth doing:** pymcdc (builds the whole truth table: killed at 4 million rows for one decision); cosmic-ray (runs the whole suite per mutant and its parser lags the language); mutmut as the gate (no module level, no forced conditions: one cross-check, then gone); CrossHair and slipcover (cost or version support).

### TypeScript and JavaScript

- **Measured:** lines, statements, functions and branches with Istanbul where the runtime has no V8 coverage (workerd), with Node's own `--experimental-test-coverage` for Node scripts, which follows child processes; MC/DC with a Vite plugin or a load hook (cla's `worker/test/tools/mcdc.mjs` and `tests/tools/node/mcdc-hook.mjs`); mutants with StrykerJS, verdicts **from the real runtime**; properties with fast-check; types with `tsc --noEmit` strict plus `*.test-d.ts` (`expectTypeOf`, `@ts-expect-error`) for the types that carry a decision.
- **Valid exclusion:** a literal the mutator turns into a syntax error (reason 4).
- **Not worth doing:** a verdict under another runtime (2 of 143 mutants were "killed" only by a Node difference); c8 (reported 100 % of functions where four were never called); type-coverage percentages and tsd (strict `tsc` and a lint against `any` say more); request interception as a network fence ([Web pages](#web-pages)).

### C and C++ (ESP-IDF firmware and native hosts)

- **Measured on the host:** every unit that can compile natively: lines and branches with gcov or llvm-cov; MC/DC with GCC 14+ `-fcondition-coverage` or Clang 18+ `-fcoverage-mcdc` (*candidates*); always under ASan and UBSan; a time-boxed fuzz harness per parser and codec (libFuzzer, *candidate*); mutants (*candidates*: Mull, or a sampled own mutator) on the deciding units first.
- **Target:** 100 % of host-testable logic, and logic lives in units with no hardware include (the `*_logic.h` pattern) so the driver shell stays thin.
- **Measured on the device:** behaviors, by hardware-in-the-loop tests; every security rule has one. The tests that pin a rule over the sources count as guards and need their planted defect.
- **Valid exclusion:** register-level driver code and interrupt shells, each naming the device test that runs it (reason 3).
- **Not worth doing:** coverage on the target (it costs flash, RAM and timing, so the image measured is not the one shipped); unit tests of the vendor SDK; a mock of all ESP-IDF to run drivers on the host (it tests the mock); whole-firmware mutation on a pull request.

### Shell

- **Rule first:** a script with more than a few decisions moves to Python or Node, where it can be measured.
- **Measured for what stays:** shellcheck; every line run by a test (trace through `BASH_XTRACEFD` and `LINENO`, no tool needed); the real script run with stub commands first in `PATH`, asserting the argument vector byte for byte, the exit code, the output and the files; one mutant per guard line (delete it: a test must fail).
- **Not worth doing:** bats (adds a dependency and nothing else); kcov (*candidate*, not tried).

### GitHub workflows

- **Measured:** every `run:` block that decides, executed from the YAML's real text as above; every `if`, `run-name` and `concurrency` expression evaluated for each trigger (`@actions/expressions`); static assertions on the parsed YAML: permissions per job, actions pinned by commit, no `pull_request_target`, a secret only in its named environment and in no run name, concurrency group or other job.
- **Tools:** actionlint, zizmor and shellcheck from the kit, plus the above.
- **Listed as not provable:** GitHub's own enforcement (environment branch policy, token permissions, concurrency) and third-party actions.
- **Not worth doing:** act (it simulates the runner from images and proves nothing about GitHub's side).

### Generators of SVG, KiCad and 3D artifacts

- The generator is code of its language and follows that section. **The artifact is measured by:** reproducibility (generated twice, identical bytes: no dates, sorted iteration, fixed number format); drift (the committed copy equals the regeneration); form (XML parses; `kicad-cli` ERC and DRC with no unlisted violation; a mesh that is closed, manifold, in the stated units and bounding box; the last two *candidates*); and invariants from the source data: every dimension, position and label equals the table it came from, every part named in the data exists once, nothing lies outside the outline.
- **Target:** 100 % of the generator, and every data row checked by an invariant.
- **Not worth doing:** a pixel snapshot with a tolerance as a gate (it passes wrong drawings and fails on a renderer update). A reference image is a reviewed diff: it changes only in a commit that says what changed.

### Web pages

- **Measured:** every route, language, theme and width (390 px and desktop) loaded in a real browser from the real bundle behind a network fence: the browser's only way out is a local proxy, and any other host is a recorded failure. Per page: no axe violation outside the list, no console error, no stray request, valid HTML, response headers by value, and what the page states asserted from the DOM, with scripts off where the page promises to work without them.
- **Tools:** Playwright and `@axe-core/playwright`; chromium on pull requests, firefox and webkit weekly.
- **Not worth doing:** the browser driver's request interception as the fence (a followed redirect left it in the trial and loaded a real sign-in page); a Lighthouse score as a gate (noisy: keep byte budgets, which are exact); full-page pixel snapshots; tests against production.

### Documentation

- **Measured:** every internal link, path and `file:line` resolves; every command in a block marked runnable runs in CI; every figure comes from one data source through a guard, never typed twice; every normative sentence of an `AGENTS.md` ("never", "always", "only") names its guard or sits on a judgment list that only shrinks; markdownlint, no hard wrap, typos.
- **Not worth doing:** external links in the pull request gate (a weekly report: the network is not ours); readability or prose-coverage scores.

## Where each measure runs

- **Every pull request**, within the repository's stated budget (cla: 6 minutes): lines, branches, MC/DC, the exclusion lists, the test counts, properties with fixed seeds, the mutants of the changed lines, and **a capped sample of mutants for a change of the tests**. Every gate but mutants measures execution, so a pull request that only weakens assertions (on cla: all 48 `expect()` of one file made no-ops, 24 assertions of a register test neutralized) passes every one of them; the sample is drawn, seeded by the pull request's number, from the sources the changed test files name or import (or, in Python, the statements the changed test modules run) first, and from the rest only with what is left of the cap, so that a helper touched beside a weakened test does not dilute it. On cla the caps are 60 to 120 mutants per area, in jobs of 30 seconds to 2.5 minutes, and the planted cases left 4 to 10 survivors.
- **Weekly and on demand:** every mutant, in shards; properties with fresh seeds; the other browsers; random test order.
- **Limits, always:** a mutation, fuzz, property or hostile-input campaign runs under a wall-time and a memory limit for the whole run and a time limit per mutant, with at most two workers on a developer machine (an unbounded run took a whole machine down on 2026-11-23). "Killed by timeout" is reported apart from "killed". A tool that mutates in place runs in a throwaway clone.
- **Dependencies** for testing are development only, latest stable, pinned (hashes or a lockfile), justified one by one, and never reach a shipped artifact; the production audit stays at zero.

## What the kit holds

Few rules, each of which holds today in every repository that calls the kit (the firmware, `jmrplens/kleidos`, does not yet) and can be read in a failing line, rather than many that could be met without testing anything. They are the `tests` check of [`policy.py`](../quality/policy.py), in the `kleidos-kit` hook and in the lint job ([`suite_rules.py`](../quality/suite_rules.py)). The kit that runs is the one called, so a pull request does not judge itself, except in this repository, where the pull request's own kit runs.

| Rule | What it reads | Why |
| --- | --- | --- |
| No test is marked to run alone: `it.only`, `describe.only` and their chains, `fit`, `fdescribe`, an `only` option that is not off, also where the name is written as a string (`it["only"]`, `{ "only": true }`). No waiver | JavaScript and TypeScript files in a test folder, with a test's name, or that import a test runner | Every other test of the file stops running, and the suite passes |
| A test that is skipped, left to do or expected to fail says why, in two words at least: in the marker's own place (`skipIf(cond, "why")`, `reason="why"`, `t.skip("why")`, `{ todo: "why" }`), or, where it has none (`it.skip`, `it.todo`, `skipIf`, `runIf`, `fails`, `expectedFailure`), in a comment `skip: <why>` on its line, or in the lines right above that hold nothing but a comment | unittest's and pytest's markers in every Python file, read as Python; vitest's and `node:test`'s in the files above | A skip with no reason is nobody's decision, and outlives what it waited for |
| coverage.py's threshold is in its configuration, never on a command line (`--cov-fail-under`, `coverage report --fail-under` and its abbreviations). No waiver | The workflows, the actions under `.github/actions/`, `package.json`, pytest's options | The command line wins over the configuration, which is where a person looks |
| A coverage threshold never falls or goes: coverage.py's `fail_under`, vitest's `thresholds`, each glob's apart, Node's `--test-coverage-*` in a command of a workflow, an action or a `package.json` | The tree, against the base of the pull request or what `main` was before the push; in the hook, against where the branch left `origin/main` | The number is the pull request's own text: a change that loses tests lowers it and is green |

A threshold that has to fall says so in the same change, in the file every weakening is in, `.github/quality/waivers.toml`, which is under `.github/` and so is read line by line before a merge ([`quality.md`, "Merging"](quality.md#merging)):

```toml
[[lowered]]
threshold = "coverage fail_under"   # as the check names it
to = 99                             # its new value, "gone" or "unreadable"
reason = "Why, with the code it was lost on"
decided = "owner 2026-11-25"        # or "agent, reviewed in PR #<n>"
```

What is compared is what the tool would use. Of the files coverage.py looks for in a folder (`.coveragerc`, `.coveragerc.toml`, `setup.cfg`, `tox.ini`, `pyproject.toml`, in that order) only the one it stops at counts, and vitest's `vitest.config.*` counts before `vite.config.*`, unless it imports it: a new file that is read first takes the threshold with it. So those are named by the tool and its folder (`coverage fail_under`, `host/coverage fail_under`, `worker/vitest lines`, `worker/vitest src/a/** lines`), and a Node flag by its file (`worker/package.json lines`). Every place a threshold is given is compared, so losing one of two commands is a fall. A value that is not a plain number (a name, a sum, an object with a spread or a computed name in it) is not held, and one that was held becoming so is a fall to "unreadable".

An entry counts in the change that adds it and in no other: what was said of one fall says nothing of the next. The job's log names every fall it accepts. Entries stay as the record of what fell, or are removed later; neither matters to the check.

**What these rules do not see.** A marker reached by another name than its import (`getattr`, a variable that holds it, a name that is computed or written with escapes, a star import of another module, a fixture that skips) or an option that comes from a variable (`it("x", options)`, a spread); a reason or a threshold that is computed when it runs; a test renamed or deleted; a suite a command leaves out (`-k`, `-m`, a glob), or a command that never runs or whose failure is ignored; a configuration a command or the environment names (`--rcfile`, `COVERAGE_RCFILE`, `--cov-config`, vitest's `--config` and `--coverage.thresholds`), or a run from another folder; a `thresholds` object that a file holds and does not use, or that a later spread or another `coverage` object replaces; a skip whose reason says nothing in two words; an assertion taken away; code moved out of what a tool measures (`omit`, a pragma, a glob, `enabled: false`); a threshold in a file or a flag the table does not name (a shell script's, a program's own floors); and C or C++. JavaScript is read as text: in a file it cannot tell apart for certain (a `/` after a `}`, JSX, a quote that never ends) a comment or a string that spells a marker is taken for one, and is worded otherwise; a vitest configuration like that holds no threshold. A reason or a `[[lowered]]` entry makes a change visible; whether it is good is for the person who merges it.

**What each repository holds by itself.** The rest of this page: the floors and their ratchet, the exclusion lists, the counted tests, the areas, the mutants. `kleidos-dev/cla` is the model (`tests/floors/`, `tests/exclusions/`, `tests/tools/`). This repository holds each file of the kit to its share of lines and branches ([`coverage_floor.py`](../quality/coverage_floor.py)).

**What nothing holds yet.** That every repository has a threshold at all, that a pragma is never used, that a floors file only falls, that mutants run: each of them is red somewhere today, so each enters the kit, as a MAJOR or once every repository passes it, after the rounds.
