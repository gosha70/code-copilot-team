# session_analytics.judge.kpis — session-level KPI rollups from labels.
#
# Aggregates heuristic_label rows into session_kpi. Unknown (NULL) labels are
# treated as "did not occur" for rate purposes (CASE ... ELSE 0). Idempotent:
# ON CONFLICT(session_id, rubric_name) DO UPDATE.

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..relational.db import Database


@dataclass
class KpiStats:
    sessions: int = 0

    def as_dict(self) -> dict:
        return {"sessions": self.sessions}


def compute_kpis(db: Database, rubric_name: str, *, session_id: Optional[int] = None) -> KpiStats:
    where = "WHERE h.rubric_name = ?"
    params: list = [rubric_name]
    if session_id is not None:
        where += " AND t.session_id = ?"
        params.append(session_id)

    rows = db.query(
        f"""
        SELECT t.session_id,
               COUNT(h.id) AS labeled,
               AVG(CASE WHEN h.user_corrects_agent THEN 1.0 ELSE 0.0 END) AS correction_rate,
               AVG(CASE WHEN h.rework_detected THEN 1.0 ELSE 0.0 END) AS rework_rate,
               AVG(CASE WHEN h.response_helpful THEN 1.0 ELSE 0.0 END) AS first_attempt,
               AVG(CASE WHEN h.phase_violation THEN 0.0 ELSE 1.0 END) AS phase_compliance,
               AVG(h.interaction_quality) AS avg_quality,
               SUM(CASE WHEN h.user_gives_command THEN 1 ELSE 0 END) AS commands,
               SUM(CASE WHEN h.user_asks_question THEN 1 ELSE 0 END) AS questions
        FROM copilot_turn t
        JOIN heuristic_label h ON h.turn_id = t.id
        {where}
        GROUP BY t.session_id
        """,
        tuple(params),
    )

    stats = KpiStats()
    for r in rows:
        (sess_id, labeled, corr, rework, first, phase, avg_q, commands, questions) = r
        denom = (commands or 0) + (questions or 0)
        autonomy = (commands / denom) if denom else None
        _upsert_kpi(
            db, sess_id, rubric_name,
            labeled=int(labeled or 0),
            correction_rate=_f(corr),
            rework_rate=_f(rework),
            first_attempt_success_rate=_f(first),
            autonomy_score=_f(autonomy),
            phase_compliance_score=_f(phase),
            avg_interaction_quality=_f(avg_q),
        )
        stats.sessions += 1
    db.commit()
    return stats


def _f(v):
    return float(v) if v is not None else None


def _upsert_kpi(
    db: Database, session_id: int, rubric_name: str, *,
    labeled: int, correction_rate, rework_rate, first_attempt_success_rate,
    autonomy_score, phase_compliance_score, avg_interaction_quality,
) -> None:
    db.execute(
        """
        INSERT INTO session_kpi
            (session_id, rubric_name, labeled_turn_count, correction_rate,
             rework_rate, first_attempt_success_rate, autonomy_score,
             phase_compliance_score, avg_interaction_quality, computed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (session_id, rubric_name) DO UPDATE SET
            labeled_turn_count=excluded.labeled_turn_count,
            correction_rate=excluded.correction_rate,
            rework_rate=excluded.rework_rate,
            first_attempt_success_rate=excluded.first_attempt_success_rate,
            autonomy_score=excluded.autonomy_score,
            phase_compliance_score=excluded.phase_compliance_score,
            avg_interaction_quality=excluded.avg_interaction_quality,
            computed_at=excluded.computed_at
        """,
        (
            session_id, rubric_name, labeled, correction_rate, rework_rate,
            first_attempt_success_rate, autonomy_score, phase_compliance_score,
            avg_interaction_quality, _now_iso(),
        ),
    )


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
