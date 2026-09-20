---
pitch_id: [NNNN-slug]
title: "[Pitch title — short, descriptive]"
appetite: [2w | 4w | 6w]
bet_status: shaping
cycle: ""
circuit_breaker: "[The line we will not cross. e.g. 'If S3 is still uphill at week 3, ship S1+S2 and shelve S3.']"
shaped_by: "[author]"
shaped_date: [YYYY-MM-DD]
---

<!-- Shape-Up pitch. Companion to SDD plan.md/spec.md/tasks.md. -->
<!-- See docs/shape-up-workflow.md for the methodology. -->

# Pitch: [Title]

## Problem

<!-- One paragraph. The raw, unshaped problem. Who hits it, when, and what
     does it cost them today? Avoid solutions here. -->

[2–4 sentences describing the problem.]

## Appetite

<!-- The fixed time-box. Not an estimate — a budget. Scope flexes, time doesn't. -->

**[2w | 4w | 6w]** — [one sentence on why this appetite, not a smaller or larger one]

## Solution shape

<!-- A rough sketch, not a spec. Enough to convince the betting table this fits
     the appetite. Diagrams welcome (fat-marker drawings, flow lines, etc.). -->

[Describe the high-level approach in 1–3 paragraphs. Identify the key elements
the team will build and how they fit together.]

## Scopes

<!-- 3–7 self-contained slices. Each scope is something a single executor can
     pick up and finish without blocking on another scope. Scopes appear on the
     hill chart and get tracked uphill → downhill → done. -->

### S1: [Scope name]

[1–2 sentences. What this scope delivers. Reference any FRs from spec.md if a
spec has been produced.]

### S2: [Scope name]

[…]

### S3: [Scope name]

[…]

<!-- Add S4–S7 as needed. If you need more than 7, the appetite is probably wrong. -->

## Rabbit holes

<!-- Specific things we can imagine going wrong or sucking up time. Name them
     so the team knows to route around them. -->

- **[Rabbit hole]**: [What it is, and the workaround we'll prefer.]
- **[Rabbit hole]**: [What it is, and the workaround we'll prefer.]

## No-gos

<!-- What's explicitly out of scope. Distinct from rabbit holes — these are
     things we *could* build but have decided not to. -->

- No [thing] — [reason]
- No [thing] — [reason]

## Circuit breaker

<!-- Concrete trigger and action. When the appetite is exhausted, what ships,
     what gets shelved, and what gets fixed in cooldown. -->

[Mirror the circuit_breaker line from frontmatter. Add 1–2 sentences of context
on what "exhausted" looks like for this pitch and which scopes are core vs.
trim-able.]

## Bet log

<!-- Filled in as the pitch progresses through bet_status transitions.
     Append-only — do not rewrite history. -->

| Date | bet_status | Note |
|------|------------|------|
| [YYYY-MM-DD] | shaping | Pitch drafted. |
