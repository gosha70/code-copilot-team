---
feature_id: auto-build-reviewer-probe
spec_mode: lightweight
status: approved
date: 2026-09-10
issue: "#190 (engine hardening from run data; no child issue by the owner's standing rule)"
origin:
  transcripts:
    - specs/auto-build-reviewer-probe/origin/2026-09-10-owner-decision.md
  user_messages:
    - "2026-09-10: 'I recommend the reviewer probe first: one small request through the actual gating-reviewer path, requiring a parseable verdict. That checks readiness, not review quality.'"
  documents:
    - "issue #190 §4 (provider_unavailable: existing preflight behavior retained), §2 (cost accounting)"
---

# Spec: the reviewer probe at admission

## Why

Runs 1 and 3 of 2026-09-09 passed the gating reviewer's healthcheck and
lost their first review round to a reviewer that could not answer: a
CLI whose `--version` worked while `exec` was broken, and an endpoint
whose `/v1/models` answered while its completions carried no content.
A healthcheck verifies an install or a listening port; nothing verifies
that the reviewer can produce a verdict until the round that needs one.

## User scenarios

- US1: I start an unattended run. Before the driver builds anything,
  the gating reviewer is sent one small review request through the same
  provider resolution, adapter command, sandbox environment, timeout and
  verdict parser a real round uses. A parseable verdict means the run
  proceeds; anything else terminates `provider_unavailable` at
  admission with the reviewer's actual answer in the detail, before a
  build session is paid for.
- US2: I read the ledger afterwards and see which provider answered the
  probe (the configured one or a fallback), what it said, how long it
  took, and what it cost — metered, or the same conservative estimate
  every unmetered invocation is debited.

## Requirements

- FR-1 **Probe mode in the runner.** `review-round-runner.sh <project>
  --probe --peer NAME [--subject NAME] --out FILE` resolves the provider
  exactly as a round does (`load_provider_config`, the healthcheck, the
  subject's fallback chain), builds a fixed probe request (a one-line
  diff under the real "Required Output Format" text, with the verdict
  shape described in prose and never instantiated — the same rule the
  parser relies on), runs the provider's command with the provider's
  timeout in the same read-only sandbox environment, and extracts the
  verdict with `rv_extract_verdict`. It touches no review state: no
  `state.json`, no findings, no breaker file, no snapshot.
- FR-2 **Probe result.** `FILE` receives `{probe: true, requested_provider,
  provider, provider_type, fingerprint, exit_code, verdict, parseable,
  duration_sec, invocation_cost_usd, error, output_tail}`. Exit 0 when
  a verdict was parsed (PASS, FAIL or INCONCLUSIVE, as the model wrote
  it); 2 when no provider in the chain passed its healthcheck; 3 when a
  provider ran and no verdict could be parsed (timeout included). Empty
  output is never a verdict.
- FR-3 **Admission placement.** In the driver's `preflight`, under the
  `unattended` profile and not under `--dry-run`, right after the gating
  reviewer's healthcheck passes: run the probe with the run's gating
  reviewer and subject provider, result written to
  `<ledger>/reviewer-probe.json`. Exit 0 journals `reviewer_probe`
  (provider, verdict, seconds, cost); any other exit disposes
  `provider_unavailable` with a detail that names the provider, the exit
  and the probe's error or output tail. Attended profiles are unchanged.
- FR-4 **Cost.** The probe is one reviewer invocation and is debited by
  the existing rule: a measured `invocation_cost_usd` debits
  `totals.cost_usd`; an unmetered probe debits the configured
  per-invocation estimate into `totals.cost_estimated_usd`, flagged in
  the journal. No separate allowance, no new config key.
- FR-5 **Tests.** Runner: probe against a passing mock (exit 0, verdict
  PASS, result file), a mock that answers prose without a verdict (exit
  3, `parseable: false`), a mock that echoes the request (no verdict —
  the prose rule holds), a down primary with a healthy fallback (the
  fallback answers, `provider` names it), a chain with nothing healthy
  (exit 2), a timing-out mock (exit 3, error names the timeout); the
  probe leaves no review state behind. Driver: an unattended run's
  ledger carries `reviewer-probe.json` and a `reviewer_probe` journal
  line; an unattended run whose reviewer answers no verdict terminates
  `provider_unavailable` at admission with no build session started and
  the detail naming the probe; the estimate test counts the probe as an
  invocation; an attended run performs no probe; `--dry-run` performs
  no probe. Test-count pins and the README counts updated.
- FR-6 **Docs.** The driver's README section on admission names the
  probe; the provider-profile template's healthcheck comment says what
  the probe adds.

## Constraints

- One PR; no new GitHub issue; no config key; no change to the verdict
  parser or the request format of a real round.
- The probe never writes under `.cct/review/`.

## Out of scope

Increment D; attended-profile probing; a probe for advisory reviewers;
judging the quality of the probe's answer beyond a parseable verdict.
