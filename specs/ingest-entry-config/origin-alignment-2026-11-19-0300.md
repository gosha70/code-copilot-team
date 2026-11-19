# Origin Alignment Check — ingest-entry-config

Date: 2026-11-19 03:00
Trigger: first alignment record for this feature (gate exit 4).

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/473 (the caller
  table, the five symptoms, the expected behaviour).
- The owner's answer in this session to "how should this be handled
  relative to #457?": "Separate bug, fix first", described as "a security bug
  issue and fix it as a spec_mode:none PR now".

## Origin claim (verbatim)

> Every ingest entry point resolves the same configuration as
> `session_analytics ingest`: the configured redaction mode, per-project
> overrides and opt-outs, project-id rules, pricing and developer id.

## Acceptance criteria — status

- Studio's pipeline ingest applies the configured redaction mode — **met**,
  tested end to end through the API (metadata-only previews).
- Per-project opt-outs are honoured — **met**, tested end to end
  (`ingest: "off"` project, 0 sessions ingested).
- Quickstart applies the configuration — **met**, tested on the `ingest()`
  call (mode, overrides, rules, pricing).
- Project-id rules, pricing and developer id reach both entry points —
  **met** through the shared helper; the rules and pricing are asserted on
  the quickstart call.

## Fail-before proof

The new test file run against master's `api/server.py`, `quickstart.py` and
`cli.py`, with only the helper added to `pipeline.py` so the imports
resolve: 2 failures and 1 error out of 4. Studio stored `['code']` where
`['metadata-only']` was configured; Studio reported "ingested 1 sessions"
for the opted-out project; quickstart called `ingest()` with no
`redaction_mode` at all. The fourth test is the helper's own unit test.

## Mismatches

- The CLI callers were correct and still change: they now build their call
  from the same helper, so the configuration list exists once. Behaviour is
  unchanged; the full suite passes.

## Verdict

Verdict: aligned
Confidence: high
