# session_analytics.judge.label_sources — "where do these labels come from?"
#
# Judge validation (#313) compares two sets of labels over the same turns:
# a judge run against another judge run (run-to-run agreement), or a judge
# run against a person (human agreement). Both are addressed the same way,
# a LABEL SOURCE: `rubric:<rubric_name>` for rows in heuristic_label,
# `human:<labeler>` for rows in human_label; a bare name is a rubric. The
# runner uses it to pick the turns another source has already labelled;
# the agreement module uses it to read the labels themselves.

from __future__ import annotations

from dataclasses import dataclass

from .. import constants as C


class UnknownLabelSourceError(ValueError):
    pass


@dataclass(frozen=True)
class LabelSource:
    kind: str     # C.LABEL_SOURCE_RUBRIC | C.LABEL_SOURCE_HUMAN
    name: str     # rubric_name or labeler

    @property
    def table(self) -> str:
        return C.TBL_HEURISTIC_LABEL if self.kind == C.LABEL_SOURCE_RUBRIC else C.TBL_HUMAN_LABEL

    @property
    def key_column(self) -> str:
        return "rubric_name" if self.kind == C.LABEL_SOURCE_RUBRIC else "labeler"

    @property
    def spec(self) -> str:
        return f"{self.kind}:{self.name}"


def parse_label_source(spec: str) -> LabelSource:
    text = (spec or "").strip()
    if not text:
        raise UnknownLabelSourceError("empty label source")
    kind, sep, name = text.partition(":")
    if not sep:
        return LabelSource(C.LABEL_SOURCE_RUBRIC, text)
    if kind not in (C.LABEL_SOURCE_RUBRIC, C.LABEL_SOURCE_HUMAN) or not name.strip():
        raise UnknownLabelSourceError(
            f"label source must be rubric:<name> or human:<labeler>, got {spec!r}"
        )
    return LabelSource(kind, name.strip())


def label_source_join(spec: str, turn_alias: str, alias: str = "src") -> tuple[str, tuple[str, ...]]:
    """An INNER JOIN restricting ``turn_alias`` (a copilot_turn) to turns
    the source has labelled, with its parameter. Judge rows join on
    turn_id and count only when they parsed (a backend_error row is an
    attempt, not a label); human rows join on (session, sequence), the
    anchor that survives a re-ingest."""
    src = parse_label_source(spec)
    if src.kind == C.LABEL_SOURCE_RUBRIC:
        join = (
            f"JOIN {src.table} {alias} ON {alias}.turn_id = {turn_alias}.id "
            f"AND {alias}.{src.key_column} = ? AND {alias}.parse_status = 'ok'"
        )
    else:
        join = (
            f"JOIN {src.table} {alias} ON {alias}.session_ref = {turn_alias}.session_id "
            f"AND {alias}.sequence_num = {turn_alias}.sequence_num AND {alias}.{src.key_column} = ?"
        )
    return join, (src.name,)
