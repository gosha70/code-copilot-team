# session_analytics.embedding.runner — the embedding pass (#285 T4).
#
# FR-6 IS EXECUTED LITERALLY, IN ORDER — not merely reproduced in
# outcome:
#
#   1. durable DB state first;
#   2. no work → return WITHOUT contacting the backend (the
#      zero-backend-calls idempotency guarantee binds before any
#      probe);
#   3. existing envelopes are never overwritten without --overwrite;
#   4. probe only when work exists — unreachable refuses the whole
#      pass before any write;
#   5. embed() returns the vector + the authoritative resolved model;
#   6. validate the COMPLETE envelope (FR-9), then ONE replacement
#      write.
#
# A failed step for a session leaves its stored value exactly as it
# was — NULL stays NULL, and under --overwrite the prior envelope
# survives a failed re-embed, because the only write is the one that
# follows successful validation.
#
# REPORTING SAYS ONLY WHAT IS KNOWABLE. Skipped envelopes are
# ``skipped_existing`` with a model distribution read from the STORED
# envelopes themselves — never ``skipped_other_model``, which would
# require an authoritative CURRENT resolved identity that an ordinary
# run (which may never contact the backend) does not have, and which
# must never be derived from the configured model name.

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..config import EmbeddingConfig
from ..relational.db import Database
from .composer import compose_input
from .contracts import FIELD_MODEL, build_envelope, validate_envelope
from .registry import get_embedding


@dataclass
class EmbedStats:
    embedded: int = 0
    skipped_existing: int = 0
    #: model → count, read from STORED envelopes only. An envelope that
    #: does not parse, or lacks a model, buckets as "(invalid-envelope)"
    #: rather than being guessed at.
    skipped_existing_models: dict[str, int] = field(default_factory=dict)
    unembeddable: int = 0
    failed: int = 0
    truncated: int = 0

    def as_dict(self) -> dict:
        return {
            "embedded": self.embedded,
            "skipped_existing": self.skipped_existing,
            "skipped_existing_models": dict(sorted(
                self.skipped_existing_models.items())),
            "unembeddable": self.unembeddable,
            "failed": self.failed,
            "truncated": self.truncated,
        }


def _stored_model(raw: str) -> str:
    try:
        env = json.loads(raw)
        model = env.get(FIELD_MODEL) if isinstance(env, dict) else None
    except (json.JSONDecodeError, TypeError):
        model = None
    return model if isinstance(model, str) and model else "(invalid-envelope)"


def run_embed(
    db: Database,
    embedding_cfg: EmbeddingConfig,
    *,
    overwrite: bool = False,
    session_id: int | None = None,
    limit: int | None = None,
) -> EmbedStats:
    """The FR-6 pass. Raises on a refused pass (probe failure, empty
    model with work pending); per-session failures are counted."""
    stats = EmbedStats()

    # ── 1. durable state FIRST ───────────────────────────────────────
    where, params = "", []
    if session_id is not None:
        where = " WHERE id = ?"
        params.append(session_id)
    rows = db.query(
        f"SELECT id, session_embedding FROM copilot_session{where} ORDER BY id",
        tuple(params),
    )

    work: list[int] = []
    for sid, stored in rows:
        if stored is None:
            work.append(sid)
        elif overwrite:
            work.append(sid)
        else:
            # ── 3. never overwritten without --overwrite ─────────────
            stats.skipped_existing += 1
            m = _stored_model(stored)
            stats.skipped_existing_models[m] = (
                stats.skipped_existing_models.get(m, 0) + 1)
    if limit is not None:
        work = work[:limit]

    # ── 2. no work → ZERO backend contact, probe included ────────────
    if not work:
        return stats

    # ── 4. probe only now, and only once ─────────────────────────────
    backend = get_embedding(
        embedding_cfg.backend,
        embedding_cfg.model,
        base_url=embedding_cfg.ollama_url,
    )
    backend.probe()  # a refused probe propagates: whole pass refused,
    #                  zero writes — never a half-done pass.

    embedded_at = _now_iso()
    for sid in work:
        try:
            composed = compose_input(
                db, sid, cap_chars=embedding_cfg.input_cap_chars)
        except ValueError:
            # e.g. duplicate sequence_num (T2): malformed durable state
            # fails closed for this session; the stored value is
            # untouched.
            stats.failed += 1
            continue
        if composed.unembeddable:
            # counted WITHOUT calling embed; stored value untouched.
            stats.unembeddable += 1
            continue
        if composed.truncated:
            stats.truncated += 1
        try:
            result = backend.embed(composed.text)
        except Exception:  # noqa: BLE001 — any backend failure = this
            #               session failed; prior value preserved.
            stats.failed += 1
            continue
        envelope = build_envelope(
            result, provider=embedding_cfg.backend, embedded_at=embedded_at)
        err = validate_envelope(envelope)
        if err is not None:
            # ── 6. FR-9 refusal: nothing is written ──────────────────
            stats.failed += 1
            continue
        # ── 6. the ONE replacement write, after validation ───────────
        db.execute(
            "UPDATE copilot_session SET session_embedding = ? WHERE id = ?",
            (json.dumps(envelope), sid),
        )
        stats.embedded += 1

    db.commit()
    return stats


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
