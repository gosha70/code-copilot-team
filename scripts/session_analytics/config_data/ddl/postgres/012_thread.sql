-- Session threads from native lineage (#371 A6): which session was
-- resumed from which, proven by identifiers the transcript exposes.
--
-- FOUR tables, all NEW, and one index on an existing table's existing
-- column. No column is added to any existing table, so create-if-absent
-- is the whole migration, nothing joins _REQUIRED_COLUMNS, and a
-- schema-11 store gains all of this in place. That is the same
-- deliberate choice A5 made and for the same reason: a recreate
-- permanently drops every session whose transcript has since been
-- pruned.
--
-- NO TIMESTAMP IS AN INPUT ANYWHERE in this model. A resumed transcript
-- copies its ancestor's records verbatim, timestamps included — two
-- sessions in one lineage share a first timestamp to the millisecond —
-- so time is not a weak signal for ancestry, it is a wrong one.
-- Ancestry comes from turn-uuid containment (FR-5), ordering from the
-- edges, terminality from the absence of an outgoing edge.

-- One detected thread.
--
-- thread_id is an opaque surrogate and never reuses a session_id value,
-- so a join cannot silently succeed on the wrong column. It is issued
-- once and never rewritten: when a later source bridges two stored
-- threads, the loser stays addressable and is REDIRECTED at the
-- survivor (FR-20), because rewriting an id would break every reference
-- already handed out and deleting one would make a valid id return
-- nothing.
--
-- Acyclicity is structural, not a consequence of the survivor ranking:
-- thread sizes change as members move, so the side that lost once can
-- outrank its survivor later. Both sides are resolved through
-- redirected_to_ref to their ACTIVE terminal before anything is
-- compared or written, and only an active thread may participate in a
-- connection or become a survivor.
--
-- A redirect target is active AT THE MOMENT THE REDIRECT IS WRITTEN. It
-- may itself be redirected later, and that is the supported transitive
-- chain: resolution follows redirected_to_ref to its end and must
-- terminate in an active thread. What never happens is an inactive
-- thread being SELECTED AS A NEW TARGET, and an already-redirected row
-- being re-pointed. Every redirect edge therefore runs from a thread
-- becoming inactive to one that was active when chosen, so no cycle can
-- form.
CREATE TABLE IF NOT EXISTS session_thread (
    id                {PK},
    thread_id         VARCHAR(64) NOT NULL,
    status            VARCHAR(20) NOT NULL DEFAULT 'active',
    -- the surviving thread, set only when status = 'redirected'
    redirected_to_ref BIGINT REFERENCES session_thread(id),
    -- a member has more than one incomparable immediate descendant:
    -- the branches are KEPT and no ordering is invented between them
    fork_suspected    BOOLEAN NOT NULL DEFAULT FALSE,
    -- lineage yields more than one terminal member, so the canonical
    -- owner is not unique: every candidate keeps is_terminal and none
    -- is chosen
    terminal_ambiguous BOOLEAN NOT NULL DEFAULT FALSE,
    -- the component has more than one member with no incoming edge.
    -- Every actual root keeps is_root and none is chosen.
    root_ambiguous    BOOLEAN NOT NULL DEFAULT FALSE,
    member_count      INTEGER NOT NULL DEFAULT 0,
    detected_at       TEXT,
    updated_at        TEXT,
    UNIQUE (thread_id),
    -- The invariants the database itself can hold. The containment
    -- threshold is deliberately NOT among them: it is the versioned
    -- application rule (constants.THREAD_RULE_VERSION), and freezing a
    -- number into DDL would make a rule change indistinguishable from a
    -- schema change.
    CHECK (status IN ('active', 'redirected')),
    -- active carries no target; redirected carries one, and never
    -- itself
    CHECK (
        (status = 'active'     AND redirected_to_ref IS NULL)
     OR (status = 'redirected' AND redirected_to_ref IS NOT NULL
                               AND redirected_to_ref <> id)
    ),
    CHECK (member_count >= 0)
);

-- A member is a SOURCE TRANSCRIPT, not a session row.
--
-- This is the whole reason the model is shaped this way. The Claude
-- Code adapter groups transcripts by the sessionId on their first line
-- and deduplicates by uuid, which is correct and load-bearing — without
-- it a resumed session's repeated turns double every count downstream.
-- But the grouping CONSUMES the evidence: three transcripts become one
-- session row and nothing records that there were three, or which
-- continued which. Several members therefore resolve to one
-- session_ref, and that is the normal case, not an anomaly.
--
-- session_ref is nullable because a transcript can be known to lineage
-- before — or without ever — being ingested.
CREATE TABLE IF NOT EXISTS thread_member (
    id                {PK},
    -- NULLABLE. A row here is a REGISTERED SOURCE first and an attached
    -- member second. Two real cases have no thread to point at: a pair
    -- that produced an unresolved relation candidate rather than an
    -- edge, and a known source that is missing on disk and links to
    -- nothing. Requiring a thread would make both unrecordable — and
    -- the candidate table references this one, so it would be
    -- unwritable too. A source attaches when lineage creates a thread,
    -- and session_thread.member_count counts ATTACHED rows only.
    thread_ref        BIGINT REFERENCES session_thread(id),
    copilot           VARCHAR(30) NOT NULL,
    -- the id the store knows the owning session by
    native_session_id VARCHAR(200) NOT NULL,
    -- the copilot_session row, when this source has been ingested
    session_ref       BIGINT REFERENCES copilot_session(id),
    -- the transcript's stable identity (its source_file path)
    source_key        VARCHAR(1000) NOT NULL,
    -- FALSE = a KNOWN source that is missing or pruned on disk. It
    -- counts in the known-source coverage denominator as unavailable.
    -- A source deleted before its path ever reached ingest_state or
    -- this table is UNDISCOVERABLE: it has no row here at all and is
    -- excluded from the denominator, which is why coverage is reported
    -- as known-source coverage and never as total coverage.
    source_available  BOOLEAN NOT NULL DEFAULT TRUE,
    turn_uuid_count   INTEGER NOT NULL DEFAULT 0,
    -- no incoming ancestor edge. May MOVE when an older ancestor is
    -- discovered later; session_thread.thread_id does not.
    is_root           BOOLEAN NOT NULL DEFAULT FALSE,
    -- no outgoing descendant edge. The canonical owner is the unique
    -- terminal member; when more than one qualifies, every candidate
    -- keeps this flag and session_thread.terminal_ambiguous is TRUE.
    is_terminal       BOOLEAN NOT NULL DEFAULT FALSE,
    -- THIS member has more than one incomparable immediate ancestor: a
    -- join, the mirror of a fork. The evidence edges are all KEPT and
    -- no canonical predecessor is chosen. It is flagged per MEMBER, not
    -- per thread, so a read surface can show the joins apart from the
    -- primary tree instead of duplicating the node under each ancestor
    -- and implying two independent descendants.
    join_suspected    BOOLEAN NOT NULL DEFAULT FALSE,
    -- A source transcript belongs to exactly ONE thread, globally. The
    -- key deliberately excludes thread_ref: keying on it would let the
    -- same (copilot, source_key) exist under two active threads, which
    -- is precisely the duplicate identity that thread connection exists
    -- to prevent. A member's thread_ref MOVES during a connection; its
    -- source identity must never duplicate.
    UNIQUE (copilot, source_key),
    CHECK (turn_uuid_count >= 0)
);

-- One ancestry edge, carrying the evidence that authorized it.
--
-- provenance records HOW THE CANDIDATE PAIR WAS FOUND and authorizes
-- nothing: 'native_group' means the two members came from one adapter
-- group, 'uuid_containment' means the pair came back from the turn-uuid
-- index probe. Adapter grouping proves common membership, NOT
-- predecessor order — and its grouping key is a sessionId that an older
-- CLI rewrote anyway. No edge is written on provenance alone; direction
-- always comes from the containment rule, whichever way the pair was
-- found, which is why both provenances carry the same evidence columns.
--
-- rule_version is the version of the containment rule that judged this
-- edge. Without it a later change to the bounds would be
-- indistinguishable from a change in the data, and the stored graph
-- would silently mean something different.
CREATE TABLE IF NOT EXISTS thread_edge (
    id                    {PK},
    thread_ref            BIGINT NOT NULL REFERENCES session_thread(id),
    ancestor_member_ref   BIGINT NOT NULL REFERENCES thread_member(id),
    descendant_member_ref BIGINT NOT NULL REFERENCES thread_member(id),
    provenance            VARCHAR(30) NOT NULL,
    -- |uuids(ancestor) ∩ uuids(descendant)|
    shared_uuids          INTEGER NOT NULL,
    -- shared / |ancestor| and shared / |descendant|. NOT NULL: an edge
    -- cannot exist without the gate having been computed, so a null
    -- here would mean an edge nobody judged.
    ancestor_containment  DOUBLE PRECISION NOT NULL,
    descendant_containment DOUBLE PRECISION NOT NULL,
    -- The EXACT set differences the direction was decided from:
    -- ancestor_only = |ancestor \ descendant| (turns the resume
    -- dropped, e.g. to a compaction trim), descendant_only =
    -- |descendant \ ancestor| (turns it added). The edge exists
    -- because descendant_only > ancestor_only. Shared count plus
    -- rounded ratios cannot re-derive that, so the counts are stored
    -- rather than recomputed.
    ancestor_only         INTEGER NOT NULL,
    descendant_only       INTEGER NOT NULL,
    rule_version          VARCHAR(30) NOT NULL,
    UNIQUE (ancestor_member_ref, descendant_member_ref),
    -- a member is never its own ancestor
    CHECK (ancestor_member_ref <> descendant_member_ref),
    CHECK (shared_uuids >= 0),
    CHECK (ancestor_only >= 0 AND descendant_only >= 0),
    CHECK (ancestor_containment >= 0 AND ancestor_containment <= 1),
    CHECK (descendant_containment >= 0 AND descendant_containment <= 1),
    -- the closed provenance set FR-4 promises, held by the database
    -- rather than by convention
    CHECK (provenance IN ('native_group', 'uuid_containment')),
    -- the direction test itself, held by the database
    CHECK (descendant_only > ancestor_only)
);

-- A gated pair that produced NO EDGE, because neither side grew.
--
-- Deliberately not called a merge candidate: only one of its two kinds
-- is a merge proposal. 'duplicate_identity' means the two sources carry
-- identical uuid sets. 'direction_ambiguous' means they genuinely
-- DIFFER and the rule cannot say which came first — merging those two
-- would destroy real information. Naming the table for the merge would
-- push every reader toward the wrong action on half its rows.
--
-- The pair is stored in canonical order (the smaller member id first)
-- so one candidate cannot be recorded twice under two orderings.
CREATE TABLE IF NOT EXISTS thread_relation_candidate (
    id             {PK},
    member_a_ref   BIGINT NOT NULL REFERENCES thread_member(id),
    member_b_ref   BIGINT NOT NULL REFERENCES thread_member(id),
    shared_uuids   INTEGER NOT NULL,
    containment_a  DOUBLE PRECISION NOT NULL,
    containment_b  DOUBLE PRECISION NOT NULL,
    -- equal by definition for every candidate — that equality IS why
    -- no edge was written — but stored so the verdict is re-derivable
    -- from the row alone.
    a_only         INTEGER NOT NULL,
    b_only         INTEGER NOT NULL,
    -- 'duplicate_identity' (both zero: identical uuid sets) or
    -- 'direction_ambiguous' (both non-zero: each side has as much the
    -- other lacks, so neither grew). The second is NOT a merge
    -- proposal; conflating them would invite merging two sources that
    -- genuinely differ.
    candidate_kind VARCHAR(30) NOT NULL,
    rule_version   VARCHAR(30) NOT NULL,
    detected_at    TEXT,
    UNIQUE (member_a_ref, member_b_ref),
    -- canonical order, enforced rather than merely conventional: this
    -- one constraint makes the pair distinct AND unrepeatable under the
    -- reversed ordering, which the UNIQUE key alone would allow
    CHECK (member_a_ref < member_b_ref),
    CHECK (shared_uuids >= 0),
    CHECK (containment_a >= 0 AND containment_a <= 1),
    CHECK (containment_b >= 0 AND containment_b <= 1),
    CHECK (a_only >= 0 AND b_only >= 0),
    -- a candidate exists precisely because neither side grew
    CHECK (a_only = b_only),
    CHECK (candidate_kind IN ('duplicate_identity', 'direction_ambiguous')),
    -- the kind is a FUNCTION of the counts, not an independent opinion
    CHECK ((candidate_kind = 'duplicate_identity'   AND a_only = 0)
        OR (candidate_kind = 'direction_ambiguous'  AND a_only > 0))
);

-- Detection probes this index with a session's turn uuids and scores
-- ONLY the sessions that come back; without it the alternative is a
-- pairwise scan over every session. Measured on 163 transcripts, the
-- probe returns nothing at all for 160 of them.
CREATE INDEX IF NOT EXISTS idx_copilot_turn_uuid ON copilot_turn (uuid);

CREATE INDEX IF NOT EXISTS idx_thread_member_thread ON thread_member (thread_ref);
CREATE INDEX IF NOT EXISTS idx_thread_member_session ON thread_member (session_ref);
CREATE INDEX IF NOT EXISTS idx_thread_edge_thread ON thread_edge (thread_ref);
CREATE INDEX IF NOT EXISTS idx_thread_edge_descendant ON thread_edge (descendant_member_ref);
CREATE INDEX IF NOT EXISTS idx_session_thread_status ON session_thread (status);
