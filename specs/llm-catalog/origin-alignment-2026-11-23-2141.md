# Origin alignment check — llm-catalog (S2: compatibility, read-only)

Date: 2026-11-23 21:41 EST

Supersedes the 2026-11-23 20:55 record (S1). This record covers slice S2
as the plan's slice table defines it, built on S1's resolver and S0's
captures. `spec.md` gains plan amendment 3, dated in FR-14, and one
departure in FR-29, dated and put to the owner for a ruling. `tasks.md` gains the S2 rows S2.1 to S2.6. `plan.md` is
unchanged.

Origin sources: issue #400 as amended by the owner on 2026-11-10, and
the owner's umbrella comment of 2026-11-20 that lists what is still
owed; the owner's rulings of 2026-11-23
(`origin/2026-11-23-replan-rulings.md`); `plan.md`, "Remaining
slices", row S2 and amendment 3; `spec.md` (approved, with the
launch-first slice); S0's captures (`verification/codex-capture.md`,
`verification/pi-capture.md`); the repository at S1's head.

## Plan row S2, and where this slice delivers it

| Plan row S2 | Delivered in |
|---|---|
| The state-file primitives (FR-29) with their tests | `scripts/lib/cct-statefile.sh`, `tests/test-cct-statefile.sh` (a killed lock holder followed by a successful writer, a TERM mid-write, concurrent writers, every stale-lock rule, symlink refusal, modes) |
| The rule table as data (FR-14), with the S0 facts and departure 3 | `shared/llm/compat-rules.json`, versioned and pinned; Codex `openai-responses` only and Pi all three protocols, from S0; Claude Code may use a managed provider (amendment 3) |
| The five states (FR-13) keyed by the evidence digest | `lcm_state` in `scripts/lib/llm-compat.sh`; the digest is FR-9's (launch identity, options, harness version, rule version), and the reason names what changed |
| Two-part records (FR-16) | `latest_attempt` and `latest_conclusive` under `llm-compat/<harness>/<llm>@<binding>.json`, written through `sf_update`; only a pass or a behavioral fail replaces the conclusive part |
| `cct llm compatibility [--json]` | `scripts/llm-cli.sh`, its schema in `shared/schemas/llm-catalog-cli.schema.json` |
| `cct doctor`'s LLM catalog section (FR-28) | `check_llm_catalog` in `scripts/lib/cct_doctor.py`, delegating to `cct llm` |
| Launches do not change | No launcher change; the launch suites pass unchanged (188, 43) |

## Mismatches

One departure from the approved text, recorded in FR-29 for the owner's
ruling: the lock directory is used on every host, never `flock`,
because a host holding `flock` and a host using a lock directory would
not exclude each other on a shared home directory. Nothing else departs
from the origin. The probe that writes records, and launches gated on
the states, are owed to S3, as the plan places them; FR-14's condition
for Codex `openai-chat` is unmet by S0's capture, so the table omits it.

Verdict: aligned
Confidence: high
