# Origin alignment check — pi-project-config (implementation, #469)

Date: 2026-11-18

Supersedes the 1500 record. Two amendments made with the implementation
PR #469, at the owner's request:

- **FR-5 corrected.** `pi-code sync` regenerates the repository's
  managed resources and never reads the project manifest or the project
  configuration, so it needs no change. The draft assumed sync read the
  manifest; the build found it does not. The ownership guarantee (the
  user configuration is never overwritten) holds unchanged.
- **FR-6 extended.** When a legacy `config.local.toml` is present,
  `migrate` first makes sure git ignores `.cct/` and `.cct.local.toml`,
  by the same `git check-ignore` rule as `init` (`--dry-run` only
  reports), so the personal override cannot be committed by accident
  after the rename; and it says so when it keeps `.code-copilot-team/`
  because other files remain.

Origin: issue #460, the #411 D5 ruling and the owner's 2026-11-18
rulings (origin record). Both changes serve the issue's concern that
committed and personal configuration end up where they belong; neither
adds behaviour the issue did not ask for.

## Mismatches

None.

Verdict: aligned
Confidence: high
