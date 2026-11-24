# Origin alignment check — llm-catalog (S1: launch plan and read-only surfaces)

Date: 2026-11-23 20:55 EST

Supersedes the 2026-11-23 18:40 record. That record carried the
owner's rulings into the plan of the remaining slices; the reviewer
approved the plan at `1cf9692` (PR #521). This record covers slice S1
as the plan's slice table defines it. `spec.md` gains plan amendment
2, dated, in FR-9. `tasks.md` gains the S1 rows S1.1 to S1.7.
`plan.md` is unchanged.

Origin sources: issue #400 as amended by the owner on 2026-11-10, and
the owner's umbrella comment of 2026-11-20 that lists what is still
owed; the owner's rulings of 2026-11-23
(`origin/2026-11-23-replan-rulings.md`); `plan.md`, "Remaining
slices", row S1 and amendment 2; `spec.md` (approved, with the
launch-first slice); the repository at `3802a47`.

## Plan row S1, and where this slice delivers it

| Plan row S1 | Delivered in |
|---|---|
| The LaunchPlan JSON schema with `env_clear` | `shared/schemas/llm-catalog-cli.schema.json` (`explain`), emitted by `lr_plan_json` in `scripts/lib/llm-resolve.sh`; names only, never a value (FR-7, FR-27) |
| `catalog_digest`, `launch_identity_digest` and `options_digest`, computed read-only | `_lr_digests` in `scripts/lib/llm-resolve.sh`; no credential value is read; the options digest covers `auto_compact_window` (amendment 2) |
| The Claude Code launcher builds its plan through the resolver, argv and environment byte-for-byte as today | `llm_prepare` in `adapters/claude-code/claude-code` calls `lr_resolve`; the 186 launch assertions pass unchanged, and two new ones check that a launch and its explanation agree |
| `cct llm show` and `cct harness explain claude-code --llm <target>` | `scripts/llm-cli.sh`, dispatched by `scripts/cct`; other harnesses are refused "adapter not implemented" |
| `--json` for `list`, `validate`, `show` and `explain`, against the schema | `scripts/llm-cli.sh`; `tests/test-llm-cli.sh` validates every JSON output against the schema |
| `pi-code --llm` refused as "adapter not implemented" | `adapters/pi/bin/pi-code`, exit 3, never forwarded to pi; tested in `tests/test-llm-cli.sh` |
| The supervisor and benchmark suites assert their native launches unchanged | No supervisor, routing or benchmark code changes; their suites pass unchanged (S1.5) |

## Mismatches

None with the origin. The commands that need later slices (`cct llm
compatibility`, `test` and `sessions`; FR-6) are owed to S2, S3 and S4,
as the plan places them. The two departures still in force (1:
unverified targets launch with a notice; 2: resume is not enforced)
are retired by S3 and S4, not by this slice.

Verdict: aligned
Confidence: high
