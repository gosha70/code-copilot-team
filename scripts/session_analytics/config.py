# session_analytics.config — config loading (no hardcoded structured data).
#
# Schema defaults live in config_data/defaults.json (and the sibling map
# files), NOT as literals in source. User configuration is a single repo-root
# ``.env`` — the SAME file the CLI and the Studio config page read and write,
# so there is one source of truth. The loader layers, lowest → highest:
#
#   defaults.json  <  ~/.cct/session-analytics.json  <  repo-root .env  <  real env vars  <  CLI args
#
# (.env only fills gaps a real environment variable hasn't already set, the
# conventional dotenv precedence.)

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Mapping, Optional

from . import constants as C

# Env vars / .env keys (presence-checked, never logged for secrets).
# The database key is CCT_SA_DB. It was CCT_SA_DSN until 2026-09 ("what
# does DSN stand for?" — the owner's first-contact finding); the old name
# is still READ so an existing .env keeps working, and is rewritten to
# the new name the next time the file is saved.
ENV_DB = "CCT_SA_DB"
ENV_DSN_LEGACY = "CCT_SA_DSN"
#: Kept as an alias for callers that import the old constant.
ENV_DSN = ENV_DB
# Developer identity (Slice B1, #187). Spec-mandated name (not CCT_SA_).
ENV_DEVELOPER_ID = "CCT_DEVELOPER_ID"
ENV_KUZU_PATH = "CCT_SA_KUZU_PATH"
ENV_BENCHMARK_RUNS_ROOT = "CCT_SA_BENCHMARK_RUNS_ROOT"
ENV_REDACTION = "CCT_SA_REDACTION"
ENV_OLLAMA_URL = "CCT_SA_OLLAMA_URL"
ENV_JUDGE_BACKEND = "CCT_SA_JUDGE_BACKEND"
ENV_JUDGE_MODEL = "CCT_SA_JUDGE_MODEL"
ENV_JUDGE_BASE_URL = "CCT_SA_JUDGE_BASE_URL"
ENV_JUDGE_API_KEY = "CCT_SA_JUDGE_API_KEY"
ENV_JUDGE_WORKERS = "CCT_SA_JUDGE_WORKERS"
ENV_EMBED_BACKEND = "CCT_SA_EMBED_BACKEND"
ENV_EMBED_MODEL = "CCT_SA_EMBED_MODEL"
ENV_EMBED_INPUT_CAP = "CCT_SA_EMBED_INPUT_CAP"
ENV_EMBED_WORKERS = "CCT_SA_EMBED_WORKERS"
ENV_NOISE_MIN_TURNS = "CCT_SA_NOISE_MIN_TURNS"
ENV_NOISE_MIN_DURATION = "CCT_SA_NOISE_MIN_DURATION_SECONDS"
ENV_NOISE_PATH_PATTERNS = "CCT_SA_NOISE_PATH_PATTERNS"   # comma-separated
ENV_SIMILARITY_THRESHOLD = "CCT_SA_SIMILARITY_THRESHOLD"
ENV_TEAM_ACTIVE_WINDOW = "CCT_SA_TEAM_ACTIVE_WINDOW"
ENV_TEAM_ALIASES = "CCT_SA_TEAM_ALIASES"   # id=Name,id2=Name
ENV_BUDGET_TEAM_DAILY = "CCT_SA_BUDGET_TEAM_DAILY_USD"
ENV_BUDGET_TEAM_MONTHLY = "CCT_SA_BUDGET_TEAM_MONTHLY_USD"
ENV_BUDGET_DEVELOPER_DAILY = "CCT_SA_BUDGET_DEVELOPER_DAILY_USD"
ENV_BUDGET_PROJECT_DAILY = "CCT_SA_BUDGET_PROJECT_DAILY_USD"
ENV_RUNAWAY_RECENT_MINUTES = "CCT_SA_RUNAWAY_RECENT_MINUTES"
ENV_RUNAWAY_MAX_TURNS_RECENT = "CCT_SA_RUNAWAY_MAX_TURNS_RECENT"
ENV_RUNAWAY_RECENT_TURNS = "CCT_SA_RUNAWAY_RECENT_TURNS"
ENV_RUNAWAY_MAX_ERROR_SHARE = "CCT_SA_RUNAWAY_MAX_ERROR_SHARE"
ENV_RUNAWAY_MIN_TURNS_FOR_ERROR_SHARE = "CCT_SA_RUNAWAY_MIN_TURNS_FOR_ERROR_SHARE"
ENV_RUNAWAY_MAX_COST_RECENT = "CCT_SA_RUNAWAY_MAX_COST_RECENT_USD"
#: The Settings page's Team group (env keys the page can edit).
TEAM_ENV_KEYS = (
    ENV_TEAM_ACTIVE_WINDOW, ENV_BUDGET_TEAM_DAILY, ENV_BUDGET_TEAM_MONTHLY,
    ENV_BUDGET_DEVELOPER_DAILY, ENV_BUDGET_PROJECT_DAILY,
)
ENV_SIMILARITY_TOP_K = "CCT_SA_SIMILARITY_TOP_K"
ENV_SOURCE_PREFIX = "CCT_SA_SOURCE_"  # + COPILOT (e.g. CCT_SA_SOURCE_CLAUDE_CODE)
# Routing-shadow (#261): evidence roots are SERVER-SIDE configuration —
# the API never serves the raw paths (only {configured, root_count}).
ENV_ROUTING_EVIDENCE_ROOTS = "CCT_SA_ROUTING_EVIDENCE_ROOTS"  # os.pathsep-separated
ENV_CALIBRATION_PREFIX = "CCT_SA_CALIBRATION_"


