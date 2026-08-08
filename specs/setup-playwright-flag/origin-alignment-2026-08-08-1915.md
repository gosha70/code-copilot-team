# Origin Alignment Check — setup-playwright-flag

Date: 2026-08-08 19:15
Trigger: plan.md revised after the user's P1/P2 on PR #219; the previous
record (`origin-alignment-2026-08-08-1830.md`) is stale.

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/212 — in
  particular its acceptance line: "`./scripts/setup.sh --playwright` either
  installs (forwarded) or exits nonzero with guidance".
- The user's P1/P2 on PR #219, both reproduced by them directly.

## Origin claim (the user's P1, verbatim)

> The exact documented command can still silently succeed without installing
> anything. With no detected tools, `setup.sh --playwright` reaches the early
> "No tools detected" exit … before the Playwright compatibility check. I
> reproduced it with an empty `HOME` and restricted `PATH`: exit `0`, "No
> tools detected." This is #212's original acceptance command.

## Working claim

`setup.sh --playwright` with nothing detected now exits 1 naming both ways
to run it; `--playwright` with `--sync` or `--memkernel` is rejected at the
wrapper before any regeneration, using the adapter's own wording; and the
suite asserts the real adapter enforces the same pair, so wrapper and
adapter cannot drift.

## Mismatches

- none against the findings.

Both were mine, and both were the same failure: asserting a behaviour
without exercising the thing that decides it. The `--sync --playwright`
test used an echo-only stub, which has no opinion about flag combinations,
so it "passed" while the real adapter rejected the pair — and I repeated
that claim in the commit message. The suite now runs the real adapter for
that contract.

All six new assertions verified to fail against `37519a9`, including the
issue's exact command: `bare 'setup.sh --playwright' never exits 0 silently
(expected '1', got '0')`.

## Verdict

Verdict: aligned
Confidence: high
