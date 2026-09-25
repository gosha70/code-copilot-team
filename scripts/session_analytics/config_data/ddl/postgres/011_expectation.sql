-- Expectations and their evaluation (#371 A5): what an unattended
-- auto-build run was required to achieve, and how it came out.
--
-- Four tables, all NEW, so create-if-absent is the whole migration and
-- an existing store is never refused. That is deliberate: the earlier
-- design put two columns on copilot_session, which would have forced a
-- recreate — and a recreate permanently drops every session whose
-- transcript has since been pruned (13 of 158 on 2026-09-24, one of
-- them a real 11,256-turn session).
--
-- Nothing here is authored by this package. The auto-build driver
-- freezes each requirement's statement_sha at admission and records
-- per-verifier outcomes at the landing gate; A5 reads those artifacts
-- so they outlive the ledger directory, which is archived and pruned —
-- the same reason auto_build_verdict exists.

-- One admitted run. The parent of everything below.
--
-- attempt_id is the driver's `$$-$RANDOM$RANDOM` (auto-build-loop.sh):
-- no ordering, no time component, and two runs of one feature can share
-- it. With an unchanged spec they share contract_fingerprint too, so
-- the contract alone cannot tell them apart — run_fingerprint digests
-- immutable ledger facts that differ between two real runs in every
-- case but one (the first `init` event's ts and detail,
-- branch_base_ref, the contract digest). It is NOT a uniqueness
-- guarantee: same attempt_id, same second, same base, same contract is
-- an accepted residual. A key match with a different run_fingerprint is
-- REPORTED AND SKIPPED by the ingest pass, never upserted over: a
-- collision must be visible, not a silent merge that overwrites the
-- first run's results.
CREATE TABLE IF NOT EXISTS expectation_run (
    id                   {PK},
    feature_id           VARCHAR(200) NOT NULL,
    attempt_id           VARCHAR(80) NOT NULL,
    run_fingerprint      VARCHAR(71) NOT NULL,
    contract_fingerprint VARCHAR(71) NOT NULL,
    -- The commit the run branched from; the admitted spec text is
    -- recovered from it (see expectation.statement_source).
    branch_base_ref      VARCHAR(40),
    ledger_path          VARCHAR(1000),
    ledger_root          VARCHAR(20),
    status               VARCHAR(30),
    outcome              VARCHAR(30),
    -- The ledger's `verifier_gate` event, which the driver journals ONLY
    -- after an all-green gate: a run with any failing requirement
    -- legitimately has NULL here. Never a proxy for "was this
    -- evaluated", and never defaulted to ingested_at.
    evaluated_at         TEXT,
    ingested_at          TEXT NOT NULL,
    UNIQUE (feature_id, attempt_id)
);

-- One admitted requirement of that run: an FR of specs/<feature>/spec.md
-- as it stood at admission.
--
-- statement_sha is the binding, frozen by the driver. The TEXT is not in
-- the frozen contract, so it is recovered from spec.md at the run's
-- branch_base_ref and accepted ONLY when its recomputed hash equals
-- statement_sha; otherwise statement is NULL and statement_source says
-- 'unavailable'. The working tree's current text is never substituted —
-- it may have changed since admission, and presenting it as what was
-- admitted is exactly the history-rewriting admission exists to prevent.
CREATE TABLE IF NOT EXISTS expectation (
    id               {PK},
    run_ref          BIGINT NOT NULL REFERENCES expectation_run(id),
    fr               VARCHAR(20) NOT NULL,
    statement_sha    VARCHAR(71) NOT NULL,
    statement        TEXT,
    statement_source VARCHAR(20) NOT NULL,
    verifier_count   INTEGER NOT NULL DEFAULT 0,
    UNIQUE (run_ref, fr)
);

-- One verifier's outcome for one requirement.
--
-- `green` is the driver's RAW boolean, kept beside the normalization so
-- the derivation stays auditable. It collapses in both directions: a
-- verifier that timed out, one that could not be bounded and a visual
-- `unreached` all read false with the reason only in prose `detail`;
-- and a WAIVED visual entry reads true although the driver's own
-- comment is that a waived invocation is never indistinguishable from
-- full verification. So `state` tests waived BEFORE green.
--
-- An expectation with no row here is UNEVALUATED — no recoverable
-- consolidated result. That is not the same as "no verifier ran": an
-- unwaived visual skip aborts the gate before anything is written.
CREATE TABLE IF NOT EXISTS expectation_result (
    id               {PK},
    expectation_ref  BIGINT NOT NULL REFERENCES expectation(id),
    verifier_ordinal INTEGER NOT NULL,
    kind             VARCHAR(30) NOT NULL,
    verifier         TEXT,
    green            BOOLEAN,
    waived           BOOLEAN,
    state            VARCHAR(20) NOT NULL,
    detail           TEXT,
    evidence         TEXT,
    -- Stored as written, relative to the project dir. The log FILE is
    -- not copied; the ledger is pruned, so `detail` and `evidence` carry
    -- the evidence that must survive and this is a provenance pointer.
    log_path         VARCHAR(1000),
    ingested_at      TEXT NOT NULL,
    UNIQUE (expectation_ref, verifier_ordinal)
);

-- A session the run's ledger recorded, keyed by the DISCOVERED identity.
--
-- session_ref is nullable on purpose: the row is written whether or not
-- the store holds that transcript yet. A later pass resolves the NULLs
-- for anything ingested since, so a session ingested after the first
-- scan is not lost — and coverage can tell "recorded but not in the
-- store" from "no session recorded for this run", which a
-- resolved-only key collapses into one silence.
--
-- phase_num is the ledger directory the session was found under:
-- provenance, never part of a key. A5 carries no phase dimension —
-- nothing maps a requirement to a phase.
CREATE TABLE IF NOT EXISTS expectation_session (
    id          {PK},
    run_ref     BIGINT NOT NULL REFERENCES expectation_run(id),
    copilot     VARCHAR(30) NOT NULL,
    session_id  VARCHAR(200) NOT NULL,
    session_ref BIGINT REFERENCES copilot_session(id),
    phase_num   INTEGER,
    ingested_at TEXT NOT NULL,
    UNIQUE (run_ref, copilot, session_id)
);

CREATE INDEX IF NOT EXISTS idx_expectation_run_feature ON expectation_run (feature_id);
CREATE INDEX IF NOT EXISTS idx_expectation_run_ref ON expectation (run_ref);
CREATE INDEX IF NOT EXISTS idx_expectation_result_ref ON expectation_result (expectation_ref);
CREATE INDEX IF NOT EXISTS idx_expectation_session_ref ON expectation_session (session_ref);