def _coerce_like(template: Any, raw: str) -> Any:
    """Coerce an env override to the defaults-file value's type — a
    threshold stays numeric, a path stays a string; an uncoercible
    override raises rather than silently changing type."""
    if isinstance(template, bool):
        return raw.lower() in ("1", "true", "yes")
    if isinstance(template, int) and not isinstance(template, bool):
        return int(raw)
    if isinstance(template, float):
        return float(raw)
    return raw


# Keys the Studio config page exposes (order = display order). Secret-bearing
# keys are flagged so the API masks them.
ENV_KEYS = (
    ENV_DB, ENV_KUZU_PATH, ENV_BENCHMARK_RUNS_ROOT, ENV_REDACTION,
    ENV_TEAM_ACTIVE_WINDOW, ENV_BUDGET_TEAM_DAILY, ENV_BUDGET_TEAM_MONTHLY,
    ENV_BUDGET_DEVELOPER_DAILY, ENV_BUDGET_PROJECT_DAILY,
    ENV_JUDGE_BACKEND, ENV_JUDGE_MODEL, ENV_JUDGE_BASE_URL, ENV_JUDGE_API_KEY,
    ENV_JUDGE_WORKERS, ENV_OLLAMA_URL, ENV_EMBED_BACKEND, ENV_EMBED_MODEL,
    ENV_DEVELOPER_ID,
)
SECRET_ENV_KEYS = frozenset({ENV_JUDGE_API_KEY})

_CONFIG_PACKAGE = "session_analytics.config_data"
_DEFAULTS_FILE = "defaults.json"
_USER_CONFIG = Path.home() / ".cct" / "session-analytics.json"

# Repo root = …/scripts/session_analytics/config.py → parents[2].
REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"


# ── judge config ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class JudgeConfig:
    """Judge resolution. ``model == ""`` means 'use the backend's native
    default model' — for the default ollama judge that is llama3; for the
    opt-in claude-code judge it is Claude Code's own default (Opus 4.8
    today)."""

    override: Optional[tuple[str, str]]            # explicit (backend, model) from .env/env — global
    by_copilot: Mapping[str, tuple[str, str]]      # per-copilot judge mapping
    default: tuple[str, str]                       # global fallback
    workers: int
    ollama_url: str
    base_url: str                                  # OpenAI-compatible (LM Studio/vLLM/OpenAI/Azure)
    api_key: str

    def resolve(self, copilot: Optional[str] = None) -> tuple[str, str]:
        """The (backend, model) to judge ``copilot`` with. An explicit
        .env/env override wins globally; else the copilot's mapped judge;
        else the global default."""
        if self.override is not None:
            return self.override
        if copilot and copilot in self.by_copilot:
            return self.by_copilot[copilot]
        return self.default

    # Back-compat convenience for the global default.
    @property
    def backend(self) -> str:
        return self.resolve(None)[0]

    @property
    def model(self) -> str:
        return self.resolve(None)[1]


@dataclass(frozen=True)
class EmbeddingConfig:
    """Embedding pass resolution (#285, E2 slice 1).

    ``model == ""`` delegates to the backend's default model — but what
    the ENVELOPE stores is always the backend-RESOLVED identity, never
    this configured string (FR-5): a request is not serving evidence.
    """

    backend: str
    model: str
    ollama_url: str
    input_cap_chars: int
    workers: int


def _sim_threshold(value: Any) -> float:
    """similarity.threshold: a finite number in [-1.0, 1.0] — the
    range cosine can produce. Booleans and non-finite values refuse."""
    if isinstance(value, bool):
        raise ValueError(
            f"similarity.threshold must be a number, got boolean {value!r}")
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"similarity.threshold {value!r} is not a number") from None
    import math as _math
    if not _math.isfinite(f):
        raise ValueError(
            f"similarity.threshold {value!r} is not finite — NaN/inf "
            f"would silently empty or saturate every neighbor set")
    if not (-1.0 <= f <= 1.0):
        raise ValueError(
            f"similarity.threshold {f} is outside [-1.0, 1.0], the "
            f"range cosine similarity can produce")
    return f


def _sim_top_k(value: Any) -> int:
    """similarity.top_k: a positive integer. Booleans, fractional
    values, and non-positive values refuse — int() would silently
    turn True into 1 and 1.9 into 1."""
    if isinstance(value, bool):
        raise ValueError(
            f"similarity.top_k must be an integer, got boolean {value!r}")
    if isinstance(value, int):
        k = value
    elif isinstance(value, str):
        try:
            k = int(value, 10)
        except ValueError:
            raise ValueError(
                f"similarity.top_k {value!r} is not an integer") from None
    elif isinstance(value, float):
        raise ValueError(
            f"similarity.top_k {value!r} has a fractional type — an "
            f"integer count is required, not truncated")
    else:
        raise ValueError(f"similarity.top_k {value!r} is not an integer")
    if k <= 0:
        raise ValueError(f"similarity.top_k must be positive, got {k}")
    return k


@dataclass(frozen=True)
class NoiseConfig:
    """sessions.noise (#307): what lists and aggregates EXCLUDE by
    default, decided at query time so a threshold change never needs a
    re-ingest. A session is noise when it has fewer than ``min_turns``
    turns, lasted under ``min_duration_seconds``, or its project path
    contains any of ``path_patterns`` (probe runs in temp dirs)."""

    min_turns: int
    min_duration_seconds: int
    path_patterns: tuple[str, ...]


