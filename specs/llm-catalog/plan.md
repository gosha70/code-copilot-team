---
spec_mode: full
feature_id: llm-catalog
risk_category: security
justification: |
  Introduces a user-level registry of LLM connections, puts credentials
  into harness child environments at launch, changes three launchers
  and adds two, changes the routing supervisor's identity resolution,
  and adds a compatibility gate that decides whether a harness starts.
  Security (credential handling, state files), integration (four
  harnesses, routing, Studio) and schema (new TOML registry, probe and
  stamp records) are all touched. FR-1..FR-29 in spec.md define the
  boundaries.
status: approved
date: 2026-11-10
issue: "#400"
origin:
  issue: "#400"
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/400
    - https://code.claude.com/docs/en/llm-gateway
    - https://developers.openai.com/codex/config-reference
    - https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md
    - https://kiro.dev/docs/cli/headless/
  transcripts:
    - specs/llm-catalog/origin/2026-11-10-issue-400-origin.md
  origin_claim: |
    Configure multiple named LLM targets once in a user-level catalog
    (providers, endpoints, llms, bindings; credentials as references),
    select one per launch with a common `--llm` flag on every harness
    launcher, resolve it through harness-specific adapters into an
    inspectable launch plan that keeps secrets out of argv, logs and
    multiplexer commands, decide compatibility per (harness, llm) pair
    before the harness starts with a falsifiable behavioral probe, stamp
    redacted provenance so resumed sessions cannot silently change
    model identity, and keep every launch without `--llm` exactly as it
    is today. Promise "any configured LLM target on any compatible
    harness", never "any LLM on any harness".
---

# Plan: harness-agnostic LLM catalog and `--llm` selection

Revision 6 (2026-11-10, after the fifth review).

## Shape

Composition, not invention. The catalog reuses the routing registry's
constrained grammar and credential-by-name boundary; the resolver
reuses the supervisor's child-only environment wiring and secret
scrub, and the routing library's two-digest construction (an
environment-independent tuple and a launch-identity digest that binds the
resolved endpoint); the probe reuses the routing probe's canary
primitives and tri-state; the launchers gain one flag each and a
child-side resolution step. New code is: the catalog schema and
validator, the resolver and its per-harness adapters, the
compatibility rule table and records, the session stamp, the state-
file primitives, the `cct llm` and `cct harness explain` commands, a
Codex launcher, a Kiro launcher, and the Studio page.

Layers, each with one owner:

1. **Catalog** — `scripts/lib/llm-catalog.sh` (parse, validate,
   accessors, catalog digest) over the shared lexer
   `scripts/lib/cct-toml.sh`; `scripts/lib/cct-home.sh` resolves the
   user home for catalog, records and stamps (`CCT_LLM_HOME` in
   tests); `scripts/lib/cct-endpoint.sh` is the one endpoint
   sanitizer, emitting `origin` (unchanged grammar, still validated by
   `routing-result.sh`), sourced by the supervisor in place of its
   private copy.
2. **Resolver** — `scripts/lib/llm-resolve.sh`: `(harness, target,
   project, resume)` → LaunchPlan as canonical JSON (jq), with the
   per-harness adapter functions in `scripts/lib/llm-adapters/
   <harness>.sh`; defines `start` versus `exec` (FR-6). Slice A ships
   the plan schema and an "adapter not implemented" refusal for every
   harness; each adapter is implemented in its slice after its
   capture.
3. **Compatibility** — `shared/llm/compat-rules.json` (`rule_version`,
   protocols, quirks and required capabilities per harness),
   `scripts/lib/llm-compat.sh` (state computation, records),
   `scripts/lib/llm-probe.sh` (capability-matrix canary over the
   primitives extracted from `routing-probe.sh`).
4. **State files** — `scripts/lib/cct-statefile.sh`: private
   directories, locked same-directory atomic replacement, symlink
   refusal, interruption cleanup (FR-29); used by records, stamps and
   any ownership manifest.
5. **Launch** — each launcher parses `--llm` and `--allow-unverified`,
   runs `start` in the outer process and `exec` inside the process
   that runs the harness. `scripts/llm-cli.sh` serves the read-only
   commands.
6. **Policy** — project `[llm].allowed`; routing `llm =` reference
   (G).
7. **Surfaces** — `cct doctor` section, docs, catalogue, Studio.

## Slices and their issues (D1)

