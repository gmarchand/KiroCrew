---
title: "The rm root row stops refusing a plain rm of named /tmp entries"
status: draft
author: kirocrew agent session, directed by the repository owner
created: 2026-11-13
last-audited: 2026-11-13
audited-at: 51349e12e7
doc-pr: null
implementation-prs: [36536]
tracking-issues: [19473, 35629]
supersedes: []
superseded-by: []
---

# RFC: The rm root row stops refusing a plain rm of named /tmp entries

## 1. Decision

The catalog row `local-destructive-rm-rf-root` keeps its pattern. It stops
refusing a command whose only match is a plain `rm` of named entries under
`/tmp` or `/var/tmp`. The repository owner made this decision on 2026-11-12,
after reading the recorded refusals: "why do we need to block deleting
/tmp/x? That seems wrong."

This changes a safety row's behaviour, and `rfc-agent-temp-reclaim.md` lists
"narrow `rm -rf /.*` to the root itself" as a rejected alternative that needs
its own decision. This document is that decision.

## 2. What the row does today

Verified at `51349e12e7`.

- `denied_rules_catalog.py` defines the row with pattern `rm -rf /.*`. Its
  description says it blocks deletion "rooted at the filesystem root".
- `deny_gate.is_denied` matches the pattern anywhere in the command text, so
  any absolute target matches: `rm -rf /tmp/build`.
- Only that literal spelling is refused. All of these are allowed on main:
  `rm -fr /tmp/x`, `rm -r -f /tmp/x`, `rm --recursive --force /tmp/x`,
  `find /tmp/x -delete`, `cd /tmp && rm -rf x`, and `shutil.rmtree` from
  `python3 -c`.
- `rm_floor.py` separately refuses recursive force deletion of `/` and `~`
  themselves in every spelling. That floor is not touched.

In 132 refusals recorded on one host from 2026-10-28 to 2026-11-12, 25 came
from this row. None was a root or system-path wipe.

## 3. Why the rejected-alternative reasoning does not hold for /tmp entries

`rfc-agent-temp-reclaim.md` rejects narrowing because "it loosens a floor
agents rely on, and it still gives an agent no way to know whether a tree is
in use".

- **"A floor agents rely on."** For a `/tmp/<name>` target the row stops one
  spelling of five. Nothing that relies on it is protected; a respelling,
  which the system prompt forbids, gets through.
- **"No way to know whether a tree is in use."** True, and the row never
  answered that either. `kirocrew tmp reclaim` (#32853) is the checked path
  for trees an agent did not make. This decision is for the entry the agent
  just made and is about to recreate (`rm -rf /tmp/x && mkdir -p /tmp/x`),
  the shape of 20 of the 25 records.

## 4. The rule

The row reads a view of the command in which each `rm` meeting all of these
is blanked; every other row and the rm floor read the full text:

1. its program word is exactly an unquoted `rm` (not `/bin/rm`, not after
   `sudo`, `env` or another wrapper);
2. every word is literal text: no `$`, glob, brace, tilde, quote or escape,
   and no `--`;
3. every operand is `/tmp/<name>[/...]` or `/var/tmp/<name>[/...]`, with no
   empty, `.` or `..` part and no trailing `/`;
4. each operand's folder resolves (realpath) to that root or below it, so a
   symlink planted at `/tmp/<link>` pointing elsewhere does not admit
   `/tmp/<link>/etc`.

So `/tmp`, `/tmp/`, `/tmp/*`, `/tmp/../etc`, `/tmp/$X` and a mixed
`/tmp/x /etc` are still refused.

## 5. Not covered

- `~/.cache/<name>` and other home paths: the `rm -rf ~.*` row is unchanged.
- Globs under `/tmp` (`/tmp/x.*`): still refused; a glob's expansion is not
  known from the text.
- Whether the tree is in use or owned by the caller: `kirocrew tmp reclaim`.
- Windows and macOS: the check is the same realpath comparison on both sides
  (`/private/tmp` on macOS); not run on either.