@dataclass(frozen=True)
class BudgetsConfig:
    """team.budgets (#174 D): USD ceilings, None = no budget for that
    scope. Team/day and team/month over everyone; developer and
    project per day."""

    team_daily_usd: Optional[float]
    team_monthly_usd: Optional[float]
    developer_daily_usd: Optional[float]
    project_daily_usd: Optional[float]

    def any_set(self) -> bool:
        return any(v is not None for v in (
            self.team_daily_usd, self.team_monthly_usd, self.developer_daily_usd, self.project_daily_usd))


@dataclass(frozen=True)
class RunawayConfig:
    """team.runaway (#174 D): a session whose newest turn is within
    ``recent_minutes`` is a runaway when its turns in that time exceed
    ``max_turns_recent``, or its error share over the last
    ``recent_turns`` turns exceeds ``max_error_share`` (given at least
    ``min_turns_for_error_share`` of them), or its priced cost in that
    time exceeds ``max_cost_recent_usd``."""

    recent_minutes: int
    max_turns_recent: int
    recent_turns: int
    max_error_share: float
    min_turns_for_error_share: int
    max_cost_recent_usd: float


@dataclass(frozen=True)
class TeamConfig:
    """team.* (#174): a heartbeat within ``active_window_seconds`` of now
    makes a developer "active" on the Team tab — last-seen semantics,
    never an alive/dead verdict — plus the budgets and runaway
    thresholds the alerts evaluate.

    ``aliases`` maps a developer id to the display name it belongs
    under: ids sharing a name are one person, folded into one row when
    the team status is read. The store is never rewritten."""

    active_window_seconds: int
    budgets: BudgetsConfig
    runaway: RunawayConfig
    aliases: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SimilarityConfig:
    """Similarity pass knobs (#287). Scores at or above ``threshold``
    are edge-eligible; each session keeps its ``top_k`` best."""

    threshold: float
    top_k: int


@dataclass(frozen=True)
class ProjectOverride:
    """One ``projects.<key>`` entry: a per-project redaction/ingest override.

    ``trace_archive`` (E10 Slice A, #98) is the EXPLICIT opt-in for full-text
    trace archiving — False by default everywhere; there is deliberately no
    global enable flag.
    """

    redaction_mode: Optional[str] = None
    ingest: str = C.INGEST_ON
    trace_archive: bool = False


@dataclass(frozen=True)
class ProjectIdRule:
    """One ``project_ids[]`` entry: a substring-match rule used when a
    session's cwd isn't a locally-detectable git repo."""

    match: str
    id: str


@dataclass(frozen=True)
class AnalyticsConfig:
    sources: Mapping[str, str]
    dsn: str
    kuzu_path: str
    #: The benchmark harness's runs directory; blank = the "Link
    #: benchmark runs" step is skipped. Expanded, never validated here
    #: (the step reports a missing directory as its failure reason).
    benchmark_runs_root: str
    redaction_mode: str
    judge: JudgeConfig
    embedding: "EmbeddingConfig"
    similarity: "SimilarityConfig"
    team: "TeamConfig"
    noise: "NoiseConfig"
    pricing: "PricingConfig"
    projects: Mapping[str, ProjectOverride] = field(default_factory=dict)
    project_id_rules: tuple[ProjectIdRule, ...] = field(default_factory=tuple)
    raw: Mapping[str, Any] = field(default_factory=dict)
    # Slice B1 (#187): identity inputs resolved through THIS loader's
    # documented layering (real env > repo .env; config files), consumed by
    # identity.derive_developer_id — never an os.environ bypass.
    developer_id_env: Optional[str] = None
    developer_id_cfg: Optional[str] = None
    #: Routing-shadow (#261): E1 evidence-set roots. Server-side only;
    #: /api/settings exposes a sanitized {configured, root_count} shape.
    routing_evidence_roots: tuple[str, ...] = ()
    #: routing-calibration (#266): the calibration policy block —
    #: thresholds, classifier parameters, the analytics-owned output
    #: root, and the operator's current policy source. Values come from
    #: the layered config (defaults.json < user config < env), never
    #: from code.
    routing_calibration: Mapping[str, Any] = field(default_factory=dict)

    def source_root(self, copilot: str) -> Optional[Path]:
        raw = self.sources.get(copilot)
        if not raw:
            return None
        return Path(raw).expanduser()

    def project_override(self, key: Optional[str]) -> Optional[ProjectOverride]:
        return self.projects.get(key) if key else None


# ── pricing config (E5 cost tracking) ───────────────────────────────────


@dataclass(frozen=True)
class ModelRate:
    """One model's per-1M-token rates, versioned by ``effective_date``.

    ``effective_date`` doubles as the price version recorded per turn
    (``copilot_turn.cost_price_version``) — see D-units/versioning in
    specs/session-analytics-cost-tracking/plan.md.
    """

    currency: str
    effective_date: str
    input: float
    output: float
    cache_read: float
    cache_write: float


@dataclass(frozen=True)
class PricingConfig:
    """The price table. Empty when no ``pricing`` block is configured —
    that is the regression-safe "cost stays NULL for everything" state."""

    models: Mapping[str, ModelRate] = field(default_factory=dict)

    def rate_for(self, model: Optional[str]) -> Optional[ModelRate]:
        if not model:
            return None
        return self.models.get(model)


