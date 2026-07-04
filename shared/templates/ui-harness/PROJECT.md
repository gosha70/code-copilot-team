# UI-Enhancement Harness (Add-On)

An **add-on bundle**, not a standalone project type. It gives any web project a
committed design-steering bundle plus a tool-agnostic visual-review loop that stops
AI-generated UI from converging on the generic "AI look." Layer it on top of a web
template (e.g. `web-dynamic`, `web-static`) or any existing frontend.

## What it ships

```
DESIGN.md            # committed art-direction steering (prose + machine-readable front-matter)
design/tokens.json   # DTCG design tokens (primitive → semantic); override the framework defaults
harness/             # tool-agnostic visual-review runner (any copilot can run it)
  package.json       # scripts: harness:init, harness:verify
  src/runner.ts      # orchestrator: boot → axe gate → anti-slop rubric → screenshot → pluggable critic
  src/audit.ts       # @axe-core/playwright WCAG 2.2 AA gate (zero critical to pass)
  src/rubric.ts      # deterministic anti-slop pre-filter (emoji-icon, default tokens, no landmarks, …)
```

## Scaffold it into a project

The bundle is installed at `~/.claude/templates/ui-harness/`. From your project root:

```bash
cp -r ~/.claude/templates/ui-harness/harness \
      ~/.claude/templates/ui-harness/design \
      ~/.claude/templates/ui-harness/DESIGN.md .
# add a root script so any copilot can invoke the loop:
#   "copilot:review": "cd harness && npm run harness:verify"
```

Then fill in `DESIGN.md` (use the `design-system` skill to derive art direction from
the app's business domain) and wire `design/tokens.json` into your styling layer
(Tailwind v4 `@theme` → CSS variables).

## Run the loop

```bash
cd harness && npm install && npm run harness:init   # one-time (downloads Chromium)
# start your dev server, then from the project root:
npm run copilot:review
```

- **Critic = agent** (default): the runner emits screenshots + a request; the driving
  agent (Claude Code `visual-reviewer`) reads the PNGs and scores them.
- **Critic = vision** (`CRITIC=vision`): the runner calls a vision LLM over HTTPS
  (key via `ANTHROPIC_API_KEY`/`VISION_API_KEY`) and gates via exit code — for
  copilots without a multimodal agent.

Config via env: `DEV_URL`, `ROUTES`, `BREAKPOINTS`, `DESIGN_MD`, `CRITIC`,
`VISION_MODEL`. Never auto-installs Playwright — if absent, it runs an HTTP-200 smoke
and SKIPs the visual pass (DOM rubric + critique need a browser); a dead server still fails.

## Skills & agent

- Read the `design-system` skill before building UI (derive direction, override the
  four defaults, enforce the anti-slop catalog + state coverage).
- Read the `visual-review` skill for the loop protocol and exit criteria.
- On Claude Code, the `visual-reviewer` agent drives the loop as the multimodal critic.

This governs **appearance and structure only** — a polished UI is not a secure
backend. Keep `security-review` in the loop for auth/data paths.
