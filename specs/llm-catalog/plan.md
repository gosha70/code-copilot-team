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
    - https://github.com/gosha70/code-copilot-team/issues/479
  transcripts:
    - specs/llm-catalog/origin/2026-11-10-issue-400-origin.md
    - specs/llm-catalog/origin/2026-11-19-launch-first-ruling.md
    - specs/llm-catalog/origin/2026-11-23-replan-rulings.md
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

Revision 7 (proposed 2026-11-23, awaiting the owner's approval): the
slices still owed after the launch-first slice are re-planned in
"Remaining slices"; nothing else in this plan changes.

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

## Launch-first slice (#479, ruled 2026-11-19)

The owner ruled on 2026-11-19 that the Claude Code launch is built
before the rest of slice A (spec.md, "Launch-first slice", which lists
what is implemented, deferred and departed from). The slice takes the
launch-bearing parts of A and B and leaves their evidence machinery to
the slices that follow:

| From | Taken by #479 | Left for its slice |
|---|---|---|
| A1 | the lexer extraction, own commit | nothing |
| A2 | nothing (no state file is written) | all of it |
| A3 | the sanitizer move, the catalog library, the example file | the digests, the `data_policy` vocabulary |
| A4, A5 | nothing | all of it |
| A6 | resolution, the plan's set and clear lists, typed-command quoting | the LaunchPlan JSON schema, the three digests |
| A7 | `cct llm list`, `validate`, `scripts/cct` dispatch | `show`, `compatibility`, `test`, `sessions`, `harness explain`, `--json` |
| A8 | nothing | all of it |
| A9 | `docs/llm-catalog.md`, the catalogue entry, generated docs, test pins, CI steps | the doctor section |
| B1 | the capture, run against local stub endpoints | `--session-id`, the JSON model field, the #399 minimum version |
| B2, B3 | the adapter, `--llm` parsing, start and in-pane exec, headless, the native guard and its mutation test | `--allow-unverified`, stamping |
| B4, B5 | nothing | all of it |
| B6 | launcher help, the guide, CHANGELOG | byte-for-byte assertions in the supervisor and benchmark suites |

**Files.** New: `scripts/lib/cct-toml.sh`, `scripts/lib/cct-endpoint.sh`,
`scripts/lib/llm-catalog.sh`, `scripts/lib/llm-adapters/claude-code.sh`,
`scripts/llm-cli.sh`, `shared/templates/llm/llms.toml.example`,
`tests/test-llm-catalog.sh`, `tests/test-llm-launch.sh`,
`docs/llm-catalog.md`. Changed: `scripts/lib/routing-config.sh` (uses
the extracted lexer), `scripts/cooldown-supervisor.sh` (sources the
moved sanitizer), `adapters/claude-code/claude-code`, `scripts/cct`.

**Commits.** (1) the lexer extraction alone, routing suite unchanged at
365 with identical output, per D4's condition; (2) the sanitizer move,
with the five test lines that read the function from its file; (3) the
catalog, the launch, the CLI, tests and docs.

**Proof.** The two suites drive the real launcher with a stub `claude`
that records its argv and whole environment, a stub cmux and a stub
tmux; a planted credential is asserted absent from everything typed,
printed and logged. A launch without `--llm` is compared with master's
launcher. The real Claude Code binary is run through `--llm` against
local stub endpoints, in a throwaway home, and what it sends is
recorded under `verification/`.

## Remaining slices (proposed 2026-11-23)

**Where #400 stands.** The launch-first slice (#479, PR #480, and the
rulings of 2026-11-20 in L11–L13) shipped the catalog file, `cct llm
list` and `validate`, and `--llm` for Claude Code with child-side
resolution, the clear-list and the static refusals. Everything the
spec's "Deferred, unchanged" paragraph lists is still owed, and two
departures are still in force: unverified targets launch with a notice
(1), and resume is not enforced (2). Installed on the build machine on
2026-11-23: `claude` 2.1.331 (the capture used 2.1.329), `codex-cli`
0.147.0, `pi` 0.83.0, `kiro-cli` 2.36.0.

**Ruled by the owner on 2026-11-23** (`origin/2026-11-23-replan-rulings.md`):

- The order is S0, S1, S2, then S4 before S3; S5 any time after S1.
- Codex and Pi are captured in S0, and Kiro at the start of S8.
- Every capture is a re-runnable script, stamped with the version of
  the CLI it ran against.
