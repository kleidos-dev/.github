# Security policy

Kleidos is a hardware password manager. A vulnerability in it can expose someone's whole set of passwords, so security reports come first.

This is the default policy for every public repository of the kleidos-dev organization that has no `SECURITY.md` of its own.

## Report it privately

**Never report a vulnerability in Discussions, in an issue, or in a pull request.** Use one of these:

1. **A private vulnerability report on the repository it concerns.** On the repository's **Security** tab, choose **Report a vulnerability**. This opens a conversation only you and the maintainer can see.
2. **Email**, when the code has no public repository to report on yet (as with the firmware), when the repository does not offer the button, or when you cannot use GitHub: write to <mail@kleidos.dev>. If you want to encrypt the report, use the OpenPGP key `9476 5B19 FB50 5392 C68A  ED60 0535 C714 FCEF 3BC3` (`Kleidos <mail@kleidos.dev>`). Your OpenPGP client can fetch it by the address alone, from the Web Key Directory of kleidos.dev (`gpg --locate-keys mail@kleidos.dev`, or
   <https://kleidos.dev/.well-known/openpgpkey/hu/dizb37aqa5h4skgu7jf1xjr4q71w4paq>),
   and it is also on [keys.openpgp.org](https://keys.openpgp.org/vks/v1/by-fingerprint/94765B19FB505392C68AED600535C714FCEF3BC3). Check the fingerprint before you use it. The first message can also simply ask for a reply, with no details.

Reports in English or Spanish are both fine.

Please do not post details anywhere public before a fix is out, and test only on hardware you own, with your own test data.

## What to include

- Which board, and which build of the firmware (version and target) if the report is about the firmware.
- What the attacker has: radio range, network access, the device in hand, a flash programmer, an unlocked computer or phone.
- The steps to reproduce it, and a proof of concept if you have one.
- What the attacker gains: credentials, a way past the PIN, persistence, a denial of service.

## What happens next

| Stage | Target |
| --- | --- |
| Acknowledgment | 3 business days |
| Triage: severity, and whether it is in scope | 7 days |
| Fix or documented mitigation, Critical or High | 30 days |
| Fix or documented mitigation, Medium or Low | 90 days |
| Public disclosure | With the fix, or 90 days after the report, whichever comes first |

Kleidos has one maintainer. These are honest targets, not a contract; if one is going to slip, you will be told before it does, with the reason and a new date.

The fix is developed privately, and you can review it before it is released. The advisory is then published, on the repository or, while the code has no public repository, on <https://kleidos.dev>, and it credits you unless you would rather not be named.

## Out of scope

- Development (`_debug`) builds, which are never shipped and must never hold real credentials.
- A compromised computer or phone that the device types into: it receives keystrokes by design.
- Hardware side channels (power or electromagnetic analysis, fault injection, decapping). The boards have no secure element and no tamper-evident case.
- Offline PIN guessing on an open build, one that can be re-flashed and is not bound to the device. Finding a way to do it faster than the documented cost is in scope.
- Exporting the passwords in plain text from an authenticated admin session. That is a feature, and the exported file is the owner's responsibility.
- A short PIN as such. A 4-digit PIN, where a board allows one, has 10,000 values; the control is the lockout and the wipe after the tenth wrong attempt, and a way around those is in scope.
- Scanner output, or findings with no security consequence.

The limits Kleidos documents are listed at <https://kleidos.dev/security/>. If you can show that one of them does not hold, that is in scope.

## Safe harbor

If you make a good-faith effort to follow this policy while researching a vulnerability in Kleidos, the project will treat your research as authorized, will not pursue or support any legal action against you for it, and will work with you to understand and fix the issue.

Good faith means that you test only on hardware you own, with your own test data; that you do not access, change, or take anyone else's data, and stop as soon as you can show the issue; that you do not disrupt any service you do not own, nor attack the project's infrastructure (GitHub, the release pipeline,
<https://kleidos.dev>) beyond what a normal user does; and that you give the
project a reasonable chance to fix the issue before you disclose it, within the targets above.

If you are not sure whether something is in bounds, ask first, privately, as described above. Asking never counts against you.

This is a commitment from this project about its own code. It cannot authorize anything with respect to third-party services, other people's devices, or the law where you live.

## Recognition

There is no bug bounty and no monetary reward. What is offered is credit in the published advisory, in the form you prefer, anonymity included.
