---
spec_mode: full
feature_id: redaction-canaries
risk_category: security
status: approved
date: 2026-11-19
---

# Spec: canary secrets on every off-machine path (#457)

## Why

Session Analytics sends session text off the machine: to the per-turn judge, to the session-analysis judge, to the Ask model, to an embedding provider and to MCP clients. Redaction happens once, at ingest, and the paths downstream send what was stored. Redaction is tested only on two paths: the steering excerpts (including the truncate-before-redact boundary case from the article) and the trace archive. The issue asks for a structural guard: plant canary secrets in the fixtures and fail the build if any of them reaches anything that leaves the machine. That includes a path added later.

The inventory behind this spec found a second gap, and the owner ruled it in scope. Only the steering excerpts and the archive apply the project's *current* redaction mode. Every other outbound path sends text stored under the mode in force at ingest. A project tightened to `metadata-only` after ingest keeps sending its old previews until someone re-ingests it.

## User Scenarios

### US1: A path that skips redaction fails the build (Priority: HIGH)

**Given** the canary corpus is ingested under a redacting mode
**When** any off-machine path runs over it
**Then** no canary the mode promises to remove appears in what that path sends, and a test failure names the canary and the path that leaked it.

### US2: A new outbound path cannot ship without canary coverage (Priority: HIGH)

**Given** a contributor adds code that sends text through a judge, embedding or MCP transport
**When** the suite runs
**Then** it fails until that path is added to the canary suite's coverage.

### US3: Tightening a project's mode takes effect without re-ingest (Priority: HIGH)

**Given** sessions ingested under `none` or `code`
**When** the project (or the global mode) is changed to `metadata-only`
**Then** every off-machine path sends `metadata-only` markers for those sessions, before any re-ingest.

### US4: Opting a project out stops it leaving the machine (Priority: HIGH)

**Given** sessions of a project already in the store
**When** that project is configured `ingest: "off"`
**Then** no off-machine path sends anything from those sessions, before any re-ingest.

## Requirements

- **FR-001: Canary corpus.** A fixture session and project root (`tests/fixtures/canary/`) carry a distinct canary string in each place session or project content can enter Session Analytics:
  - a fenced code block in a user turn and in an assistant turn;
  - prose in a user turn and in an assistant turn;
  - a tool-input value;
  - tool output and an error message;
  - `AGENTS.md` and `CLAUDE.md` in the project root, each with a fenced and a prose canary;
  - a fence that straddles the 500-character preview cut, and one that straddles the 1,200-character steering cut.

  Canaries are distinctive, secret-shaped strings (e.g. `sk-canary-<placement>-…`), so a failure names the place that leaked.
- **FR-002: Capture at the boundary.** The suite captures everything each path would send, with no network:
  - a fake judge backend, registered through `judge/registry.py`, records every `rate_turn` context and every `complete` prompt;
  - a fake embedding provider records every input;
  - Ask tool results and MCP tool and resource outputs are captured from their own entry points.
