---
spec_mode: none
feature_id: review-round-ceiling
risk_category: bugfix
justification: |
  Non-security bug fix (#227): three defects that make the max_rounds
  breaker a dead end. Per-attempt round budget, config wiring, and a
  stable staleness key; no new surface.
status: approved
date: 2026-08-09
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/227
  origin_claim: |
    Bug #227: "max_rounds breaker is a dead end: /review-decide retry can't
    resolve it, review.max_rounds is dead config, stale-finding breaker
    defeated by rewording". (1) Round numbering is monotonic, so with
    current_round=5 and MAX_ROUNDS=5, retry re-trips the breaker before the
    reviewer is invoked. (2) review.max_rounds ships in the template but the
    driver only ever sets CCT_REVIEW_MAX_ROUNDS for the advisory pass, so
    the gating loop always uses the runner's default. (3) Finding ids hash
    the description, so a reviewer that rewords produces fresh ids and
    consecutive_fixed never increments — the stale breaker never fires.
---

# Plan: the round budget is per attempt (#227)

**D1.** The ceiling now counts rounds IN THE CURRENT ATTEMPT, so monotonic
numbering and a bounded budget stop contradicting each other. The anchor is
maintained by the runner rather than by `/review-decide`: requiring a slash
command to write `attempt_start_round` would put a safety invariant in a
model's hands. Two signals set it — a change in `attempt` since the last
completed round, and `attempt > 1` with no anchor at all, which is what a
retry looks like because the breaker exits before state is rewritten.
Legacy state with neither signal keeps the old cumulative behaviour rather
than silently forgiving a spent budget.

**D2.** `review.max_rounds` is read by the driver and passed to the gating
round, with `CCT_REVIEW_MAX_ROUNDS` still winning. Same fix as #205's
`loop_timeout_sec`, and the same defect class: config surfaced in the
template but never wired.

**D3.** Staleness is bucketed by `(file, category)` — a `repeat_key` that
ignores prose — while finding ids keep hashing the description, because
dispositions are keyed by id and that contract is unchanged. A reviewer
that restates the same defect in new words now increments the bucket's
`consecutive_fixed`, so `on_stale_finding` engages instead of the loop
reading N fresh findings per round.

## Not changed

Finding-id derivation. Ids identify a specific worded finding for
disposition purposes; making them fuzzy would break that mapping. The
recurrence signal is a separate, coarser key.
