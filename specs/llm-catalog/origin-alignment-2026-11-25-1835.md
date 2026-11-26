# Origin alignment check — llm-catalog (S4, after the owner's review)

Date: 2026-11-25 18:35 EST

Supersedes the 2026-11-25 17:31 record (S4). Since that record, PR #539
opened at `62ffc0a`, and the owner returned it with a gap a reviewer
reproduced against the real Claude Code 2.1.332: `--resume <id>` beside a
single-dash cluster such as `-cd` passed S4's checks, while Claude Code
read the cluster as `-c` and continued another session.

Origin sources: the 17:31 record's, and the owner's message on #539 of
2026-11-25, quoted in `origin/2026-11-25-s4-rulings.md`.

## What changed, and where the origin stands

| Origin | Delivered in |
|---|---|
| The owner on #539: read single-dash clusters by their letters (`c` is `--continue`, `r` a resume without an id) in `lss_classify`, `llm_resume_id` and `llm_resume_unpinned` | `scripts/lib/llm-sessions.sh`; the launcher's `llm_resume_override` and `llm_named_resume_id`, which those two now use |
| The owner on #539: `-cp`, `-pc` and `-cd` beside `--resume <id>`, with `--llm` and without: refused, nothing run, no stamp refreshed | `llm_restore_target` refuses a stamped session named beside a flag Claude Code acts on first; `tests/test-llm-launch.sh` runs all six cases and checks the stamp and that nothing was typed |
| The owner on #539: the capture records Claude Code refusing `--session-id` beside `--continue` or `--resume` without `--fork-session` | `verification/capture-claude.sh`, sections 7 and 8 of its record for 2.1.332; D9's note |
| The owner on #539: an issue for the 71 older variables | filed separately; not part of this slice |

`spec.md`'s FR-18 and D9 notes say the above. The long form,
`--resume <id> --continue` without `--llm`, of a stamped session, is now
refused like the clusters, where the 17:31 state ran it natively with a
notice: the same case, written another way.

## Mismatches

The one departure from the approved text is unchanged and accepted by the
owner on 2026-11-25: the native notice for `--continue` and the picker
prints only where stamps exist (FR-18). Nothing else departs from the
origin.

Verdict: aligned
Confidence: high
