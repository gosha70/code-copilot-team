# Cross-cutting compliance record — TX.1–TX.3

Closes the three cross-cutting/meta tasks of the pi-harness-adoption tracker.
These are delivery-conduct assertions, not code: this record is their audit and
their honest verdict. Written 2026-08-04, after the last functional task (FU-2,
PR #168) merged. Two verdicts are qualified — read them, they are not rubber
stamps.

| Task | Verdict |
|---|---|
| **TX.1 (P0)** security tasks have acceptance tests + audit-log coverage | **MET** |
| **TX.2 (P0)** integration-branch policy; no merge to master until DoD | **CLOSED BY DOCUMENTED DIVERGENCE** — literal policy not followed; intent preserved by equivalent controls |
| **TX.3 (P1)** each task records files-affected + delivery slice in its PR | **SUBSTANTIALLY MET** — files-affected recorded; slice label lived in tasks.md, not every PR body |

---

## TX.1 (P0) — acceptance tests + audit-log coverage for security work — MET

Two halves, both present across the delivery.

**Audit-log coverage.** `adapters/pi/runtime/policy/audit.ts` appends JSONL
records for security-relevant decisions with the C-9 fields — `decision`,
`rule`, `subject` (path/normalized command, truncated; never file contents),
plus `ts` and `mode`. Emission is *asserted* (not just present) in 8 runtime
test files: `enforcement` (primary site — 32 audit assertions),
`permission-live-wiring`, `sandbox`, `config`, `hooks`, `mcp`, `memory`,
`review`.

**Acceptance tests for the DoD #11 threat list.** `security-battery.test.mjs`
carries 9 batteries, one per named threat class:

| Battery | Threat (DoD #11 / spec) |
|---|---|
| 1 | trust gating — untrusted project config refused, not applied (fail-closed) |
| 2 | protected paths — traversal to a protected file denied |
| 3 | command denial — privilege prefix cannot hide a package install |
| 4 | sandbox fail-closed — required sandbox on an unrestricted host blocked |
| 5 | secret redaction — a secret value is detected; ordinary text is not |
| 6 | lifecycle honesty — an unobservable Pi event reports unsupported |
| 7 | tamper-safe ledger — two-lead / bogus-approval `team.json` rejected |
| 8 | fail-closed team/worktree — unsafe claim + foreign cleanup refused |
| 9 | degraded honesty — degraded surfaces reported degraded, never `enabled` |

**Analytics secret leakage** (DoD #11 last clause) is covered on two surfaces:
`scripts/session_analytics/tests/test_redaction.py` +
`test_project_privacy.py` at the store boundary, and the launcher's secret-leak
sweep in `tests/test-pi-launcher.sh` (a loop over *every* diagnostic surface —
`config`/`doctor`/`features`/`export`/`resources`/`provenance`, each in text and
`--json`) that fails if any surface echoes a planted `sk-…` value.

Verdict: **MET.** Every security-relevant surface has an acceptance test, and
security decisions are audit-logged with the C-9 fields and asserted in tests.

## TX.2 (P0) — branch policy — CLOSED BY DOCUMENTED DIVERGENCE

**Stated policy:** all work on a long-lived `feature/pi-harness-adoption`
integration branch (or child branches merged into it); **no merge to `master`
until the spec.md Definition of Done holds.**

**What actually happened:** the delivery was **trunk-based** — each task on its
own short-lived child branch (`feature/pi-t114-release`,
`feature/fu1-session-metadata`, `feature/fu2-provenance`, `fix/pi-t81-review-safety`,
…), opened as its own PR and merged **directly to `master`**, task by task. No
long-lived integration branch ever existed.

**Why the divergence is deliberate, not an accident.** The repo's actual
workflow is autosync-driven: any local commit is pushed and raised as a PR (and
may be auto-merged) within seconds, which makes a long-lived hand-held
integration branch unworkable. This was the owner's chosen workflow throughout,
not a lapse.

**Why the divergence is safe — the *intent* of TX.2 was preserved by equivalent
controls.** TX.2's purpose is "never let `master` hold half-built,
security-sensitive, or unenforced work." That was enforced per-PR instead of
per-DoD:

- Every PR was independently green (its own test suites + the runtime
  type-check gate) before merge — master was releasable at every step.
- Security-sensitive surfaces shipped with their tests *in the same PR*
  (per TX.1), never ahead of them.
- Capability honesty was gated per-PR: a capability may report `enabled` only
  when its acceptance suite passes (the `test-pi-provider-gate.sh` circuit), so
  no half-built capability was ever advertised as working on master.
- The DoD's 13 gates are themselves tested gates that were satisfied
  incrementally; the final one (T11.x — generated docs/SBOM/checksums/lessons)
  landed last, matching "DoD holds" at the end of the sequence.

Verdict: **the literal branch policy was not followed; its intent was met by a
per-PR gating discipline.** Recorded as a divergence rather than a false `[x]`.
No action possible or desirable on merged history — this record *is* the
resolution (document-divergence, per the origin-confirmation escalation).

## TX.3 (P1) — files-affected + delivery slice in each PR — SUBSTANTIALLY MET

**Files-affected: recorded.** Each PR body (fed from the commit message by
autosync) enumerates the files touched with a per-file description — e.g. PR #168
lists `cli.ts`, the `pi-code` launcher, and the test changes with what each
does. The durable per-task record in `tasks.md` also lists files affected for
every task.

**Delivery slice: recorded, but in `tasks.md`, not every PR body.** The slice
membership (Slice B/D/E/F, Phase N) is captured in the `tasks.md` header and
per-task entries rather than restated in each PR description. The auto-appended
PR template sections (`## Summary` / `## Changes` / `## Validation` checkboxes)
were frequently left as placeholders because the substantive content was already
in the commit-message body above them.

Verdict: **SUBSTANTIALLY MET.** The information TX.3 asks for exists and is
discoverable (commit/PR body for files; `tasks.md` for slice), but it is not
uniformly co-located in every PR description. Noted as a deviation, not claimed
as perfect literal compliance.

---

## Net

TX.1 met; TX.3 substantially met; TX.2 closed by documented divergence. With
these three closed, the pi-harness-adoption tracker is **65 of 65** — every
functional task and both follow-ups (FU-1, FU-2) delivered and merged. The only
open honesty note is TX.2's branch-policy divergence, recorded here in full
rather than hidden behind a checkbox.
