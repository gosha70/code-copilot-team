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
COPILOT_PI = "pi"

# Pi (T11.1) sources CCT's OWN emitted analytics under a project's .cct/, NOT
# Pi's native session transcript (format unverified). Defined once here.
PI_ANALYTICS_REL = ".cct/worker-analytics.jsonl"  # T7.4 interim neutral source
PI_SESSION_REL = ".cct/pi-session.json"  # T9.1 checkpoint (feature/phase)

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

# Config key for an explicit developer id (Slice B1, #187).
CFG_DEVELOPER_ID = "developer_id"

# The CCT workflow phases — mirrors the Pi runtime's PHASE_ORDER (a
# cross-adapter shared-semantics contract item).
CCT_PHASES = ("research", "plan", "build", "review")
#: The review phase by name — referenced by phase-process metrics, which
#: must not spell it as a literal on the other side of a module boundary.
PHASE_REVIEW = "review"

#: Cap on entries returned by the settings path picker's browse
#: endpoint — a directory with 100k files must not hang the UI.
FS_BROWSE_MAX_ENTRIES = 500

#: The Pi runtime's persisted workflow state (#301). Distinct from
#: PI_SESSION_REL: that file holds only the CURRENT phase/feature, while
#: this one carries `history[]` — the timestamped, feature-bound record
#: of phases left behind, capped by the runtime at the last 50 entries.
PI_WORKFLOW_REL = ".cct/pi-workflow.json"
#: Retention cap the Pi runtime applies to `history[]` (`.slice(-50)`).
#: Surfaced in payloads so "not observed" is never read as "never
#: happened" — an eviction and an absence are different claims.
PI_WORKFLOW_HISTORY_CAP = 50

#: Adapter-neutral per-session metadata (FU-1), one row per (session, key).
TBL_SESSION_METADATA = "copilot_session_metadata"

#: `copilot_session_metadata.key` under which the Pi adapter records the
#: feature a session belongs to. Named here because it crosses a module
#: boundary — the adapter writes it, phase-process metrics read it — and a
#: literal on both sides is a silent breakage waiting to happen.
METADATA_KEY_FEATURE_ID = "feature_id"

# ── Config keys (defaults.yaml) ────────────────────────────────────────
CFG_SOURCES = "sources"
CFG_ROUTING_EVIDENCE_ROOTS = "routing_evidence_roots"
#: routing-calibration (#266): ONE nested config block; every key
#: inside is operator policy — no default value lives in Python source.
CFG_ROUTING_CALIBRATION = "routing_calibration"
CFG_SOURCE_ROOT = "root"
CFG_DSN = "dsn"
CFG_KUZU_PATH = "kuzu_path"
#: Where the benchmark harness wrote its runs (Settings → Benchmarks).
CFG_BENCHMARK_RUNS_ROOT = "benchmark_runs_root"
#: The Kùzu store FILE name: the packaged default under ~/.cct, and the
#: file created inside a directory when kuzu_path points at one.
KUZU_STORE_NAME = "session-analytics-graph"
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

# ── Embedding config keys (#285, E2 slice 1) ─────────────────────────
CFG_EMBEDDING = "embedding"
CFG_EMBEDDING_BACKEND = "backend"
CFG_EMBEDDING_MODEL = "model"
CFG_EMBEDDING_INPUT_CAP = "input_cap_chars"
CFG_EMBEDDING_WORKERS = "workers"

# ── Session noise config keys (#307, Studio Phase 2) ─────────────────
# Query-time exclusion of probe/temp-dir/too-short sessions from lists
# and aggregates. Keys cross config-data → config.py → session_filter.
CFG_SESSIONS = "sessions"
CFG_SESSIONS_NOISE = "noise"
CFG_NOISE_MIN_TURNS = "min_turns"
CFG_NOISE_MIN_DURATION = "min_duration_seconds"
CFG_NOISE_PATH_PATTERNS = "path_patterns"

