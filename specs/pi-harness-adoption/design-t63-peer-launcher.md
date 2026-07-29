# T6.3 Design Read — peer-review launcher flags + audited override (FR-000a)

Status: **design read — paused for decisions before implementation.**
Scope: `pi-code` mirrors the Claude Code launcher's peer-review flags
(`--peer-review [provider]`, `--peer-review-off`, `--peer-review-scope`), exports
the env contract (`CCT_PEER_REVIEW_ENABLED`, `CCT_PEER_PROVIDER`,
`CCT_PEER_REVIEW_SCOPE`), and provides an audited human override.

## Ground truth (verified)

**Claude parses these at a REAL launcher binary** (`adapters/claude-code/claude-code`,
not hook/skill-only): `--peer-review [provider]` (optional-provider heuristic via
`${2:0:2}` prefix checks so `--peer-review /path` ≠ `--peer-review gemini`),
`--peer-review-off` → `PEER_REVIEW_ENABLED=false`, `--peer-review-scope`
(**unvalidated**, default `both`). Emits `CCT_PEER_REVIEW_ENABLED`/`CCT_PEER_PROVIDER`/
`CCT_PEER_REVIEW_SCOPE` (+ non-required extras `CCT_PEER_TRIGGER`,
`CCT_REVIEW_COMMITS`, `CCT_REVIEW_MAX_ROUNDS`). The provider-collaboration SKILL
documents the same contract (and its bypass: `--peer-review-off` / `CCT_PEER_BYPASS`).

**pi-code launcher** (`adapters/pi/bin/pi-code`): CCT-option `case` parse loop
(`:200-223`) with a `-*)` catch-all that forwards unknown flags to `pi` — so new
flags MUST be explicit arms above it. Single enforced export block (`:279-285`).
bash-3.2 hazards: `set -euo pipefail`, empty-array `${a[@]+"${a[@]}"}` guard, no
`declare -A`, and the **`CCT_PI_MODE` case precedent** (`:264-277`): a per-element
loop tripped `set -e`/`$?` fragility in command substitution and was replaced by a
space-padded-join `case`. Mirror that pattern; avoid loops in `$(...)`.

**Review-loop consumption**: the `/cct:review-submit` handler (`index.ts:842-892`)
takes `peerProvider` from a command ARG (`parts[0]`) and HARDCODES
`reviewScope: "both"`. These flow into `initReviewState` → `.cct/review/state.json`.
**No `CCT_PEER_*` is read anywhere in the runtime today.**

**The load-bearing tension (decision C)**: `review.ts:123-129` deliberately IGNORES
ambient `CCT_REVIEW_*` — "the env layer's sanctioned path into config is
`CCT_CONFIG__*`; honoring ambient `CCT_REVIEW_*` too would open a second, unaudited
override channel." So: may launcher-set `CCT_PEER_*` feed the review loop? The
launcher is a *sanctioned, audited* source (it parses explicit user flags at
session start), unlike ambient shell env — but it is still env.

**Override surfaces today**: (1) `/cct:review-decide approve` → `writeDecision`
writes `bypass:true` loop-summary + **audits** it (`review.ts:322-353`,
`index.ts:894-920`) — the closest "audited human override". (2) floor
`relaxed-by-override` (`floor.ts:82-119`): CLI/env/session/project-local layers may
relax `review.mandatory`, recorded + reported. (3) SKILL `CCT_PEER_BYPASS` /
`--peer-review-off` — **documented, no pi runtime consumer**. `review.mandatory`
(`cfg` at `index.ts:579`) is the gate toggle.

**Divergence reporting**: `pi-code features` renders the capability seed's `reason`
field (drift-guarded TS+YAML). No dedicated launcher-parity capability; nearest is
`review.enforcement`.

## Proposed design (pending approval)

- **Launcher (bash-3.2-safe):** add explicit arms ABOVE `-*)`:
  `--peer-review [provider]` (mirror the `${2:0:2}` optional-provider heuristic) →
  `PEER_ENABLED=true`, optional `PEER_PROVIDER`; `--peer-review-off` → `PEER_ENABLED=false`;
  `--peer-review-scope <v>` → `PEER_SCOPE`. Export **only the required trio** on the
  ENFORCED path (`:279-285`), not on `--no-cct`. No loops in `$(...)`.
- **Review-loop wiring:** `/cct:review-submit` reads the session contract with clear
  precedence: **explicit ARG > `CCT_PEER_PROVIDER` > profile default** for provider;
  `CCT_PEER_REVIEW_SCOPE` (default `both`) replaces the hardcoded scope. This is a
  SEPARATE channel from `CCT_REVIEW_*` (which is config-authoritative limits) — the
  launcher is the audited source of *session intent*, read at an explicit user
  action, so it does not reopen the decision-C hole (A below).
- **Audited human override:** `--peer-review-off` (`CCT_PEER_REVIEW_ENABLED=false`) →
  when `review.mandatory` would block, the review gate instead records an AUDIT
  (`origin:"review-gate"`, `decision:"override"`, `rule:"peer-review-off"`) and
  permits phase-complete — never a silent skip. Consolidate `CCT_PEER_BYPASS` to the
  same path (give the documented-but-dead env a real, audited consumer).
- **Divergence reporting:** the required trio is fully mirrored (no divergence);
  note the un-mirrored Claude extras (`CCT_PEER_TRIGGER`, session-recreate, tmux) in
  `review.enforcement`'s `reason` rather than adding a new capability.

## Decisions needed

