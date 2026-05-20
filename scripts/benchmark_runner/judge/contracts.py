# benchmark_runner.judge.contracts — Judge protocol + dataclasses.
#
# The Judge protocol mirrors the Backend protocol from
# benchmark_runner.contracts: frozen input/output dataclasses + a
# runtime_checkable Protocol with a single method.
#
# Additivity invariant (load-bearing): the judge produces a per-attempt
# judge.json that lands adjacent to score.json. score.json is NEVER
# overwritten by judge code; the deterministic verdict is authoritative
# and the judge is strictly secondary. Calibration / re-running the
# judge / changing the rubric MUST NOT require re-running the
# underlying benchmark.
#
# Determinism contract (peer-reviewed 2026-05-20). The local ``claude``
# CLI exposes only ``--model`` / ``--fallback-model`` — there is no
# ``--temperature`` and no ``--seed`` flag. The claude_code judge
# therefore records ``temperature: None`` / ``seed: None`` /
# ``temperature_control: "unsupported"`` / ``seed_control:
# "unsupported"``. Re-run stability is an EMPIRICAL property surfaced
# by the calibration step's Spearman against human labels, not a
# guarantee from a fixed T=0. A future judge whose backend exposes the
# knob MAY set these fields to non-None / "supported"; the schema is
# forward-compatible.
#
# All dataclasses are frozen — judge records must not mutate after
# capture, mirroring the contracts.py convention.

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Protocol, runtime_checkable


# ── Identifier / enum constants ────────────────────────────────────────
# Use these everywhere instead of bare strings so renames are caught
# by the type checker rather than by surprise at runtime.

# Rating bounds (inclusive). The rubric prompt + the validate step
# both reference these; defining them here keeps the bounds grep-able
# as one unit.
JUDGE_RATING_MIN = 1
JUDGE_RATING_MAX = 5

# Sentinel values for ``JudgeInvocation.temperature_control`` and
# ``seed_control``. ``"supported"`` means the judge backend can pin
# the knob and did pin it; ``"unsupported"`` means the backend CLI
# does not expose the knob at all (the claude-code judge case).
# ``"available_not_pinned"`` is reserved for a future judge that
# *could* pin the knob but deliberately left it at the model default
# (e.g. for a fidelity-comparison run).
TEMPERATURE_CONTROL_SUPPORTED = "supported"
TEMPERATURE_CONTROL_UNSUPPORTED = "unsupported"
TEMPERATURE_CONTROL_AVAILABLE_NOT_PINNED = "available_not_pinned"

SEED_CONTROL_SUPPORTED = "supported"
SEED_CONTROL_UNSUPPORTED = "unsupported"
SEED_CONTROL_AVAILABLE_NOT_PINNED = "available_not_pinned"


# ── Rubric ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RubricSpec:
    """The rubric a Judge rates against.

    ``name`` identifies the rubric version (e.g. ``"default-v1"``).
    Calibration reports are recorded against this name so a future
    reader can identify which rubric a report was generated against.

    ``dimensions`` is the ordered tuple of dimension names; the judge
    produces one rating per dimension. The rubric file at
    ``benchmarks/calibration/rubric-<name>.md`` is the source of
    truth for prompt phrasing and 1–5 anchor descriptions — this
    dataclass carries only the data the judge code needs at runtime.

    ``prompt_template`` is the rendered prompt sent to the judge,
    with placeholders for ``{task_id}``, ``{benchmark_id}``,
    ``{prompt}``, ``{diff}``, ``{verify_output}``, and
    ``{rubric_dimensions_block}``. The loader that reads the .md
    file is responsible for rendering the dimensions block into the
    template.
    """

    name: str
    dimensions: tuple[str, ...]
    prompt_template: str


# ── Judge input + output primitives ────────────────────────────────────


@dataclass(frozen=True)
class JudgeInput:
    """Per-attempt context handed to a Judge.

    The Judge READS the already-written attempt artifacts (it does
    not re-execute the model). ``attempt_dir`` is the existing
    ``<run-dir>/<task-slug>/attempt-NN-run-MM/`` directory; the judge
    reads from it and writes ``judge.json`` into it. ``diff_path``,
    ``prompt_path``, and ``verify_output`` are passed explicitly
    rather than rediscovered from the directory so that fake-CLI
    tests can stage attempts without a full run.

    ``verify_output`` is the text emitted by the deterministic
    verify step (typically the test runner's stdout/stderr tail).
    Passed as a string rather than a path because (a) the runner
    sometimes truncates it before writing, and (b) the judge's
    prompt template wants the content inline.
    """

    attempt_dir: Path
    task_id: str
    benchmark_id: str
    diff_path: Path
    prompt_path: Path
    verify_output: str
    rubric: RubricSpec


