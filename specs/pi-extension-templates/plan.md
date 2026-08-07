---
spec_mode: full
feature_id: pi-extension-templates
risk_category: integration
justification: |
  Delivers #179 (enterprise programmatic guardrails) as user-side extension
  templates, a reference validator, headless recipes, and linkage docs —
  strictly on verified Pi surfaces (tool_call gate, session_start,
  registerCommand, --mode json, explicit --extension loading). Touches the
  init scaffolding path and ships runnable user-facing artifacts across
  >2 files, hence full mode; the CCT enforcement runtime itself is not
  modified. Every unverified API from the issue is documented, not shipped.
status: draft
date: 2026-08-07
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/179
  origin_claim: |
    Prompt enforcement alone is insufficient for enterprise environments
    that require deterministic, programmatic guardrails (AST-level
    transformations, custom static analysis, proprietary CI gates).
    Introduce native Pi harness extension templates (.pi/extensions/) and
    programmatic hook recipes: mid-generation execution gates intercepting
    write/edit to spawn external validation and feed failures back for
    self-correction; AST parsing/transformation wrappers; dynamic
    event-driven model routing; headless JSON-RPC bootstrap recipes.
    Acceptance: a .pi/extensions/ starter template in project presets;
    docs linking hooks with AGENTS.md/SYSTEM.md definitions; a reference
    validator demonstrating mid-generation interception; standard headless
    launch configurations.
---

# Plan: Pi extension templates & hook recipes (#179)

## Existing facts (verified 2026-08-07, on the PR #188 stack)

- `hooks/events.ts`: SessionStart + PreToolUse `supported`; Notification
  `degraded`; **PostToolUse/Stop/etc `unsupported`** — rows may flip only
  when a Pi build is confirmed to emit the event.