- **A — the decision-C boundary (the crux).** Confirm: launcher-set `CCT_PEER_*` may
  feed `/cct:review-submit` as *session intent* (provider/scope/enabled), read at an
  explicit user action and audited, WITHOUT violating decision C (which governs
  config-authoritative `CCT_REVIEW_*` limits, a different concern)? Precedence
  ARG > env > profile. — or must `CCT_PEER_*` route through the sanctioned
  `CCT_CONFIG__*` channel instead?
- **B — audited override semantics.** Confirm `--peer-review-off` records an audited
  override of the mandatory-review gate (not a silent skip), and `CCT_PEER_BYPASS`
  joins the same audited path?
- **C — scope.** T6.3 = peer-review launcher flags + env + audited review override
  only. Verify-gate override stays the existing floor `relaxed-by-override` path (no
  `CCT_VERIFY_*` here). `pi-code init`/`sync` = T6.4. Confirm.
- **D — `--peer-review-scope` validation.** Validate against `code|design|both`
  (fail-fast, fits pi-code's `set -euo` posture) — or mirror Claude's unvalidated
  acceptance? (I lean validate.)
- **E — env set.** Export ONLY the FR-000a required trio; do NOT mirror Claude's
  extras (`CCT_PEER_TRIGGER`/`CCT_REVIEW_COMMITS`/`CCT_REVIEW_MAX_ROUNDS`). Confirm.
- **F — divergence reporting.** Fold the parity note into `review.enforcement.reason`
  vs a new `launcher.parity` capability. (I lean fold-in, no new capability.)

## Scope boundary + tests

IN: launcher flag arms + exports (bash-3.2-safe, mirror the CCT_PI_MODE case
pattern), review-submit env wiring (ARG>env>profile, scope), the audited
`--peer-review-off`/`CCT_PEER_BYPASS` override, divergence note, launcher tests
(`test-pi-launcher.sh`: flag→export matrix incl. the optional-provider heuristic,
`--no-cct` carries no peer env, invalid scope rejected) + runtime tests
(env→submit precedence, audited-override record).

OUT: `pi-code init`/`sync` (T6.4); the Claude-extra env vars; generalizing to a
verify launcher contract.

## Review guardrails (internalized — not yet decisions)

Sharpening from review framing; A is the main risk.

- **A — `CCT_PEER_*` is session intent ONLY, never a config-policy backdoor.**
  - `CCT_PEER_PROVIDER`, `CCT_PEER_REVIEW_SCOPE` = pure session intent (which
    reviewer, what scope); precedence **ARG > env > profile**. They touch no
    policy and never write config.
  - `CCT_PEER_REVIEW_ENABLED=false` is the ONE env that could affect policy (does
    the mandatory-review gate block). It is therefore NOT a silent config channel:
    it is routed as an AUDITED override (B), recorded — it never writes
    `review.mandatory` or any `CCT_CONFIG__*` value, and it cannot strengthen or
    silently weaken config-authoritative policy. Config-authoritative review policy
    stays exactly where it is (config layers + floor); env only expresses intent
    and a recorded human bypass.
- **B/C — the bypass stays narrow.** The audited override is **peer-review only**,
  composed through the EXISTING primitives (`writeDecision` audit trail + floor
  `relaxed-by-override`), adding NO new bypass channel. It does NOT touch the
  verification gate (that override remains the floor `relaxed-by-override` path) and
  does NOT touch the permission engine. No generic verification/permission bypass.

## Decisions — CONFIRMED

- **A** — `CCT_PEER_PROVIDER` / `CCT_PEER_REVIEW_SCOPE` = session intent only,
  precedence `ARG > env > profile`. MUST NOT mutate or override persisted config.
- **B** — `CCT_PEER_REVIEW_ENABLED=false` = audited peer-review override ONLY;
  records through the existing decision/audit path + floor relaxation; NEVER
  silently downgrades `review.mandatory`.
- **C** — the bypass is peer-review-only: NO effect on verify, permissions, SDD
  gates, protected paths, or package/network policy.
- **D** — export ONLY the FR-000a required trio (`CCT_PEER_REVIEW_ENABLED`,
  `CCT_PEER_PROVIDER`, `CCT_PEER_REVIEW_SCOPE`); do not mirror Claude extras.
- **E** — exports on the ENFORCED exec path only (not `--no-cct`, not global/user
  shell state).
- **F** — bash-3.2 conservative: explicit option arms BEFORE `-*)`, no associative
  arrays, guarded empty arrays; tests for spaced (`--peer-review-scope code`) and
  equals (`--peer-review-scope=code`) forms + unknown-flag passthrough.

Minor items (my call, low-risk):
- `--peer-review-scope` validated against `code|design|both` (fail-fast usage
  error on invalid; pi-code is `set -euo`).
- Divergence: the required trio is fully mirrored, so no new capability; at most a
  one-line parity note in `review.enforcement.reason`.

## Implementation refinement — launcher owns the peer env (guardrail A hardening)

Surfaced during implementation + testing: an AMBIENT shell `CCT_PEER_REVIEW_ENABLED=false`
(e.g. inherited from the Claude launcher that started the shell) would otherwise
leak through `exec` into the Pi session and silently trigger the audited bypass
WITHOUT `--peer-review-off` — exactly guardrail A's backdoor. Fix: `pi-code`
**unsets ambient `CCT_PEER_*` and re-sets only from its own flags** before exec,
on both paths. The launcher is therefore the SOLE sanctioned source of the peer
contract; the runtime (loaded only via `pi-code`) never sees ambient shell values.