| Slice | Issue (to file) | Delivers | Depends on |
|---|---|---|---|
| A | catalog and read-only CLI | layers 1–4 without any launcher change; `cct llm list/show/validate/compatibility/test/sessions`, `cct harness explain`; `start`/`exec` definitions; plan schema with "adapter not implemented" refusals; rule table; probe records; doctor section; docs; example file | — |
| B | Claude Code | capture first; the `claude-code` adapter; `--llm` on `claude-code` and `cct start`; child-side resolution inside the cmux/tmux pane; `rejects-dynamic-tools`; stamps, promotion and exact-id resume rules; native byte-for-byte; behavioral probe through the real launcher (mock and one real run on the owner's machine) | A |
| C | Codex | capture against the installed CLI; `adapters/codex/bin/codex-code`; `-c` overlay; rule table amended by capture; stamps, exact-id resume, native byte-for-byte (FR-17–19, FR-27); probe | A, B's launch contract |
| D | Pi | capture: launch-scoped agent-directory overlay versus owned merge; D11 ruled on the capture; `--llm` on `pi-code`; `--provider/--model`; stamps, exact-id resume, native byte-for-byte (FR-17–19, FR-27); probe | A, B |
| E | Kiro | capture of the installed `kiro-cli`; `adapters/kiro/bin/kiro-code`, managed-model-only; `--model`, `--resume-id`; endpoint bindings `unsupported`; stamps, exact-id resume, native byte-for-byte (FR-17–19, FR-27); managed-harness evidence contract; docs state the limit | A, B |
| F | Unified launch and Studio | `cct harness start/exec`; Studio read-only page, non-secret editing, id-only command generation | B, C, D, E |
| G | Routing and provenance | `llm =` / `binding =` in routing profiles; supervisor resolves through the resolver; journal and stamp agree by launch-identity digest; closes #400 | A–F merged |

Each slice gets its own `tasks.md` section when its issue opens;
`tasks.md` here details A and B and outlines the rest.

## Design decisions carried into tasks (see spec.md § Decisions)

D1 slicing · D2 one user-home helper · D3 three files · D4 shared
lexer · D5 explicit bindings only · D6 canary primitives shared, not
routing's runner · D7 refuse unverified, `--allow-unverified` escape ·
D8 quirks in execution identity · D9 generated session ids, bare
`--continue` native and refused with `--llm` · D10 Codex `-c` after
capture, no silent fallback · D11 Pi form decided by capture (deferred
to slice D) · D12 Kiro managed-model launcher in E (scope only) · D13
`[llm].allowed` only · D14 Studio never spawns an interactive session
(narrowing) · D15 `start`/`exec` defined in A.

Fourteen were ruled by the owner on 2026-11-10, all as recommended,
with conditions on D1 (slice PRs say "Part of #400"; only G closes it)
and D4 (the extraction is its own commit, routing-config tests
unchanged); D11 is deferred to slice D's capture. The two narrowings
(D14 and the secure-store deferral) were approved and #400's slice F
and credential sentences amended to match on the same day.

## Interfaces

- `scripts/lib/cct-toml.sh`: `ct_lex_line <line>` producing the
  record format `ctx<US>key<US>type<US>value` that `rc_parse` produces
  today; `routing-config.sh` sources it and keeps its vocabulary,
  table-header rules and validator unchanged.
- `scripts/lib/cct-home.sh`: `cct_user_home`, `cct_llm_catalog_path`,
  `cct_llm_compat_dir`, `cct_llm_sessions_dir`.
- `scripts/lib/llm-catalog.sh`: `lc_parse <file>`, `lc_validate
  <file>`, `lc_get <table> <id> <key>`, `lc_ids <table>`,
  `lc_binding_for <harness> <target>` (explicit only),
  `lc_catalog_digest <binding>`.
- `scripts/lib/llm-resolve.sh`: `lr_plan <harness> <target> <project>
  [--resume <key>] [--allow-unverified] [--probe]` → JSON on stdout,
  exit 0 plan, 3 refused (reason in `.refusal`), 2 catalog unusable.
  Always computes the digests (the resolved endpoint value is read,
  validated and hashed read-only) and `env_clear`; reads credential
  values only when `LR_CHILD=1`; otherwise `env_names` carries
  set/unset per name. `--probe` applies the FR-15 exemption.
- `scripts/lib/llm-compat.sh`: `lcm_state <harness> <binding>` → one
  of the five states plus reason; `lcm_record_attempt`,
  `lcm_record_conclusive`, `lcm_record_read`.
- `scripts/lib/llm-probe.sh`: `lp_probe <plan-json>` → outcome
  (`pass | fail | unverifiable`) plus the capability matrix JSON; seam
  `CCT_LLM_PROBE_CMD`; watchdog `CCT_LLM_PROBE_TIMEOUT_SEC` with
  TERM→KILL on the process group; signal-safe temp cleanup.
- `scripts/lib/cct-statefile.sh`: `sf_write <path> <content>` (locked,
  same-dir temp, rename, `0600`, symlink refusal, stale lock-directory
  reclaim), `sf_read <path>`, `sf_dir <path>` (`0700`).
- `scripts/lib/llm-stamp.sh`: `ls_write_attempted <plan-json>
  <session-key>`, `ls_promote <harness> <session-key> <evidence>`,
  `ls_read <harness> <session-key>`.
- `scripts/llm-cli.sh`: the commands of FR-6; `--json` output
  validated by `shared/schemas/llm-catalog-cli.schema.json`.
- Launchers: `--llm <target>` / `--llm=<target>` and
  `--allow-unverified` parsed before the forward-unknown rule;
  `CCT_LLM_CHILD=1` marks the exec-side invocation; the typed
  multiplexer command is the launcher name plus ids.

## Test strategy

- `tests/test-llm-catalog.sh`: grammar (every rejected construct by
  name), entities, credential modes and auth headers, references,
  duplicates, secret-shape scan, catalog digest stability and
  collision cases, example file valid, explicit-binding resolution and
  the `@binding` form.
- `tests/test-llm-compat.sh`: each state from fixtures; rule-version
  and digest changes degrade `supported`; `latest_attempt` versus
  `latest_conclusive`; probe matrix via the mock harness in front of
  the stub gateway (`tests/fixtures/llm-stub-gateway.py`), one
  negative-control switch per capability (tool call dropped, tool
  result ignored, no streaming, wrong model id, system prompt ignored,
  rejected request shape, auth rejected, limits exceeded, timeout) and
  the state each yields.
- `tests/test-cct-endpoint.sh`: the sanitizer on userinfo, query,
  fragment, path, IPv6, case, non-http schemes; `origin` byte-identical
  to the supervisor's former private function for every existing
  supervisor fixture and accepted by `rr_origin_is_sanitized`; the
  resolved `base_url_env` value validated by the same rule.
- `tests/test-cct-statefile.sh`: permissions, same-directory rename,
  symlink refusal, interrupted write (killed writer leaves no temp or
  partial file), two concurrent writers, a writer killed while holding
  the fallback lock directory followed by a successful writer,
  malformed file refused by name.
- `tests/test-llm-cli.sh`: every command, text and JSON, redaction of
  a planted secret value; a planted path token and the readable path
  absent from every output; schema validation of JSON; set/unset
  reporting without values; `sessions` promotion from a fixture
  transcript; `test` runs an `unverified` and an `incompatible`
  fixture target and refuses `unsupported` and `unavailable` ones.
- `tests/test-claude-code-launcher.sh` (extended) and a new
  `tests/test-llm-launch.sh`: stub `claude` records argv and env;
  stub `cmux`/`tmux` record the typed command; assertions for FR-10,
  FR-11 (with mutation), FR-12 including the escape hatch, FR-17–19
  (exact id, bare `--continue` native and refused with `--llm`,
  launch-identity mismatch refused with and without the flag,
  evidence-only change bypassable), FR-20; hostile project paths
  (spaces, quotes, newlines, `$( )`, `;`) through the stub
  multiplexers; a newline path refused; a planted secret and a
  planted path token are grepped out of every capture, record and
  stamp; a planted ambient `ANTHROPIC_API_KEY` and
  `CLAUDE_CODE_USE_BEDROCK` are absent from the stub harness's
  environment with `--llm` and present without it (FR-30).
- Routing suite unchanged in count after the lexer extraction (pin
  365) and the probe-primitive extraction (routing probe/recovery pins
  unchanged); supervisor suite proves FR-27 for routed launches in
  A/B and the `llm =` form in G.
- CI: the suites run in `sync-check` like the routing suites (bash 3.2
  and jq only). Each real-harness probe run (B, C, D, E) is
  owner-executed and quoted in the PR, never claimed from a mock.

## External facts to re-verify during build (captures)

- Codex (C, first task): nested `-c model_providers.<id>.<key>`
  overrides on the installed CLI (the vendor documents the form for
  the app-server; the CLI must be captured), `wire_api` accepted
  values, `--profile` layering, `codex resume`, the effective-model
  field of `exec --json`. A disproving capture stops the slice for a
  ruling (D10).
- Claude Code (B): whether `--output-format json` reports the
  effective model; `--session-id` on a new session and the transcript
  path that proves the session was established; minimum version for
  the #399 retry behaviour; whether a settings-file `env` block
  overrides variables the launcher sets in the child environment
  (FR-20).
- Pi (D, first task): the overlay-versus-merge capture of FR-22;
  refusal behaviour for an unknown `--provider`; `--session-id` on a
  new session; `$VAR` interpolation when the variable exists only in
  the child environment; whether the Pi runtime config lint
  (`adapters/pi/runtime/config/lint.ts`) accepts the project `[llm]`
  table.
- Kiro (E, first task): model id strings for `--model`, `--model` on
  new and `--resume-id` sessions, session id discovery, headless
  output format, `KIRO_API_KEY` scope.

## Risks

| Risk | Mitigation |
|---|---|
| A credential value reaches a capture, stamp, record, journal, digest or multiplexer command | One redaction function; planted-secret grep over every artifact in every suite; value read only behind `LR_CHILD=1`; digests take the credential name only |
| A gateway path carrying a tenant id or token is stamped as provenance | Durable provenance is origin only; the launch-identity digest binds the full URL opaquely; planted path token asserted absent |
| Lexer or probe-primitive extraction changes routing behaviour | Routing pins unchanged; extraction commits contain no vocabulary change |
| A `supported` state outlives the endpoint it was measured against | Evidence digest binds the launch identity (resolved endpoint, options) plus harness and rule versions; mismatch degrades to `unverified` |
| A resume silently changes what runs, or a harness upgrade refuses every resume | Resume compares launch identity only; evidence-only changes degrade, never refuse |
| The first probe can never run | `cct llm test` is the controlled path exempt from the `unverified`/`incompatible` refusals, pinned by a regression test |
| A probe hangs or orphans a child | Watchdog with TERM→KILL on the process group; expiry is `unverifiable` |
| A project path hijacks the typed command | `printf %q` for typed commands (bash/zsh), paths needing `$'…'` refused, argv arrays for direct exec, hostile-path tests |
| An ambient credential or provider switch rides into a selected launch | FR-30 clear-list per adapter, applied only with `--llm`, printed by `explain`, proven by the sentinel control |
| A settings-file `env` block silently overrides the injected variables | B's capture decides; if so the adapter refuses on conflicting keys by name |
| An inconclusive probe erases conclusive evidence | Two-part records; only `pass` or behavioral `fail` updates `latest_conclusive` |
| Native launches change by accident | FR-11 byte-for-byte assertion plus mutation test |
| `--continue` binds the wrong session | Bare `--continue` stays native; only exact ids are enforced; stamps are `attempted` until the harness's own evidence promotes them |
| Pi overlay damages user state | Decided by capture; merge path requires ownership manifest, collision refusal and FR-29 |
| Codex `-c` form unsupported by the installed CLI | Capture first; slice stops for a ruling, no silent fallback |
| Partial or racing state-file writes, or a wedged fallback lock | FR-29 primitives with interruption, concurrency and stale-lock recovery tests |
| Kiro expectations | Managed-model-only launcher; rule table and docs state the limit; endpoint bindings refused |
| #411 moves the home directory | One helper for catalog, records and stamps |

## Delivery gates

A pushed draft of this bundle turns `sync-check` red on purpose: that
required check runs `validate-spec.sh --all`, which fails on the open
`[NEEDS CLARIFICATION]` markers. The auto-opened PR is made a draft
with the body "Part of #400. Spec bundle for review; sync-check is
expected red until the open decisions are ruled.", and GitHub's
closing-references list for it must be empty. The check goes green
when the owner's rulings remove the markers.

Per slice: `validate-spec.sh --feature-id llm-catalog`,
`check-origin-alignment.sh llm-catalog` (fresh record), the suites
above, `generate-feature-index.sh --check` and the other generators,
`check-doc-accuracy`, `git diff --check`, `pre-pr-check.sh --closes
<slice-issue>` (never #400 before G), peer review through the review
runner, CI green on the final head read from GitHub.