- The runtime's own enforcement intercepts at the **`tool_call` gate** and
  blocks with `{ block: true, reason }` — the reason reaches the model
  (the exact self-correction loop #179 wants, pre-write).
- Headless: `pi --mode json -p` is spawned by the T7.2 runner and
  classified by the launcher (`CCT_PI_MODE=json`); the result envelope is
  the T10.3 contract. `--mode rpc` appears nowhere verified.
- Extension loading: the launcher loads the CCT runtime via
  `--extension "$RUNTIME_ENTRY"`; unknown args forward to pi unmodified —
  so a user extension loads with a forwarded `--extension` flag.
- `pi-code init` scaffolds `.code-copilot-team/config.toml` + a manifest
  (`.cct-init.json` with per-file hashes), never clobbers, honors
  `--dry-run`, rejects unknown options (exit 2). Generated user-facing
  resources live under `adapters/pi/resources/` (managed by
  generate/sync); init copies from there.

## Design

### D0 — Phase-1 review redesign (2026-08-07; methodology correction)
The phase-1 review verified against the INSTALLED pi package (0.83.0) and
proved the original design wrong in both directions:
- **Facts corrected**: `tool_result` (post-tool interception, result
  patching) has shipped since pi 0.18.0; `.pi/extensions/` auto-discovery
  is supported (trust-gated) and upstream-recommended; explicit
  `--extension` bypasses the trust gate (security caveat, F3);
  `setModel` exists on ExtensionAPI; `--mode rpc` is a shipped mode.
  Root cause: "verifying" against `hooks/events.ts` (a record of what CCT
  hooks) inverted "unchecked" into "pi doesn't have it". Standing rule
  now: primary-source citations for every pi claim, version named.
- **Gate redesigned** (review F4/F5): pre-write validation now judges the
  INCOMING `write` content via a temp file (a fresh write of broken
  content is blocked before disk — previously a guaranteed no-op), and a
  `tool_result` post-execution gate validates the on-disk result of
  `write`/`edit`, patching the result with the report on failure —
  which also dissolves the legacy-file deadlock (repairs pass).
- **Hardening** (F6-F13): bash-bypass boundary stated; env override
  renamed `GUARDRAILS_VALIDATOR_CMD` (out of the CCT_*-kept namespace)
  and surfaced at session_start; async execFile (no event-loop stall);
  `--` argv separator + maxBuffer; violation vs validator-error outcomes
  distinct (exit 1 vs other); warn-and-allow warns; validator 0755 with
  the 3-state exit contract; canonical pi event keys only (dead fallback
  patterns dropped).

### D1 — Template artifacts (source of truth in resources/; shape superseded by D0 where they differ)
`adapters/pi/resources/extension-template/` holds four files (tsconfig
added by the verification round):
- `cct-guardrails.ts` — the starter extension: registers a `tool_call`
  handler that, for `write`/`edit`, resolves the target path, runs a
  configurable validator command (`CCT_VALIDATOR_CMD` env or an in-file
  constant), and returns `{ block: true, reason: <stderr> }` on non-zero
  exit — the model sees the reason and self-corrects BEFORE the file is
  touched. Also demonstrates `session_start` (banner/registration) and
  `registerCommand` (a `/guardrails:status` example). Comment-dense; no
  unverified API anywhere.
- `validators/check-python-ast.py` — stdlib `ast.parse` reference: exit 0
  clean; exit 1 with a readable syntax report on stderr.
- `README.md` — loading recipe (forwarded `--extension`), the honesty
  table (FR-6), the swap-your-own-validator guide, and the FR-5 linkage
  section (prompts declare intent/personas; extensions enforce).

### D2 — Init scaffolding (`bin/pi-code`)
`cct_init` gains `--extension-template`: copies the three files into
`<project>/.pi/extensions/` (validator under `validators/`), records them
in the init manifest with hashes, never clobbers an existing file (report
+ preserve, same as config.toml), `--dry-run` reports without writing.
Bash 3.2; help text updated; unknown-option behavior unchanged.

### D3 — Headless doc (`adapters/pi/docs/headless-harness.md`)
Recipes on the verified surface only: one-shot enforced run
(`pi-code -- --mode json -p "…"` shape — exact flag threading verified in
tests with the pi shim), envelope parsing (jq example over the T10.3
fields), exit codes, a minimal GitHub-Actions job, and the `--mode rpc`
honesty note. Cross-links: unattended-runs.md (posture), the template
README.

### D4 — Docs integration
README doc list entry; extension-development.md gets a pointer note
("user-side project templates: see the extension-template README" — the
existing doc stays repo-internal-focused).

## Deliverables

1. `adapters/pi/resources/extension-template/{cct-guardrails.ts,
   validators/check-python-ast.py, README.md}`.
2. `bin/pi-code` init `--extension-template` + help.
3. `adapters/pi/docs/headless-harness.md` + README/doc pointers.
4. Tests: launcher (scaffold/no-clobber/dry-run/manifest/help), template
   validity (strip-types parse; validator both exits), headless recipe
   shape against the pi shim.

## Sequencing

1. D1 template artifacts (+ validity tests).
2. D2 init scaffolding (+ launcher tests).
3. D3/D4 docs (+ help/test wiring).

Per-phase review loop as #186/#188: review agent after each phase,
findings fixed + re-verified before the next.

## Test strategy

- Launcher: `init --extension-template` scaffolds all three files;
  re-init preserves an edited template; `--dry-run` writes nothing;
  manifest lists them with hashes; `init` without the flag scaffolds
  nothing new; help documents the flag.
- Template: `node --experimental-strip-types --check`-equivalent load of
  the scaffolded TS (the same execution class the runtime uses); the
  validator exits 0 on a valid file and non-zero with non-empty stderr on
  a syntax error.
- Headless: the doc's exact command shape launches through the launcher
  with the pi shim and the forwarded flags arrive (ARGS capture), mirroring
  the existing launcher-test pattern.
- Honesty: a test greps the shipped template + docs for the unverified
  tokens (`post_tool_call`, `agent_event`, `setModel(`, `--mode rpc`) and
  asserts they appear ONLY in the honesty-table/doc context (the table
  file), never in the template code.

## Open questions (leans recorded; user is remote — proceeding on leans,
## flagged for PR review)

1. **Scaffold target dir** — the issue says `.pi/extensions/`; lean:
   honor it verbatim (it is the user-side convention the issue proposes;
   nothing in the repo owns `.pi/`). Alternative was
   `.code-copilot-team/extensions/`.
2. **Validator config surface** — lean: in-template constant +
   `CCT_VALIDATOR_CMD` env override; NOT a new `security.*` config key
   (the template is user-owned code, not runtime policy).
3. **No new capability id** — lean: correct (no runtime change); noted in
   FR-6 docs instead.
