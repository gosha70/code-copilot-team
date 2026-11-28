# Origin alignment check — llm-catalog (S3 follow-up, after #555's review)

Date: 2026-11-27 23:12 EST

Supersedes the 2026-11-27 16:56 record. Since then, the owner forwarded a
review of #555 at `c00ac3b`: one fix before merge, three minor points
to take here or later.

Origin sources: the 16:56 record's, and the review the owner forwarded on
2026-11-27, which this record quotes in part.

## What the review asked, and where it stands

| Point | Delivered in |
|---|---|
| (1) "Reject an empty reported name as `unverifiable`, and require the shorter name to appear as a whole part of the longer one (bounded by start, end or a non-alphanumeric). Add tests for those three." | `scripts/lib/llm-probe.sh`: names are compared by their parts, split at anything not a letter or digit; the shorter list must run whole and in order inside the longer. `octopus-7` and `o` for `opus` fail; an empty name is `unverifiable`, and the detail says so. Three tests, through a new gateway option, `--report-model` |
| (2) "add `launch_state` and `launch_reason` to the JSON and schema" | `cct llm list`, `cct llm show` and `cct harness explain` give them in their JSON, beside the static `state` (`compatibility` in explain's); `shared/schemas/llm-catalog-cli.schema.json` requires them; a test reads them |
| (3) "`cct llm list` went from 1,134 ms to 1,982 ms" | `lcm_state` computes the evidence digests only when a conclusive record needs comparing, for a caller that sets `LCM_LAZY_EVIDENCE`, as list, show and explain do; they no longer resolve the target twice. On this machine: 1,491 ms on master, 2,802 ms at `c00ac3b`, 1,696 ms now |
| (4) "send the run shell's stderr to a file in the probe directory, not `/dev/null`" | `runner-stderr.txt` in the probe's directory, removed with it |

The owner's earlier points stand as the 16:56 record has them.
`spec.md`'s FR-15 S3 notes say the above.

## Mismatches

- **A variant of the requested model still matches.** `gpt-4o-mini` holds `gpt-4o` as whole parts. Name matching cannot tell a variant from a snapshot, and `model_identity` was never proof: an endpoint can report any name.
- **Unchanged since the 16:56 record:** managed settings are not read; the stub gateway speaks Anthropic Messages only; a refused credential is an `unavailable` attempt; the native notice for `--continue` prints only where stamps exist.

Verdict: aligned
Confidence: high
