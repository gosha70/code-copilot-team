"""Cost with explicit provenance, owned by routing-eval.

Why this lives here and not in the harness: ``specs/benchmark-harness/
spec.md`` § Constraints declares dollar-cost reporting "permanently out
of scope until billing-correlation is solved across providers; no schema
slot for cost estimation is added", and
``test_no_dollar_cost_in_backend_metadata`` enforces it by asserting
``total_cost_usd`` never reaches ``backend_metadata``. E1 does not
reverse that. It reads the value straight from the backend transcript
into routing-eval's own record, leaving ``BackendResult``,
``backend_metadata``, and every shared schema untouched.

Provenance is a closed set (plan.md § Cost and reporting contract):

``measured``
    ``total_cost_usd`` reported by the backend itself, read from the
    transcript's final ``type: "result"`` record. This mirrors
    ``rb_measured_cost`` in ``scripts/lib/routing-probe.sh``: normalize
    the JSON/JSONL stream, select the last result record (or the single
    untyped object of a bare-JSON transcript), and accept the field only
    when it is a number ``>= 0``. Reading the *stream* rather than any
    mapping matters — an assistant message that happens to contain a
    ``total_cost_usd`` key is in-band model output, not accounting, and
    must never become a measured cost.

``estimated``
    ``tokens x a versioned price table``. The table version and the
    inputs are recorded so the number is reproducible. An estimate that
    cannot price BOTH the input and output buckets is refused: a partial
    estimate silently understates, and an understated cost wins
    ``always_cheapest``.

``unavailable``
    Neither was obtainable. This propagates as ``insufficient_evidence``
    and is never defaulted to zero — a fabricated zero would silently
    win ``always_cheapest`` and distort the cost axis.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

MEASURED = "measured"
ESTIMATED = "estimated"
UNAVAILABLE = "unavailable"

#: Rates in the price table are quoted per this many tokens.
_TOKENS_PER_RATE_UNIT = 1_000_000

#: Buckets an estimate must price. Refusing a partial estimate is the
#: point: input+output are never optional, and a priced pair understated
#: by a missing bucket is worse than no estimate.
_REQUIRED_TOKEN_KINDS = ("input", "output")

#: Buckets that may add to an estimate when present with a valid rate.
#: A positive count here WITHOUT a rate refuses the estimate instead of
#: silently dropping the bucket.
_OPTIONAL_TOKEN_KINDS = ("cache_read", "cache_write")


def _is_valid_amount(value: Any) -> bool:
    """A usable count/rate/cost: a real, finite, non-negative number.

    Booleans are rejected explicitly — in Python ``bool`` is an ``int``,
    so ``True`` would otherwise read as ``1.0``.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value)) and float(value) >= 0


def _check_estimate_inputs(inputs: Any) -> None:
    """Reject estimator inputs that cannot recompute the estimate.

    The closed shape: ``input`` and ``output`` buckets are REQUIRED,
    ``cache_read``/``cache_write`` optional, nothing else — and every
    bucket present must pair a valid token count with a valid
    per-million rate. ``{"input": {"tokens": 1}}`` is non-empty but has
    no rate and no output bucket, so the number it claims to explain
    cannot be recomputed from it; that is not evidence.
    """
    if not isinstance(inputs, Mapping):
        raise ValueError("estimated cost requires its inputs, for reproducibility")
    unknown = set(inputs) - set(_REQUIRED_TOKEN_KINDS) - set(_OPTIONAL_TOKEN_KINDS)
    if unknown:
        raise ValueError(f"estimate inputs carry unknown bucket(s) {sorted(unknown)}")
    for kind in _REQUIRED_TOKEN_KINDS:
        if kind not in inputs:
            raise ValueError(f"estimate inputs missing required bucket {kind!r}")
    for kind, bucket in inputs.items():
        if (
            not isinstance(bucket, Mapping)
            or not _is_valid_amount(bucket.get("tokens"))
            or not _is_valid_amount(bucket.get("rate_per_million"))
        ):
            raise ValueError(
                f"estimate inputs bucket {kind!r} must pair a valid token "
                f"count with a valid rate_per_million"
            )


