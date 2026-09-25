---
feature_id: sa-expectations
spec_mode: lightweight
status: draft
date: 2026-09-25
issue: "#371 (slice A5; separate PR; leaves #371 open)"
origin:
  issue: "#371"
  transcripts:
    - specs/sa-expectations/origin/2026-09-25-owner-direction.md
  user_messages:
    - "2026-09-25: 'Take up A5 next; keep A6 deferred.'"
    - "2026-09-25: 'The spec acceptance criteria remain the source of truth.'"
    - "2026-09-25: 'choose option 1 and drop phase from A5 ... keyed at the attempt level: (feature_id, attempt_id, fr)'"
---

# Spec: expectations and their evaluation (A5)

## Why

"Success" is inferred today, never declared. The judge scores turns and
rolls them into `session_kpi`; `correlate` links benchmark outcomes.
Nothing records what a piece of work was *supposed* to achieve, so
A4b's harness comparison can report cost, turns, errors and two rubric
rates but not whether the work succeeded.

The declaration already exists and is already frozen — it is just never
stored. An unattended auto-build run admits a feature only after
`validate-spec.sh --unattended` proves every `FR-N` in `spec.md` maps
to an executable verifier, freezes each requirement's `statement_sha`
into the ledger, and later records per-FR outcomes. A5 stores that
pair — what was required, and how it came out — so it outlives the
ledger and can be aggregated.

## Verified facts (2026-09-25, master da24d52)

| Fact | Where |
|---|---|
| FRs **are** the acceptance criteria; `vc_extract_frs` is the one parser (`^- (\*\*)?FR-[0-9]+[a-z]?` inside `## Requirements`), and `vc_fr_sha` = `sha256("FR-N: <normalized statement>")` | `scripts/lib/verification-common.sh:37-96` |
| Admission asserts spec.md is "the ONLY authoritative source of requirement text", recomputes every `statement_sha`, and fails with "spec.md text changed after finalization" | `scripts/validate-spec.sh:340, 355-364` |
| Admission runs **once per run**, before the ledger exists, only for `profile: unattended`; a refused admission leaves no durable state | `scripts/auto-build-loop.sh:5590-5615, 824-826` |
| The frozen contract is written into `state.json.preflight.contract` and `frozen-contract.json`, then pinned in process memory so a build session cannot move the bar | `scripts/auto-build-loop.sh:1865-1930` |
| The frozen contract carries `verifiers.set[] = {fr, statement_sha, test, metric}` — **no phase dimension at any level** | `.cct/auto-build/team-developer-aliases/frozen-contract.json` |
| `verification-results.json` is **one file per run**, written once at the landing gate, overwritten, with `{frs: {FR-N: {green, verifiers:[{fr, kind, verifier, statement_sha, green, detail, log}]}}}` and **no timestamp** | `scripts/auto-build-loop.sh:3137-3155`; the real file's keys are `schema_version, frs, green` |
| An FR is green iff every one of its verifiers is green; `green` is a strict boolean from the exit code — 124 (timed out) and 125 (could not be bounded) both yield `false` with the reason only in prose `detail` | `scripts/auto-build-loop.sh:2475-2484, 3145-3146` |
| Richer verdicts exist upstream and collapse into that boolean: conformance `pass\|fail`; visual `pass\|fail\|skip\|unreached`, where `skip` is green only under a frozen `skip_is_failure:false` waiver and `unreached` is always red | `scripts/auto-build-loop.sh:2712, 2987, 3057-3069` |
| The `verifier_gate` event carries an ISO timestamp — but it is journalled **only after an all-green gate**: every failure path calls `vg_finish` and `return 1` before it. A run with a failing requirement never emits it | `scripts/auto-build-loop.sh:3171-3182` |
| A **waived** visual entry is written `green: true` with `waived: true` — the driver's own comment calls a waived invocation "never indistinguishable from full verification". An **unwaived** visual `skip` aborts the gate (`vg_finish` + `return 1`) and never reaches the results file at all | `scripts/auto-build-loop.sh:3036-3081` |
| The frozen contract carries **no `statement` text** — only `{fr, statement_sha, test, metric}`. The admitted text lives in `spec.md` at the run's `branch_base_ref`; recovering it there and recomputing the hash reproduces the frozen `statement_sha` exactly (verified 4/4 on this repo's one real run) | `frozen-contract.json`; `state.json.branch_base_ref`; measured |
| `attempt_id` is `$$-$RANDOM$RANDOM` — no ordering, no time component; it is already `auto_build_verdict.run_key`, UNIQUE | `scripts/auto-build-loop.sh:148`; `009_auto_build_verdict.sql` |
| Ledgers live under **both** `.cct/auto-build/` and `.cct/auto-build-archive/`; `auto_build_verdict` exists precisely because its row "outlives the ledger directory being archived or pruned" | `constants.py:214-216`; `009_auto_build_verdict.sql:3-6` |
| `api/auto_build.py` reads every ledger file live per request and stores nothing; it already surfaces `admission_mapped` and `results{green,total,frs[{fr,green}]}`, but no requirement text and no evidence | `api/auto_build.py:152-165, 275-390` |
| A phase session's Claude Code id is in `phase-N/build-result-M.json` (the `system/init` event); that session is in the store with `phase` NULL and no run link. Of 145 sessions, **0** carry a phase, run dir or `feature_id` | `.cct/auto-build/team-developer-aliases/phase-1/build-result-1.json` |
| `copilot_session.phase` is the **workflow** phase (`research\|plan\|build\|review`), written only by the Pi adapter — a different concept from the ledger's numbered `phase-N` | `constants.py:54-59`; `adapters/pi.py:159` |
| `store.link_benchmark_run` is the precedent for binding a session to a run: an idempotent parameterized UPDATE on `(copilot, session_id)` that reports unmatched rather than guessing | `relational/store.py:421-441` |
| Only **3 of 85** spec bundles have a `verification.yaml` (all finalized); the FR parser can read **59 of 85** `spec.md` files | measured with `vc_extract_frs` over `specs/*/spec.md` |

