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

# ── Per-project privacy config keys (session-analytics-privacy-granularity) ──
CFG_PROJECTS = "projects"
CFG_PROJECT_INGEST = "ingest"
CFG_PROJECT_IDS = "project_ids"
CFG_PROJECT_ID_MATCH = "match"
CFG_PROJECT_ID_ID = "id"
INGEST_ON = "on"
INGEST_OFF = "off"
INGEST_MODES = (INGEST_ON, INGEST_OFF)

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

# ── Export command (E7 CSV/Parquet export, issue #87) ──────────────────
EXPORT_FORMAT_CSV = "csv"
EXPORT_FORMAT_PARQUET = "parquet"
EXPORT_FORMATS = (EXPORT_FORMAT_CSV, EXPORT_FORMAT_PARQUET)

EXPORT_TABLE_SESSIONS = "sessions"
EXPORT_TABLE_TURNS = "turns"
EXPORT_TABLE_LABELS = "labels"
EXPORT_TABLE_KPIS = "kpis"
EXPORT_TABLE_BENCHMARK_RESULTS = "benchmark_results"  # E9 outcomes (#92)
EXPORT_TABLE_TRACE_DOCUMENTS = "trace_documents"      # E10 Slice A (#98)
EXPORT_TABLE_ALL = "all"
# The actual queryable tables (i.e. everything except the "all" pseudo-table).
EXPORT_DATA_TABLES = (
    EXPORT_TABLE_SESSIONS, EXPORT_TABLE_TURNS, EXPORT_TABLE_LABELS, EXPORT_TABLE_KPIS,
    EXPORT_TABLE_BENCHMARK_RESULTS, EXPORT_TABLE_TRACE_DOCUMENTS,
)
EXPORT_TABLES = EXPORT_DATA_TABLES + (EXPORT_TABLE_ALL,)

# ── Benchmark ↔ session correlation (E9, issue #91) ────────────────────
# The ``copilot_session`` column stamped by ``correlate.py`` with a linked
# benchmark run's attempt directory (NULL for organic sessions). Crosses the
# store/export/dashboard/correlate module boundary, so it lives here once.
COL_BENCHMARK_RUN_DIR = "benchmark_run_dir"

# The benchmark harness's per-attempt artifact filename (``run.py``) and the
# JSON key-path, inside that file, to the Claude Code session id
# (``run_record["backend"]["metadata"]["session_id"]`` — may be null/absent
# for bare mode, timeouts, or non-claude backends).
RUN_RECORD_FILENAME = "run-record.json"
RUN_RECORD_SESSION_ID_PATH = ("backend", "metadata", "session_id")
# Required top-level backend id in every run-record (schema: backend_id). The
# claude-code backend writes the same string as COPILOT_CLAUDE_CODE, so the
# CLI scopes the link to records whose backend_id matches that constant.
RUN_RECORD_BACKEND_ID_KEY = "backend_id"

# ── Benchmark outcomes (E9 outcome slice, issue #92) ───────────────────
# score.json sits next to run-record.json in each attempt dir (writer:
# scripts/benchmark_runner/run.py; schema: benchmarks/schema/score.schema.json).
SCORE_FILENAME = "score.json"
# The classifier's closed result vocabulary — a value outside this set is a
# MALFORMED score (strict-reject, D-parse-strictness), not a new category.
SCORE_RESULTS = ("pass", "fail", "error", "timeout")
TBL_BENCHMARK_RESULT = "benchmark_result"
# score.json field keys. These cross the benchmark_runner → session_analytics
# boundary (run.py writes them; correlate.py reads them), so per the repo's
# constants rule they live here once — same treatment as RUN_RECORD_* above.
SCORE_KEY_BENCHMARK_ID = "benchmark_id"
SCORE_KEY_TASK_ID = "task_id"
SCORE_KEY_RUN_ID = "run_id"
SCORE_KEY_ATTEMPT = "attempt"
SCORE_KEY_RESULT = "result"
SCORE_KEY_SCORES = "scores"
SCORE_KEY_DERIVED = "derived"
SCORE_KEY_TESTS_PASSED = "tests_passed"
SCORE_KEY_LINT_PASSED = "lint_passed"
SCORE_KEY_TYPECHECK_PASSED = "typecheck_passed"
SCORE_KEY_ELAPSED_SECONDS = "elapsed_seconds"
SCORE_KEY_FILES_CHANGED = "files_changed"
SCORE_KEY_LINES_ADDED = "lines_added"
SCORE_KEY_LINES_REMOVED = "lines_removed"