# ── .env file I/O (shared by CLI setup + the Studio config page) ────────


def parse_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    """Parse a minimal ``KEY=VALUE`` .env (stdlib only). Ignores comments
    and blank lines; strips surrounding quotes."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, _, val = s.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            out[key] = val
    return out


def write_env_file(values: Mapping[str, str], path: Path = ENV_FILE) -> None:
    """Write the analyzer's keys to ``.env`` (creating it), preserving any
    unrelated keys already present."""
    existing = parse_env_file(path)
    existing.update({k: v for k, v in values.items() if v is not None})
    lines = [
        "# session-analytics configuration (shared by the CLI and the Studio).",
        "# Written by `session-analytics setup` or the Studio Settings page.",
        "# This file may contain secrets (e.g. an external-LLM API key) — it is",
        "# gitignored; do not commit it.",
        "",
    ]
    # The old database key is folded into the new one, never written back:
    # two keys naming one store is how a file ends up lying about itself.
    if ENV_DSN_LEGACY in existing:
        legacy = existing.pop(ENV_DSN_LEGACY)
        existing.setdefault(ENV_DB, legacy)
    for key in ENV_KEYS:
        if key in existing:
            lines.append(f"{key}={existing.pop(key)}")
    for key, val in existing.items():  # any extra/unknown keys preserved
        lines.append(f"{key}={val}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)  # may hold secrets (API keys, DSN passwords) — owner-only


def is_initialized() -> bool:
    """First-run detection: True once a .env exists."""
    return ENV_FILE.is_file()


# ── loading ────────────────────────────────────────────────────────────


def _load_json_text(text: str) -> dict[str, Any]:
    data = json.loads(text) if text.strip() else {}
    if not isinstance(data, dict):
        raise ValueError("config root must be a mapping")
    return data


def _read_defaults() -> dict[str, Any]:
    text = resources.files(_CONFIG_PACKAGE).joinpath(_DEFAULTS_FILE).read_text(encoding="utf-8")
    return _load_json_text(text)


def _deep_merge(base: dict[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _spec_tuple(d: Any, fallback: tuple[str, str]) -> tuple[str, str]:
    if isinstance(d, Mapping):
        return (str(d.get("backend") or fallback[0]), str(d.get("model") or ""))
    return fallback


def _load_pricing(data: Mapping[str, Any]) -> PricingConfig:
    """Parse + validate the ``pricing`` block. No block / empty block →
    an empty ``PricingConfig`` (cost stays NULL everywhere — regression-safe).

    Raises ``ValueError`` if the table mixes currencies (no normalization is
    performed — a mixed table is rejected outright at load, per FR-1)."""
    pdata = data.get(C.CFG_PRICING)
    if not isinstance(pdata, Mapping):
        return PricingConfig()

    raw_models = pdata.get(C.CFG_PRICING_MODELS)
    if not isinstance(raw_models, Mapping):
        return PricingConfig()

    models: dict[str, ModelRate] = {}
    currencies: set[str] = set()
    for model_id, entry in raw_models.items():
        if not isinstance(entry, Mapping):
            raise ValueError(f"pricing.models[{model_id!r}] must be a mapping of rates")
        currency = str(entry.get(C.CFG_PRICE_CURRENCY) or "")
        if not currency:
            raise ValueError(f"pricing.models[{model_id!r}] is missing 'currency'")
        currencies.add(currency)
        # effective_date is the price version stamped into
        # copilot_turn.cost_price_version; a blank version would break the
        # audit/reproducibility guarantee (FR-1/FR-3), so require it.
        effective_date = str(entry.get(C.CFG_PRICE_EFFECTIVE_DATE) or "")
        if not effective_date:
            raise ValueError(f"pricing.models[{model_id!r}] is missing 'effective_date'")

        # Rate values must be present + numeric + non-negative. A missing or
        # misspelled rate key must NOT silently become 0 (that would price
        # those tokens free and understate cost with no error) — an explicit
        # 0.0 is allowed, an absent key is not.
        def _rate(field_key: str) -> float:
            if field_key not in entry:
                raise ValueError(
                    f"pricing.models[{model_id!r}] is missing rate {field_key!r}"
                )
            try:
                val = float(entry[field_key])
            except (TypeError, ValueError):
                raise ValueError(
                    f"pricing.models[{model_id!r}] rate {field_key!r} is not a "
                    f"number: {entry[field_key]!r}"
                )
            if val < 0:
                raise ValueError(
                    f"pricing.models[{model_id!r}] rate {field_key!r} is negative"
                )
            return val

        models[str(model_id)] = ModelRate(
            currency=currency,
            effective_date=effective_date,
            input=_rate(C.CFG_PRICE_INPUT),
            output=_rate(C.CFG_PRICE_OUTPUT),
            cache_read=_rate(C.CFG_PRICE_CACHE_READ),
            cache_write=_rate(C.CFG_PRICE_CACHE_WRITE),
        )

    if len(currencies) > 1:
        raise ValueError(
            f"pricing table mixes currencies {sorted(currencies)!r} without "
            "normalization; a price table must use a single currency"
        )

    return PricingConfig(models=models)


def _load_projects(
    data: Mapping[str, Any],
) -> tuple[dict[str, ProjectOverride], tuple[ProjectIdRule, ...]]:
    """Parse + validate the ``projects`` / ``project_ids`` blocks. Absent or
    non-mapping/non-list blocks resolve to empty ({}, ()) — the
    regression-safe "every session ingests with the global redaction_mode"
    state (FR-6)."""
    projects: dict[str, ProjectOverride] = {}
    pdata = data.get(C.CFG_PROJECTS)
    if isinstance(pdata, Mapping):
        for key, entry in pdata.items():
            if not isinstance(entry, Mapping):
                raise ValueError(f"projects[{key!r}] must be a mapping")

            mode = entry.get(C.CFG_REDACTION)
            if mode is not None and mode not in C.REDACTION_MODES:
                raise ValueError(
                    f"projects[{key!r}]: invalid redaction mode {mode!r}; "
                    f"expected one of {C.REDACTION_MODES}"
                )

            ingest_val = entry.get(C.CFG_PROJECT_INGEST, C.INGEST_ON)
            if ingest_val not in C.INGEST_MODES:
                raise ValueError(
                    f"projects[{key!r}]: invalid ingest mode {ingest_val!r}; "
                    f"expected one of {C.INGEST_MODES}"
                )

            # E10 Slice A (#98): explicit opt-in only — a real boolean, never
            # a truthy coercion ("true"/1 would silently widen the privacy
            # surface; reject them loudly instead).
            trace_archive = entry.get(C.CFG_PROJECT_TRACE_ARCHIVE, False)
            if not isinstance(trace_archive, bool):
                raise ValueError(
                    f"projects[{key!r}]: {C.CFG_PROJECT_TRACE_ARCHIVE} must be "
                    f"a boolean, got {trace_archive!r}"
                )

            projects[str(key)] = ProjectOverride(
                redaction_mode=mode, ingest=ingest_val, trace_archive=trace_archive
            )

    rules: list[ProjectIdRule] = []
    idata = data.get(C.CFG_PROJECT_IDS)
    if isinstance(idata, list):
        for entry in idata:
            if not isinstance(entry, Mapping):
                raise ValueError("project_ids[] entries must be mappings")
            match = entry.get(C.CFG_PROJECT_ID_MATCH)
            pid = entry.get(C.CFG_PROJECT_ID_ID)
            if not isinstance(match, str) or not match:
                raise ValueError("project_ids[] entry is missing non-empty 'match'")
            if not isinstance(pid, str) or not pid:
                raise ValueError("project_ids[] entry is missing non-empty 'id'")
            rules.append(ProjectIdRule(match=match, id=pid))

    return projects, tuple(rules)


def _developer_id_cfg(data: Mapping[str, Any]) -> Optional[str]:
    """The `developer_id` config key; a wrong TYPE is a config error (raises,
    matching the package's other config blocks) — never coerced into a
    fabricated id (PR #188 review B-10)."""
    value = data.get(C.CFG_DEVELOPER_ID)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(
            f"config '{C.CFG_DEVELOPER_ID}' must be a string, got {type(value).__name__}"
        )
    return value


def _load_team(data: Mapping[str, Any], env) -> TeamConfig:
    """team.* from the data file, env on top. Every value refuses
    loudly when malformed, naming the key: a budget that silently
    became None would never alert."""
    block = data.get(C.CFG_TEAM) or {}

    def positive_int(name: str, raw: Any) -> int:
        try:
            value = int(str(raw))
        except (TypeError, ValueError):
            raise ValueError(f"{C.CFG_TEAM}.{name} must be an integer, got {raw!r}") from None
        if value <= 0:
            raise ValueError(f"{C.CFG_TEAM}.{name} must be positive, got {value}")
        return value

    def budget(name: str, env_key: str) -> Optional[float]:
        raw = env(env_key)
        if raw is None or raw == "":
            raw = (block.get(C.CFG_TEAM_BUDGETS) or {}).get(name)
        if raw is None or raw == "":
            return None
        try:
            value = float(str(raw))
        except ValueError:
            raise ValueError(f"{C.CFG_TEAM}.{C.CFG_TEAM_BUDGETS}.{name} must be a number of USD, got {raw!r}") from None
        if value != value or value < 0:  # nan or negative
            raise ValueError(f"{C.CFG_TEAM}.{C.CFG_TEAM_BUDGETS}.{name} must be a non-negative number, got {raw!r}")
        return value

    def runaway(name: str, env_key: str, kind):
        raw = env(env_key)
        if raw is None or raw == "":
            raw = (block.get(C.CFG_TEAM_RUNAWAY) or {}).get(name)
        try:
            value = kind(str(raw))
        except (TypeError, ValueError):
            raise ValueError(f"{C.CFG_TEAM}.{C.CFG_TEAM_RUNAWAY}.{name} must be a number, got {raw!r}") from None
        if value != value or value <= 0:
            raise ValueError(f"{C.CFG_TEAM}.{C.CFG_TEAM_RUNAWAY}.{name} must be positive, got {raw!r}")
        return value

    def aliases() -> dict[str, str]:
        """team.aliases from the data file, env entries on top. Refuses
        loudly: an alias nobody notices is dropped would leave the two
        ids the operator meant to join sitting side by side."""
        key = f"{C.CFG_TEAM}.{C.CFG_TEAM_ALIASES}"
        raw = block.get(C.CFG_TEAM_ALIASES, {})
        if not isinstance(raw, Mapping) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in raw.items()):
            raise ValueError(f"{key} must be a mapping of developer id to display name, got {raw!r}")
        merged = {k.strip(): v.strip() for k, v in raw.items()}
        if not all(merged) or not all(merged.values()):
            raise ValueError(f"{key} has an entry with an empty developer id or name")
        for entry in (env(ENV_TEAM_ALIASES) or "").split(","):
            if not entry.strip():
                continue
            dev, sep, name = entry.partition("=")
            if not sep or not dev.strip() or not name.strip():
                raise ValueError(
                    f"{key}: {ENV_TEAM_ALIASES} entry {entry.strip()!r} is not 'id=Name'")
            merged[dev.strip()] = name.strip()
        return merged

    share = runaway(C.CFG_RUNAWAY_MAX_ERROR_SHARE, ENV_RUNAWAY_MAX_ERROR_SHARE, float)
    if share > 1:
        raise ValueError(f"{C.CFG_TEAM}.{C.CFG_TEAM_RUNAWAY}.{C.CFG_RUNAWAY_MAX_ERROR_SHARE} is a share (0–1), got {share}")
    return TeamConfig(
        active_window_seconds=positive_int(
            C.CFG_TEAM_ACTIVE_WINDOW, env(ENV_TEAM_ACTIVE_WINDOW) or block.get(C.CFG_TEAM_ACTIVE_WINDOW)),
        budgets=BudgetsConfig(
            team_daily_usd=budget(C.CFG_BUDGET_TEAM_DAILY, ENV_BUDGET_TEAM_DAILY),
            team_monthly_usd=budget(C.CFG_BUDGET_TEAM_MONTHLY, ENV_BUDGET_TEAM_MONTHLY),
            developer_daily_usd=budget(C.CFG_BUDGET_DEVELOPER_DAILY, ENV_BUDGET_DEVELOPER_DAILY),
            project_daily_usd=budget(C.CFG_BUDGET_PROJECT_DAILY, ENV_BUDGET_PROJECT_DAILY),
        ),
        runaway=RunawayConfig(
            recent_minutes=runaway(C.CFG_RUNAWAY_RECENT_MINUTES, ENV_RUNAWAY_RECENT_MINUTES, int),
            max_turns_recent=runaway(C.CFG_RUNAWAY_MAX_TURNS_RECENT, ENV_RUNAWAY_MAX_TURNS_RECENT, int),
            recent_turns=runaway(C.CFG_RUNAWAY_RECENT_TURNS, ENV_RUNAWAY_RECENT_TURNS, int),
            max_error_share=share,
            min_turns_for_error_share=runaway(
                C.CFG_RUNAWAY_MIN_TURNS_FOR_ERROR_SHARE, ENV_RUNAWAY_MIN_TURNS_FOR_ERROR_SHARE, int),
            max_cost_recent_usd=runaway(C.CFG_RUNAWAY_MAX_COST_RECENT, ENV_RUNAWAY_MAX_COST_RECENT, float),
        ),
        aliases=aliases(),
    )


def _load_noise(data: Mapping[str, Any], env) -> NoiseConfig:
    """sessions.noise from the data file, env overrides on top. Same
    discipline as similarity: the data file is the ONLY source of
    defaults; a missing block or key refuses loudly, naming itself."""
    block = data.get(C.CFG_SESSIONS)
    ndata = block.get(C.CFG_SESSIONS_NOISE) if isinstance(block, Mapping) else None
    if not isinstance(ndata, Mapping):
        raise ValueError(
            "config has no 'sessions.noise' block — defaults.json is the "
            "single source of noise defaults"
        )
    missing = [
        k for k in (C.CFG_NOISE_MIN_TURNS, C.CFG_NOISE_MIN_DURATION, C.CFG_NOISE_PATH_PATTERNS)
        if k not in ndata
    ]
    if missing:
        raise ValueError(f"sessions.noise config is missing {', '.join(missing)}")

    def _count(key: str, env_key: str) -> int:
        raw = env(env_key)
        value = raw if raw is not None else ndata[key]
        if isinstance(value, bool):
            raise ValueError(f"sessions.noise.{key} must be an integer, got boolean {value!r}")
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"sessions.noise.{key} {value!r} is not an integer") from None
        if n < 0:
            raise ValueError(f"sessions.noise.{key} must be >= 0, got {n}")
        return n

    raw_patterns = env(ENV_NOISE_PATH_PATTERNS)
    if raw_patterns is not None:
        patterns: Any = [p.strip() for p in raw_patterns.split(",")]
    else:
        patterns = ndata[C.CFG_NOISE_PATH_PATTERNS]
    if not isinstance(patterns, (list, tuple)) or not all(isinstance(p, str) for p in patterns):
        raise ValueError("sessions.noise.path_patterns must be a list of strings")
    return NoiseConfig(
        min_turns=_count(C.CFG_NOISE_MIN_TURNS, ENV_NOISE_MIN_TURNS),
        min_duration_seconds=_count(C.CFG_NOISE_MIN_DURATION, ENV_NOISE_MIN_DURATION),
        path_patterns=tuple(p for p in patterns if p),
    )


