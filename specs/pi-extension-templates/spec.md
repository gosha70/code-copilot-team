# Spec: Pi extension templates & programmatic hook recipes (#179)

Source: GitHub issue **#179** ("Programmatic Extension Architecture via Pi
Harness Integration for Enterprise Custom Logic"). The issue's intent —
deterministic, programmatic guardrails beyond prompt discipline — is
delivered through pi surfaces **verified against the installed pi package**
(0.83.0 primary sources: typings, shipped docs, changelog, live probes).
Every claim about pi — including "unsupported" claims — must cite that
primary source; the phase-1 review proved that inferring pi's surface from
CCT internals produces confident falsehoods in both directions.

## Verified surface inventory (REVISED by the phase-1 review — sourced
## from the INSTALLED pi package, 0.83.0: types.d.ts / docs / changelog)

The phase-1 review proved the original inventory wrong on three rows: it
had been "verified" against `hooks/events.ts`, a CCT-internal record of
*what CCT hooks*, whose own design doc says Pi's events "must not be
inferred" from it. The corrected rule: **every claim about pi — positive
or negative — cites the installed pi package** (typings, shipped docs,
changelog, or a live probe), with the version named.

| Issue ask | pi 0.83.0 reality (primary source) |
|---|---|
| `post_tool_call` interception | **Supported** as the `tool_result` event (since pi 0.18.0; `types.d.ts` `on("tool_result", ...)`, `docs/extensions.md` "Can modify result", middleware chaining) — **used by this feature's post-execution gate** |
| `agent_event` + `setModel()` | No `agent_event` event exists; **`setModel(model)` DOES exist** on `ExtensionAPI` (`types.d.ts`) and is callable from any handler. Documented (with the caveat that the CCT runtime does not wrap it); not templated |
| `pi --mode rpc` | **A shipped pi mode** (`docs/rpc.md`, `rpc-entry.js`); the CCT harness has not exercised it — the harness's verified headless recipes use `--mode json` (T7.2/T10.3), stated as CCT-unexercised, not pi-absent |
| `.pi/extensions/` auto-discovery | **Supported, trust-gated** (project-local entries load once the project is trusted; `docs/extensions.md`), and upstream-recommended (enables `/reload`). Explicit `--extension` also works but **bypasses the project-trust gate** — a security caveat the docs must state |

## User Scenarios

- **US1 — Deterministic validation guardrail.** As an enterprise
  developer, I scaffold an extension template into my project and point it
  at my own validator. A `write`'s **incoming content** is validated
  before it lands on disk (blocked with the report on failure), and every
  `write`/`edit` **result on disk** is validated after execution (the tool
  result is patched to an error carrying the report) — the model
  self-corrects in both cases, and an edit that repairs an already-broken
  file passes (post-state validation: no legacy deadlock).
- **US2 — Headless/CI harness.** As a platform engineer, I drive the
  enforced harness from CI with a copy-paste recipe built on the verified
  `--mode json` surface, with exit-code and result-envelope semantics
  documented.
- **US3 — No false promises.** As the project owner, nothing in the
  templates claims an API this Pi build does not expose; each unverified
  ask from #179 is named, its status stated, and the working alternative
  given.

## Requirements

- **FR-1 — Starter extension template, two gates.** `pi-code init
  --extension-template` scaffolds `.pi/extensions/cct-guardrails.ts` (plus
  a sibling README): a commented, self-contained skeleton on pi-shipped
  surfaces — `session_start` (prints the resolved validator, so an ambient
  override is never invisible), the `tool_call` gate (validates a
  `write`'s **incoming `input.content`** via a temp file; `{block,
  reason}` on violation — disk untouched), the `tool_result` hook
  (validates the on-disk result of `write`/`edit`; patches `{isError,
  content}` with the report on violation), and `registerCommand`. `edit`
  is deliberately not pre-gated (patch-list input; the post gate covers
  it). Validator runs are async (never block pi's loop), argv-safe (`--`
  separator), bounded (timeout + maxBuffer), and env-overridable via
  `GUARDRAILS_VALIDATOR_CMD` (deliberately NOT in the CCT_* kept
  namespace). Distinct outcomes: violation (model-facing report) vs
  validator-error (never blamed on the model; FAIL_CLOSED decides, and
  warn-and-allow actually warns). The bash-tool bypass boundary is stated
  in code and README. Init semantics unchanged: no-clobber, manifest,
  `--dry-run`.
- **FR-2 — Reference validator.** A runnable, executable (0755)
  `.pi/extensions/validators/check-python-ast.py` reference (stdlib-only:
  `ast.parse`) demonstrating the contract: exit 0 = pass; exit 1 =
  violation with a human-readable stderr report; any other exit =
  validator error (misconfiguration — handled per FAIL_CLOSED, never
  presented as the model's fault). Tolerates the `--` separator. The
  README shows swapping in tree-sitter/Java/linters.
- **FR-3 — Loading recipe with the trust caveat.** The template README
  recommends the upstream path: `.pi/extensions/` **auto-discovery**,
  which is trust-gated and enables `/reload`. The explicit `--extension`
  flag is documented as the pinned/CI alternative WITH its security
  caveat: explicit CLI extension paths bypass pi's project-trust gate, so
  a standing `-e .pi/extensions/...` alias would execute an untrusted
  repo's code — stated plainly, per pi's own security docs.
- **FR-4 — Headless JSON recipes.** `adapters/pi/docs/headless-harness.md`
  with copy-paste recipes for the verified surface: one-shot
  `pi --mode json -p` through the enforced launcher, result-envelope
  fields (the T10.3 contract: `type:"result"`, `subtype`,
  `total_cost_usd`, `session_id`), exit-code handling, and a minimal CI
  job example. `--mode rpc` (a shipped pi mode) is noted as
  CCT-unexercised, with `--mode json` as the harness-verified alternative.
- **FR-5 — Prompt-definition linkage.** Documentation connecting the
  extension hooks to the prompt-layer definitions (AGENTS.md /
  SYSTEM.md-style personas): what belongs in prompts (intent, personas)
  vs what belongs in extensions (deterministic gates), and how the two
  compose in this harness.
- **FR-6 — Honesty table, primary-sourced.** The template README carries
  the issue-ask → pi-0.83.0-status → notes table (as above), each row
  citing its source, with the version named and a re-verify-on-upgrade
  note. A test asserts the table's claims against the INSTALLED pi
  package's typings when resolvable (VISIBLE skip, never fake, when pi is
  absent — which includes CI: the canary is a developer-local gate by
  design; CI does not install pi).
- **FR-7 — Tests + gates.** Launcher tests for the init flag (scaffold,
  no-clobber, dry-run, manifest entry); a template validity check (the
  scaffolded TS parses under the same strip-types execution the runtime
  uses; the reference validator runs and both exit paths behave); all
  existing gates stay green.

## Constraints / What NOT to Build

- **Primary-source rule** — every pi-surface claim in templates/docs
  (positive or negative) cites the installed pi package; the one #179 API
  pi does not ship (`agent_event`, and the `post_tool_call` NAME — pi's
  event is `tool_result`) appears nowhere in template code.
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
4. Every #179 ask is either delivered on a pi-shipped surface (both
   gates, auto-discovery loading) or recorded with its true pi-0.83.0
   status and alternative (`setModel` exists-but-unwrapped; `--mode rpc`
   shipped-but-CCT-unexercised) — with the primary source cited.
5. #179 closable; launcher + runtime + adapter gates green.
