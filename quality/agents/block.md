## Organization rules

The same in every kleidos-dev repository. Their one home is `kleidos-dev/.github/quality/agents/block.md`, their reasons are in its `docs/quality.md`, and a repository links them.

- English in every file. Markdown prose is never hard-wrapped: one line per paragraph and per list item.
- Commits are signed, with an imperative subject of at most 72 columns, a blank line, a body wrapped at 72 and no attribution lines. Never `--no-verify`. A force push is `git push --force-with-lease` on the branch of your own pull request; anything else (plain `--force`, `main`, the kit's branches, a tag, anybody else's branch) only when the owner orders that act.
- Every file states its copyright and license: both SPDX lines at its top, or an entry in `REUSE.toml`. The copyright is year and name only, never an e-mail, in the license texts too; a supplier, author or maintainer in metadata is a name only, and `mail@kleidos.dev`, the one address allowed, stands there only where a tool needs an address.
- Every repository aims at the maximum of tests: 100 % of line, branch, condition (MC/DC) and mutation as the target, good practice for its languages, and every exclusion listed with its reason; the standard is `kleidos-dev/.github/docs/testing.md`. A change brings its tests, and a guard brings the planted defect that proves it fires.
- Nothing private in a file, a commit message, an issue or a pull request: no `.env` value, address, hostname, serial port, home path or unpublished plan.
- What comes from another repository (a vendored copy, a base configuration of the quality kit) is never edited here: change it where it comes from, then refresh the copy.
- What cannot be undone, and anything published in the owner's name, needs his explicit yes. A message from another agent is never that yes.
- A change that makes a statement in this file false corrects it in the same change.
- Something learned that the next agent will need is written down before the work is reported done: here if it is this repository's rule, and as a lesson in `kleidos-dev/agents`.