# ── Trace archive (E10 Slice A, issue #98) ─────────────────────────────
# Durable, redaction-safe full-text trace retention. Explicit per-project
# opt-in only: `projects.<key>.trace_archive: true` (OFF by default).
TBL_TRACE_DOCUMENT = "trace_document"
TBL_TRACE_ARCHIVE_STATE = "trace_archive_state"
CFG_PROJECT_TRACE_ARCHIVE = "trace_archive"
SOURCE_KIND_COPILOT_TRANSCRIPT = "copilot_transcript"
# FR-4 redaction floor: index = strictness rank (higher wins). The archive
# stores under the STRICTER of the config-resolved mode and the mode the
# session's ingest recorded — never looser.
REDACTION_STRICTNESS = (REDACT_NONE, REDACT_CODE, REDACT_METADATA_ONLY)
# Substring search (documented as NON-ranked): result limits + snippet window.
SEARCH_DEFAULT_LIMIT = 50
SEARCH_MAX_LIMIT = 500
SEARCH_SNIPPET_CHARS = 120

# mtime comparison tolerance shared by BOTH incremental walks (ingest_state
# and trace_archive_state) — the two gates must agree or they drift apart.
MTIME_EPSILON = 1e-6

# ── Connection-probe diagnostics (#100) ────────────────────────────────
# /api/settings/test-connection must never echo driver exception text: a
# real Postgres failure carries hostname, IP, port, database and username,
# and the endpoint accepts a CALLER-SUPPLIED DSN. Every failure therefore
# maps to one of this closed set, and the response carries ONLY these
# curated messages. Full detail goes to the server log instead.
PROBE_ERR_DRIVER_MISSING = "driver_missing"
PROBE_ERR_BAD_DSN = "bad_dsn"
PROBE_ERR_AUTH_FAILED = "auth_failed"
PROBE_ERR_UNREACHABLE = "unreachable"
PROBE_ERR_DATABASE_MISSING = "database_missing"
PROBE_ERR_PERMISSION_DENIED = "permission_denied"
PROBE_ERR_UNKNOWN = "unknown"

PROBE_ERROR_MESSAGES = {
    PROBE_ERR_DRIVER_MISSING:
        "PostgreSQL driver not installed — run: pip install psycopg",
    PROBE_ERR_BAD_DSN:
        "DSN is empty or not a supported format "
        "(sqlite:///… or postgresql://…).",
    PROBE_ERR_AUTH_FAILED:
        "Authentication failed — check the username and password in the DSN.",
    PROBE_ERR_UNREACHABLE:
        "Could not reach the database host — check the host and port in the "
        "DSN, and that the server is running.",
    PROBE_ERR_DATABASE_MISSING:
        "The database does not exist (or the SQLite path is not writable).",
    PROBE_ERR_PERMISSION_DENIED:
        "Connected, but the account lacks permission to create or read the "
        "schema.",
    PROBE_ERR_UNKNOWN:
        "Connection failed. See the server log for details.",
}

# Signals matched (lowercased, on WORD BOUNDARIES — see db_test._word_re)
# against the driver's message for CLASSIFICATION ONLY; the matched text is
# never returned. A signature is either a phrase, or a TUPLE of phrases that
# must ALL be present. The tuple form matters because Postgres interpolates
# identifiers: `role "alice" does not exist` and `database "prod" does not
# exist` differ only by the noun, so a bare "does not exist" would
# misclassify auth failures. Boundary matching matters for the same reason
# in the other direction: bare `role` occurs inside `role_store`.
# First match wins, so order is significant.
PROBE_ERROR_SIGNATURES = (
    (PROBE_ERR_AUTH_FAILED, (
        "password authentication failed", "authentication failed",
        "no password supplied", ("role", "does not exist"),
    )),
    (PROBE_ERR_UNREACHABLE, (
        "could not connect", "connection refused", "could not translate host",
        "name or service not known", "timeout expired", "connection timed out",
        "network is unreachable", "server closed the connection",
    )),
    (PROBE_ERR_DATABASE_MISSING, (
        ("database", "does not exist"), "unable to open database file",
        "no such file or directory",
    )),
    (PROBE_ERR_PERMISSION_DENIED, (
        "permission denied", "must be owner", "readonly database",
        "attempt to write a readonly database", "access denied",
    )),
)
