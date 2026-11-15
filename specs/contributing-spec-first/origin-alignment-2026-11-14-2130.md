# Origin alignment check — contributing-spec-first (after the #455 review)

Date: 2026-11-14 21:30 EST

Supersedes the 19:00 record. The review of PR #455 at 906faff found two
wording defects, both fixed: the shortcut sentence exempted every bug fix
and single-file change, so the section now limits the `spec_mode: none`
path to non-security bug fixes, documentation-only and trivial changes
and classifies everything else by risk, as the spec-workflow table does;
and the artifact list now states the exact mapping per mode (`none` =
`plan.md`; `lightweight` = `plan.md` + `spec.md`; `full` = `plan.md` +
`spec.md` + `tasks.md`). Both corrections serve #441's purpose, which is
that implementation never starts under the wrong spec mode.

Origin: issue #441 (body as of 2026-11-14, no comments). The 19:00
record's mapping table stands; the missing-label deviation is unchanged.

Verdict: aligned
Confidence: high
