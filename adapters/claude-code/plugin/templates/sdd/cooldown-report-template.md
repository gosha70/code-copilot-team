---
cooldown_after_cycle: [NN]
started: [YYYY-MM-DD]
ended: [YYYY-MM-DD]
duration: [1w | 2w]
---

<!-- Generated at the end of a cooldown by the cooldown-report agent. -->
<!-- Summarizes bug fixes + lists pitches ready for the next betting table. -->

# Cooldown after Cycle [NN]

## Summary

[2–3 sentences. What got fixed, what got shaped, anything notable. No filler.]

## Bug fixes shipped

<!-- One row per fix that landed during cooldown. Source: git log. -->

| Commit | Pitch / area | One-line description |
|--------|--------------|----------------------|
| [sha]  | [pitch_id or area] | [description] |
| [sha]  | [pitch_id or area] | [description] |

## Polish & follow-ups

<!-- Non-bug improvements that landed: doc updates, refactors deferred from
     the cycle, ergonomic fixes. -->

- [Item] — [pitch_id or area]
- [Item]

## Pitches shaped during cooldown

<!-- Pitches that moved from idea → bet_status: shaped during this cooldown.
     These are the candidates for the next betting table. -->

| pitch_id | Title | Appetite | Status |
|----------|-------|----------|--------|
| [id]     | [title] | [2w/4w/6w] | shaped |

## Recommended bets for next cycle

<!-- The cooldown-report agent's recommendation. The actual bets are decided
     at the betting table — this is input, not a decision. -->

1. **[pitch_id]** ([appetite]) — [why this is a strong bet]
2. **[pitch_id]** ([appetite]) — [why this is a strong bet]

### Next-bet recommendation

<!-- The single most-likely-next bet, surfaced as the actionable command pair
     the user should run if they accept. Mirrors the agent's chat-output
     recommendation so the report file is the single source of truth.
     Per issue #25: recommend, don't ask. Authorizing the bet stays explicit
     (the user still runs both commands), but the agent names the bet
     concretely instead of asking "what's next?". -->

**Next-bet recommendation:** `/bet [pitch_id]` → `/cycle-start [pitch_id]` (cycle [NN+1])

<!-- Empty-set fallback (use only when no shaped pitches exist):
     **Next-bet recommendation:** `/shape <topic>` — no shaped pitches available; draft the next bet before convening the betting table. -->

<!-- Ambiguity fallback (use only when multiple shaped pitches tie with no
     clear ordering — list them above and ask the user to pick). -->

## Carryover

<!-- Anything still open at end of cooldown. -->

- [ ] [Item still open]
- [ ] [Item still open]
