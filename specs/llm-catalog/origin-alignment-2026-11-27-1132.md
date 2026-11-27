# Origin alignment check — llm-catalog (S3, refuse when hooks are off)

Date: 2026-11-27 11:32 EST

Supersedes the 2026-11-27 10:13 record. Since then, the owner asked at
`1e27311` that the test refuse, not warn, when hooks are off.

Origin sources: the 10:13 record's, and the owner's message of
2026-11-27, recorded in `origin/2026-11-26-s3-rulings.md`, section
"2026-11-27, later: refuse when hooks are off".

## What the owner asked, and where it stands

| The owner's point | Delivered in |
|---|---|
| "Make it refuse and name the cause" | `scripts/llm-cli.sh` `cmd_test`: when `lp_hooks_off` finds hooks off, the test is refused before anything runs, with exit 3 and the cause: the settings file that sets `disableAllHooks`, or `CLAUDE_CODE_SIMPLE` or `CLAUDE_CODE_SAFE_MODE` in its env block or in the environment |
| "with a flag such as --without-guard to proceed" | `--without-guard` runs the test unguarded, with the warning before the run. It never turns the guard off where hooks are on |
| "and add a test" | `tests/test-llm-cli.sh`: a refusal, in text and under `--json`, that names the cause and the flag, with nothing sent to the gateway and no record; the flag's run; the two other causes refused by name |

The earlier points stand as the 10:13 record has them, (3) still waiting
on the owner's runs. `spec.md`'s FR-15 S3 notes say the above.

## Mismatches

- **Managed settings are not read.** A managed policy that turns hooks off would turn the guard off without a refusal. The test's verdict still fails such a run, and the docs say so.
- **Point (3) of the second review waits on the owner's runs against a configured target.**
- **Unchanged since the 10:13 record:** the stub gateway speaks Anthropic Messages only; a refused credential is an `unavailable` attempt; the native notice for `--continue` prints only where stamps exist.

Verdict: aligned
Confidence: high
