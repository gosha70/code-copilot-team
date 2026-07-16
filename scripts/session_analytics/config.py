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
ENV_DSN = "CCT_SA_DSN"
ENV_KUZU_PATH = "CCT_SA_KUZU_PATH"
ENV_REDACTION = "CCT_SA_REDACTION"
ENV_OLLAMA_URL = "CCT_SA_OLLAMA_URL"
ENV_JUDGE_BACKEND = "CCT_SA_JUDGE_BACKEND"
ENV_JUDGE_MODEL = "CCT_SA_JUDGE_MODEL"
ENV_JUDGE_BASE_URL = "CCT_SA_JUDGE_BASE_URL"
ENV_JUDGE_API_KEY = "CCT_SA_JUDGE_API_KEY"
ENV_JUDGE_WORKERS = "CCT_SA_JUDGE_WORKERS"
ENV_SOURCE_PREFIX = "CCT_SA_SOURCE_"  # + COPILOT (e.g. CCT_SA_SOURCE_CLAUDE_CODE)

# Keys the Studio config page exposes (order = display order). Secret-bearing
# keys are flagged so the API masks them.
ENV_KEYS = (
    ENV_DSN, ENV_KUZU_PATH, ENV_REDACTION,
    ENV_JUDGE_BACKEND, ENV_JUDGE_MODEL, ENV_JUDGE_BASE_URL, ENV_JUDGE_API_KEY,
    ENV_JUDGE_WORKERS, ENV_OLLAMA_URL,
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
class ProjectOverride:
    """One ``projects.<key>`` entry: a per-project redaction/ingest override."""

    redaction_mode: Optional[str] = None
    ingest: str = C.INGEST_ON


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
    redaction_mode: str
    judge: JudgeConfig
    pricing: "PricingConfig"
    projects: Mapping[str, ProjectOverride] = field(default_factory=dict)
    project_id_rules: tuple[ProjectIdRule, ...] = field(default_factory=tuple)
    raw: Mapping[str, Any] = field(default_factory=dict)

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

            projects[str(key)] = ProjectOverride(redaction_mode=mode, ingest=ingest_val)

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

    # sources (+ optional per-copilot env override CCT_SA_SOURCE_<COPILOT>)
    sources = dict(data.get(C.CFG_SOURCES) or {})
    for copilot in list(sources.keys()):
        ov = env(ENV_SOURCE_PREFIX + copilot.replace("-", "_").upper())
        if ov:
            sources[copilot] = ov

    resolved_dsn = dsn or env(ENV_DSN) or data.get(C.CFG_DSN) or ""
    resolved_kuzu = (
        kuzu_path or env(ENV_KUZU_PATH) or data.get(C.CFG_KUZU_PATH)
        or str(Path.home() / ".cct" / "session-analytics-graph")
    )
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
    # An explicit judge backend in .env/env is a GLOBAL override.
    env_backend = env(ENV_JUDGE_BACKEND)
    override = (env_backend, env(ENV_JUDGE_MODEL) or "") if env_backend else None

    judge = JudgeConfig(
        override=override,
        by_copilot=by_copilot,
        default=default_spec,
        workers=int(env(ENV_JUDGE_WORKERS) or jdata.get(C.CFG_JUDGE_WORKERS) or 2),
        ollama_url=str(env(ENV_OLLAMA_URL) or jdata.get(C.CFG_OLLAMA_URL) or "http://localhost:11434"),
        base_url=str(env(ENV_JUDGE_BASE_URL) or jdata.get(C.CFG_JUDGE_BASE_URL) or ""),
        api_key=str(env(ENV_JUDGE_API_KEY) or ""),
    )

    pricing = _load_pricing(data)
    projects, project_id_rules = _load_projects(data)

    return AnalyticsConfig(
        sources=sources,
        dsn=str(resolved_dsn),
        kuzu_path=str(Path(resolved_kuzu).expanduser()),
        redaction_mode=resolved_redaction,
        judge=judge,
        pricing=pricing,
        projects=projects,
        project_id_rules=project_id_rules,
        raw=data,
    )


def load_map(filename: str) -> dict[str, Any]:
    """Load one of the sibling config map files (tool-name-map.json, …)."""
    text = resources.files(_CONFIG_PACKAGE).joinpath(filename).read_text(encoding="utf-8")
    return _load_json_text(text)