- `[llm].allowed` is read from `.cct.toml` only: not from
  `.cct.local.toml`, and not from the legacy
  `.code-copilot-team/config.toml`. S5 also teaches Pi's config lint
  the `[llm]` table.
- This plan goes to review as a plan-only PR, "Part of #400", closing
  nothing; the S0 and S1 issues are filed after it merges. Nothing
  merges until the owner says whether 2.1.1 ships first.

**The slices.** Each is its own issue and PR, says "Part of #400", and
adds its task rows to `tasks.md` when its issue opens. Only S10's PR
closes #400. The letters are the approved plan's.

| Slice | From | Delivers | Depends on | Size |
|---|---|---|---|---|
| S0 Captures: Codex and Pi | Task 0 of C and D | Facts only, from two re-runnable scripts that stamp the CLI version. Codex: nested `-c model_providers.*`, `wire_api` values, `--profile` layering, `codex resume`, the model field of `exec --json`. Pi: overlay versus owned merge for FR-22, an unknown `--provider`, `--session-id`, `$VAR` interpolation from the child environment. Both run against local stub endpoints, as the Claude Code capture did. Outcome: the D10 contingency known, D11 put to the owner as a recorded amendment, the rule table's Codex and Pi rows taken from evidence | — | S |
| S1 Launch plan and read-only surfaces | A3 (digests), A6, A7 (part), B6 | The LaunchPlan JSON schema with `env_clear`; `catalog_digest`, `launch_identity_digest` and `options_digest` computed read-only; the Claude Code launcher builds its plan through the resolver with argv and environment byte-for-byte as today; `cct llm show`, `cct harness explain claude-code --llm <target>`; `--json` for `list`, `validate`, `show` and `explain` against `shared/schemas/llm-catalog-cli.schema.json`; `pi-code --llm` refused as "adapter not implemented"; the supervisor and benchmark suites assert their native launches unchanged | — | M |
| S2 Compatibility, read-only | A2, A4, A9 (doctor) | The state-file primitives (FR-29) with their tests; the rule table as data (FR-14), with the S0 facts and departure 3; the five states (FR-13) keyed by the evidence digest; two-part records (FR-16); `cct llm compatibility [--json]`; `cct doctor`'s LLM catalog section (FR-28). Launches do not change | S0, S1 | M |
| S4 Stamps and exact-id resume, Claude Code | B1 (rest), B4, A7 (`sessions`) | Opens with the Claude Code capture as a re-runnable script stamped with the CLI version (amendment 4), adding `--session-id` on a new session, the transcript that proves it and the JSON model field; generated session ids (D9); stamps `attempted` to `established` (FR-17); the resume rules (FR-18) and re-resolution (FR-19), which retire departure 2; `cct llm sessions` | S1, S2 | M |
| S3 Probe and the D7 gate | A5, B5, B2 (`--allow-unverified`) | The probe runner (FR-15) over canary primitives extracted from `routing-probe.sh` with routing pins unchanged (D6); the watchdog; the stub gateway with one negative-control switch per capability; `cct llm test`; Claude Code launches refuse `unverified` and `incompatible` targets, with `--allow-unverified` (D7, or open decision 1's milder rule), which retires departure 1; the real binary run through the stub gateway with every switch, and once against a configured target, quoted in the PR | S2, S4 | L |
| S5 Project policy | A8 | `[llm].allowed` (FR-24, D13), read from `.cct.toml` only, by the Claude Code launcher as well as `pi-code` (amendments 1 and 5); Pi's config lint (`adapters/pi/runtime/config/lint.ts`, which `scripts/validate-cct-config.sh` also runs) learns the `[llm]` table | S1 | S |
| S6 Codex (C) | C | `adapters/codex/bin/codex-code` with `--llm`, the `-c` overlay (D10), native passthrough byte-for-byte, stamps, exact-id resume, the probe; a disproving S0 capture stops the slice for a ruling | S0–S4 | L |
| S7 Pi (D) | D | `--llm` on `pi-code`, `--provider`/`--model` through the form D11 rules, stamps, exact-id resume, native byte-for-byte, the probe | S0–S4 | L |
| S8 Kiro (E) | E | Opens with the Kiro capture, a re-runnable script stamped with the CLI version: model ids, `--model` on new and resumed sessions, session id discovery, headless output. Kiro has no endpoint to stub, so the capture uses the owner's Kiro login and runs only on the owner's word. Then `adapters/kiro/bin/kiro-code`, managed models only (FR-23), endpoint bindings `unsupported`, the managed-harness evidence contract, stamps and resume | S1–S4 | M |
| S9 Unified entry and Studio (F) | F | `cct harness start` and `exec` (D15); a Studio page over the `--json` surfaces: targets, states, the explained launch, non-secret edits through the validator, the id-only command to copy; Studio never starts a harness (D14) | S1–S4, and the adapters that have landed | L |
| S10 Routing reference (G) | G | `llm =` and `binding =` in routing profiles with conflict refusals (FR-25); the supervisor resolves through the resolver; journal and stamp agree by launch-identity digest; `docs/llm-routing.md`; closes #400 | S1–S9 merged | M |

**Order.** S0, S1, S2, S4 and S3, in that order, as the owner ruled; S5
can land any time after S1. The adapters S6–S8 follow S3 and S4, since
each carries the probe, the stamp and the resume contract, and they are
independent of each other; S8 opens with its own capture. S9 follows
them, and S10 comes last.

**Why the captures come first.** The approved plan runs each capture as
its adapter's first task. Capturing Codex and Pi in S0, before S2, lets
the rule table start from evidence rather than placeholders and puts
the D10 contingency and the D11 ruling in front of the owner early, at
the cost of two scripts and their records and no product code. Each
script names the CLI version in the record it writes, so a newer CLI is
re-captured by running it again.

**User-visible changes along the way.**

- S4 refuses `--continue` and the resume picker with `--llm`, and a
  resume under a different target, as FR-18 rules.
- S3 refuses a target until `cct llm test` passes for it, as D7 rules;
  `--allow-unverified` launches with a notice. In full: the evidence
  digest (FR-9) includes the harness version, so every Claude Code
  update returns every target to `unverified` (FR-13), and under D7 as
  ruled each target is then refused until it is tested again. Claude
  Code updates often: the installed version moved from 2.1.329 to
  2.1.331 between 20 and 23 November. Open decision 1 is a milder rule.
  S3's CHANGELOG entry carries an upgrade note either way.

**Spec amendments this plan needs.** Each is recorded in `spec.md`
with its date when its slice starts, never as a silent edit:

1. FR-24 and the scenario that quotes it name
   `.code-copilot-team/config.toml`. `[llm].allowed` is read from
   `.cct.toml` only (#460): not from `.cct.local.toml`, and not from
   the legacy file (S5).
2. Departure 8 added `auto_compact_window`; FR-9's options digest
   gains it beside `small_fast_model`, `max_output_tokens`,
   `reasoning_effort` and `thinking` (S1).
3. FR-14's rule table states departure 3: a Claude Code binding may
   name a `managed` provider, with no endpoint, meaning Claude Code's
   own login (S2).
4. The FR-20 capture is re-run on the installed `claude`, by a
   re-runnable script stamped with the CLI version, before S4 and S3
   rely on it: 2.1.331 may carry variables 2.1.329 did not (S4).
5. `.cct.toml` is read by Claude Code launches as well as by Pi; today
   only `pi-code` reads it (S5).

**Open decisions.**

1. **S3: a target tested on an older harness version.** As ruled (D7
   with FR-13's evidence digest), every Claude Code update refuses
   every target until it is tested again. The milder rule: refuse a
   target that was never tested, whose latest conclusive record
   failed, or whose launch identity changed; give a notice, and
   launch, when only the harness version is newer than the one its
   passing record was measured on. Adopting it amends FR-12, FR-13 and
   D7. A changed tuning option or rule version is neither case, so the
   ruling places those too.
2. **The release that ships these slices.** Six source files (the
   `claude-code` launcher and its `harness-stamp.sh` hook, `pi-code`,
   `home.ts`, `cct-home.sh`, `home.py`), `docs/cct-home.md` and the
   2.1.0 upgrade notes say 2.2 removes the legacy-home fallbacks:
   `~/.code-copilot-team` and a project's
   `.code-copilot-team/config.toml`. These slices add features, so the
   release that ships them would be 2.2.0. Either that release also
   removes the fallbacks, as those texts promise, or the removal moves
   to a later version and the texts change with it.

**Proof and gates.** As "Test strategy" and "Delivery gates" above, per
slice: every probe matrix quoted in a PR comes from a real harness run,
never a mock, and a planted secret and a planted path token are absent
from every artifact.

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
