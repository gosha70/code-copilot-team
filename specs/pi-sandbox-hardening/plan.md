---
spec_mode: full
feature_id: pi-sandbox-hardening
risk_category: security
justification: |
  Closes #173. Two of the issue's three asks (sandbox backend integration +
  CI security battery) already shipped (T10.1/T10.4, T11.5); the net-new,
  security-sensitive work is environment scrubbing at the CCT-controlled spawn
  boundaries (subagent child sessions + the worktree-run worker handoff) so
  host credentials do not flow into sub-sessions. Name-based, fail-safe,
  audited, config-gated; the primary interactive session is explicitly out of
  scope and the containment boundary stays honestly degraded (Pi detects and
  gates sandboxes; it never creates one).
status: draft
date: 2026-08-06
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/173
  origin_claim: |
    Out of the box, the Pi coding agent operates with the raw terminal
    permissions of the active host user. Implement
    design-t115-security-battery.md and evaluate robust sandbox backends to
    force agent runtime tools into an isolated environment. Requirements:
    (1) backend integration — evaluate/choose an isolation wrapper layer;
    (2) environment variable scrubbing — intercept host process parameters to
    strip AWS, GitHub, or internal API tokens before exposing the shell to the
    subagent; (3) execution battery — a baseline adversarial suite that
    executes cleanly in CI. Acceptance: destructive commands in a Pi
    sub-session are contained; file access restricted to the repository
    boundary; the battery validates rules in CI.
---

# Plan: Pi sandbox hardening (#173) — env scrubbing + honest closure

## Existing facts (verified 2026-08-06 on `0f908fb`)

- `policy/sandbox.ts` ships `SandboxProvider`, a docker detector, an
  env-declaration backend, `detectSandbox()`, fail-closed `sandboxGate()`;
  `index.ts` wires both at `session_start` (report/audit) and `tool_call`
  (deny while unsatisfied). `sandbox-backends-eval.md` (T10.4) records the
  backend decision: explicit declaration, **no new blind detectors**.
- `security-battery.test.mjs` (8 canonical invariants) +
  `cross-adapter-contract.test.mjs` + the `security-battery.md` manifest exist
  and run in `.github/workflows/pi-tests.yml` behind an anti-skip guard.
- The exposure: `child-session.ts` `runSubagent` spawns with
  `env: { ...process.env, ...built.env }`; `bin/pi-code worktree run` exports
  `CCT_WORKER_*` and re-execs the launcher, which execs pi with the full host
  env. Nothing scrubs credentials at either boundary.
- Config lint (`config/lint.ts`) registers exact known keys; `security.*`
  currently has no scrub keys. Capability registry = 4 files
  (`shared/capabilities/catalog.yaml|pi.yaml|claude-code.yaml`,
  `adapters/pi/runtime/capabilities.ts`) enforced by
  `scripts/validate-capabilities.sh` (every catalog id classified by every
  adapter).
- `workflow/memory.ts containsSecret` is the **value-side** redaction guard
  used by persistence surfaces — distinct concern, untouched here.

## Design

### D0 — Build-discovered deltas (recorded 2026-08-06, build phase 1)
Three facts surfaced during implementation that adjust HOW (never WHAT):
1. **Floor engine not used for `env_scrub`.** `config/floor.ts`
   RELAXATION_LAYERS excludes the `global` layer, so a floored default-ON
   bool could never be disabled from the user's own global config —
   contradicting resolved decision 1/5. The FR-004a asymmetry is instead
   enforced by **provenance** in `resolveScrubPolicy`: the checked-in
   `project` layer is honored only when it tightens (enable-only for
   `env_scrub`; union-only for `env_scrub_extra`; ignored for
   `env_scrub_keep`).
