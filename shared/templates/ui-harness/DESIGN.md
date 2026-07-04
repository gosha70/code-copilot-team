---
# Machine-readable steering (mirror of design/tokens.json — keep in sync).
# The critic and the coding agent read this front-matter as hard constraints.
tokens_source: design/tokens.json
color:
  neutral: "← REPLACE (not slate/zinc)"
  primary: "← REPLACE (one saturated accent, not indigo-600)"
  bg: "{color.semantic.bg}"
  text: "{color.semantic.text-primary}"
typography:
  display: "← REPLACE (real display face, not Inter/Geist)"
  body: "← REPLACE (real body face)"
radius: "← REPLACE (deliberate, not framework default)"
breakpoints: [375, 768, 1440]
---

# DESIGN.md — Design Steering Context

> This file is the committed art-direction boundary for every AI agent touching
> UI in this repo. Fill in every `← REPLACE`/`← UPDATE`. Shipping the placeholders
> unchanged **is** the AI-slop tell. Derive the content with the `design-system`
> skill; verify against it with the `visual-review` skill (`npm run copilot:review`).

## 1. Overview — Brand & archetype
- **Product**: ← UPDATE (what it is, who it's for, in 2–3 sentences).
- **Primary archetype / secondary**: ← UPDATE (e.g. Sage + Creator). Drives visual semiotics.
- **Tone**: ← UPDATE (e.g. "focused and quiet; no celebratory animation").
- **Information density**: ← UPDATE (compact data app / generous marketing / balanced).

## 2. Design principles (3–5, opinionated)
- ← UPDATE (e.g. "clarity over density"; "high contrast for data views"; "motion sparingly").

## 3. Colors
Use semantic tokens (`design/tokens.json`) — never hardcode hex in components.
- **Neutral**: ← REPLACE (distinct, not slate/zinc). When to use.
- **Brand/accent**: ← REPLACE (one saturated accent, ≤10% visual load). When NOT to use.
- **Semantic**: success / warning / danger / info.
- **Gradients**: banned on text, card borders, and backgrounds unless explicitly art-directed.

## 4. Typography
- **Pairing**: ← REPLACE display + body (not Inter/Poppins/Geist/Space Grotesk). Rationale.
- **Scale**: modular (cap ~5–7 sizes). Body line-height 1.4–1.6; headings 1.1–1.25.
- **Hierarchy**: distinct weight/size/color per level.

## 5. Layout & spacing
- **Grid**: ← UPDATE (e.g. master–detail split, or asymmetric dashboard grid). **No lone centered column** on app surfaces.
- **Spacing**: 4/8pt scale; internal ≤ external spacing; whitespace restraint on dense views.

## 6. Elevation & depth
- ← UPDATE (border **or** shadow as the card vocabulary — not both).

## 7. Radius / shape
- ← REPLACE one radius vocabulary site-wide.

## 8. Components — composition grammar
- ← UPDATE how primitives combine for *this* product (the "wrong composition" is the top failure). No card-in-card.

## 9. States (required — non-negotiable)
Every data-bearing component ships: **empty** (helpful, actionable — not a blank box),
**loading** (skeleton matching final layout — not a spinner/"loading…"), **error**
(inline, accessible), **success**, **disabled**, **focus** (visible ≥2px ring).

## 10. Responsive behavior
- Breakpoints 375 / 768 / 1440. ← UPDATE intent per breakpoint.

## 11. Do's & Don'ts  ← the anti-slop filter (highest-value section)
**Don't:**
- ❌ default indigo/violet/purple accent, or default slate/zinc neutral.
- ❌ centered hero + badge-above-H1 + "1·2·3" steps + exactly 3 feature cards + logo strip.
- ❌ `shadow-xl`/`rounded-3xl` on every card; card-in-card ("cardocalypse").
- ❌ colored 3–4px left-border strips.
- ❌ emoji as iconography; giant centered icon above a heading.
- ❌ glassmorphism / floating gradient orbs / neon glowing borders unless art-directed.
- ❌ `<div onClick>` — use semantic HTML + ARIA.
- ❌ "Empower your team to unlock productivity" copy; lorem ipsum / "Item 1, 2, 3".
**Do:** ← UPDATE product-specific do's.

## 12. Agent prompt guide
Before writing any component: read this file + `design/tokens.json`; wire semantic
tokens into `tokens.css`; build within the layout grammar (§5); ship all states
(§9); then run `npm run copilot:review` and fix every finding in
`tmp/ui-review/critique-feedback.json` until it passes.
