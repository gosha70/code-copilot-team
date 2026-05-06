---
page_type: workflow
slug: origin-alignment
title: Run the Origin-Alignment Gate
status: stable
last_reviewed: 2026-05-06
sources:
  - pr: 27
  - url: https://gist.github.com/karpathy/3ef5df0e1ee5d36d59b29eb91f8d35c1
    retrieved: 2026-05-06
  - issue: 12
---

# Run the Origin-Alignment Gate

## When to use this

Run the origin-alignment gate at three points in any feature's life:

1. **Plan approval** — before announcing that a plan is approved.
2. **Build entry** — as the build agent's first action, before
   delegating any sub-agent work.
3. **Phase completion** — `/phase-complete` runs the gate
   automatically; you do not need to invoke it manually there, but
   you can preview the verdict ahead of time with
   `/origin-check <feature-id>`.

The gate exists because of the PR #27 derailment: the wiki-ingest-pipeline
branch shipped a "guarded page-draft generator" while the user's
actual origin (issue #12 + Karpathy's LLM Wiki gist) called for a
wiki maintainer with three operations. Detection came from a
third-party external review, not from the assistant team. Running
this gate would have caught the drift on the planner's first pass.

## Procedure

### 1. Verify origin frontmatter exists

The feature's `specs/<feature-id>/plan.md` must carry an `origin:`
block. If it does not, `scripts/check-origin-alignment.sh` exits 5
and you cannot proceed. Author or amend the block per the convention
documented in [`../schema/page-types.md`](../schema/page-types.md)
and the [`origin-confirmation` skill](../../../shared/skills/origin-confirmation/SKILL.md).

### 2. Read every origin source into context

For each `issue`, URL, and transcript listed under `origin:`:

- `issue: <repo>#N` — `gh issue view N --repo <repo>` and read the
  body in full.
- `urls:` — fetch each URL (`curl -fsSL` with caching, or `WebFetch`
  in Claude Code) and read it. Do not paraphrase from training-data
  memory.
- `transcripts:` — read each file under
  `specs/<feature-id>/origin/<date>-<slug>.md`.

Skipping this step degrades the verdict's confidence to `low` at
best. The breaker still passes (exit 1), but reviewers reading the
alignment record see the lower confidence and may push back.

### 3. Produce the alignment block

Append a new file at
`specs/<feature-id>/origin-alignment-<YYYY-MM-DD-HHMM>.md` with:

```
# Origin alignment check — <feature-id>

Origin: <link or path to the strongest origin source>

Origin claim:
> <one-paragraph quote from the origin>

Working claim:
> <one-paragraph derivation from current spec.md / plan.md>

Mismatches:
  - <bullet> | none

Verdict: aligned | partial | derailed
Confidence: high | medium | low
```

Files are append-only. One per gate firing — never overwrite a
prior record. The verifier script picks the lexicographically
latest filename, so the timestamped naming convention orders
records chronologically.

### 4. Run the verifier script

```
bash scripts/check-origin-alignment.sh <feature-id>
```

Map the exit code to a decision:

| Exit | Meaning | Decision |
|------|---------|----------|
| 0 | aligned, high | Proceed clean. |
| 1 | aligned, medium/low — OR partial/derailed with a fresh committed `origin-divergence.md` | Proceed with a recorded warning. |
| 2 | partial | Stop. Surface the three-resolution escalation. |
| 3 | derailed | Stop. Surface the three-resolution escalation. |
| 4 | missing or stale alignment record | Re-run step 3, then re-run the script. |
| 5 | origin frontmatter missing or malformed | Author or amend the `origin:` block, then re-run. |

### 5. On exit ≥ 2, surface the escalation

The verifier prints the resolution menu in its error output. The
slash command (in Claude Code) renders it as `AskUserQuestion`. In
other adapters, present the same three options as plain text:

- **A) Rescope the working spec to match the origin.**
- **B) Restart from origin** (close the current PR, start fresh).
- **C) Document the divergence as deliberate**
  (`specs/<feature-id>/origin-divergence.md`). Commit the file. On
  the next run, the verifier sees the divergence is newer than the
  latest alignment record and exits 1 (proceed with warning) instead
  of 2/3 — the gate stops blocking, but reviewers reading the record
  still see the documented divergence.

There is no fourth option. There is no silent "proceed with warning"
that bypasses the record. The user — not the assistant — picks the
resolution.

## Verification

To confirm the gate is wired correctly in your environment:

- `bash scripts/check-origin-alignment.sh origin-confirmation-circuit-breaker`
  exits 0 (the breaker satisfies its own gate).
- `bash scripts/check-origin-alignment.sh some-spec-without-origin`
  exits 5 with a pointer to the missing frontmatter.
- `bash tests/test-origin-alignment.sh` exits 0 (15 fixture cases
  cover all six exit codes).

## Related

- [`shared/skills/origin-confirmation/SKILL.md`](../../../shared/skills/origin-confirmation/SKILL.md)
  — the full skill body the protocol comes from.
- [`promote-lesson-to-wiki.md`](promote-lesson-to-wiki.md) — the
  curator workflow that runs after a lesson is approved.
- [`specs/origin-confirmation-circuit-breaker/spec.md`](../../../specs/origin-confirmation-circuit-breaker/spec.md)
  — the spec for the breaker itself.
