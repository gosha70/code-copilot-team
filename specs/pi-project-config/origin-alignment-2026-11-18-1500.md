# Origin alignment check — pi-project-config (review of 222f012)

Date: 2026-11-18

Supersedes the 1400 record. The owner's review of PR #468 at `222f012`
asked for five changes, all applied:

- **FR-6 and Constraints.** `migrate` makes no git change, but in a git
  work tree it runs the read-only `git check-ignore`; if `.cct.toml` or
  `.cct-init.json` would be ignored it moves nothing, names the rule and
  exits 1. Without this, a hiding rule would let the next commit record
  the old configuration as deleted with nothing added, which loses the
  team's configuration. Success Criteria add the refusal case.
- **FR-4 and plan § Risks.** `init` decides "already ignored" with
  `git check-ignore` (any spelling, `.git/info/exclude`, a global
  gitignore) instead of matching three spellings, so it never appends a
  duplicate line.
- **FR-8 and task 7.** The CHANGELOG states the removal version per
  FR-9, not "2.2" (after the D4 condition).
- **FR-8.** `isSpecPath` admits `.cct-init.json`, which the legacy
  `.code-copilot-team/` prefix used to cover.
- **Scenario 3.** `pi-code doctor` is quiet after a migrate "unless a
  conflict was reported".

Origin: issue #460, the #411 D5 ruling and the owner's 2026-11-18
rulings (origin record). The check-ignore refusal serves the issue's
own concern that committed configuration must not be lost to ignore
rules; it adds no behaviour the issue did not ask for.

## Mismatches

None.

Verdict: aligned
Confidence: high
