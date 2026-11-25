# Origin alignment check — llm-catalog (S4)

Date: 2026-11-25 17:31 EST

Supersedes the 2026-11-24 14:33 record (S5) for this branch. This record
covers slice S4 as this branch delivers it: the stamps of Claude Code
launches with `--llm`, resume by exact id, and `cct llm sessions`.

Origin sources: issue #400 as amended by the owner on 2026-11-10; the
owner's rulings of 2026-11-23 (`origin/2026-11-23-replan-rulings.md`),
which order S4 before S3 and ask for re-runnable captures; the owner's
rulings and acceptance of 2026-11-25 (`origin/2026-11-25-s4-rulings.md`);
issue #536; `plan.md`, "Remaining slices", row S4 and amendment 4;
`spec.md`, FR-6, FR-17 to FR-20, FR-30 and D9.

## What the slice delivers, against the origin

| Origin | Delivered in |
|---|---|
| D9 and the owner's ruling: CCT owns the session id | the launcher generates every `--llm` session's id and passes `--session-id`; a `--session-id` given with `--llm` is refused, saying to drop it (accepted 2026-11-25) |
| FR-17: a stamp before the harness runs, promoted only from the harness's own evidence | `scripts/lib/llm-sessions.sh`; promotion from Claude Code's transcript, at a resume by id or by `cct llm sessions`, never from an API error or a fork's copied history |
| FR-18 and the owner's points 1 to 6 | `lss_classify` and `lss_rules`, reading the flags in Claude Code's own order; the launcher's restore; the refusal of an unstamped session resumed with `--llm` names the ways out (accepted 2026-11-25) |
| FR-19: the restored target resolved again; an identity change refused, a tuning change said | `lss_rules`; `tests/test-llm-launch.sh` |
| FR-6 and the owner's point 7: `cct llm sessions [--harness <h>] [--project <dir>]` | `cmd_sessions` in `scripts/llm-cli.sh`, eligibility by the launcher's own checks in its order; the schema's `sessions` form |
| FR-20: the minimum version the #399 work recorded; plan amendment 4 | `shared/llm/compat-rules.json` (`min_version` 2.1.305, rule version 2); `verification/capture-claude.sh` and its record for 2.1.332 |
| D-S4-env | no name added to the clear-list; the PR lists the 30 new variables, each with the reason it stays off |

## Mismatches

One departure from the approved text, accepted by the owner on
2026-11-25 and recorded in FR-18: the native notice for `--continue` and
the picker prints only where stamps exist, so a launcher that never used
`--llm` stays as it was (FR-11, FR-27). Nothing else departs from the
origin.

Verdict: aligned
Confidence: high
