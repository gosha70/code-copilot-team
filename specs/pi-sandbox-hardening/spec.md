# Spec: Pi sandbox hardening — close #173 (env scrubbing + honest gap mapping)

Source: GitHub issue **#173** ("Zero-Trust Sandbox Isolation & Security
Battery", `design-t115-security-battery.md`). Gap analysis 2026-08-06: two of
the issue's three asks are **already delivered** on master; the net-new work is
**environment-variable scrubbing at the CCT-controlled spawn boundaries**, plus
the honest mapping that lets #173 close without overclaiming.

## Gap analysis (verified against master `0f908fb`)

| #173 ask | Status | Delivered by |
|---|---|---|
| 1. Backend integration — evaluate/choose isolation wrapper | **DONE** | T10.1 `policy/sandbox.ts` (`SandboxProvider`, docker + env-declaration backends, `detectSandbox`, fail-closed `sandboxGate`, wired at `session_start` + `tool_call`); T10.4 `specs/pi-harness-adoption/sandbox-backends-eval.md` (recommendation: explicit declaration; **no new blind detectors**) |
| 2. Env-var scrubbing before exposing the shell to the subagent | **MISSING** | — this spec's net-new scope |
| 3. Execution battery runs cleanly in CI | **DONE** | T11.5 `tests/pi-runtime/security-battery.test.mjs` + `cross-adapter-contract.test.mjs` + manifest `specs/pi-harness-adoption/security-battery.md`, executed by `.github/workflows/pi-tests.yml` (with an anti-skip guard) |

The exposure that remains: `agents/child-session.ts` spawns a subagent with
`env: { ...process.env, ...built.env }` — the **full host environment**
(cloud/GitHub/API credentials included) flows into every child session — and
the `pi-code worktree run` handoff exec's the worker pi with the full host env.

## User Scenarios

- **US1 — Subagent gets a scrubbed environment.** As a developer running
  subagent delegation, a child Pi session spawned by the runtime does **not**
  inherit my host credentials (AWS keys, GitHub tokens, generic `*_SECRET`/
  `*_TOKEN` values); it still receives everything it needs to run (PATH/HOME,
  the CCT contract vars, its LLM provider credential).
- **US2 — Worker handoff is scrubbed.** As an operator using
  `pi-code worktree run`, the worker session launched inside the worktree gets
  the same scrubbed environment — the `CCT_WORKER_*` contract survives, the
  host credential set does not.
- **US3 — Honest closure.** As the project owner, when #173 closes I can point
  at an auditable mapping: which acceptance items are enforced, which are
  satisfied by already-shipped work, and which are **degraded by construction**
  (Pi cannot itself create a sandbox — containment is the operator's
  sandbox/backend, detected + gated, never fabricated).

## Requirements

- **FR-1 — Pure scrub policy, single source of truth.** A pure function
  `scrubEnv(env, policy) → { env, removed }` in `policy/env-scrub.ts`.
  Blocklist of credential-shaped **names** (patterns: `AWS_*`, `GITHUB_TOKEN`,
  `GH_TOKEN`, `NPM_TOKEN`, and generic suffixes `*_TOKEN`, `*_SECRET`,
  `*_KEY`, `*_PASSWORD`, `*_PASSPHRASE`, `*_CREDENTIAL`, `*_CREDENTIALS`),
  minus a **keep-list** that always survives: `PATH`, `HOME`, `SHELL`, `TERM`,
  `LANG`/`LC_*`, `TMPDIR`, `USER`, `LOGNAME`, every `CCT_*` contract var —
  **except the loader's two env-borne config carriers — the `CCT_CONFIG__*`
  namespace and `CCT_CLI_SETS` (the `--set` layer) — which are scrubbed
  wholesale** (both are sanctioned to carry arbitrary config values
  including secrets, and name shape cannot recognize every secret-bearing
  config key; only an exact-name keep from a trusted scope restores a
  specific carrier var, never a prefix or suffix glob) — and the child's LLM provider
  credential(s) (configurable — see FR-3). Matching is on names only;
  **values are never read, logged, or persisted**.
- **FR-2 — Enforced at CCT-controlled spawn boundaries only.**
  (a) `runSubagent` (`agents/child-session.ts`) spawns with the scrubbed env;
  (b) the `pi-code worktree run` handoff scrubs before exec'ing the worker.
  The **primary interactive session is out of scope** — its environment is the
  user's own shell, and scrubbing it would be a behavior change to the user's
  session, not a subagent boundary (documented, not silent).