2. **`runSubagent` has no live caller yet** (T7.2 is a library awaiting its
   live wiring), so "index.ts supplies the scrub option" has no call site.
   Scrub is instead part of the runner's contract: `scrub?: ScrubPolicy |
   false` where omitted ⇒ built-in default policy (fail-safe ON — a future
   caller that forgets config still scrubs), `false` ⇒ trusted opt-out,
   policy ⇒ config-resolved. Removed names are reported in
   `ChildResult.scrubbedEnv` (names only) for the future live wiring to
   audit.
3a. **Phase-1 review addendum (2026-08-06).** The phase-1 review hardened
   delta 1: BOTH in-repo layers (`project` AND `project-local`) are
   tighten-only — `config.local.toml` is gitignored by convention only, so a
   repo can commit one (verified: it is not ignored in this repo). This
   deliberately diverges from floor.ts's RELAXATION_LAYERS. Precedence is an
   ordered walk, so a later user-controlled explicit boolean beats an
   earlier repo `env_scrub = true` latch (review F2). Keep globs are exact/
   `PREFIX_*` only (F8); defaults gained `ANTHROPIC_AUTH_TOKEN` + AWS
   selector keeps (F3) and `PGPASSWORD`/`SSH_AUTH_SOCK`/`DOCKER_AUTH_CONFIG`/
   `*_PAT` patterns (F5); the test fixture dumps env NAMES (values only for
   CCT_*/MOCK_PI_* canaries) and cleans up (F4); no scrub is reported when
   no spawn happened (F6). A custom `providers.*.api_key_env` name must be
   kept via `security.env_scrub_keep` — auto-keeping it is future wiring.
3b. **Phase-2 review addendum (2026-08-06).** The phase-2 review proved one
   leak and hardened the handoff: (F1) removal now happens via
   `exec /usr/bin/env -u NAME ...` so names that are not shell identifiers
   (e.g. `my-app_TOKEN`, which bash `unset` cannot touch) are also removed —
   proven end-to-end; (F2) the scrub-list call moved BEFORE provisioning, so
   a scrub-list failure refuses the handoff with NO git side effects — and
   that made the fail-closed branch constructible (NODE_OPTIONS recipe) and
   tested; (F3) an unscrubbed handoff is never silent — the CLI prints an
   explicit disabled marker (final form `=disabled=<layer>` — unforgeable,
   since an env var name can never contain `=`; the interim `#` form was
   spoofable and replaced in the final round) via new `disabledBy`
   provenance in `resolveScrubPolicy`, the launcher exports `CCT_ENV_SCRUB_OFF=<layer>`
   or an always-present `CCT_ENV_SCRUBBED` (empty = "ran, nothing matched"),
   and the worker session_start audits `env.scrub` as `scrubbed` (count may
   be 0) or `disabled` (with the layer); (F4) stderr is never fed to the
   name parser; (F5) audit truncation is marked (`,[truncated]`) with a
   pre-slice count, and control chars are stripped from audited names —
   forgeability by a real worker session is documented as mitigated by
   attach validation, not eliminated; (F6) per-name unset failure is
   impossible by construction under `env -u`; (F7) empty failure output no
   longer prints a bare error line.
4. **Launcher boundary is global/env/cli-scope only.** The loader's trust
   contract never reads project layers untrusted, so the out-of-session CLI
   cannot see a project-local `env_scrub_extra` either; launcher-side
   tightening from checked-in project config does not apply (it still applies
   in-session). The live `env.scrub` audit for the worker handoff is emitted
   at the worker's `session_start` from `CCT_ENV_SCRUBBED` (names only,
   sanitized, set by the launcher after unsetting).

### D1 — `policy/env-scrub.ts`: pure policy, names only
`resolveScrubPolicy(cfg)` merges built-in patterns (`AWS_*`, `GITHUB_TOKEN`,
`GH_TOKEN`, `NPM_TOKEN`, `*_TOKEN`, `*_SECRET`, `*_KEY`, `*_PASSWORD`,
`*_PASSPHRASE`, `*_CREDENTIAL`, `*_CREDENTIALS`) with
`security.env_scrub_extra`, and built-in keeps (`PATH`, `HOME`, `SHELL`,
`TERM`, `LANG`, `LC_*`, `TMPDIR`, `USER`, `LOGNAME`, `CCT_*`,
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `PI_API_KEY`) with
`security.env_scrub_keep`. `scrubEnv(env, policy)` returns `{ env, removed }`;
exact-name keeps beat patterns; values are never inspected. Pattern syntax is
prefix/suffix globs only (no regex from config — bounded, no ReDoS).

### D2 — Subagent boundary (`child-session.ts`)
`runSubagent` builds `env: { ...scrubEnv(process.env, policy).env,
...built.env }` when `security.env_scrub` resolves true (default ON), and
audits `env.scrub` (count + removed names) per spawn. The pure builder
`buildChildArgv` stays pure/untouched; the policy applies at the spawn site.
Plumbing: `runSubagent` gains an optional `scrub` option supplied by the
caller in `index.ts` (which owns config) — the library keeps no config read.
In-session policy resolution uses the session's trust-gated config load;
even in a positively-trusted session the in-repo layers may only tighten —
loosening requires the user's own scopes (global config, env, cli). See the
phase-1 review addendum in D0.

### D3 — Worker handoff (`bin/pi-code`), one pattern source, trust-aware
A read-only CLI surface `pi-code env scrub-list [--json]` prints the names the
launcher must unset, computed by `scrubEnv` against the CLI's own env. The
CLI resolves project config as **untrusted** outside a session (existing
`pi-code` trust model), so it applies the FR-3 asymmetry directly: the
off-switch and `env_scrub_keep` are read from **global/user config only**;
project-local config at `CCT_CLI_CWD` contributes only `env_scrub_extra`
(tightening). A project-local `security.env_scrub=false` is ignored at this
boundary — launcher-side opt-out is global-config-authoritative (documented).
In the `worktree run` path (and only there), when scrubbing is enabled the
launcher captures that list and `unset`s each name before the final exec.
CLI failure while scrub is enabled ⇒ refuse the handoff with a clear message
(fail closed — never silently unscrubbed); scrub disabled **in global/user
config** ⇒ pass-through, no CLI call. Bash stays 3.2-safe (while-read loop,
no arrays needed beyond existing patterns).

