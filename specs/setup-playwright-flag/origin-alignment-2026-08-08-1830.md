# Origin Alignment Check — setup-playwright-flag

Date: 2026-08-08 18:30
Trigger: first alignment record for this feature (gate exit 4).

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/212 (mechanism
  with line references, the two docs that recommend the flag, the accepted
  fixes, and the acceptance criterion).
- The user's instruction: "start …/issues/212".

## Origin claim (verbatim)

> `./scripts/setup.sh --playwright` is **silently ignored**. It is worse than
> a rejection: the flag is accepted and nothing happens. … _Accept:_
> `./scripts/setup.sh --playwright` either installs (forwarded) or exits
> nonzero with guidance; a smoke test asserts non-silent behavior.

## Working claim

The root installer forwards `--playwright` to the claude-code adapter
(verified reaching it, alone and with `--sync`), exits nonzero with a
pointer to the adapter when the resolved tool set cannot carry it, and no
longer swallows any unknown flag as a project directory. Eight assertions
in `tests/test-sync.sh` cover forwarding, the no-phantom-argument case,
both rejection paths, the surviving positional project dir, and `--help`.

## Mismatches

- **Scope widened deliberately**, and flagged here: the issue names
  `--playwright`, but the mechanism it describes — `*)` assigning unknown
  args to `PROJECT_DIR` — silently mis-handles EVERY unknown flag, including
  a misspelled tool flag. Fixing only the named flag would leave the same
  trap for the next one. The issue's own principle ("Never silently
  ignore") is what justifies it.
- The two docs that recommend `setup.sh --playwright` are now correct as
  written, so they are left untouched.

## Verdict

Verdict: aligned
Confidence: high