@dataclass(frozen=True)
class Cost:
    """A cost value that always knows where it came from.

    The documented invariants are ENFORCED at construction, not merely
    described: ``unavailable`` carries no value and no estimator;
    ``measured`` carries a finite non-negative value and no estimator;
    ``estimated`` carries a finite non-negative value, a named
    estimator, and its inputs. A ``Cost`` that violates them cannot
    exist, so ``satisfies()`` never has to defend against one.
    """

    value: Optional[float]
    provenance: str
    estimator: Optional[str] = None
    inputs: Optional[Mapping[str, Any]] = None
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.provenance == UNAVAILABLE:
            if self.value is not None or self.estimator is not None or self.inputs is not None:
                raise ValueError("unavailable cost must carry no value/estimator/inputs")
            return
        if not _is_valid_amount(self.value):
            raise ValueError(f"{self.provenance} cost requires a finite value >= 0, got {self.value!r}")
        if self.provenance == MEASURED:
            if self.estimator is not None or self.inputs is not None:
                raise ValueError("measured cost must not carry estimator/inputs")
            return
        if self.provenance == ESTIMATED:
            if not isinstance(self.estimator, str) or not self.estimator:
                raise ValueError("estimated cost requires a named estimator version")
            _check_estimate_inputs(self.inputs)
            # BIND the stored value to its recorded inputs: a Cost whose
            # inputs recompute to a different number is a structurally
            # valid lie, and always_cheapest trusts the stored value.
            recomputed = sum(
                float(b["tokens"]) / _TOKENS_PER_RATE_UNIT * float(b["rate_per_million"])
                for b in self.inputs.values()
            )
            if not math.isclose(self.value, recomputed, rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError(
                    f"estimated cost {self.value!r} does not equal its inputs' "
                    f"recomputed total {recomputed!r} — the value is not bound "
                    f"to its evidence"
                )
            return
        raise ValueError(f"unknown cost provenance {self.provenance!r}")

    def as_record(self) -> dict[str, Any]:
        """Shape this for ``routing-run.schema.json``'s ``cost`` object."""
        return {
            "value": self.value,
            "provenance": self.provenance,
            "estimator": self.estimator,
            "inputs": dict(self.inputs) if self.inputs is not None else None,
        }

    def satisfies(self, cost_basis: str) -> bool:
        """Whether this cost may be used under ``cost_basis``.

        A comparison declares one basis and every cost-bearing cell must
        satisfy it; mixing provenance is refused everywhere cost is used.
        ``estimated`` additionally has to match the table version, so two
        estimates from different tables are never compared.
        """
        if self.value is None:
            return False
        if cost_basis == MEASURED:
            return self.provenance == MEASURED
        if cost_basis.startswith(ESTIMATED + "@"):
            wanted = cost_basis.split("@", 1)[1]
            return self.provenance == ESTIMATED and self.estimator == wanted
        return False


def _unavailable(reason: str) -> Cost:
    return Cost(None, UNAVAILABLE, reason=reason)


# ── transcript reading (mirrors rb_json_records + rb_measured_cost) ────


def _json_records(text: str) -> list[Any]:
    """Normalize a transcript into a list of JSON records.

    Same shape as ``rb_json_records``: the whole text as one JSON
    document (a top-level array flattens to its elements), else JSONL —
    one record per parseable line, unparseable lines skipped.
    """
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        records = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records
    return list(doc) if isinstance(doc, list) else [doc]


def measured_cost(transcript_text: str) -> Optional[float]:
    """Return the backend's own reported spend, or ``None``.

    Mirrors ``rb_measured_cost``'s selection rule exactly: the LAST
    ``type: "result"`` record wins; a transcript that is a single JSON
    object with no ``type`` key counts as its own result record. Records
    of any other type — assistant messages included — are never
    consulted, so in-band model output cannot forge a measured cost.
    The value counts only when it is a real, finite number ``>= 0``.
    """
    if not isinstance(transcript_text, str):
        return None
    records = _json_records(transcript_text)

    result: Optional[Mapping[str, Any]] = None
    for record in records:
        if isinstance(record, Mapping) and record.get("type") == "result":
            result = record
    if result is None and len(records) == 1:
        only = records[0]
        if isinstance(only, Mapping) and "type" not in only:
            result = only
    if result is None:
        return None

    raw = result.get("total_cost_usd")
    if not _is_valid_amount(raw):
        return None
    return float(raw)


# ── estimation ─────────────────────────────────────────────────────────


def load_price_table(path: Path) -> Mapping[str, Any]:
    """Load a versioned price table.

    Raises ``ValueError`` (named, not an ``AttributeError`` from deep
    inside an estimate) when the root is not an object.
    """
    with Path(path).open(encoding="utf-8") as handle:
        table = json.load(handle)
    if not isinstance(table, Mapping):
        raise ValueError(f"{path}: price table root must be a JSON object")
    return table


def estimate_cost(
    tokens: Mapping[str, Any],
    model: Optional[str],
    price_table: Mapping[str, Any],
) -> Cost:
    """Estimate from token counts, or report why it was not possible.

    Strict by design:
    - An unlisted model yields ``unavailable`` rather than a default
      rate — the table ships no default deliberately.
    - Input AND output counts must both be valid and priced. A partial
      estimate silently understates.
    - A malformed count or rate (negative, non-finite, boolean,
      non-numeric) refuses the whole estimate instead of being skipped:
      skipping is how a negative or understated number wins
      ``always_cheapest``.
    - A positive cache count with no cache rate refuses the estimate for
      the same reason.
    """
    # A malformed table is absence of evidence, never a crash: the
    # caller is in the middle of resolving one attempt's cost, and an
    # AttributeError here would take the whole run down instead of
    # marking one cell insufficient.
    if not isinstance(price_table, Mapping):
        return _unavailable("price table root is not an object")
    version = price_table.get("version")
    if not isinstance(version, str) or not version:
        return _unavailable("price table declares no version")
    if model is None:
        return _unavailable("no model recorded for the attempt")

    models = price_table.get("models")
    if not isinstance(models, Mapping):
        return _unavailable(f"{version} 'models' section is not an object")
    rates = models.get(model)
    if not isinstance(rates, Mapping) or not rates:
        return _unavailable(f"model {model!r} is not listed in {version}")

    used: dict[str, Any] = {}
    total = 0.0

    for kind in _REQUIRED_TOKEN_KINDS:
        count = tokens.get(kind)
        rate = rates.get(kind)
        if not _is_valid_amount(count):
            return _unavailable(f"{kind} token count is missing or invalid: {count!r}")
        if not _is_valid_amount(rate):
            return _unavailable(f"{version} lists no valid {kind} rate for model {model!r}")
        total += (float(count) / _TOKENS_PER_RATE_UNIT) * float(rate)
        used[kind] = {"tokens": count, "rate_per_million": rate}

    for kind in _OPTIONAL_TOKEN_KINDS:
        count = tokens.get(kind)
        if count is None:
            continue
        if not _is_valid_amount(count):
            return _unavailable(f"{kind} token count is invalid: {count!r}")
        if float(count) == 0:
            continue
        rate = rates.get(kind)
        if not _is_valid_amount(rate):
            return _unavailable(
                f"{kind} tokens were consumed but {version} lists no valid "
                f"{kind} rate for model {model!r} — refusing an understated estimate"
            )
        total += (float(count) / _TOKENS_PER_RATE_UNIT) * float(rate)
        used[kind] = {"tokens": count, "rate_per_million": rate}

    return Cost(total, ESTIMATED, estimator=version, inputs=used)


def resolve_cost(
    transcript_text: Optional[str],
    tokens: Mapping[str, Any],
    model: Optional[str],
    price_table: Optional[Mapping[str, Any]] = None,
) -> Cost:
    """Resolve one attempt's cost: measured, else estimated, else absent.

    The order is deliberate — a backend's own reported spend outranks
    anything computed from a rate table.
    """
    if transcript_text is not None:
        value = measured_cost(transcript_text)
        if value is not None:
            return Cost(value, MEASURED)
    if price_table is None:
        return _unavailable("no measured total_cost_usd and no price table supplied")
    return estimate_cost(tokens, model, price_table)