- **FR-3 — Config-gated, fail-safe defaults, trust-asymmetric.** New keys
  (registered in `config/lint.ts`): `security.env_scrub` (bool, **default
  ON**), `security.env_scrub_keep` (extra exact names to keep),
  `security.env_scrub_extra` (extra name patterns to scrub). Keep defaults
  include the LLM provider keys a child pi needs to run (`ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`, `PI_API_KEY`, plus `ANTHROPIC_AUTH_TOKEN` for
  gateway/local-LLM provider setups and the non-secret `AWS_REGION`/
  `AWS_DEFAULT_REGION`/`AWS_PROFILE` selectors) so default-ON scrubbing does
  not brick child sessions; the keep-list (exact names or `PREFIX_*` globs —
  deliberately narrower than patterns, since keeps loosen) wins over
  patterns and is itself documented. **Trust asymmetry (FR-004a):** config
  that *loosens* the policy (`env_scrub=false`, `env_scrub_keep`) is honored
  only from genuinely **user-controlled** scopes — global/user config,
  `CCT_CONFIG__*` env, `pi-code --set` (cli). **Both** in-repo layers
  (`config.toml` and `config.local.toml`) may only tighten:
  `config.local.toml` is gitignored by convention only, so a repo can commit
  one, and a silently-honored scrub opt-out there is exactly the
  exfiltration vector this feature closes (a deliberate, recorded divergence
  from floor.ts's relaxation-layer precedent). Precedence is **ordered**: a
  later user-controlled layer's explicit boolean beats an earlier repo
  enable (a repo cannot latch scrubbing against the user's own opt-out).
  Config that *tightens* (`env_scrub_extra`) is honored from any layer. A
  repo's config can therefore never weaken scrubbing.
- **FR-4 — One pattern source for both languages, CLI-side trust honored.**
  The bash launcher must not carry its own copy of the pattern list (drift
  risk). `bin/pi-code` obtains the resolved unset list from the runtime (a
  read-only CLI surface, e.g. `pi-code env scrub-list`) and unsets exactly
  those names before the worker exec; the CLI computes it with the same
  `scrubEnv` against the launcher's environment. Because `pi-code`
  diagnostics resolve project config as **untrusted** outside a session, the
  CLI applies the FR-3 asymmetry structurally: project layers are simply
  never read untrusted (the loader's existing contract), so the whole scrub
  policy — off-switch, keeps, extras — resolves from **global/user config +
  env/cli overrides only** at this boundary. A project-local
  `security.env_scrub=false` is **ignored** here — launcher-side opt-out is
  global-config-authoritative — and a checked-in `env_scrub_extra` tightens
  the in-session boundary only. Launcher stays bash-3.2 compatible. If the CLI
  call fails while scrubbing is enabled, the handoff **fails closed** (never
  continues silently unscrubbed — refused, surfaced, audited).
- **FR-5 — Audit + honesty.** Each scrubbed spawn audits `env.scrub` with the
  **count and names** of removed variables (names only, never values). Docs:
  `adapters/pi/docs/security-model.md` gains the scrub contract + the
  primary-session boundary; the #173 closure comment maps all three asks.
- **FR-6 — Capability entry.** New id `security.env-scrub` across the four
  registry files (`shared/capabilities/catalog.yaml`, `pi.yaml`,
  `claude-code.yaml`, `adapters/pi/runtime/capabilities.ts`). Pi:
  **`degraded`** — enforced at CCT spawn boundaries; the primary session's env
  is untouched by design and Pi cannot verify what the OS/sandbox exposes.
  Claude Code: **`disabled`** (not implemented in that adapter; its sandboxing
  is native). `validate-capabilities.sh` stays green.
- **FR-7 — Battery consolidation.** One new canonical invariant in
  `security-battery.test.mjs`: a credential-shaped var present in the parent
  env does **not** survive into the built child env, while `CCT_*` and
  keep-list vars do. A row in the `security-battery.md` manifest, plus a
  "degraded, not parity" note reaffirming that fork-bomb/OS containment is the
  sandbox backend's job (#173 AC-1 honesty).

## Constraints / What NOT to Build

- **No re-implementation** of `detectSandbox`/`sandboxGate` and **no new blind
  detectors** (the T10.4 recommendation stands: unverified backends are
  explicit declarations).
- **No scrubbing of the primary interactive session's environment.**
- **No value-based secret detection here** — `containsSecret` remains the
  value-side guard for persistence surfaces; this feature is name-based at
  spawn time (values are never read).
- **No daemon, no new Pi event source** — wiring touches only the existing
  spawn sites, CLI dispatch, and config/registry surfaces.
- Never break a working child session silently: scrub failures and refusals
  are surfaced + audited, and the keep-list defaults must keep children
  functional with scrubbing default-ON.

## Key Entities

- `ScrubPolicy` — `{ patterns: string[], keep: string[] }`, resolved from
  built-in defaults + `security.env_scrub_extra` + `security.env_scrub_keep`.
- `ScrubResult` — `{ env: Record<string,string>, removed: string[] }`.
- Config keys — `security.env_scrub`, `security.env_scrub_keep`,
  `security.env_scrub_extra`.
- Capability id — `security.env-scrub` (four files).
- Audit rule — `env.scrub` (names + count only).

## Success Criteria

1. A child session spawned via `runSubagent` with `AWS_SECRET_ACCESS_KEY`,
   `GITHUB_TOKEN`, and `FOO_TOKEN` in the parent env receives **none of them**;
   it still receives `PATH`, `CCT_AGENT_*` correlation vars, and configured
   keep names. Proven with a real spawn (shim) test, not just the pure builder.
2. `pi-code worktree run` launches the worker with the same scrub applied and
   the `CCT_WORKER_*` contract intact (launcher test with a pi shim).
3. `security.env_scrub=false` restores pass-through from **user-controlled
   scopes only** (global config, `CCT_CONFIG__*` env, cli `--set`). Both
   in-repo layers are provably unable to loosen — opt-out and keep additions
   from `config.toml`/`config.local.toml` are ignored (tests) — and a later
   user opt-out beats an earlier repo enable. Checked-in `env_scrub_extra`
   tightens the in-session boundary (the untrusted CLI never reads project
   layers at all). All three keys lint-registered.
4. Every scrubbed spawn emits an `env.scrub` audit record with removed names +
   count; no secret **value** ever appears in any log/audit/artifact.
5. The battery gains the scrub invariant; `pi-tests.yml` gates stay green
   (runtime suite, typecheck, launcher, capability registry).
6. #173 can close with the gap-mapping table above — nothing claimed enforced
   that is actually degraded/declared.
