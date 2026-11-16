# Kleidos

Kleidos is free firmware that turns a small ESP32 board from M5Stack or LilyGO
into a hardware password manager. Your passwords stay encrypted on the board,
which types the one you pick into your computer or phone over Bluetooth, and
only after you have unlocked it on the board itself. No app, no cloud.

It is not released yet. Read more at **<https://kleidos.dev>**.

## Boards

Kleidos runs on nine boards: four on the ESP32-S3 and five on the classic
ESP32.

| Board | Chip | You operate it with |
| --- | --- | --- |
| M5StickS3 | ESP32-S3 | Two buttons |
| M5Cardputer ADV | ESP32-S3 | A keyboard |
| LilyGO T-Deck Plus | ESP32-S3 | A keyboard, a trackball, and a touchscreen |
| M5Stack CoreS3 SE | ESP32-S3 | A touchscreen |
| M5StickC Plus2 | ESP32 | Two buttons |
| M5StickC Plus 1.1 | ESP32 | Two buttons |
| M5StickC Plus SE | ESP32 | Two buttons |
| M5Stack CoreInk | ESP32 | A wheel |
| M5Stack Core2 v1.3 | ESP32 | A touchscreen |

The CoreInk's screen is e-paper; the other eight have an LCD.

Want it on another board? Open a request in
[New board requests](https://github.com/orgs/kleidos-dev/discussions/categories/new-board-requests).

## Take part

- Ask a question, share an idea, or show your build in
  [Discussions](https://github.com/orgs/kleidos-dev/discussions).
- Read [how to contribute](https://github.com/kleidos-dev/.github/blob/main/CONTRIBUTING.md)
  and the [code of conduct](https://github.com/kleidos-dev/.github/blob/main/CODE_OF_CONDUCT.md).

## Security

Do not report a vulnerability in Discussions or in an issue. Report it
privately, as described in the
[security policy](https://github.com/kleidos-dev/.github/blob/main/SECURITY.md).

## License

Kleidos is licensed under the
[GNU General Public License, version 3 or later](https://www.gnu.org/licenses/gpl-3.0.html)
(GPL-3.0-or-later). Each repository states its own license in its `LICENSE`
file.
