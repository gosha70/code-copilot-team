# Origin alignment check — cct-command-naming (re-check)

Supersedes `origin-alignment-2026-11-07-0925.md`, which went stale when
`spec.md` and `plan.md` were edited after the design review. Kept so the
sequence stays visible.

Origin: specs/cct-command-naming/origin/2026-11-07-owner-direction.md
(the owner's two messages of 2026-11-07) and
https://github.com/gosha70/code-copilot-team/issues/410.

Origin claim:
> I run `claude-code` but want to always start within CCT; and every CCT
> command should be abbreviated to `cct` instead of `code-copilot-team`.
> File the issue, plan, then build.

Working claim:
> Unchanged in shape from the 0925 record: `cct start`, a `~/.local/bin/cct`
> shim installed by `setup.sh --claude-code`, the plugin renamed `cct`,
> docs and tests following. Two hardening additions from the design review
> the owner pasted back: the shim exits 2 with a named remedy when its
> baked checkout is gone (instead of bash's "no such file"), and
> `cct doctor` reports the `cct` on `PATH` and fails when the shim points
> at a missing checkout. The refusal text of `cct start` now says it wants
> the installed launcher, not a checkout's copy.

## What changed since the 0925 record, and why it does not move the scope

- **FR-2 gained the shim's failure mode and a doctor check.** Both make
  the thing the origin asks for (one `cct` command the user can trust)
  diagnosable when it breaks. They add no surface the owner did not ask
  for: no new command, no new flag, no new file beyond the shim already
  planned.
- **`cct start`'s refusal text** explains why a checkout's launcher copy is
  not used. Wording only.
- The deferral of the `~/.code-copilot-team/` move stands; the review
  agreed it is a migration and leaned to deciding it at 2.1.

Mismatches:
  - none

Verdict: aligned
Confidence: high
