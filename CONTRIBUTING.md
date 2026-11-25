<!--
SPDX-FileCopyrightText: 2026 José M. Requena Plens
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Contributing to Kleidos

Thank you for being here. This is the default guide for every public repository of the kleidos-dev organization; a repository with its own `CONTRIBUTING.md` adds its specific rules there.

Kleidos is a hardware password manager, so the bar for a change is higher than "it works on my board". Small, well-scoped, and well-tested changes are the most welcome.

## Where to ask

- **Questions**: [Q&A](https://github.com/orgs/kleidos-dev/discussions/categories/q-a).
- **Ideas and feature requests**: [Ideas](https://github.com/orgs/kleidos-dev/discussions/categories/ideas). For anything larger than a bug fix, start there before writing code: Kleidos runs on nine boards with tight flash and power budgets, and a change that is easy on one can be impossible on another.
- **Security problems**: never in public. Follow [SECURITY.md](SECURITY.md).

Questions, ideas and pull requests all reach the maintainers; there is no need to mention anyone.

Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).

## How a new board gets added

1. **Request it** in [New board requests](https://github.com/orgs/kleidos-dev/discussions/categories/new-board-requests). The form asks for the board's chip, memory, screen, input, and power, and how you could help.
2. **A port is a decision, not a vote.** Whether a board is ported depends on its hardware, the work it needs, and whether a unit is available to test on. Upvotes help show interest; they do not decide it, and there are no dates.
3. **There are two levels:**
   - **Community-tested**: someone has run Kleidos on their own board and reported how it went. The maintainer has not run the full bench test on it.
   - **Supported**: the maintainer has run the full bench test on the device itself. Only then is a board called supported.

   **The full bench test** means flashing the board's own firmware builds onto the device and passing the project's hardware test suites on it: unlocking and reading the stored passwords, typing over Bluetooth to a paired computer, using the admin portal over Wi-Fi, and sleeping and waking; and, on a board the bench meter can measure, measuring its current draw. This definition will be revised as the bench grows.

### Helping with a board

You can help by donating a device, by donating to the project, or by testing builds on your own board.

- **Devices are accepted only as donations.** A donated board stays on the test bench for future testing; it is not sent back.
- **Never post a postal address** in a discussion, an issue, or a pull request. If you want to donate a device, write to <mail@kleidos.dev> and the shipping is arranged privately by email.
- **A donation is a gift.** Donations go through [GitHub Sponsors](https://github.com/sponsors/jmrplens) or [Ko-fi](https://ko-fi.com/jmrplens) and get you nothing in return: no reward, no tier, no priority, no date, and no name on any list the project keeps (GitHub Sponsors and Ko-fi let you stay private).
- **Money can be given toward one board.** Say which board in the Ko-fi message, public or private as you prefer, or in an email to <mail@kleidos.dev>; never post amounts or receipts in a discussion, an issue, or a pull request. That money goes to buying that board, up to its price. If the board is bought and the money falls short, the project pays the rest. Anything beyond the price, and all of it if the board is never bought (discontinued, or the port declined), goes to a general fund for the project's other costs, such as more boards and bench parts. It is still a gift, with nothing in return.
- **Neither a donation nor a donated device guarantees support for a board, or a date for it.**

## Pull requests

- Write everything in the repository in English: code, comments, commit messages, and documentation.
- Commit messages in the imperative mood: `Add the CoreInk wheel legend`, not `fixed stuff`.
- One concern per pull request.
- Say what you tested and on what. If you have no hardware, say so; that is fine and it tells the reviewer what to check.
- Update the documentation in the same change.
- Do not bypass checks (`--no-verify`). A force push is `git push --force-with-lease` on the branch of your own pull request; anything else (plain `--force`, any other branch, a tag) only when the owner orders that act.

You do not need to mention or assign anyone: every pull request asks the maintainers (`@kleidos-dev/maintainers`) for a review on its own, through `CODEOWNERS`.

## License of contributions

Kleidos is licensed under the GNU General Public License, version 3 or later (`GPL-3.0-or-later`). Each repository states its license in its `LICENSE` file.

A contribution is accepted under the license of the repository it goes to, and under nothing else (inbound = outbound): you keep the copyright of what you wrote. If the project ever asks contributors to sign a contributor agreement, it will be announced here before it applies to anything.

Every file that can carry a comment starts with two lines, copyright first, then the SPDX identifier of the repository's license for it, in that file's comment syntax: the year is the year the file was first committed, and there is no e-mail address. For example:

<!-- REUSE-IgnoreStart -->

```cpp
// SPDX-FileCopyrightText: 2026 José M. Requena Plens
// SPDX-License-Identifier: GPL-3.0-or-later
```

<!-- REUSE-IgnoreEnd -->

A file that cannot carry a comment (an image, a JSON file, generated data) gets both through the repository's `REUSE.toml`. The quality kit's header check enforces this, and `spdx_headers.py --write` writes the lines with the right year (`docs/quality.md` in kleidos-dev/.github, "Licensing headers").

## The name and the logo

The license covers copyright. It grants no right to the Kleidos name or logo. If you plan to sell a device, or to publish a fork under a name like Kleidos, ask first.
