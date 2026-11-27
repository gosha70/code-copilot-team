# Origin alignment check — llm-catalog (S3 follow-up, after #547 merged)

Date: 2026-11-27 16:56 EST

Supersedes the 2026-11-27 11:32 record. Since then, #547 merged
(`affac1b`), and the owner ran `cct llm test` on two configured targets
and ruled on what an alias's later test does.

Origin sources: the 11:32 record's, and the owner's runs and ruling of
2026-11-27, recorded in `origin/2026-11-26-s3-rulings.md`, section
"2026-11-27, after #547 merged".

## What the owner asked, and where it stands

| The owner's point | Delivered in |
|---|---|
| "if names differ, record the reported name on the first pass and compare later runs with it" | `scripts/lib/llm-probe.sh`: a reported name that contains the requested one, or is contained in it, passes `model_identity`, and the attempt keeps the reported names as `reported_models` (`scripts/lib/llm-compat.sh` admits the field) |
| The ruling on a later test whose name differs: "Pass, record the new name" | That test passes too, the record takes the new names, and the detail says the alias moved, naming the earlier test and its names |
| S3.7, the configured-target runs | The two runs are recorded in the origin record (the LAN address replaced) and quoted in the PR; `tasks.md` ticks S3.7 and S3.9 and adds S3.10 |

Found in the same paste, and fixed with it: `cct llm list` explained its
STATE column as "unverified: launchable; no compatibility probe exists
yet", untrue since S3. `cct llm list`, `cct llm show` and
`cct harness explain` now give the tested state in their text; their JSON
keeps the static state its schema names.

`spec.md`'s FR-15 S3 notes say the above.

## Mismatches

- **The JSON of list, show and explain keeps the static state.** The tested state reaches JSON through `cct llm compatibility --json`; changing the other forms' `state` would change their schema.
- **Unchanged since the 11:32 record:** managed settings are not read; the stub gateway speaks Anthropic Messages only; a refused credential is an `unavailable` attempt; the native notice for `--continue` prints only where stamps exist.

Verdict: aligned
Confidence: high