## Requirements

- **FR-1** A table `expectation_run`, one row per admitted run, keyed
  `UNIQUE (feature_id, attempt_id)`: `id`, `feature_id`, `attempt_id`,
  `run_fingerprint`, `contract_fingerprint` (a digest over the frozen
  contract's ordered `(fr, statement_sha)` pairs), `branch_base_ref`,
  `ledger_path`, `ledger_root` (live or archive), `status`, `outcome`,
  `evaluated_at`, `ingested_at`. The run is the parent; everything else
  hangs off it.
- **FR-2** **Attempt collisions are detected by a run fingerprint, not
  by the contract.** `attempt_id` is `$$-$RANDOM$RANDOM` — no ordering,
  no time component — so two runs of the same feature can share it, and
  if neither the spec nor the verifiers changed they share a
  `contract_fingerprint` too; comparing contracts alone would silently
  merge them. `run_fingerprint` is a digest over immutable ledger facts
  that differ between two real runs **in every case but one**: the
  **first `init` event's `ts` and `detail`** (which carries profile,
  branch and base), `branch_base_ref`, and the contract digest. The
  exception is accepted, not solved — two runs of one feature that
  collide on `attempt_id`, start in the same second, branch from the
  same commit and carry an identical contract are indistinguishable
  here, and are recorded as a known residual risk. A stored run whose key
  matches but whose `run_fingerprint` differs is **reported and
  skipped**, never upserted over. A ledger with no readable `init`
  event yields no fingerprint, and the run is skipped with that reason
  rather than stored under a weaker identity.
- **FR-3** A table `expectation`, one row per admitted requirement,
  keyed `UNIQUE (run_ref, fr)`: `statement_sha`, `statement`,
  `statement_source`, `verifier_count`. **No `session_ref`**:
  admission is per run, and a requirement is a property of the run, not
  of any session within it.
- **FR-4** The admitted statement is **recovered, or recorded as
  unavailable — never taken from today's text.** The frozen contract
  carries no statement. The pass reads `spec.md` at the run's
  `branch_base_ref`, extracts requirements with the same parser
  admission used, and accepts a statement **only when its recomputed
  hash equals the frozen `statement_sha`**; `statement_source` records
  `recovered`. When the commit is unreachable, the file is absent, or a
  hash does not match, `statement` is NULL and `statement_source` is
  `unavailable` — the current working-tree text is never substituted,
  because it may have changed since admission.
- **FR-5** A table `expectation_result`, one row per (expectation,
  verifier), keyed `UNIQUE (expectation_ref, verifier_ordinal)`:
  `kind` (`deterministic`, `runtime_conformance`, `visual`),
  `verifier` (the command or criterion), `green` (the driver's raw
  boolean, nullable), `detail`, `evidence`, `log_path`, `waived`,
  plus the normalized `state` of FR-6. The driver's raw outcome is
  stored **beside** the normalization, never replaced by it.