# ── Similarity config keys (#287, E2 slice 2) ────────────────────────
CFG_SIMILARITY = "similarity"
#: team.* — the Team tab (#174): how recent a heartbeat counts as active.
CFG_TEAM = "team"
CFG_TEAM_ACTIVE_WINDOW = "active_window_seconds"
#: team.budgets — null = no budget for that scope (Slice D of #174).
CFG_TEAM_BUDGETS = "budgets"
CFG_BUDGET_TEAM_DAILY = "team_daily_usd"
CFG_BUDGET_TEAM_MONTHLY = "team_monthly_usd"
CFG_BUDGET_DEVELOPER_DAILY = "developer_daily_usd"
CFG_BUDGET_PROJECT_DAILY = "project_daily_usd"
#: team.aliases — developer id → display name; ids sharing a name are one
#: person, folded into one row at READ time (the store keeps every id).
CFG_TEAM_ALIASES = "aliases"
#: team.runaway — what makes a still-running session a runaway.
CFG_TEAM_RUNAWAY = "runaway"
CFG_RUNAWAY_RECENT_MINUTES = "recent_minutes"
CFG_RUNAWAY_MAX_TURNS_RECENT = "max_turns_recent"
CFG_RUNAWAY_RECENT_TURNS = "recent_turns"
CFG_RUNAWAY_MAX_ERROR_SHARE = "max_error_share"
CFG_RUNAWAY_MIN_TURNS_FOR_ERROR_SHARE = "min_turns_for_error_share"
CFG_RUNAWAY_MAX_COST_RECENT = "max_cost_recent_usd"
#: Alert levels: a warning is worth a look, a breach is the bound crossed.
ALERT_WARNING = "warning"
ALERT_BREACH = "breach"
ALERT_LEVELS = (ALERT_WARNING, ALERT_BREACH)
#: A budget alert starts warning at this share of the budget, and at this
#: share of an auto-build run's cost or wall-clock cap.
BUDGET_WARNING_SHARE = 0.8
#: The auto-build block of the alerts report (auto-build-cap-alerts): was
#: the ledger root read at all, and how many runs were still running.
ALERT_AUTO_BUILD = "auto_build"
ALERT_AUTO_BUILD_EVALUATED = "evaluated"
ALERT_AUTO_BUILD_LIVE_RUNS = "live_runs"

# ── Auto-build runs (#190 §12, auto-build-run-surface) ──────────────────
#: auto_build.* — where the auto-build driver's ledgers are read from and
#: how recent a state.json write still counts as a live run.
CFG_AUTO_BUILD = "auto_build"
CFG_AUTO_BUILD_LEDGER_ROOT = "ledger_root"
CFG_AUTO_BUILD_ACTIVE_WINDOW = "active_window_seconds"
#: The two directories read beneath the ledger root: the driver writes
#: the first (CCT_AUTOBUILD_DIR's default); a person moves finished
#: ledgers into the second by hand.
AUTO_BUILD_LIVE_DIR = "auto-build"
AUTO_BUILD_ARCHIVE_DIR = "auto-build-archive"
AUTO_BUILD_SUBDIRS = (AUTO_BUILD_LIVE_DIR, AUTO_BUILD_ARCHIVE_DIR)
#: Ledger files the reader knows (scripts/auto-build-loop.sh writes them).
LEDGER_STATE_FILE = "state.json"
LEDGER_EVENTS_FILE = "events.jsonl"
LEDGER_TERMINATION_FILE = "termination.json"
LEDGER_TRIAGE_FILE = "triage-report.md"
LEDGER_ESCALATIONS_DIR = "escalations"
LEDGER_VERIFICATION_FILE = "verification-results.json"
LEDGER_PHASE_DIR_PREFIX = "phase-"
LEDGER_REVIEW_SUMMARY = "review/loop-summary.json"
#: Ledger states after which the driver writes nothing more.
LEDGER_TERMINAL_STATUSES = frozenset({"done", "terminated_policy", "parked", "aborted"})
#: Journal events that are policy decisions — what the driver DECIDED,
#: as opposed to progress (status, phase_commit, pushed …).
POLICY_EVENTS = frozenset({
    "terminated_policy", "parked", "review_state_reset", "review_bypass_accepted",
    "artifact_skipped", "artifact_error", "merge_skipped", "merge_armed",
    "merge_already_armed", "cap_updated", "capability_downgrade", "visual_waiver",
    "coverage_gate", "verifier_gate", "advisory_skipped", "cost_debit_failed",
    "max_turns_continuation", "wip_push_failed", "notify_failed",
})
#: The human verdict on the PR a run produced (#190 §12). Absence = no
#: verdict yet; nothing derives one.
VERDICT_MERGED_UNMODIFIED = "merged_unmodified"
VERDICT_MERGED_WITH_FIXES = "merged_with_fixes"
VERDICT_REJECTED = "rejected"
VERDICTS = (VERDICT_MERGED_UNMODIFIED, VERDICT_MERGED_WITH_FIXES, VERDICT_REJECTED)
VERDICT_NOTE_MAX_CHARS = 2000
TBL_AUTO_BUILD_VERDICT = "auto_build_verdict"
CFG_SIMILARITY_THRESHOLD = "threshold"
CFG_SIMILARITY_TOP_K = "top_k"

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
#: Per-turn judge labels (E10 label correlation reads them alongside
#: archived traces, so the table name crosses a module boundary).
TBL_HEURISTIC_LABEL = "heuristic_label"