### D4 — Config + capability + docs
`config/lint.ts`: register `security.env_scrub`, `security.env_scrub_keep`,
`security.env_scrub_extra`. Capability `security.env-scrub` in the 4 registry
files — Pi `degraded` (enforced at CCT spawn boundaries; primary session
untouched by design), Claude Code `disabled`. Docs: scrub contract +
primary-session boundary in `adapters/pi/docs/security-model.md`; README/help
lines; `configuration-reference.md` keys.

### D5 — Battery + manifest (T11.5 pattern: consolidation)
`security-battery.test.mjs` gains invariant 9: with `AWS_SECRET_ACCESS_KEY`,
`GITHUB_TOKEN`, `X_TOKEN` in the parent env, the scrubbed spawn env contains
none of them and still contains `PATH` + `CCT_*` + a configured keep.
`security-battery.md` gains the row + an explicit "#173 closure mapping"
section (ask 1/3 delivered by T10.x/T11.5; ask 2 by this feature; containment
honestly degraded — the operator's sandbox contains, Pi detects/gates).

### D6 — Honest #173 closure
The PR targets **#173 only** (close-keyword audit per standing rule). The
closure comment carries the gap-mapping table from `spec.md`.

## Deliverables

1. `adapters/pi/runtime/policy/env-scrub.ts` (+ unit tests).
2. `child-session.ts` spawn-site scrub + `index.ts` plumbing + audit.
3. `cli.ts` `env scrub-list` + `bin/pi-code` worktree-run unset loop + help.
4. Config lint keys; capability entry ×4 files; docs.
5. Battery invariant + manifest row + closure mapping.

## Sequencing

1. D1 pure module + tests.
2. D2 subagent boundary + audit + tests (real spawn shim).
3. D3 CLI + launcher handoff + launcher test.
4. D4 config/capability/docs (+ registry gate green).
5. D5 battery + manifest; full gates.

## Test strategy

- **Pure:** pattern/keep semantics incl. `LC_*`/`CCT_*` prefixes, exact-keep
  beats pattern, extra/keep config merging, no value reads (API shape).
- **Subagent:** real `runSubagent` with a pi shim asserting the child's actual
  env (dump env in shim) — credential names absent, keeps present; audit
  record emitted; `security.env_scrub=false` ⇒ pass-through.
- **Launcher:** `tests/test-pi-launcher.sh` — worker exec env scrubbed, the
  `CCT_WORKER_*` contract survives, CLI-failure ⇒ handoff refused (fail
  closed), scrub-off **via global config** ⇒ no CLI dependency; a
  project-local `security.env_scrub=false` is provably ignored by
  `env scrub-list` while a project-local `env_scrub_extra` still tightens
  (the trust-asymmetry tests).
- **Battery:** invariant 9 as above; manifest row asserted present.
- **Registry:** `validate-capabilities.sh` green with the new id ×4.

## Resolved decisions (settled with the user, 2026-08-06)

1. **Default ON** — `security.env_scrub` defaults true; opt-out honored from
   trusted scopes per decision 5. Subagent spawning is itself opt-in
   (`agents.subagents_enabled`) and the keep-list keeps children functional.
2. **Keep-list defaults** — `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
   `PI_API_KEY` (plus the OS/CCT baselines); anything else via
   `security.env_scrub_keep`.
3. **Capability status** — Pi `degraded` (enforced at CCT spawn boundaries
   only; primary session untouched by design); Claude Code `disabled`.
4. **Handoff mechanism** — CLI-computed unset list (`pi-code env scrub-list`),
   single TS pattern source, fail-closed when the call fails while scrub is
   enabled.
5. **Trust asymmetry for scrub config** (pre-commit review + phase-1 review,
   2026-08-06) — loosening keys (`env_scrub=false`, `env_scrub_keep`) are
   honored only from user-controlled scopes: global config, `CCT_CONFIG__*`
   env, cli `--set`. BOTH in-repo layers (`config.toml`, `config.local.toml`)
   are tighten-only, and a later user-controlled explicit boolean beats an
   earlier repo enable (ordered walk). Tightening (`env_scrub_extra`) is
   honored from any layer. The out-of-session CLI (`env scrub-list`) treats
   project config as untrusted (existing model) and therefore never honors a
   project-local opt-out — no FR-004a bypass, and launcher pass-through tests
   target global config, not project config.
