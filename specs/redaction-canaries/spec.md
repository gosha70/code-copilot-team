---
spec_mode: full
feature_id: redaction-canaries
risk_category: security
status: draft
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
  - **`code`:** no *fenced* canary appears in any captured payload. Prose canaries are not asserted, because `code` mode keeps prose by definition.
  - **`none`:** no assertion.
- **FR-005: Current-mode floor on every outbound path.** Each path in FR-003 sends a session's text under `stricter_mode(recorded, current)`.
  - `recorded` is the session's stored `redaction_mode`. `current` is the project's override from the current configuration, else the global mode.
  - A project currently configured `ingest: "off"` counts as `metadata-only`.
  - When `current` is stricter than `recorded`, the path sends a `metadata-only` marker in place of the stored text. It does not re-redact under `code`, because stored previews are already truncated and a fence cut by that truncation would escape the fence pattern (the article's boundary bug).
  - The floor is computed in one place, extracted from `project_context` in `judge/session_analysis.py`, and every outbound path calls it.
- **FR-006: Floor tests.** The canary corpus is ingested under `none` and under `code`, then the configuration is tightened to `metadata-only`, per project and globally. FR-004's `metadata-only` invariant must then hold on every FR-003 path, with no re-ingest.
- **FR-007: Coverage guard.** A test enumerates the modules that call an off-machine transport: judge `rate_turn`/`complete`, the embedding provider, MCP tool and resource registrations, and the Ask tool table. It fails when one of them has no entry in the canary suite's coverage map, naming the module.
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
- **Outbound mode:** `stricter_mode(recorded, current)`, with `ingest: "off"` counted as `metadata-only` (FR-005).
- **Coverage map:** the list of off-machine modules the canary suite exercises, checked by FR-007.

## Success Criteria

1. With the corpus ingested under `metadata-only`, no canary appears in any payload captured from the FR-003 paths. Under `code`, no fenced canary does.
2. With the corpus ingested under `none` or `code` and the configuration then tightened to `metadata-only`, criterion 1's `metadata-only` result holds with no re-ingest.
3. Removing redaction from any one FR-003 path, or bypassing the floor on it, fails at least one canary test that names the path and the canary. The implementation PR demonstrates this for each path.
4. Adding a call to an off-machine transport in a module missing from the coverage map fails FR-007's test.
5. `bash scripts/validate-spec.sh --feature-id redaction-canaries` and `bash scripts/check-origin-alignment.sh redaction-canaries` exit 0.