# Session-level LLM analysis (#65 Phase 1). The kind names cross the
# config-data / API / Studio boundary, so they live here.
TBL_SESSION_ANALYSIS = "session_analysis"
ANALYSIS_KIND_TUNING = "tuning"
ANALYSIS_KIND_COACHING = "coaching"
ANALYSIS_KIND_EFFICIENCY = "efficiency"
ANALYSIS_KINDS = (ANALYSIS_KIND_TUNING, ANALYSIS_KIND_COACHING, ANALYSIS_KIND_EFFICIENCY)
#: What the judge saw: archived full text, content previews only, or both.
TRANSCRIPT_SOURCE_ARCHIVE = "archive"
TRANSCRIPT_SOURCE_PREVIEW = "preview"
TRANSCRIPT_SOURCE_MIXED = "mixed"
#: Analysis parse statuses beyond the judge's own sentinels.
ANALYSIS_PARSE_MISSING_KEYS = "missing_keys"
#: The model answered but hit its output cap before closing the document.
ANALYSIS_PARSE_ANSWER_TRUNCATED = "answer_truncated"

# Judge validation (#313). A "label source" names where labels come
# from: `rubric:<rubric_name>` (a judge run) or `human:<labeler>`; a bare
# name means a rubric. The prefixes cross CLI / API / Studio.
TBL_HUMAN_LABEL = "human_label"

# Session tags (Studio): the two a person sets by hand. "analyzed" is
# derived from session_analysis and is never stored as a flag.
TBL_SESSION_FLAG = "session_flag"
TBL_LOCAL_HEARTBEAT = "local_heartbeat"
FLAG_FAVORITE = "favorite"
FLAG_TODO = "todo"
SESSION_FLAGS = (FLAG_FAVORITE, FLAG_TODO)
LABEL_SOURCE_RUBRIC = "rubric"
LABEL_SOURCE_HUMAN = "human"
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
# Search result limits. With the E10 Slice B index the max is a ranked
# top-N (best first), not the arbitrary truncation the Slice A ordering
# gave it; the fallback path keeps the Slice A meaning.
SEARCH_DEFAULT_LIMIT = 50
SEARCH_MAX_LIMIT = 500

# ── Trace search index (E10 Slice B, issue #65) ────────────────────────
# Tokenized + ranked search. The index NEVER holds its own copy of trace
# text: sqlite uses an FTS5 external-content table (index only, rows read
# back from trace_document) and postgres a GENERATED column derived from
# trace_document.content. Both consequences are deliberate — a policy
# purge of a trace row removes it from the index by the same statement,
# and no redaction floor can be stale in one store but not the other.
TBL_TRACE_DOCUMENT_FTS = "trace_document_fts"
COL_TRACE_CONTENT_TSV = "content_tsv"
IDX_TRACE_CONTENT_TSV = "idx_trace_content_tsv"
# Stemming is an explicit choice, not a property of FTS: sqlite's default
# `unicode61` does NOT stem, and postgres stems per text-search config.
# These two are chosen to agree (English, Porter) and are asserted to.
FTS5_TOKENIZER = "porter unicode61"
PG_TEXT_SEARCH_CONFIG = "english"
# Which index backs a store, resolved at run time (FTS5 is a compile-time
# sqlite option and is not guaranteed present).
SEARCH_INDEX_FTS5 = "fts5"
SEARCH_INDEX_TSVECTOR = "tsvector"
SEARCH_INDEX_NONE = "none"

#: Upper bound for the read-only similarity/cluster API surfaces
#: (#293 FR-B). Range-guarding lives at the endpoint signature so an
#: existing tool contract is not altered by a UI slice.
SIMILAR_MAX_LIMIT = 100
SEARCH_SNIPPET_CHARS = 120

# mtime comparison tolerance shared by BOTH incremental walks (ingest_state
# and trace_archive_state) — the two gates must agree or they drift apart.
MTIME_EPSILON = 1e-6

