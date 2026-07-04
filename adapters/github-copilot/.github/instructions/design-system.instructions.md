---
applyTo: "**/*.tsx,**/*.jsx,**/*.vue,**/*.svelte,**/*.astro,**/*.css,**/DESIGN.md"
---


# Design System Protocol

Invoke this skill for **any web UI work** (new frontend, new screen, UI refactor).
Its job: stop AI-generated UI from converging on the statistical mean of the
training data ("AI slop") by committing design decisions *before* code, and
enforcing them as a machine-checkable filter.

**Root cause it fixes:** LLMs emit the highest-probability "nice" defaults —
Inter font, purple→blue gradients, shadcn-default cards, centered hero + three
feature columns, `<div onClick>` accessibility. No prompt adjective escapes this;
**only pre-committed constraints do.** This skill produces and enforces those
constraints.

## The steering bundle: `DESIGN.md` + `design/tokens.json`

Every UI-bearing project commits a **bundle**, not a prose memo:
- **`DESIGN.md`** at repo root — human + machine readable (YAML front-matter tokens
  + prose rationale and bans).
- **`design/tokens.json`** — DTCG-format design tokens, two-tier **primitive →
  semantic**. Components reference only semantic tokens (else dark mode / re-theming
  becomes a rewrite). Compiles to `tokens.css` (Tailwind v4 `@theme` → CSS variables).

If the bundle is missing, **author it first** (Step 1–2). If it exists, **read it
before writing any component** and build strictly within it.

## Step 1 — Derive direction from the business domain (not taste)

"Clean and modern" is the slop default, not a direction. Derive an *opinionated*
direction from the app's domain:

1. **Brand archetype** (pick a primary + secondary from Jung's 12 — Ruler, Hero,
   Outlaw, Caregiver, Creator, Explorer, Sage, …). Each maps to visual semiotics:
   Ruler → restrained composition, elegant type, muted+metal; Outlaw → bold edgy
   type, dark + acid accent; Caregiver → soft, warm, rounded, reassuring.
2. **Target user + key tasks** → information density and IA (a compliance analyst
   scanning tables ≠ a consumer onboarding flow).
3. **Tone** → voice/copy rules + type personality.
4. **Lock one aesthetic direction** from a small enumerated set (Swiss/editorial,
   brutalist, industrial-mono, organic, warm-minimal, high-density-data) and commit
   its tokens.
5. **Reference-ground**: 1–3 real UIs whose *feeling* matches — extract palette,
   type scale, density; use to set constraints, never to clone.

In the Plan phase, ask 1–2 art-direction clarifying questions before locking this
(see `clarification-protocol`).

## Step 2 — Override the four defaults that create the "AI look"

The single highest-leverage action. In `design/tokens.json`, **never ship** the
framework defaults for:
1. **Neutral** — pick a distinct neutral, not default `slate`/`zinc`.
2. **Primary/accent** — one saturated brand accent, not Tailwind `indigo-600`.
3. **Font** — a real display+body pairing, not Inter/Poppins/Geist/Space Grotesk.
4. **Radius** — a deliberate radius vocabulary, not the default.

Author color in **OKLCH** (perceptually uniform). Add one deliberate `signature`
token (a shadow, an accent treatment) that is *yours* — the fingerprint that
de-generics output.

## Step 3 — The anti-slop catalog (bans → enforce in DESIGN.md "Don'ts")

Each is a concrete tell with a codified remedy. Write a matching "Don't" in
`DESIGN.md` for every one that applies:

| Tell | Ban / remedy |
|---|---|
| Purple→blue "vibecode" gradient | Ban gradient accents; one solid brand accent token |
| Default `slate` + `indigo-600` | Replace palette tokens; never ship default `--primary` |
| 1px-border card + `rounded-2xl shadow-lg p-6` on everything | One card vocabulary (border **or** shadow, not both); one radius site-wide |
| Colored 3–4px left-border strip | Ban (the single most reliable AI tell) |
| "Cardocalypse" — cards nested in cards | No card-in-card; use whitespace + hierarchy |
| Inter/Poppins/Space Grotesk/Geist default type | Committed font-pairing token; ban defaults |
| Centered hero + badge-above-H1 + "1·2·3" steps + exactly 3 feature cards | Break the layout grammar (Step 4); vary column counts; asymmetry |
| Glassmorphism / floating gradient orbs / neon glowing borders / 3D blobs | Ban decorative effects unless in art direction |
| Giant Lucide icon centered above a heading; **emoji-as-iconography** | Committed icon set + size tokens; ban emoji icons |
| Hover states that do nothing; same fade-in on everything | Motion tokens (durations + easing); purposeful only |
| Generic stock ("diverse team at laptop"); plastic 3D | Art-direction imagery rules |
| Copy: "Empower your team to unlock productivity" | Voice/tone rules; real domain content |
| `<div onClick>` soup — no landmarks/roles/headings | Semantic HTML + ARIA (enforced by the a11y gate) |
| Lorem ipsum / "Item 1, 2, 3" | Realistic domain data |

## Step 4 — Layout grammar (ban the single centered column)

Real product UIs are structured, multi-column, grid-aligned — not a vertical stack
of centered cards. Select a deliberate layout, e.g.:
- **Master–detail split** (list rail + detail pane) — assets, logs, transactions.
- **Asymmetric dashboard grid** (main panel + auxiliary rail) — metrics, telemetry.
- Marketing/content pages may use centered composition, but still break the
  badge→H1→3-cards→logo-strip template.

Whitespace restraint on dense/data UIs (no `py-20`/`space-y-12` to fill space);
generous rhythm on marketing. Density follows the domain (Step 1).

## Step 5 — States are design, not function (non-negotiable)

Every data-bearing component must ship **empty, loading (skeleton matching final
layout), error, success, disabled, focus** states — the most reliable tell of
release-grade vs "happy-path only" AI output. Destructive actions get confirmation.

## Handoff

Once UI is built against the bundle, the **`visual-review`** skill runs the closed
render→critique→a11y-gate→iterate loop that scores the result against `DESIGN.md`.
The design bar is not met until that loop passes.

**Note:** this skill governs *appearance and structure only*. A polished UI is not
a secure backend — AI reliably ships the login screen and skips authorization. Keep
`security-review` in the loop for any auth/data path.