- **FR-003: Paths covered** (the owner's "everything off-machine"):
  - the per-turn judge (`judge/runner.py`);
  - session analysis: the transcript, steering excerpts, session facts and harness stamp (`judge/session_analysis.py`);
  - Ask: the prompt and every tool result (`ask/loop.py`, `ask/tools.py`);
  - embeddings (`embedding/composer.py` → provider);
  - every MCP tool and resource (`mcp/server.py`, `mcp/resources.py`).
- **FR-004: Invariant per mode.**
  - **`metadata-only`:** no canary from FR-001 appears in any captured payload.
  - **`code`:** none of the following appears in any captured payload:
    - the fenced canaries, including both straddle cases;
    - the steering files' fenced canaries;
    - the tool-input value canary (`code` keeps only the key names and a hash);
    - the tool-output and error-message canaries (`code` reduces both to a length-and-hash marker).

    Only the prose canaries are exempt, in turns and in steering files, because `code` keeps prose by definition.
  - **`none`:** no assertion.
- **FR-005: Current-mode floor on every outbound path.** Each path in FR-003 sends a session's text under `stricter_mode(recorded, current)`.
  - `recorded` is the session's stored `redaction_mode`. `current` is the project's override from the current configuration, else the global mode.
  - When `current` is stricter than `recorded`, the path sends a `metadata-only` marker in place of the stored text (D1). It does not re-redact under `code`, because stored previews are already truncated and a fence cut by that truncation would escape the fence pattern (the article's boundary bug).
  - **A session whose project is currently configured `ingest: "off"` is skipped on every outbound path (D2).** The path sends no row, text, marker or identifier from that session:
    - the per-turn judge selects none of its turns;
    - session analysis refuses it, saying the project is opted out;
    - Ask tools and MCP tools and resources leave its rows out;
    - embeddings skip it.

    Aggregates over the store (counts, totals) are not per-session data. Totals may include them, but no aggregate is broken down by, or names, an opted-out project or its sessions. The stored sessions are not deleted.
  - The floor is computed in one place, extracted from `project_context` in `judge/session_analysis.py`, and every outbound path calls it. The steering path keeps its behaviour, except that an opted-out project's steering files are not read.
- **FR-006: Floor tests.** The canary corpus is ingested under `none` and under `code`, then the configuration is changed with no re-ingest:
  - **Tightened to `metadata-only`**, per project and globally: FR-004's `metadata-only` invariant must hold on every FR-003 path.
  - **Opted out**, with the project set to `ingest: "off"`: no FR-003 path sends any canary, row, marker or identifier from the corpus session.
- **FR-007: Coverage guard.** A test enumerates the modules that call an off-machine transport: judge `rate_turn`/`complete`, the embedding provider, MCP tool and resource registrations, and the Ask tool table. It fails when one of them has no entry in the canary suite's coverage map, naming the module. Exemptions are listed by name with a reason (D3).

  **Limits.** The check is a static scan of call names, so it misses:
  - **aliases:** a transport method bound to another name (`send = judge.complete; send(p)`) or passed as a callback;
  - **dynamic lookup:** `getattr(judge, "complete")(p)` and similar;
  - **new transport methods:** a backend method with a name the scan does not list (it knows `rate_turn`, `complete` and `embed`);
  - **direct HTTP:** a module that sends text with `urllib`, `httpx`, `requests` or a socket, bypassing the judge and embedding backends.

  These are left to review: a change that adds any of them must add the path to the coverage map by hand. The canary assertions still catch a leak on any path the suite runs.
- **FR-008: Existing guards stay.** The steering straddle tests in `test_session_analysis.py` and the archive canary test in `test_trace_archive.py` remain. The corpus repeats both boundary cases at the canary level.

## Constraints / What NOT to Build

- No change to what each redaction mode removes. `code` still keeps prose; secret-pattern scanning is not added.
- Metadata is not content and no mode redacts it: `project_path`, file paths, slash commands, tool names, model names and harness-stamp digests. Canaries are not placed there, and the spec does not change that.
- On-machine outputs are out of scope, per the owner's coverage ruling: Studio API responses, search snippets shown in Studio, CSV/Parquet export and the hand-labelling CSV.
- Project text that is not session content stays out: expectation statements and verifier evidence (from `spec.md` and the ledger), and the auto-build triage report. The gap is recorded as a follow-up.
- No real network, provider or model in any test.
- No schema change. Stores ingested before the change need no migration: the floor reads the stored mode.

## Key Entities

- **Canary corpus:** the FR-001 fixture session and project root, with one named canary per placement.
- **Capturing backends:** the fake judge and fake embedding provider that record payloads (FR-002).
- **Outbound mode:** `stricter_mode(recorded, current)`, or *skip* when the project is currently `ingest: "off"` (FR-005).
- **Coverage map:** the list of off-machine modules the canary suite exercises, checked by FR-007.

## Decisions (ruled by the owner on 2026-11-19)

- **D1: a marker on tightening.** When the current mode is stricter than the recorded one, the path sends a `metadata-only` marker rather than re-redacting the stored, already-truncated text. Agreed.
- **D2: opted-out projects are skipped.** Sessions of a project currently configured `ingest: "off"` are skipped on every outgoing path, not sent as `metadata-only` markers. Their stored rows are not deleted.
- **D3: named exemptions in the coverage guard.** A module that calls a transport for something other than session data, such as the backend connection test, which sends a fixed string, is exempted by name with a reason. Agreed.

## Success Criteria

1. With the corpus ingested under `metadata-only`, no canary appears in any payload captured from the FR-003 paths. Under `code`, no canary except the prose ones does.
2. With the corpus ingested under `none` or `code` and the configuration then tightened to `metadata-only`, criterion 1's `metadata-only` result holds with no re-ingest. With the project then set to `ingest: "off"`, nothing from the corpus session appears in any payload.
3. Removing redaction from any one FR-003 path, or bypassing the floor on it, fails at least one canary test that names the path and the canary. The implementation PR demonstrates this for each path.
4. Adding a call to an off-machine transport in a module missing from the coverage map fails FR-007's test.
5. `bash scripts/validate-spec.sh --feature-id redaction-canaries` and `bash scripts/check-origin-alignment.sh redaction-canaries` exit 0.
