# Origin alignment check — llm-catalog (S5: project policy)

Date: 2026-11-23 22:05 EST

Supersedes the 2026-11-23 20:55 record (S1), on which this slice is
built; it does not depend on S2. This record covers slice S5 as the
plan's slice table defines it. `spec.md` gains plan amendments 1 and 5,
dated, in FR-24. `tasks.md` gains the S5 rows S5.1 to S5.5. `plan.md` is
unchanged.

Origin sources: issue #400 as amended by the owner on 2026-11-10, and
the owner's umbrella comment of 2026-11-20; the owner's rulings of
2026-11-23 (`origin/2026-11-23-replan-rulings.md`), ruling (4) above
all: "`[llm].allowed` is read from `.cct.toml` only: not the local file
and not the legacy config. S5 also teaches Pi's config lint the `[llm]`
table. Add a fifth spec change: `.cct.toml` is read by Claude Code
launches as well as Pi"; `plan.md`, "Remaining slices", row S5 and
amendments 1 and 5; `spec.md` (FR-24, D13); the repository at S1's head.

## The owner's ruling (4) and plan row S5, and where this slice delivers them

| Ruling / plan row S5 | Delivered in |
|---|---|
| `[llm].allowed` (FR-24, D13) | `lc_project_policy` in `scripts/lib/llm-catalog.sh`: `allowed` only; any other key, the table written another way, a malformed list or entry, refused by name ("projects restrict, never grant") |
| Read from `.cct.toml` only: not `.cct.local.toml`, not the legacy config (amendment 1) | the reader opens `<project root>/.cct.toml` alone; tested with both other files present and restricting |
| Claude Code launches read `.cct.toml` (amendment 5) | `llm_prepare` passes its launch directory to `lr_resolve`, which applies the policy; `cct harness explain --project` applies the same |
| ... by `pi-code` as well | `pi-code --llm` is refused until S7 (S1); the resolver it will use applies the policy already |
| Pi's config lint learns the `[llm]` table | `adapters/pi/runtime/config/lint.ts`: `llm.allowed` known, any other `llm.*` key a `refused` error; `scripts/validate-cct-config.sh` counts it |
| A launch without `--llm` is unchanged (FR-27) | the policy is read only inside `llm_prepare`; tested with a `.cct.toml` whose `[llm]` table is refused |

## Mismatches

None with the origin. Restored stamps are narrowed by the same list
when S4's resume rules land, as FR-24 says; until then no stamp exists.

Verdict: aligned
Confidence: high
