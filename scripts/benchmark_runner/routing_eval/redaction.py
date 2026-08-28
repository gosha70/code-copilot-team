"""Write-time redaction and the measured changed-file boundary (E1 T6).

plan.md decision 8, implemented exactly: **redaction is a property of
the writer, not the reader**. Secret values, authorization headers, API
keys, connector-inventory carriers, and sensitive absolute paths are
scrubbed at the point the record is written, so a leaked artifact
cannot contain them regardless of who reads it. Scrubbing at read or
report time is structurally too late — by then the secret already
reached durable storage — and the regression suite proves that
counterfactual explicitly.

The guarantee has two layers, and the ORDER matters:

- **The dynamic literal-secret set is the actual-value guarantee.** A
  credential that reached harvested evidence is removed by literal
  value, not by shape — a deliberately boring token
  (``correct-horse-X7``) echoed in prose with no label, no header, and
  no recognizable format is still scrubbed. Values are resolved from
  the credential references the executed registry itself declares
  (``credential_env`` carries environment-variable NAMES — increment
  A's structural boundary), never by enumerating the environment, and
  are replaced literally (longest first, regex metacharacters inert)
  BEFORE any pattern runs.
- **The closed pattern set is defense in depth.** It catches
  secret-shaped material whose value E1 was never told about.

Two further invariants make redaction safe for an evaluation artifact:

- **Redaction never alters measurement semantics.** The scrub touches
  string values only, and ``write_run_records`` refuses to persist any
  record whose *measurement view* — fingerprints, identities, trial
  coordinates, costs, tokens, states, verdicts, counts — differs after
  scrubbing. A pattern set that would rewrite a digest is a bug and
  fails loudly, never silently.
- **Redaction never breaks the contract.** Every scrubbed record must
  still validate against ``routing-run.schema.json`` before a byte is
  written.

The same writer owns the changed-file boundary: virtual environments,
caches, bytecode, VCS internals, and generated runtime noise are
excluded from the changed-file measure (``is_measured_path`` /
``measured_diff_lines``), so environment churn can never masquerade as
semantic product.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional, Sequence

from .record_check import load_schema, validate

REDACTED = "[REDACTED]"


class RedactionError(RuntimeError):
    """The artifact cannot be persisted without violating decision 8."""


# ── the closed secret-pattern set ──────────────────────────────────────
# Each entry is (pattern, replacement). The set is CLOSED and reviewed:
# authorization headers, key/token/secret assignments (the carrier
# keeps its name, the value is redacted), the CCT config carriers that
# a namespace keep would otherwise shield (CCT_CONFIG__*, CCT_CLI_SETS
# — the connector-inventory channel), well-known bare token shapes, and
# private-key blocks. Prose channels fail TOWARD redaction; the
# measurement view guarantees measurement fields cannot be touched.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
        ),
        REDACTED,
    ),
    (
        re.compile(r"(?im)^(\s*(?:proxy-)?authorization\s*[:=]\s*).+$"),
        r"\g<1>" + REDACTED,
    ),
    (
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
        "Bearer " + REDACTED,
    ),
    (
        re.compile(r"\b(CCT_CONFIG__[A-Za-z0-9_]+|CCT_CLI_SETS)\s*[=:]\s*(?:\"[^\"]*\"|'[^']*'|\S+)"),
        r"\g<1>=" + REDACTED,
    ),
    (
        re.compile(
            r"(?i)\b([A-Za-z0-9_.-]*(?:api[_-]?key|token|secret|password|passwd|credential)s?[A-Za-z0-9_.-]*)"
            r"(\s*[=:]\s*)(?:\"[^\"]*\"|'[^']*'|\S+)"
        ),
        r"\g<1>\g<2>" + REDACTED,
    ),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), REDACTED),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}"), REDACTED),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), REDACTED),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), REDACTED),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"), REDACTED),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
        REDACTED,
    ),
)


#: A `credential_env` line in the registry's accepted grammar: the
#: value is an environment-variable NAME (increment A's structural
#: boundary — no registry field ever holds a literal credential).
_CREDENTIAL_REF_RE = re.compile(
    r'^\s*credential_env\s*=\s*"?([A-Za-z_][A-Za-z0-9_]*)"?\s*(?:#.*)?$'
)


def secret_values_from_registry(
    registry_path: "Path | str",
    environ: "Mapping[str, str] | None" = None,
) -> tuple[str, ...]:
    """Resolve ONLY the credential values the executed registry
    references. Each ``credential_env`` line names an environment
    variable; those names — and no others — are looked up, and their
    non-empty values become the dynamic literal-secret set. The
    environment is never enumerated, dumped, or pattern-matched: the
    credential boundary stays exactly where increment A drew it."""
    env = os.environ if environ is None else environ
    values: list[str] = []
    path = Path(registry_path)
    if not path.exists():
        return ()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _CREDENTIAL_REF_RE.match(line)
        if match:
            value = env.get(match.group(1))
            if value:
                values.append(value)
    return tuple(dict.fromkeys(values))


def _scrub_literals(text: str, secret_values: Sequence[str]) -> str:
    """The actual-value pass: every known credential value is replaced
    LITERALLY — regex metacharacters are inert, empty values are
    ignored, and replacement is deterministic longest-first so an
    overlapping shorter secret can never leave a fragment of a longer
    one behind."""
    ordered = sorted(
        {v for v in secret_values if v}, key=lambda v: (-len(v), v)
    )
    for value in ordered:
        text = text.replace(value, REDACTED)
    return text


def scrub_text(
    text: str,
    *,
    home: "Path | str | None" = None,
    secret_values: Sequence[str] = (),
) -> str:
    """Scrub one string: known credential VALUES first (literally —
    the guarantee that a boring, unlabeled secret still never ships),
    then the closed secret patterns, then sensitive absolute paths
    (the user home prefix collapses to ``~`` so no username ships in
    an artifact). Idempotent: the replacement token matches no pattern
    and no credential value."""
    text = _scrub_literals(text, secret_values)
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    home_prefix = str(home if home is not None else Path.home()).rstrip("/")
    if home_prefix and home_prefix != "/":
        text = text.replace(home_prefix, "~")
    return text


def scrub(
    value: Any,
    *,
    home: "Path | str | None" = None,
    secret_values: Sequence[str] = (),
) -> Any:
    """Deep-scrub a JSON-like structure. String VALUES only — our
    writers never carry payload data in keys, and rewriting keys could
    break the closed schemas. Numbers, booleans, and null are returned
    untouched by construction."""
    if isinstance(value, str):
        return scrub_text(value, home=home, secret_values=secret_values)
    if isinstance(value, list):
        return [scrub(v, home=home, secret_values=secret_values) for v in value]
    if isinstance(value, dict):
        return {
            k: scrub(v, home=home, secret_values=secret_values)
            for k, v in value.items()
        }
    return value


# ── the measured changed-file boundary ─────────────────────────────────
#: Path segments that are environment/cache churn, never semantic
#: product. CLOSED: venvs, package caches, bytecode, VCS internals,
#: node_modules, and the CCT runtime evidence tree itself.
_EXCLUDED_SEGMENTS = frozenset(
    {
        ".venv",
        "venv",
        ".git",
        "node_modules",
        "__pycache__",
        ".cache",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".direnv",
        ".eggs",
        ".cct",
    }
)
_EXCLUDED_SEGMENT_SUFFIXES = (".egg-info", ".dist-info")
_EXCLUDED_FILE_SUFFIXES = (".pyc", ".pyo")


def is_measured_path(path: str) -> bool:
    """True when the path counts toward the changed-file measure."""
    parts = PurePosixPath(path.replace("\\", "/")).parts
    for segment in parts:
        if segment in _EXCLUDED_SEGMENTS:
            return False
        if segment.endswith(_EXCLUDED_SEGMENT_SUFFIXES):
            return False
    return not path.endswith(_EXCLUDED_FILE_SUFFIXES)


def measured_diff_lines(numstat_text: str) -> Optional[int]:
    """Total added+deleted lines from ``git diff --numstat`` output,
    over measured paths only. Binary churn in a measured path has no
    honest line count — the measure is None (insufficiency downstream),
    never a guess and never zero."""
    total = 0
    for line in numstat_text.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        adds, dels, path = parts
        if not is_measured_path(path):
            continue
        if adds == "-" or dels == "-":
            return None
        total += int(adds) + int(dels)
    return total


# ── the measurement view: what redaction must never change ─────────────
def measurement_view(record: Mapping[str, Any]) -> Mapping[str, Any]:
    """The record minus its prose channels, counts preserved.

    Everything in this view is measurement semantics — fingerprint
    components, trial coordinates, mode/profile identity, costs,
    tokens, decision states and verdicts, packet and reconciler
    identities, and the COUNTS of the prose-only collections (rows 6,
    8, 11 measure lengths, so a scrub that dropped an entry would be a
    measurement change). Only the prose payloads themselves — reasons,
    evidence references, violation text, insufficiency reasons — are
    outside the view and therefore scrubbable.
    """
    view = json.loads(json.dumps(record))
    for verifier in view.get("verifiers") or []:
        verifier.pop("evidence_ref", None)
    for decision in view.get("routing_decisions") or []:
        decision.pop("reason", None)
        for candidate in decision.get("considered") or []:
            candidate.pop("reason", None)
    for channel in ("scope_violations", "interventions", "rollbacks"):
        if view.get(channel) is not None:
            view[channel] = len(view[channel])
    view["insufficient_evidence"] = sorted(
        (view.get("insufficient_evidence") or {}).keys()
    )
    return view


def _relativize_evidence(record: dict, evidence_root: Path) -> None:
    """Evidence references become artifact-root-relative BEFORE the
    scrub, so they stay resolvable (the T6 contract: verifier evidence
    references resolve to readable artifacts) instead of being mangled
    by the home-path scrub. An absolute reference outside the artifact
    root cannot ship with the artifact — refused, never guessed at."""
    root = Path(evidence_root).resolve()
    carriers = list(record.get("verifiers") or []) + list(
        record.get("repair_cycles") or []
    )
    for carrier in carriers:
        ref = carrier.get("evidence_ref")
        if not isinstance(ref, str) or not os.path.isabs(ref):
            continue
        resolved = Path(ref).resolve()
        try:
            carrier["evidence_ref"] = resolved.relative_to(root).as_posix()
        except ValueError:
            raise RedactionError(
                f"referenced evidence {ref!r} lives outside the artifact "
                f"root {str(root)!r} — an artifact whose evidence "
                f"references cannot ship with it is not a reproducible "
                f"artifact"
            ) from None


def write_run_records(
    records: Sequence[Mapping[str, Any]],
    path: "Path | str",
    *,
    evidence_root: "Path | str",
    secret_values: Sequence[str],
    home: "Path | str | None" = None,
) -> Path:
    """THE persistence gate for routing-run records (decision 8).

    ``secret_values`` is REQUIRED — there is no empty default a caller
    can silently fall into. Production callers resolve it from the
    executed registry (``secret_values_from_registry`` /
    ``SupervisorRunner._secret_values``); passing ``()`` is an
    explicit declaration that no runtime credential exists, never an
    accident of omission.

    Per record, in order: evidence references relativized against the
    artifact root; the deep scrub; the measurement-view equality check
    (redaction that altered any measurement field refuses the whole
    write); full schema validation of the SCRUBBED record; then one
    canonical JSON line. The file is written atomically and a
    pre-existing path refuses — the same freshness rule every other E1
    evidence writer follows. Records are scrubbed before any byte
    reaches durable storage; there is no raw-then-scrub window.
    """
    out = Path(path)
    if out.exists():
        raise RedactionError(
            f"artifact {out} already exists — refusing to overwrite a "
            f"persisted result artifact"
        )
    schema = load_schema("routing-run")
    lines = []
    for i, source in enumerate(records):
        record = json.loads(json.dumps(source))
        _relativize_evidence(record, Path(evidence_root))
        before = measurement_view(record)
        scrubbed = scrub(record, home=home, secret_values=secret_values)
        if measurement_view(scrubbed) != before:
            raise RedactionError(
                f"record {i}: redaction altered the measurement view — a "
                f"scrub that changes measurement semantics or fingerprints "
                f"is refused, never persisted"
            )
        errors = validate(scrubbed, schema)
        if errors:
            raise RedactionError(
                f"record {i} is not schema-valid after redaction: {errors[:3]}"
            )
        lines.append(json.dumps(scrubbed, sort_keys=True, separators=(",", ":")))
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    return out
