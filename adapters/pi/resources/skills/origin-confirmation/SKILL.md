---
name: origin-confirmation
description: "Origin-confirmation circuit breaker: machine-checkable origin frontmatter, alignment-check protocol, three gates (plan-approval, build-entry, phase-complete), and interactive escalation on deviation."
---

# Origin-Confirmation Circuit Breaker

Before producing any plan, rubric, evaluation, build, or merge for a
feature, you MUST locate and re-read the **origin artifact** — the
user's original description of the idea — and verify that the working
spec/plan/PR is a faithful realisation of it.

The latest in-repo `spec.md` / `plan.md` is **not** automatically the
origin. Those are derived artifacts that may already be drifting. The
origin lives in the issue body, external references the user has cited,
and the user's own messages.

This skill is always-on. If a session derives an implementation from a
derived spec without re-checking against the origin, that session has
violated this skill.

## Origin frontmatter convention

Every `specs/<feature-id>/plan.md` carries an `origin:` block in YAML
frontmatter. `scripts/validate-spec.sh` enforces it.

```yaml
---
feature_id: example-feature
spec_mode: full | lightweight | none
status: draft | approved
origin:
  # at least one of: issue, urls, transcripts
  issue: gosha70/code-copilot-team#12
  urls:
    - https://gist.github.com/.../llm-wiki     # Karpathy's LLM Wiki gist
    - https://www.mindstudio.com/.../wiki      # MindStudio explainer
  transcripts:
    - specs/example-feature/origin/2026-05-04-user-directive.md
  origin_claim: |
    One paragraph in the user's words: what the user originally asked
    for, before any spec/plan derived artifacts. Quote literally where
    possible. This is the machine-checkable target for the alignment
    check.
---
```

### Escape hatches

Some specs genuinely have no external origin (pure-internal cleanups,
generator refactors, test plumbing). Those use the `internal` exemption:

```yaml
origin:
  type: internal
  reason: "Refactor generator hook ordering — no user-facing behavior change."
```

A few legacy specs may have an origin that we cannot honestly recover.
Those use the `unrecoverable` marker, which exits 5 from the verifier
and surfaces the missing origin to anyone who touches the spec next:

```yaml
origin:
  type: unrecoverable
  note: "Pre-dates origin-confirmation breaker; original session memory lost."
```

## Alignment-check protocol — `origin_alignment_check`

Run this procedure at every gate. It produces a structured **alignment
record** that the verifier script reads to decide whether to proceed.

1. **Read every origin link into context.**
   - For `issue: <repo>#N`: fetch the issue body via `gh issue view N`
     or read the linked transcript.
   - For `urls:`: fetch each URL (`curl -fsSL`, with caching) and read
     it. Do not paraphrase from memory or training data.
   - For `transcripts:`: read each file under
     `specs/<id>/origin/<date>-<slug>.md`.

2. **State the origin claim.** Quote the `origin_claim` paragraph
   verbatim. If `origin_claim` is missing, derive it from the origin
   sources and quote the strongest verbatim sentence available.

3. **State the working claim.** One paragraph derived from the current
   `spec.md` (or `plan.md` when no spec.md exists), describing what the
   working artifact actually delivers — feature shape, scope, surface,
   data flow.

4. **List concrete mismatches.** Each bullet names a specific feature,
   operation, surface, or data path that the origin requires but the
   working artifact does not deliver, or vice versa. If the working
   artifact is a faithful realisation of the origin, write `none`.

5. **Render the verdict block.** Append to
   `specs/<feature-id>/origin-alignment-<YYYY-MM-DD-HHMM>.md`:

   ```
   # Origin alignment check — <feature-id>

   Origin: <link or path to the strongest origin source>

   Origin claim:
   > <one-paragraph quote>

   Working claim:
   > <one-paragraph derivation>

   Mismatches:
     - <bullet> | none

   Verdict: aligned | partial | derailed
   Confidence: high | medium | low
   ```

   Verdict semantics:
   - **aligned** — every requirement in the origin maps onto a delivered
     part of the working artifact. Surface, scope, and shape match.
   - **partial** — the working artifact delivers a strict subset of the
     origin. Some required features are missing or scope is reduced
     without explicit user approval.
   - **derailed** — the working artifact delivers something
     fundamentally different from the origin (different surface,
     different data flow, different output target). PR #27 was
     derailed against issue #12 + Karpathy's gist.

   Confidence semantics:
   - **high** — origin links read in full this session; mismatches
     enumerated exhaustively.
   - **medium** — most origin links read; one or two skimmed.
   - **low** — origin reconstructed from `origin_claim` only without
     refreshing the linked sources. Acceptable only when the linked
     sources are unavailable.

