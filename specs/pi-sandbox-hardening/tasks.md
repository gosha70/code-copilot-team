# Tasks: Pi sandbox hardening (#173) — env scrubbing + honest closure

Wiring/policy only — `detectSandbox`/`sandboxGate` (T10.1), the backend
evaluation (T10.4), and the battery/manifest structure (T11.5) already exist
and MUST NOT be re-implemented. Keep gates green (`test-pi-runtime.sh`,
`test-typecheck-gate.sh`, `test-pi-launcher.sh`, `validate-capabilities.sh`).
Targets **#173**. `AC` = acceptance criterion in `spec.md`.

## US1 — Scrubbed subagent boundary

| # | [P] | Task | File(s) | AC |
|---|-----|------|---------|----|
| 1 | | `policy/env-scrub.ts`: `resolveScrubPolicy(cfgReader)` + pure `scrubEnv(env, policy) → {env, removed}`; prefix/suffix glob patterns only (no config regex); exact keeps beat patterns; `CCT_*`/`LC_*` prefix keeps; never reads values. | `policy/env-scrub.ts` | SC-1/3 |
| 2 | | Unit tests: pattern semantics, keep-beats-pattern, `env_scrub_extra`/`env_scrub_keep` merging, prefix keeps, empty/undefined values, no mutation of input. | `tests/pi-runtime/env-scrub.test.mjs` | SC-1/3 |
| 3 | | `runSubagent` spawn-site scrub via an injected `scrub` option; `index.ts` supplies it from config (default ON) + audits `env.scrub` (names+count, never values) per spawn. | `agents/child-session.ts`, `index.ts` | SC-1/4 |
| 4 | | Real-spawn test with a pi shim that dumps its env (NAMES + CCT_*/MOCK_PI_* canary values only; dump dir cleaned): credential names absent, `PATH`/`CCT_*`/keeps present; `security.env_scrub=false` ⇒ pass-through **only from user-controlled scopes** (global/env/cli — both in-repo layers tighten-only); `ChildResult.scrubbedEnv` reporting asserted (names only; the live `env.scrub` audit lands with the US2 handoff wiring per plan D0.2). | `tests/pi-runtime/child-session.test.mjs` (+ fixture) | SC-1/3/4 |

**Checkpoint US1** — child sessions cannot see host credentials; escape hatch +
audit proven.

## US2 — Scrubbed worker handoff (one pattern source)

| # | [P] | Task | File(s) | AC |
|---|-----|------|---------|----|
| 5 | | `cli.ts`: read-only `env scrub-list [--json]`, trust-asymmetric per the CLI's existing untrusted-project model: off-switch + `env_scrub_keep` from **global/user config only**; project config at `CCT_CLI_CWD` contributes only `env_scrub_extra` (tighten); project-local `env_scrub=false` ignored. Route in `runCli` + usage. | `cli.ts` | SC-2/3 |
| 6 | | `bin/pi-code`: in the `worktree run` path, when scrub enabled, capture `scrub-list` and `unset` each name before the final exec; CLI failure ⇒ refuse handoff (fail closed, clear message); scrub-off **per global/user config** ⇒ no CLI call. Bash 3.2. | `bin/pi-code` | SC-2/3 |
| 7 | | Launcher tests: worker exec env scrubbed with `CCT_WORKER_*` intact (shim dumps env); CLI-fail ⇒ refusal; global-config scrub-off pass-through; project-local `env_scrub=false` ignored while project-local `env_scrub_extra` tightens; help lists `env scrub-list`. | `tests/test-pi-launcher.sh` | SC-2/3 |

**Checkpoint US2** — the worktree-run worker starts scrubbed, from a single
TS pattern source, fail-closed.

## US3 — Config, capability, battery, honest closure

| # | [P] | Task | File(s) | AC |
|---|-----|------|---------|----|
| 8 | | Register `security.env_scrub`, `security.env_scrub_keep`, `security.env_scrub_extra` in config lint; document in `configuration-reference.md`. | `config/lint.ts`, docs | SC-3 |
| 9 | [P] | Capability `security.env-scrub` ×4 files — Pi `degraded` (CCT spawn boundaries only; primary session untouched by design), Claude Code `disabled`; registry gate green. | `shared/capabilities/*.yaml`, `capabilities.ts` | SC-5 |
| 10 | [P] | Battery invariant 9 (credential-shaped var does not survive into the scrubbed spawn env; keeps do) + `security-battery.md` row + "#173 closure mapping" section (asks 1/3 already delivered; containment honestly degraded). | `tests/pi-runtime/security-battery.test.mjs`, `specs/pi-harness-adoption/security-battery.md` | SC-5/6 |
| 11 | | Docs: scrub contract + primary-session boundary in `security-model.md`; README pointer; launcher help. | `adapters/pi/docs/*`, `bin/pi-code` | SC-6 |

**Checkpoint US3** — #173 closable with an auditable, non-overclaiming map;
all gates green.

## Global definition of done (every task)

`build` + strict typecheck + pi-runtime suite + launcher suite +
capability-registry gate green · no re-implementation of sandbox
detection/gate · no new blind detectors · primary interactive session env
untouched · no secret **values** read/logged anywhere · scrub default-ON with
functional keep defaults, opt-out honored from trusted scopes only ·
**untrusted project config may tighten but never loosen scrub policy
(FR-004a)** · fail-closed handoff (never silently unscrubbed) · every scrub
audited (names+count) · PR closes **#173 only** (close-keyword audit on every
commit message + PR body).

---

## Status (build, 2026-08-06/07)

- **US1 (tasks 1–4): DONE** — commit `e3e10e3` + review-fix `ebb0cf6`;
  phase-1 review PASS on all 10 findings (re-verified).
- **US2 (tasks 5–7): DONE** — commit `3563a2b`; launcher suite 156/0
  (10 new #173 assertions). CLI-failure refusal covered by a source
  assertion (a scenario where provisioning succeeds but scrub-list fails is
  not constructible from outside the process — provisioning uses the same
  runtime and fails first).
- **US3 (tasks 8–11): built** — config keys (lint + BUILTIN_DEFAULTS
  default-ON), `security.env-scrub` ×4 registry files +
  regenerated COMPATIBILITY.md, battery #10 + manifest rows + #173 closure
  mapping, security-model/config-reference/README docs.
- **Review rounds (per-phase, review agent):** phase 1 → 10 findings fixed
  (`ebb0cf6`), re-verified PASS. Phase 2 → 7 findings incl. one proven leak
  (non-identifier names bypassing bash `unset`) fixed (`268b7c2`):
  env -u exec, pre-provision fail-closed ordering, always-audited handoff.
  Final round → spoofable `#` marker replaced by unforgeable `=disabled=`
  protocol, signal-var mutual exclusion + scrubbed-first audit precedence,
  /usr/bin/env preflight, argv-contract test (`9655d5d`).
- Final gates: pi-runtime 428/0 · typecheck 7/7 · launcher 167/0 ·
  capability registry 177/0 · cct-config 0 err · provider gate 7/0 ·
  adapter suite 144/1 (the 1 = pre-existing `prepare-release.sh` host-env
  failure, fails identically on the clean base — verified via stash).