- **FR-6** A three-state normalization, derived on ingest and stored:
  `met`, `not_met`, `unknown`, in **exactly this order**, reading only
  `waived`, `green` and `detail`:
  1. **`waived` → `unknown`, tested before `green`.** The driver writes
     a waived visual entry `green: true`; its own comment is that a
     waived invocation is never indistinguishable from full
     verification. Waived means *not verified*, so it must not read as
     `met`.
  2. **`green` true → `met`.**
  3. **`not_met` ONLY for a shape known to mean a real negative:** a
     `deterministic` verifier whose `detail` is exactly
     `exit <nonzero integer>`, or a `runtime_conformance` or `visual`
     verdict of exactly `fail`.
  4. **Everything else → `unknown`** — the fail-safe fallback. This
     covers a bound that was hit, a run that could not be bounded, a
     visual `unreached`, a missing or malformed `detail`, a verifier
     kind this code does not know, a contradictory `green: false` with
     `detail: exit 0`, and **any wording a future driver invents**.

  The fallback direction is load-bearing and is the opposite of the
  obvious one. The exit code is never stored, so step 3 must read prose;
  matching *inconclusive* wording and defaulting the rest to `not_met`
  would mean a reword in `auto-build-loop.sh` silently reports
  requirements as **failed that were never judged**. Defaulting to
  `unknown` turns the same drift into visible missing coverage, which
  FR-13 already excludes from both sides of the rate. The raw `green`
  and `detail` are stored beside the state so the derivation stays
  auditable.

  An FR with no result row is **unevaluated**, which means *no
  recoverable consolidated result* — NOT "no verifier ran". The
  unwaived visual `skip` proves the distinction: a verifier ran, the
  gate aborted before writing any result, and the outcome is
  unrecoverable from `verification-results.json`. Unevaluated is the
  absence of rows, never a row with a null state. The rule lives in one
  function whose docstring names each raw input it reads.
  **Not recoverable, and not claimed:** an *unwaived* visual `skip`
  aborts the gate before any result is written, so that state never
  reaches `verification-results.json` and A5 cannot report it.
