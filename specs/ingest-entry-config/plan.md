---
spec_mode: none
feature_id: ingest-entry-config
risk_category: bugfix
justification: |
  Privacy bug fix (#473): Studio's pipeline ingest step and quickstart's
  first-run ingest called ingest() with its defaults instead of the
  configuration. The fix routes every ingest entry point through one helper;
  no schema change, no new configuration. The owner chose the spec_mode none
  path in-session (2026-11-19) so the leak is fixed ahead of #457's spec.
status: draft
date: 2026-11-19
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/473
  origin_claim: |
    Bug #473, found by the #457 redaction inventory: `api/server.py:702`
    (Studio pipeline "ingest" step) and `quickstart.py:188` (first-run
    ingest) call ingest() without `redaction_mode`, `projects`,
    `project_id_rules`, `pricing` or `developer_id`, so they store code-mode
    previews when the global or a project's mode is metadata-only, ingest
    projects configured `ingest: "off"`, ignore project-id rules, and store
    no cost. Expected: every ingest entry point resolves the same
    configuration as `session_analytics ingest`. The owner's ruling: "Separate
    bug, fix first", as its own PR ahead of #457.
---

# Plan: every ingest entry point applies the configuration (#473)

1. **One helper.** `ingest/pipeline.py` gains `configured_options(cfg, *,
   developer_id=None)`, returning the five configuration-driven `ingest()`
   arguments: `redaction_mode`, `projects`, `project_id_rules`, `pricing` and
   `developer_id`. Without a CLI flag-derived id it derives the developer id
   from env and config, the same way the CLI does with no flag.
2. **Every caller uses it.** The two broken callers, Studio's pipeline step
   (`api/server.py`) and quickstart (`quickstart.py`), build their call from
   it. The CLI `ingest` and `watch` calls, which were correct, use it too, so
   there is one list of configuration arguments and a new entry point cannot
   drop one. CLI-only arguments (`--redact`, `--root`, selection) stay at the
   call site.
3. **Tests** (`tests/test_ingest_config.py`):
   - Studio's ingest step, driven through `/api/pipeline/run/ingest`, stores
     `metadata-only` previews under a metadata-only config, and ingests
     nothing from a project configured `ingest: "off"`;
   - quickstart's `ensure_store` passes the configured mode, overrides, rules
     and pricing to `ingest()` (checked on the call, since a real run would
     read every adapter's default root on the machine);
   - `configured_options` carries every setting.

## Not done

- Stores already ingested through Studio or quickstart keep their code-mode
  previews until they are re-ingested (`ingest --full`). Session Analytics is
  unreleased, so no migration is added.
- The stale-mode gap on outbound paths (a project tightened after ingest
  still sends its old previews) is #457's scope, by the owner's ruling.
