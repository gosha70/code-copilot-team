---
cycle: [NN]
pitch_ids: [list of pitch_ids that ran in this cycle]
appetite: [2w | 4w | 6w]
started: [YYYY-MM-DD]
ended: [YYYY-MM-DD]
outcome: [shipped | partial | shelved]
---

<!-- Generated at the end of a cycle by the cycle-retro agent. -->
<!-- Reads pitch.md, hill.json, and git log to summarize the cycle. -->

# Cycle [NN] Retrospective

## Bets

<!-- One line per pitch that ran in this cycle. Outcome ties back to bet_status. -->

| Pitch | Appetite | Outcome | Final bet_status | Notes |
|-------|----------|---------|-------------------|-------|
| [pitch_id] | [2w/4w/6w] | [shipped/shelved/partial] | [shipped/shelved] | [one line] |

## Hill chart final state

<!-- Per-scope landing position. Pulled from hill.json at end of cycle. -->

### [pitch_id]

| Scope | Final status | Notes |
|-------|--------------|-------|
| S1 — [name] | [done/downhill/uphill] | [one line] |
| S2 — [name] | [done/downhill/uphill] | [one line] |

## What worked

<!-- 2–4 bullets. Concrete things — a specific decision, a specific tool use,
     a specific scope structure that paid off. Avoid generic praise. -->

- [Specific thing]
- [Specific thing]

## What didn't

<!-- 2–4 bullets. Things that cost time or surprised us. Each should imply a
     change for next cycle. -->

- [Specific thing] — [implication for next cycle]
- [Specific thing] — [implication for next cycle]

## Circuit breaker activations

<!-- Did any pitch hit its circuit breaker? If so, what did we ship vs. shelve? -->

- [pitch_id]: [hit / not hit]. [If hit: what shipped, what was shelved.]

## Carryover into cooldown

<!-- Bug fixes, polish, scope cleanup that should land in the next cooldown. -->

- [ ] [Item] — [pitch_id, scope]
- [ ] [Item]

## Inputs to next betting table

<!-- New pitches, sharpened pitches, or shelved-but-promising ideas worth
     re-shaping. Concrete pointers, not aspirations. -->

- [Pitch idea] — [why it's a candidate, expected appetite]
- [Pitch idea] — [why it's a candidate, expected appetite]