6. **Run the verifier script.**
   `scripts/check-origin-alignment.sh <feature-id>`. Exit code drives
   the gate's decision (see § Gates below).

## Three gates

The breaker fires at three points where derailment historically
happens. Each gate must run the `origin_alignment_check` procedure
above (or trust an existing fresh record) and act on the verdict.

### Gate 1 — plan approval

The planning agent (or human) runs `/origin-check <feature-id>` before
announcing plan approval. The slash command runs the protocol and the
verifier script. Acceptable verdicts: `aligned, high`. `aligned, medium`
or `low` proceed with a recorded warning. Anything else escalates.

### Gate 2 — build entry

The build agent's **first action**, before delegating any sub-agent
work, is `scripts/check-origin-alignment.sh <feature-id>`. Exit 0 or 1
proceeds. Exit ≥ 2 halts before delegation and surfaces the escalation
to the user.

### Gate 3 — phase complete

`/phase-complete` calls the verifier script after gathering context and
before checking the peer-review loop. Exit ≥ 2 aborts the command with
the escalation prompt — even if peer review has already passed. Peer
review scores implementation quality; this gate scores origin alignment.
The two are independent.

## Interactive escalation

When the breaker fires (verdict `partial` / `derailed` or missing
record), the active session **must** surface a prompt with exactly
three resolutions. **No fourth option. No silent proceed.**

```
Origin alignment check — <feature-id>: <verdict>
Mismatches:
  - <bullet>
  - <bullet>

How do you want to resolve this?

  A) Rescope the working spec to match the origin
     → revise specs/<id>/spec.md and plan.md to align with the origin;
       re-run the alignment check; resume only after verdict=aligned.

  B) Restart from origin
     → close the current PR/branch; open a fresh branch with a new spec
       written directly from the origin; the existing branch's code
       can be cherry-picked but not merged as the feature delivery.

  C) Document the divergence as deliberate
     → write specs/<id>/origin-divergence.md explaining why the working
       artifact intentionally diverges from the origin (often: the user
       changed their mind after the spec was written). Commit it. The
       verifier then treats a fresh divergence file (newer than the
       latest alignment record) as proceed-with-warning (exit 1), so the
       gate stops blocking. If the spec drifts FURTHER after the
       divergence is committed, a new alignment record is produced and
       the user must update the divergence (or pick A/B) before the
       gate releases again.
```

For Claude Code, render this as `AskUserQuestion`. For other adapters
(Codex, Cursor, GitHub Copilot, Windsurf, Aider) without a structured
question primitive, render the same three options as plain-text and
wait for the user's pick. Same labels, same semantics.

## What you must never do

- **Treat `spec.md` / `plan.md` as the origin.** They are derived. The
  origin lives in the issue body, external references, and user
  messages.
- **Auto-resolve a deviation.** When the verifier exits ≥ 2, you stop
  and ask. Never pick A/B/C on the user's behalf, regardless of how
  obvious the right answer feels.
- **Add a fourth option.** "Proceed with warning" is not an option for
  `partial`/`derailed` verdicts — that is exactly the failure mode that
  produced PR #27.
- **Bypass via flag or env var.** No `--no-origin-check`, no
  `CCT_SKIP_ORIGIN_GATE`. The only legitimate bypass is option C
  (committed `origin-divergence.md`), which is auditable in git history.
- **Edit the `origin:` block in a non-amendment commit.** The origin is
  immutable except via a commit whose subject begins with
  `origin-amendment:`. Other commits that touch the block fail
  validation. This catches origin drift at review time.

## Why this skill exists

PR #27 (`feat/wiki-ingest-pipeline`) shipped a "guarded page-draft
generator" while the user's actual origin (issue #12 + Karpathy's LLM
Wiki gist + linked MindStudio explainers) called for a wiki maintainer
with three operations (ingest-updates-existing-wiki / query /
knowledge-health lint). Three roles failed in sequence: the planner
treated `specs/wiki-ingest-pipeline/spec.md` as authoritative without
re-reading the origin; the builder built faithfully against the
derived spec; the reviewer scored implementation quality of an off-spec
artifact and a dogfood A/B rubric measured the wrong feature. Detection
came from a third-party external review, not from the assistant team.
This skill makes that failure mode architecturally impossible to
repeat: structured origin, three gates, interactive escalation, no
silent bypass.
