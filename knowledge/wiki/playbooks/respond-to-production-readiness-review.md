---
page_type: playbook
slug: respond-to-production-readiness-review
title: Respond to a Production-Readiness Review Without Scope Creep
status: stable
last_reviewed: 2026-05-03
sources:
  - issue: gosha70/rlmkit#34
---

# Respond to a Production-Readiness Review Without Scope Creep

## Symptom

Someone (an external reviewer, a stakeholder, a forcing function from
upstream) files an issue or sends a doc that says "before you can
ship, you need: Redis, Postgres, multi-tenancy, fallback routing,
horizontal scale, Kubernetes manifests, …" and lists 20 items.

The temptation is to either (a) accept the bar and try to ship all
20, or (b) reject the review wholesale because most items are
premature.

Both are wrong. The review is usually a useful **forcing function**
that conflates multiple release targets — "first public release,"
"stable single-node," "enterprise/high-concurrency" — into one
checklist. The right response separates them.

The reference instance is RLMKit's reply to
[`gosha70/rlmkit#34`](https://github.com/gosha70/rlmkit/issues/34),
captured in the gitignored doc
`rlmkit doc_internal/responses/issue-34-reply.md`.

## Recovery steps

1. **Acknowledge the review as useful.** Open with one line that
   says the review is a useful forcing function for separating
   release targets. Not flattery — it sets the frame for the rest
   of the response.
2. **Itemize the original list.** Don't paraphrase or compress. If
   the review listed 20 items, the response addresses 20 items by
   reference. Otherwise the responder picks which items to engage
   with and looks evasive.
3. **Bucket each item into one of four categories:**
   - **Already shipped.** State this with a concrete pointer
     (file path, PR number, doc section). One sentence each.
   - **Required for the next release** (the smallest meaningful
     ship). State the deliverable and rough effort.
   - **Out of scope for the next release, tracked for later.**
     State the reason in one sentence — usually "this belongs to
     a different release target."
   - **Disagree.** State the disagreement and the alternative.
     Rare but always allowed; document the reasoning so it's not
     re-litigated.
4. **State the release call explicitly.** "Vnext (first public
   release): ready with caveats once X/Y/Z land. Enterprise:
   separate milestone with its own epic." This is the
   forcing-function the response is creating in return.
5. **Open a follow-up issue for the deferred bucket.** Don't let
   "out of scope for v1.1" become a memory hole. The follow-up
   issue is the home for the larger-scope work; cite it from
   this response.
6. **Land the response, don't hold it.** A 24-hour turnaround on
   a review of this size is a strong signal that the project has
   thought about this. A two-week silence is a signal of disarray
   even if the eventual response is identical.

## Verification

- Every item in the original review is addressed in your response
  (cross-check by grep on the original list).
- Every "already shipped" item has a concrete pointer (file path,
  PR, doc section) — not just "we have that."
- Every "required for next release" item has an effort estimate
  and lands as its own PR with a link back to the response.
- Every "deferred" item has a reason stated in one sentence and
  lives in a follow-up issue.
- The release call distinguishes at least two release targets
  (e.g., "first public release" and "enterprise") — a single-target
  response is a sign the bucketing wasn't done.

## Prevention

- **Frame release targets explicitly in the project's own docs**
  (README "Deployment model & support boundary" section, OPERATIONS
  doc, CHANGELOG headings). When the project's own docs make the
  distinctions, external reviewers tend to file better-bucketed
  reviews.
- **Maintain an explicit "out of scope for v1.X" list** in the
  release notes or a follow-up tracking issue. Reviewers who can
  see the list don't need to re-raise the same items.
- **Treat the response as a doc, not a comment.** Capture it in
  `doc_internal/responses/<issue>.md` *before* posting; that draft
  becomes the artifact a future maintainer can grep when the same
  topic resurfaces.
- **Don't argue inline.** A long comment thread defending a single
  item is a sign that the bucketing was wrong and the item belongs
  in "required" or "deferred" with a reason, not "disagree."

## Related

- [`doc-coverage-audit`](../workflows/doc-coverage-audit.md) —
  the same project-hygiene impulse, applied periodically rather
  than reactively.
- [`spec-driven-development`](../concepts/spec-driven-development.md) —
  the underlying SDD context (release targets are themselves a
  kind of spec boundary).
