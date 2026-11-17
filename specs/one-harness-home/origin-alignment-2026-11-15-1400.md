# Origin alignment check — one-harness-home (build, FR-2 amended)

Date: 2026-11-14 22:55 EST (host clock). Filed as `2026-11-15-1400` so it
follows the bundle's earlier records, which are dated 2026-11-15; the
checker orders records by name.

Supersedes the 2026-11-15 13:00 record. Written at the end of the build,
after one spec amendment: FR-2 now states that the three installed
scripts that run without a checkout (the harness-stamp hook, the
`claude-code` launcher, `pi-code`) carry a verbatim copy of the bash
resolver block, kept byte-identical by the structure suite, and that
`cct home`, `cct doctor` and the `cct` help print the legacy name on
purpose. The amendment adds no behaviour the issue did not ask for: the
issue wants one rule everywhere, and an installed hook with no checkout
to source from can only have that rule by carrying it.

Origin: issue #411 and the repository at `56c2e5d`, recorded in
`origin/2026-11-15-issue-411-origin.md`. The 12:00 record's mapping
table stands; the 13:00 record's rulings stand.

## Build-time findings against the origin

- Seven readers outside the planning inventory still spelled the legacy
  home (`providers-health.sh`, `routing-cli.sh`, `routing_registry.py`,
  `validate-providers-profile.sh`, `validate-spec.sh`, Pi `cli.ts`,
  Pi `audit.ts`) and two spelled `~/.cct` directly, bypassing the
  fallback (`analytics_layers.py`, `setup_cmd.py`). All nine now go
  through a resolver. The structure guard that should have caught them
  used `\b`, which macOS `git grep -E` does not support; it is fixed and
  the planted-spelling checks prove it bites.
- The peer-review and review-round runners source the bash resolver, so
  `adapters/claude-code/setup.sh` installs `lib/cct-home.sh` beside
  `lib/review-verdict.sh` and both runners refuse with a named file
  when it is missing (same contract as the verdict parser).

## Mismatches

None. The per-project `.code-copilot-team/` directory is unchanged, as
ruled (D5).

Verdict: aligned
Confidence: high