- **FR-7** An expectation's rolled-up state is `met` only when every one
  of its results is `met` (the driver's own rule); `not_met` when any is
  `not_met`; `unknown` when results exist and none is `not_met` but at
  least one is `unknown`. Exposed as a derived value, never stored
  twice.
- **FR-8** `evaluated_at` on `expectation_run` comes from the ledger's
  `verifier_gate` event, and is NULL when there is none — never
  invented, never defaulted to the ingest time. **That event is
  journalled only after an all-green gate**, so a run with any failing
  requirement legitimately has `evaluated_at = NULL`; this is a
  property of the driver, stated in the README, not a gap to paper
  over. `ingested_at` is recorded separately.
- **FR-9** Evidence is stored, not pointed at: `detail`, the
  conformance/visual `evidence` string, and the relative `log_path` as
  written. The log file itself is not copied. Text fields are bounded
  and the bound is a named constant. Rationale: the ledger directory is
  archived and pruned, so a path alone would decay into a dangling
  reference.
- **FR-10** Ingest is a separate pass, `session-analytics expectations`
  (mirroring `correlate`), which walks the configured ledger roots —
  live and archive — and for each run directory with a readable
  `state.json` carrying an `attempt_id` and a `preflight.contract`,
  upserts its expectations and results. It is idempotent on the natural
  keys. A run **without** a frozen contract writes nothing: a refused
  admission never created a ledger. A run with a contract but **no
  recoverable consolidated results** stores its expectations with no
  result rows — the unevaluated case of FR-6, which covers both a gate
  that was never reached and one that ran and aborted before writing
  anything recoverable.
- **FR-11** Sessions associate through an **additive table**,
  `expectation_session`, keyed `UNIQUE (run_ref, copilot, session_id)`
  with a **nullable `session_ref`**, plus `phase_num` (the ledger
  directory the session was found under — provenance, not a key) and
  `ingested_at`. **No column is added to `copilot_session`**: a column
  would force the store to be recreated, and a recreate permanently
  drops every session whose transcript has since been pruned — 13 of
  158 on 2026-09-24, one of them a real 11,256-turn session. An
  association table lands in place.
  The row is keyed by the **discovered identity**, not by the resolved
  one: the pass records every session id found in a
  `phase-N/build-result-M.json` `system/init` event whether or not the
  store holds it yet, with `session_ref` NULL when it does not. A later
  pass resolves NULLs for transcripts ingested since — a session
  ingested after the first scan is not lost — and coverage can tell
  **"recorded but not in the store"** from **"no session recorded for
  this run"**, which a resolved-only key collapses into one silence.
- **FR-12** Read surfaces, with **one durable surface and one
  enrichment** — the distinction is load-bearing:
  - `GET /api/expectations?feature_id=&attempt_id=` is the **durable**
    surface. It reads the store alone, so it keeps answering after the
    ledger directory is archived or pruned. The MCP tool mirrors it.
  - `api/auto_build.py`'s run detail is **enriched** from the store with
    the requirement text and each expectation's state, beside the
    `admission_mapped` / `results` counts it already derives from the
    ledger. It is **not** a post-pruning fallback and must not be
    described as one: that route finds a run by scanning ledger
    directories, so it is unreachable once the directory is gone.
  - A run-detail fallback is **out of scope** and would need a design
    first: `GET /api/runs/{key}` is keyed by `attempt_id` alone, while
    the store's identity is the composite `(feature_id, attempt_id)`,
    so serving a pruned run there needs a rule for an attempt id that
    two features could share.
- **FR-13** A4b's harness comparison gains expectation success **only
  with coverage beside it, attributed at RUN grain**. A run is
  attributable to a harness row only when **both** hold: every session
  the pass discovered for it is linked (no `session_ref` is NULL), and
  every linked session resolves to that same row. A run failing either
  test is excluded and counted, never attributed.
  - **Per row:** `expectations_met`, `expectations_evaluated`,
    `expectations_unknown`, `expectations_unevaluated`,
    `runs_with_expectations`, `sessions_with_expectations`.
  - **Top-level, not per row** (an excluded run belongs to no row, so
    reporting it inside one would be a contradiction):
    `runs_spanning_groups` and `runs_with_unmatched_sessions`.
  - **The rate is exactly `expectations_met / expectations_evaluated`**,
    where `expectations_evaluated` counts expectations whose rolled-up
    state is `met` or `not_met` only. `expectations_unknown` and
    `expectations_unevaluated` are in **neither** numerator nor
    denominator, and are reported beside the rate so the gap is visible.
  - The rate is **NULL — never zero** — when `expectations_evaluated`
    is 0, the discipline the judge columns already follow.
- **FR-14** Tests: the three-state normalization over every raw shape
  the driver can produce — green true; exit non-zero; timed out; could
  not be bounded; `unreached`; **waived `green: true` → unknown**. An
  unwaived visual `skip` is NOT among them: it never reaches the
  results file, and a test asserting a shape the driver cannot write
  would pin fiction;
  the roll-up rule; statement recovery matching the frozen hash, and
  each unavailable path (commit unreachable, file absent, hash
  mismatch) recording `unavailable` rather than substituting current
  text; an attempt collision with a different fingerprint refused and
  reported; a run with a contract and no results unevaluated with zero
  result rows; a directory with no `attempt_id` skipped with a reason;
  idempotence of a second pass; `evaluated_at` NULL for a failed run;
  session association matched and unmatched; the aggregate's
  NULL-not-zero, its coverage, and a run spanning two harness groups
  excluded and counted; a run with an unlinked session excluded and
  counted separately; a second pass resolving a `session_ref` that was
  NULL on the first; two runs sharing an `attempt_id` and a contract
  but differing in `run_fingerprint` reported and skipped; the API and
  MCP contract. The real ledger in
  this repo is a fixture beside synthetic ones — its four statements
  are known to recover and match.

## Constraints

- One new pass and four new tables; no change to `auto-build-loop.sh`,
  `validate-spec.sh`, `verification-common.sh` or either JSON schema.
  A5 is a reader of artifacts that already exist. Adding a field at
  admission instead would mean changing `preflight-result.schema.json`
  (`admission` is `additionalProperties: false`), the bash validator and
  the driver — three coupled edits for data the ledger already holds.
- **No phase dimension** (the owner's ruling): nothing maps an FR to a
  `## US<N>` phase, and attributing one through the session would
  fabricate it.
- The `expectation` tables are for **unattended auto-build runs only**.
  A manual session has no run/attempt identity, and free-form
  expectations wait — the owner's ruling, and the data agrees.
- Coverage is small and accrues forward: 3 of 85 bundles have a
  `verification.yaml`, one has a ledger in this repo, and 0 of 145
  sessions are bound today. The README says so rather than implying a
  populated feature.
- **Schema 11 adds TABLES ONLY and must not refuse an existing store.**
  Four new tables land in place through the create-if-absent DDL, as
  A3's `feedback` did; nothing joins `_REQUIRED_COLUMNS`. No session
  column, no recreate, and therefore no repeat of the 2026-09-24 loss
  of 13 sessions to transcript pruning.
- One PR under #371, no close marker.

## Out of scope

Per-phase attribution of requirements (the owner's option 2, its own
change to the SDD workflow if ever wanted). Expectations for manual
sessions. Free-form, human-written expectations. Changing the driver to
record a three-state outcome at source.

**Expectation-aware judge scoring is an explicit A5 SUCCESSOR slice,
not delivered here.** This slice records what was required and what
happened. Nothing in it makes the judge read an expectation, score a
session against one, or turn an expectation into a session-level
verdict. The issue's phrasing — "that the judge and the outcome logic
can score against" — describes that successor, and A5 only makes it
possible. The two
defects found while modelling (`routing-packet.sh:293`; the transient
`verification` key `validate-spec.sh` writes) stay outside.