# ── API request admission (#103) ───────────────────────────────────────
# The API has no authentication and binds loopback, but loopback does not
# stop a BROWSER: a page using DNS rebinding (attacker.com re-resolved to
# 127.0.0.1) reaches the API same-origin, so CORS never applies. Host
# validation is the control that closes that path — a browser always sets
# Host from the URL, so page script cannot forge it.
#
# NOTE (IPv6): Starlette's TrustedHostMiddleware compares
# `host.split(":")[0]`, which yields "[" for an IPv6 literal like
# "[::1]:8765" — IPv6 hosts CANNOT be allowlisted here. Moot while
# api/serve.py binds IPv4 127.0.0.1; revisit if that ever becomes "::".
API_ALLOWED_HOSTS = ("127.0.0.1", "localhost")

# The Studio's browser origins are built from these hosts plus the ACTUAL
# --ui-port (see api/server.studio_origins), so running the Studio on a
# non-default port is not silently broken. Used for BOTH the CORS allowlist
# and the Origin guard, so the two can never drift apart.
STUDIO_ORIGIN_HOSTS = ("localhost", "127.0.0.1")
DEFAULT_UI_PORT = 3000  # keep in sync with cli.py's --ui-port default

# Methods exempt from the Origin check. GET/HEAD are safe; everything else
# (POST/PUT/PATCH/DELETE/OPTIONS) is checked, so new state-changing routes
# are covered without maintaining a route list.
ORIGIN_SAFE_METHODS = frozenset({"GET", "HEAD"})
MSG_ORIGIN_NOT_ALLOWED = "Origin not allowed"
# The ONE curated 500 detail. A route that lets an unexpected exception
# escape hands the caller a stack trace (CodeQL py/stack-trace-exposure)
# — the same class of leak the probe's closed error set exists to
# prevent, where a driver message carried hosts, IPs and usernames.
# The exception is LOGGED in full; only this constant is returned.
MSG_INTERNAL_ERROR = "Internal error. See the server log for details."


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
# Pre-connection rejections (#101). The endpoint takes a caller-supplied
# DSN, so what it will ATTEMPT is constrained before any connection: only
# known schemes, only loopback or the configured host, and — because
# probing a fresh sqlite path used to CREATE a database file at an
# arbitrary location — only sqlite files that already exist.
PROBE_ERR_SCHEME_NOT_ALLOWED = "scheme_not_allowed"
PROBE_ERR_HOST_NOT_ALLOWED = "host_not_allowed"
PROBE_ERR_SQLITE_FILE_MISSING = "sqlite_file_missing"
# The probe must never be able to modify the target. SQLite gets that at
# the file open (mode=ro); PostgreSQL has no open-time mode, so the
# session is set read-only and VERIFIED. If it cannot be established the
# probe REFUSES — failing open would leave the database writable exactly
# on the connections where the protection did not take.
PROBE_ERR_READ_ONLY_UNAVAILABLE = "read_only_unavailable"

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
    PROBE_ERR_SCHEME_NOT_ALLOWED:
        "Unsupported DSN scheme — use sqlite:… or postgresql://…",
    PROBE_ERR_HOST_NOT_ALLOWED:
        "Host not allowed — this endpoint only tests localhost or the "
        "database host already configured.",
    PROBE_ERR_SQLITE_FILE_MISSING:
        "That SQLite database file does not exist yet — save the "
        "configuration and run ingest to create it.",
    PROBE_ERR_READ_ONLY_UNAVAILABLE:
        "Could not put the connection into read-only mode, so the test was "
        "refused — a connection test must never be able to modify the "
        "database.",
}

# Schemes the probe will attempt at all (#101). Compared case-normalized.
SCHEME_SQLITE = "sqlite"
PROBE_ALLOWED_SCHEMES = (SCHEME_SQLITE, "postgresql", "postgres")
# Loopback host NAMES always allowed, alongside the CONFIGURED DSN's host.
# Only the name lives here: loopback IP ADDRESSES in every notation
# (127.0.0.1, 127.0.0.2, expanded ::1) are matched semantically by
# db_test._is_loopback_host, so listing the canonical IPs here too would be
# redundant. Extra config-declared hosts are deliberately deferred.
PROBE_LOOPBACK_HOSTS = ("localhost",)

# libpq reads a connection URI's query string as connection keywords, and
# some of them CHANGE WHICH SERVER is contacted — so a caller could smuggle
# a target past the host allowlist via `?host=…`, `?hostaddr=…`, or a
# `?service=…` that pulls the host from a file (#101 follow-up). When psycopg
# is installed the effective host is read from libpq's OWN parser and this
# list is unused; it is the fallback for environments without psycopg, where
# only the raw query can be inspected. Compared lowercased.
PROBE_DSN_REDIRECT_PARAMS = ("host", "hostaddr", "service")

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