def load_config(
    *,
    dsn: Optional[str] = None,
    kuzu_path: Optional[str] = None,
    redaction_mode: Optional[str] = None,
    extra_overrides: Optional[Mapping[str, Any]] = None,
) -> AnalyticsConfig:
    """Resolve configuration with the documented precedence."""
    data = _read_defaults()
    if _USER_CONFIG.is_file():
        data = _deep_merge(data, _load_json_text(_USER_CONFIG.read_text(encoding="utf-8")))
    if extra_overrides:
        data = _deep_merge(data, extra_overrides)

    env_file = parse_env_file()

    def env(key: str) -> Optional[str]:
        # real environment wins over the .env file (conventional dotenv).
        v = os.environ.get(key)
        if v is not None and v != "":
            return v
        v = env_file.get(key)
        return v if v else None

    def env_db() -> Optional[str]:
        # The new and the old database key are ALIASES within each layer:
        # a process CCT_SA_DSN still beats a .env CCT_SA_DB, exactly as
        # a process CCT_SA_DB would. Resolving the new name across both
        # layers first would let a Settings save redirect a running
        # legacy-configured command to another store.
        for layer in (os.environ, env_file):
            for key in (ENV_DB, ENV_DSN_LEGACY):
                v = layer.get(key)
                if v:
                    return v
        return None

    # routing-shadow evidence roots: config-file list, env override
    # (os.pathsep-separated), CLI extra_overrides via the merged data
    roots_raw = data.get(C.CFG_ROUTING_EVIDENCE_ROOTS) or []
    roots_env = env(ENV_ROUTING_EVIDENCE_ROOTS)
    if roots_env:
        roots_raw = [r for r in roots_env.split(os.pathsep) if r]
    routing_evidence_roots = tuple(str(r) for r in roots_raw)

    # routing-calibration (#266): the nested block from the layered
    # data, with per-key env overrides CCT_SA_CALIBRATION_<KEY>.
    calibration = dict(data.get(C.CFG_ROUTING_CALIBRATION) or {})
    for key in list(calibration.keys()):
        ov = env(ENV_CALIBRATION_PREFIX + key.upper())
        if ov is not None:
            try:
                calibration[key] = _coerce_like(calibration[key], ov)
            except ValueError:
                raise ValueError(
                    f"{ENV_CALIBRATION_PREFIX}{key.upper()}={ov!r} cannot "
                    f"be coerced to the type of the configured "
                    f"'{key}' value — refusing a silently mistyped "
                    f"calibration override"
                ) from None

    # sources (+ optional per-copilot env override CCT_SA_SOURCE_<COPILOT>)
    sources = dict(data.get(C.CFG_SOURCES) or {})
    for copilot in list(sources.keys()):
        ov = env(ENV_SOURCE_PREFIX + copilot.replace("-", "_").upper())
        if ov:
            sources[copilot] = ov

    resolved_dsn = dsn or env_db() or data.get(C.CFG_DSN) or ""
    resolved_kuzu = Path(
        kuzu_path or env(ENV_KUZU_PATH) or data.get(C.CFG_KUZU_PATH)
        or str(Path.home() / ".cct" / C.KUZU_STORE_NAME)
    ).expanduser()
    # Kùzu refuses a directory ("Database path cannot be a directory"),
    # and a user who sets CCT_SA_KUZU_PATH=~/.cct means "keep the graph
    # there". Resolve a directory to the store file inside it instead of
    # letting the graph step crash.
    if resolved_kuzu.is_dir():
        resolved_kuzu = resolved_kuzu / C.KUZU_STORE_NAME
    raw_runs_root = env(ENV_BENCHMARK_RUNS_ROOT) or data.get(C.CFG_BENCHMARK_RUNS_ROOT) or ""
    runs_root = str(Path(raw_runs_root).expanduser()) if raw_runs_root else ""
    resolved_redaction = (
        redaction_mode or env(ENV_REDACTION) or data.get(C.CFG_REDACTION) or C.REDACT_CODE
    )
    if resolved_redaction not in C.REDACTION_MODES:
        raise ValueError(
            f"invalid redaction mode {resolved_redaction!r}; expected one of {C.REDACTION_MODES}"
        )

    jdata = dict(data.get(C.CFG_JUDGE) or {})
    default_spec = _spec_tuple(jdata.get(C.CFG_JUDGE_DEFAULT), ("ollama", ""))
    by_copilot = {
        str(k): _spec_tuple(v, default_spec)
        for k, v in (jdata.get(C.CFG_JUDGE_BY_COPILOT) or {}).items()
    }
    # An explicit judge backend in .env/env is a GLOBAL override. A model
    # alone (backend left at the packaged default in Settings) is one
    # too — for the default backend — or a chosen model would be
    # silently ignored.
    env_backend = env(ENV_JUDGE_BACKEND)
    env_model = env(ENV_JUDGE_MODEL) or ""
    if env_backend:
        override = (env_backend, env_model)
    elif env_model:
        override = (default_spec[0], env_model)
    else:
        override = None

    judge = JudgeConfig(
        override=override,
        by_copilot=by_copilot,
        default=default_spec,
        workers=int(env(ENV_JUDGE_WORKERS) or jdata.get(C.CFG_JUDGE_WORKERS) or 2),
        ollama_url=str(env(ENV_OLLAMA_URL) or jdata.get(C.CFG_OLLAMA_URL) or "http://localhost:11434"),
        base_url=str(env(ENV_JUDGE_BASE_URL) or jdata.get(C.CFG_JUDGE_BASE_URL) or ""),
        api_key=str(env(ENV_JUDGE_API_KEY) or ""),
    )

    # embedding (#285, FR-8): defaults.json is the ONLY source of the
    # embedding defaults. A structurally missing block or key is
    # REFUSED — reconstructing packaged defaults here would create a
    # second normative source beside the data file, which is the exact
    # config-discipline failure the house rules exist to prevent.
    #
    # Per-field precedence, highest first:
    #   CLI (the embedding block of extra_overrides, kept separately so
    #        the caller's direct value genuinely wins)
    #   > real env  > repo .env          (both via env())
    #   > merged config (defaults.json < ~/.cct/session-analytics.json)
    #
    # Values are read by key PRESENCE, never truthiness: model == ""
    # is a legitimate configured value (backend default model), not an
    # absence. The URL shares ENV_OLLAMA_URL with the judge: one local
    # Ollama is the operating assumption.
    edata = data.get(C.CFG_EMBEDDING)
    if not isinstance(edata, Mapping):
        raise ValueError(
            "config has no 'embedding' block — defaults.json is the single "
            "source of embedding defaults, and the loader refuses to "
            "reconstruct them in code"
        )
    _embed_required = (
        C.CFG_EMBEDDING_BACKEND, C.CFG_EMBEDDING_MODEL, C.CFG_OLLAMA_URL,
        C.CFG_EMBEDDING_INPUT_CAP, C.CFG_EMBEDDING_WORKERS,
    )
    _embed_missing = [k for k in _embed_required if k not in edata]
    if _embed_missing:
        raise ValueError(
            f"embedding config is missing {', '.join(_embed_missing)} — "
            f"defaults.json is the single source of embedding defaults"
        )
    _embed_cli = (extra_overrides or {}).get(C.CFG_EMBEDDING)
    _embed_cli = dict(_embed_cli) if isinstance(_embed_cli, Mapping) else {}

    def _embed_value(key: str, env_key: str) -> Any:
        if key in _embed_cli:            # CLI — the caller's direct value
            return _embed_cli[key]
        ov = env(env_key)                # real env > repo .env
        if ov is not None:
            return ov
        return edata[key]                # merged defaults < user JSON

    embedding = EmbeddingConfig(
        backend=str(_embed_value(C.CFG_EMBEDDING_BACKEND, ENV_EMBED_BACKEND)),
        model=str(_embed_value(C.CFG_EMBEDDING_MODEL, ENV_EMBED_MODEL)),
        ollama_url=str(_embed_value(C.CFG_OLLAMA_URL, ENV_OLLAMA_URL)),
        input_cap_chars=int(_embed_value(C.CFG_EMBEDDING_INPUT_CAP, ENV_EMBED_INPUT_CAP)),
        workers=int(_embed_value(C.CFG_EMBEDDING_WORKERS, ENV_EMBED_WORKERS)),
    )

    # similarity (#287): the same discipline as embedding — the data
    # file is the ONLY source of defaults, presence beats truthiness,
    # CLI (the similarity block of extra_overrides) is highest.
    sdata = data.get(C.CFG_SIMILARITY)
    if not isinstance(sdata, Mapping):
        raise ValueError(
            "config has no 'similarity' block — defaults.json is the "
            "single source of similarity defaults, and the loader refuses "
            "to reconstruct them in code"
        )
    _sim_required = (C.CFG_SIMILARITY_THRESHOLD, C.CFG_SIMILARITY_TOP_K)
    _sim_missing = [k for k in _sim_required if k not in sdata]
    if _sim_missing:
        raise ValueError(
            f"similarity config is missing {', '.join(_sim_missing)} — "
            f"defaults.json is the single source of similarity defaults"
        )
    _sim_cli = (extra_overrides or {}).get(C.CFG_SIMILARITY)
    _sim_cli = dict(_sim_cli) if isinstance(_sim_cli, Mapping) else {}

    def _sim_value(key: str, env_key: str) -> Any:
        if key in _sim_cli:
            return _sim_cli[key]
        ov = env(env_key)
        if ov is not None:
            return ov
        return sdata[key]

    # Validated BEFORE coercion (#287 T1 review): float()/int() accept
    # exactly the malformed values these knobs must refuse — "nan" and
    # "inf" coerce cleanly, int(1.9) truncates, int(True) is 1 — and
    # T2 will let these settings drive edge reconciliation, so a bad
    # value must refuse loudly here, naming the setting.
    similarity = SimilarityConfig(
        threshold=_sim_threshold(_sim_value(
            C.CFG_SIMILARITY_THRESHOLD, ENV_SIMILARITY_THRESHOLD)),
        top_k=_sim_top_k(_sim_value(
            C.CFG_SIMILARITY_TOP_K, ENV_SIMILARITY_TOP_K)),
    )

    noise = _load_noise(data, env)
    team = _load_team(data, env)

    pricing = _load_pricing(data)
    projects, project_id_rules = _load_projects(data)

    return AnalyticsConfig(
        sources=sources,
        routing_evidence_roots=routing_evidence_roots,
        routing_calibration=calibration,
        dsn=str(resolved_dsn),
        kuzu_path=str(resolved_kuzu),
        benchmark_runs_root=runs_root,
        redaction_mode=resolved_redaction,
        judge=judge,
        embedding=embedding,
        similarity=similarity,
        team=team,
        noise=noise,
        pricing=pricing,
        projects=projects,
        project_id_rules=project_id_rules,
        raw=data,
        developer_id_env=env(ENV_DEVELOPER_ID),
        developer_id_cfg=_developer_id_cfg(data),
    )


def load_map(filename: str) -> dict[str, Any]:
    """Load one of the sibling config map files (tool-name-map.json, …)."""
    text = resources.files(_CONFIG_PACKAGE).joinpath(filename).read_text(encoding="utf-8")
    return _load_json_text(text)
