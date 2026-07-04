Perform a full UI-Enhancement review against the committed design steering:
1. As Design Engineer: confirm `DESIGN.md` + `design/tokens.json` exist and every `← REPLACE`/`← UPDATE` is filled (no placeholder tokens shipped).
2. As QA: run `npm run copilot:review` — boots the app, runs the axe-core WCAG 2.2 AA gate, the anti-slop rubric, and captures screenshots at 375/768/1440.
3. As Design Engineer: read `tmp/ui-review/*.png` and score against the `visual-review` rubric (typography, spacing, color, hierarchy, states, anti-slop flags, domain fit).
4. As Frontend Developer: address every finding in `tmp/ui-review/critique-feedback.json`; re-run. Iterate ≤3, then hand residual [Medium]/[Nitpick] items to the human.
5. As Team Lead: summarize verdict (PASS/FAIL per gate) with action items.
