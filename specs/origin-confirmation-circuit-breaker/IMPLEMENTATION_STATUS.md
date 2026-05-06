# Origin-Confirmation Circuit Breaker — Rollout Status

Snapshot taken on 2026-05-06 immediately after the breaker landed and
backfill completed. Exit codes are from
`scripts/check-origin-alignment.sh <feature-id>` against each spec.

| Spec | Origin shape | Exit | Status |
|------|--------------|------|--------|
| `origin-confirmation-circuit-breaker` | issue + transcripts + alignment record | 0 | Self-dogfood: aligned, high. |
| `code-reviewer-assistant` | `type: internal` | 0 | Framework-level peer review infra; exempt. |
| `infra-verification-gate` | `type: internal` | 0 | Framework-level quality gate; exempt. |
| `sdd-sprint-1` | `type: internal` | 0 | Framework specification layer; exempt. |
| `llm-wiki-groundwork` | issue gosha70/code-copilot-team#12 + Karpathy gist URL | 4 | No alignment record yet — `/origin-check llm-wiki-groundwork` produces one before next change. |
| `memkernel-integration` | urls (memkernel repo) | 4 | No alignment record yet — needs `/origin-check`. |
| `pitches/0001-shape-up-support` | url (basecamp.com/shapeup) | 4 | No alignment record yet — needs `/origin-check`. |

**Specs not yet on master** (live on other branches; will run through
the breaker after rebase):

| Spec | Branch | Expected verdict on first run |
|------|--------|------------------------------|
| `wiki-ingest-pipeline` | `feat/wiki-ingest-pipeline` | **derailed** against issue #12 + Karpathy gist. This is the proof that the breaker fires on real drift. The user picks resolution A/B/C in the next session. |

## Notes

- "Exit 4" is expected for any spec with a real external origin until an
  alignment record exists. The breaker is doing its job: it surfaces the
  missing record to the next person who touches the spec.
- "Exit 0" via `type: internal` is a deliberate, committed exemption.
  Specs that reach for the exemption when a real origin exists will be
  flagged in code review.
- All seven existing specs pass `bash scripts/validate-spec.sh --all`
  after the backfill (14/14, 0 failures).
- Adapter propagation verified after `bash scripts/generate.sh`: the
  `origin-confirmation` skill body appears in
  `adapters/codex/AGENTS.md`, `adapters/cursor/.cursor/rules/origin-confirmation.mdc`
  (with `alwaysApply: true`),
  `adapters/github-copilot/.github/copilot-instructions.md`,
  `adapters/windsurf/.windsurf/rules/rules.md`, and
  `adapters/aider/CONVENTIONS.md`.