@dataclass(frozen=True)
class DimensionRating:
    """One dimension's rating in a JudgeResult.

    ``rating`` is an integer in ``[JUDGE_RATING_MIN, JUDGE_RATING_MAX]``
    when the dimension applies, or ``None`` when the dimension is
    STRUCTURALLY INAPPLICABLE to the attempt (per the rubric's
    "When a dimension does not apply" clause). ``None`` is the narrow
    carve-out for cases like ``test_thoughtfulness`` on a task whose
    instructions explicitly forbid editing tests, NOT for ordinary
    absence (no tests on a task that allowed them is rating 1).

    The 1..5-or-None invariant is enforced in ``__post_init__`` —
    this dataclass is the API surface that parsers/runners trust
    before writing ``judge.json`` and before calibration computes
    Spearman, so out-of-range values are rejected at construction
    rather than silently propagated.

    ``explanation`` is REQUIRED in both cases — for numeric ratings
    it explains the rating; for ``None`` ratings it justifies the
    inapplicability claim.

    ``prompt_sha256`` is the SHA-256 of the exact prompt the judge
    sent for this dimension. Per-dimension rather than per-attempt
    because a judge implementation MAY use separate prompts per
    dimension (the v1 prompt template uses one combined prompt; the
    field is per-dimension so a future judge can split without
    schema migration).
    """

    rating: Optional[int]
    explanation: str
    prompt_sha256: str

    def __post_init__(self) -> None:
        if self.rating is None:
            return
        # ``bool`` is a subclass of ``int`` in Python — reject it
        # explicitly so ``True``/``False`` cannot quietly coerce to
        # rating 1/0. This is the kind of silent-coercion bug the
        # null-vs-zero discipline elsewhere already guards against.
        if isinstance(self.rating, bool) or not isinstance(self.rating, int):
            raise TypeError(
                f"DimensionRating.rating must be int or None; "
                f"got {type(self.rating).__name__} {self.rating!r}"
            )
        if not (JUDGE_RATING_MIN <= self.rating <= JUDGE_RATING_MAX):
            raise ValueError(
                f"DimensionRating.rating must be in "
                f"[{JUDGE_RATING_MIN}, {JUDGE_RATING_MAX}] or None; "
                f"got {self.rating!r}"
            )


@dataclass(frozen=True)
class JudgeInvocation:
    """Reproducibility record for one Judge invocation.

    ``model`` is the model alias the judge passed to its backend
    (e.g. ``"sonnet"``). ``temperature`` and ``seed`` are recorded
    as the judge actually controlled them — ``None`` means "judge
    did not pin this knob"; the ``*_control`` fields disambiguate
    *why* ("unsupported" = the CLI does not expose the knob;
    "available_not_pinned" = the knob exists but the judge chose
    not to pin it; "supported" = the knob exists and was pinned to
    the recorded value).

    ``provider_endpoint_present`` is a PRESENCE BOOLEAN — never the
    endpoint URL or any secret. Mirrors the backends' provider-env
    discipline: report that routing happened, never what to.
    """

    model: str
    temperature: Optional[float] = None
    seed: Optional[int] = None
    temperature_control: str = TEMPERATURE_CONTROL_UNSUPPORTED
    seed_control: str = SEED_CONTROL_UNSUPPORTED
    provider_endpoint_present: bool = False


@dataclass(frozen=True)
class JudgeResult:
    """What a Judge produced on one attempt.

    ``ratings`` is keyed by dimension name (matching the input
    ``RubricSpec.dimensions`` tuple). The runner serializes this
    into ``judge.json`` adjacent to ``score.json`` (the additivity
    invariant — score.json is never modified by judge code).

    ``tokens_input`` / ``tokens_output`` are ``Optional[int]``
    because not all judge backends report them; mirrors
    ``BackendResult``'s null-vs-zero discipline. ``None`` means
    "judge did not provide"; ``0`` means "judge reported zero." Do
    not coerce.
    """

    judge_id: str
    judge_model: str
    judge_backend_id: str
    rubric_name: str
    ratings: Mapping[str, DimensionRating]
    invocation: JudgeInvocation
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    judge_metadata: Mapping[str, object] = field(default_factory=dict)


# ── Protocols ──────────────────────────────────────────────────────────


@runtime_checkable
class Judge(Protocol):
    """Contract every Judge implementation must satisfy.

    Implementations live under
    ``scripts/benchmark_runner/judge/<id>_judge.py`` and register via
    ``benchmark_runner._register`` (parallel to the backends'
    registration pattern).
    """

    judge_id: str

    def rate(self, attempt: JudgeInput) -> JudgeResult:
        """Rate one already-completed attempt against the rubric.

        The judge does NOT re-execute the underlying model — it
        reads ``attempt.diff_path``, ``attempt.prompt_path``, and
        ``attempt.verify_output``, invokes its own LLM with the
        rubric prompt template, and returns a ``JudgeResult``. The
        runner is responsible for writing ``judge.json``; the Judge
        produces the in-memory record only.
        """
