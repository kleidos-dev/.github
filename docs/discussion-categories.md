<!--
SPDX-FileCopyrightText: 2026 José M. Requena Plens
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Discussion categories

The organization's Discussions are hosted by this repository (`kleidos-dev/.github`). This file lists the categories to set up, in display order, and the welcome post to pin in General.

When Discussions are turned on, GitHub creates six default categories (Announcements, General, Ideas, Polls, Q&A, Show and tell). Keep them, edit their descriptions to the ones below, and add **New board requests**.

The emoji column gives GitHub's shortcode for the picker.

| Name | Emoji | Format | Description | Who can post |
| --- | --- | --- | --- | --- |
| Announcements | `:mega:` | Announcement | News from the project: releases, new repositories, changes to these rules. | Maintainers only (anyone can comment) |
| Q&A | `:pray:` | Question / Answer | Ask how something works or why it does not, and mark the answer that solved it. | Anyone |
| Ideas | `:bulb:` | Open-ended discussion | Propose a feature or a change before anyone writes code for it. | Anyone |
| New board requests | `:electric_plug:` | Open-ended discussion | Propose a board for Kleidos, one request per board, through the form. | Anyone |
| Show and tell | `:raised_hands:` | Open-ended discussion | Show your board, your case, your setup, or something you built around Kleidos. | Anyone |
| Polls | `:ballot_box:` | Poll | Ask the community to choose between options. | Anyone |
| General | `:speech_balloon:` | Open-ended discussion | Anything about Kleidos that fits no other category. | Anyone |

## Notes for setup

- **New board requests** must have the slug `new-board-requests`, so that it picks up the form in [`.github/DISCUSSION_TEMPLATE/new-board-requests.yml`](../.github/DISCUSSION_TEMPLATE/new-board-requests.yml). GitHub derives the slug from the name; check it after creating the category.
- **Announcements** is the only format that limits who can open a discussion. Every other category is open to anyone.
- **Q&A** and **New board requests** link from `CONTRIBUTING.md` and the profile README by their slugs (`q-a`, `new-board-requests`). If a slug changes, update those links.
- Security reports never belong in any category: see `SECURITY.md`.

## Pinned welcome post (General)

Title: **Welcome to Kleidos Discussions**

> Welcome. Kleidos is free firmware that turns a small ESP32 board from M5Stack or LILYGO into a hardware password manager: your passwords stay encrypted on the board, which types the one you pick over Bluetooth once you have unlocked it on the board itself. It runs on nine boards today and is not released yet. More at <https://kleidos.dev>.
>
> Where things go:
>
> - **Q&A**: questions about how it works.
> - **Ideas**: features and changes, before any code.
> - **New board requests**: a board you would like it on. Use the form, one request per board, and upvote a request that already exists instead of opening a second one.
> - **Show and tell**: what you have built.
> - **General**: everything else.
>
> A few rules:
>
> - **Never post a vulnerability here.** Report it privately, as `SECURITY.md` explains.
> - **Never post a postal address**, yours or anyone's. If you want to donate a board, write to mail@kleidos.dev and it is arranged by email. Devices are accepted only as donations: a donated board stays on the test bench for future testing.
> - **Donations are gifts.** GitHub Sponsors and Ko-fi are the two routes, and a donation through either gets you nothing in return: no reward, no priority, no support for a board, no date, and no name on any list the project keeps (GitHub Sponsors and Ko-fi let you stay private). To give toward a specific board, name it in the Ko-fi message, public or private as you prefer, or in an email to mail@kleidos.dev. Never post amounts or receipts here. That money goes to buying that board, up to its price: if the board is bought and the money falls short, the project pays the rest. Anything beyond the price, and all of it if the board is never bought (discontinued, or the port declined), goes to a general fund for the project's other costs, such as more boards and bench parts.
> - A board is **supported** only after the maintainer has run the full bench test on the device: its builds flashed onto it and the hardware test suites passing on it, as `CONTRIBUTING.md` defines. Before that it can be **community-tested**: someone has run Kleidos on their own unit of it and reported how it went.
>
> Be kind, stay on topic, and assume good faith; everyone here follows the [code of conduct](https://github.com/kleidos-dev/.github/blob/main/CODE_OF_CONDUCT.md). Thanks for being here.
