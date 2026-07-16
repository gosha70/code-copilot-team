# session_analytics.constants — cross-module named constants.
#
# Per the coding-standards rule: any string key that crosses a module
# boundary (copilot id, enum value, config key) is defined ONCE here and
# imported everywhere, so a rename is a single edit and a typo is an
# ImportError rather than a silent runtime mismatch.

from __future__ import annotations

# ── Copilot identifiers ────────────────────────────────────────────────
# Claude Code is the primary analyzer target; Aider is the secondary
# multi-copilot example. Kiro is intentionally NOT here — Kiro ingestion is
# owned by the upstream kiro-analyzer this tool mirrors architecturally.
COPILOT_CLAUDE_CODE = "claude-code"
COPILOT_AIDER = "aider"

# ── Turn roles ─────────────────────────────────────────────────────────
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"

# ── File access types ──────────────────────────────────────────────────
ACCESS_READ = "read"
ACCESS_WRITE = "write"
ACCESS_CREATE = "create"
ACCESS_DELETE = "delete"

# ── Tool-result status ─────────────────────────────────────────────────
STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"

# ── Redaction modes ────────────────────────────────────────────────────
# ``none``          — store content verbatim.
# ``code``          — keep text previews, strip fenced code blocks + tool
#                     inputs to length + sha256 (default).
# ``metadata-only`` — store zero content; only counts/names/timestamps.
REDACT_NONE = "none"
REDACT_CODE = "code"
REDACT_METADATA_ONLY = "metadata-only"
REDACTION_MODES = (REDACT_NONE, REDACT_CODE, REDACT_METADATA_ONLY)

# ── Default multi-tenant developer id (E1) ─────────────────────────────
DEFAULT_DEVELOPER_ID = "local"

# ── Config keys (defaults.yaml) ────────────────────────────────────────
CFG_SOURCES = "sources"
CFG_SOURCE_ROOT = "root"
CFG_DSN = "dsn"
CFG_KUZU_PATH = "kuzu_path"
CFG_REDACTION = "redaction_mode"
CFG_JUDGE = "judge"
CFG_JUDGE_DEFAULT = "default"
CFG_JUDGE_BY_COPILOT = "by_copilot"
CFG_JUDGE_BACKEND = "backend"
CFG_JUDGE_MODEL = "model"
CFG_JUDGE_WORKERS = "workers"
CFG_JUDGE_BASE_URL = "base_url"
CFG_JUDGE_API_KEY = "api_key"
CFG_OLLAMA_URL = "ollama_url"

# ── Pricing config keys (E5 cost tracking) ─────────────────────────────
# Rates are per-1,000,000 tokens. Each model entry declares its own
# ``currency`` + ``effective_date`` (the "version" stamped onto priced
# turns via ``copilot_turn.cost_price_version``).
CFG_PRICING = "pricing"
CFG_PRICING_MODELS = "models"
CFG_PRICE_CURRENCY = "currency"
CFG_PRICE_EFFECTIVE_DATE = "effective_date"
CFG_PRICE_INPUT = "input"
CFG_PRICE_OUTPUT = "output"
CFG_PRICE_CACHE_READ = "cache_read"
CFG_PRICE_CACHE_WRITE = "cache_write"

# ── Stable CLI exit codes (mirror benchmark_runner) ────────────────────
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_RUNTIME = 3
EXIT_NOT_IMPLEMENTED = 8

# ── Content-preview length (chars) for content_preview columns ─────────
CONTENT_PREVIEW_CHARS = 500
INPUT_PREVIEW_CHARS = 500
