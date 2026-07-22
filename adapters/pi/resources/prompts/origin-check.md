---
description: "Run the origin-confirmation circuit breaker for a feature. Validates that the working spec/plan is a faithful realisation of the user's original idea, and surfaces an interactive escalation if it has drifted."
---

Run the origin-confirmation circuit breaker for a feature. Validates that the working spec/plan is a faithful realisation of the user's original idea, and surfaces an interactive escalation if it has drifted.

## When to use this

- Before announcing plan approval (Plan agent / human reviewer).
- As the build agent's first action, before delegating any sub-agent work.
- Before `/phase-complete` (it's already wired into the post-phase
  checklist, but `/origin-check` lets you preview the verdict).
- Any time you suspect a spec has drifted from the user's actual ask.

The full protocol lives in `shared/skills/origin-confirmation/SKILL.md`.

## Argument

`$ARGUMENTS` — the `feature_id` of the spec under
`specs/<feature_id>/` or `specs/pitches/<feature_id>/`. If empty, ask
the user which feature to check before proceeding.

## Procedure

1. **Check the script.** Run
   `bash scripts/check-origin-alignment.sh "$ARGUMENTS"`. Capture both
   the exit code and the printed message.

2. **If exit 0** — proceed clean. Tell the user the feature is aligned
   and stop.

3. **If exit 1** — proceed with warning. Tell the user the alignment
   record's confidence is medium/low and recommend re-running the
   alignment-check protocol with full origin sources read into
   context.

4. **If exit 4** — there's no alignment record yet, or the latest one
   is older than the most recent edit to `plan.md` / `spec.md`. Run
   the `origin_alignment_check` procedure from
   `shared/skills/origin-confirmation/SKILL.md` end-to-end:

   - Read every link in the `origin:` block of
     `specs/<feature_id>/plan.md` (issue body via
     `gh issue view`, URLs via `WebFetch`, transcripts from disk).
   - State the origin claim verbatim (quote the `origin_claim`
     paragraph or the strongest origin sentence).
   - State the working claim (one paragraph derived from the current
     `spec.md`).
   - List concrete mismatches as bullets, or `none`.
   - Render the verdict block.
   - Append the block to
     `specs/<feature_id>/origin-alignment-<YYYY-MM-DD-HHMM>.md`
     (one file per gate firing — append-only).
   - Re-run the script. Report the new exit code.

5. **If exit 2 or 3** — escalate to the user via
   `AskUserQuestion`. Use these three options exactly, in this order,
   with no fourth option:

   - **A) Rescope the working spec to match the origin** — revise
     `specs/<feature_id>/spec.md` and `plan.md` so they match the
     origin; re-run `/origin-check <feature_id>`; resume only after
     verdict=aligned.
   - **B) Restart from origin** — close the current PR/branch; open a
     fresh branch with a new spec written directly from the origin;
     existing branch's code can be cherry-picked but not merged as the
     feature delivery.
   - **C) Document the divergence as deliberate** — write
     `specs/<feature_id>/origin-divergence.md` explaining why the
     working artifact intentionally diverges from the origin (often:
     the user changed their mind after the spec was written). Commit
     it. After commit, re-run the script: a divergence file newer
     than the latest alignment record downgrades the verdict to
     proceed-with-warning (exit 1), so the gate stops blocking.
     Reviewers reading the record still see the documented
     divergence and can audit the user's deliberate choice.

   Wait for the user's pick. Do not pick A/B/C on their behalf, and do
   not invent a fourth option ("proceed with warning", "skip the
   gate", "ignore for now"). The whole point of the breaker is that
   the user picks.

6. **If exit 5** — origin frontmatter is missing or malformed. Tell
   the user that `specs/<feature_id>/plan.md` needs an `origin:` block
   per `shared/skills/origin-confirmation/SKILL.md`. Offer to draft
   one based on the issue body / cited references / session
   transcripts, then re-run the script.

## What you must never do

- **Add a fourth option.** "Proceed with warning" on `partial`/
  `derailed` is exactly the failure mode that produced PR #27.
- **Auto-pick a resolution.** No matter how obvious the right answer
  feels, the user picks A/B/C.
- **Skip the script and "judge alignment from memory".** Always run
  the script and let the exit code drive the gate.
