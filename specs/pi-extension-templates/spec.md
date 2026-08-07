# Spec: Pi extension templates & programmatic hook recipes (#179)

Source: GitHub issue **#179** ("Programmatic Extension Architecture via Pi
Harness Integration for Enterprise Custom Logic"). The issue's intent —
deterministic, programmatic guardrails beyond prompt discipline — is
delivered through **verified Pi surfaces only**; every API the issue
sketches that is not verifiable on this Pi build is documented as
unverified/unsupported with the working alternative, never templated as if
it existed (the repo's standing honesty rule: no unverified surface is ever
shipped as working).

## Verified surface inventory (master + PR #188 head, 2026-08-07)

| Issue ask | Verified reality |
|---|---|
| `post_tool_call` interception | **Unsupported today** — `hooks/events.ts` marks PostToolUse `unsupported`; the runtime's own enforcement uses the **`tool_call` (PreToolUse) gate**, which is `supported` and can BLOCK a write with a reason the model sees — a *pre-write* execution gate, strictly stronger than post-write repair |
| `agent_event` + `ctx.setModel()` | Not present on any surface this repo has verified; per-phase model policy exists as config-reported state only |
| `pi --mode rpc` | Unverified; **`pi --mode json -p` is the verified headless surface** (the T7.2 child-session runner spawns it; the launcher classifies it) |
| `.pi/extensions/` auto-discovery | Unverified; the **verified loading mechanism is explicit `--extension <path>`** (exactly how `pi-code` loads the CCT runtime) |

## User Scenarios

- **US1 — Deterministic pre-write guardrail.** As an enterprise developer,
  I scaffold an extension template into my project, point it at my own
  validator (AST checker, linter, policy script), and every `edit`/`write`
  is validated BEFORE it lands on disk — a failing validator blocks the
  write and the error text reaches the model for self-correction.
- **US2 — Headless/CI harness.** As a platform engineer, I drive the
  enforced harness from CI with a copy-paste recipe built on the verified
  `--mode json` surface, with exit-code and result-envelope semantics
  documented.
- **US3 — No false promises.** As the project owner, nothing in the
  templates claims an API this Pi build does not expose; each unverified
  ask from #179 is named, its status stated, and the working alternative
  given.

## Requirements

- **FR-1 — Starter extension template.** `pi-code init --extension-template`
  scaffolds `.pi/extensions/cct-guardrails.ts` (plus a sibling README):
  a commented, self-contained extension skeleton using ONLY verified
  surfaces — `session_start`, the `tool_call` gate (returning
  `{ block, reason }`), and `registerCommand`. The template runs a
  configurable validator command against the file a `write`/`edit` is
  about to touch and blocks with the validator's stderr on failure. Init
  semantics match the existing contract: never clobbers an existing file,
  recorded in the init manifest, `--dry-run` honored.
- **FR-2 — Reference validator.** A runnable
  `.pi/extensions/validators/check-python-ast.py` reference (stdlib-only:
  `ast.parse`) demonstrating the contract: exit 0 = pass; non-zero with a
  human-readable stderr = block reason. The template's default command
  points at it; the README shows swapping in tree-sitter/Java/linters.
- **FR-3 — Loading recipe, honestly bounded.** The template README
  documents the verified load path — launching pi with
  `--extension .pi/extensions/cct-guardrails.ts` forwarded through
  `pi-code` — and states plainly that `.pi/extensions/` auto-discovery is
  not a verified behavior of this Pi build.
- **FR-4 — Headless JSON recipes.** `adapters/pi/docs/headless-harness.md`
  with copy-paste recipes for the verified surface: one-shot
  `pi --mode json -p` through the enforced launcher, result-envelope
  fields (the T10.3 contract: `type:"result"`, `subtype`,
  `total_cost_usd`, `session_id`), exit-code handling, and a minimal CI
  job example. `--mode rpc` is named as unverified with this alternative.
- **FR-5 — Prompt-definition linkage.** Documentation connecting the
  extension hooks to the prompt-layer definitions (AGENTS.md /
  SYSTEM.md-style personas): what belongs in prompts (intent, personas)
  vs what belongs in extensions (deterministic gates), and how the two
  compose in this harness.
- **FR-6 — Honesty table.** The doc carries the issue-ask → status →
  alternative table (as above), so #179 closes without overclaiming:
  post-write interception and dynamic `setModel` routing are recorded as
  not-available-today with their pre-write / config-policy alternatives.
- **FR-7 — Tests + gates.** Launcher tests for the init flag (scaffold,
  no-clobber, dry-run, manifest entry); a template validity check (the
  scaffolded TS parses under the same strip-types execution the runtime
  uses; the reference validator runs and both exit paths behave); all
  existing gates stay green.

## Constraints / What NOT to Build

- **No unverified API in any template or recipe** — no `post_tool_call`,
  `agent_event`, `setModel`, `--mode rpc`, or auto-discovery claims.
- **No runtime behavior change**: the CCT enforcement runtime is not
  modified; the template is user-side scaffolding loaded separately.
- **No new capability id** (no new runtime surface — this is templates +
  docs; `pi-code features` is untouched).
- **No new Pi event source**; no daemon.
- The reference validator is stdlib-only (no new dependencies).

## Key Entities

- Template files — `.pi/extensions/cct-guardrails.ts`, its README,
  `validators/check-python-ast.py` (shipped under
  `adapters/pi/resources/extension-template/`, scaffolded by init).
- Init flag — `--extension-template` (+ manifest entries).
- Docs — `adapters/pi/docs/headless-harness.md`, extension-template README,
  linkage section, honesty table.

## Success Criteria

1. `pi-code init <dir> --extension-template` scaffolds the template +
   validator + README; re-init never clobbers; `--dry-run` writes nothing;
   manifest records the files.
2. The scaffolded template is executable TS under
   `node --experimental-strip-types` syntax loading, and the reference
   validator demonstrably passes a valid file and blocks an invalid one
   with readable stderr.
3. The headless doc's recipe works against the verified `--mode json`
   surface as written (validated with the launcher's pi shim in tests).
4. Every #179 ask is either delivered on a verified surface or explicitly
   recorded as unverified with its alternative — no template references an
   unverified API.
5. #179 closable; launcher + runtime + adapter gates green.
