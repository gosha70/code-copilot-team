# Origin Alignment Check — routing-eval

Date: 2026-09-25 21:33 (re-check)
Trigger: a maintenance fix outside this feature — correcting the
verifier-kind match in `scripts/lib/routing-packet.sh` and
`scripts/lib/routing-tasks.sh` from the non-schema string `"test"` to
the schema's `deterministic` — tripped this feature's decision-2 diff
guard, `TestNoProductionRoutingFileTouched`. The owner approved
retiring that guard and directed this re-check rather than any edit to
the 2026-08-25 record, which stays byte-identical.

Origin: #260 (E1 of #109) — see `plan.md`'s `origin:` block and the
`origin/` sources enumerated in
`origin-alignment-2026-08-25-1100.md`, all of which this re-check
leaves in force.

## Origin sources re-read

- `specs/routing-eval/plan.md` decision 2 — "Injection drives the
  existing test-only seams; production routing code is untouched",
  naming `CCT_SUPERVISOR_HARNESS_CMD`
  (`scripts/cooldown-supervisor.sh:57`) and `CCT_ROUTING_PROBE_CMD`
  (`scripts/lib/routing-probe.sh:37`), and closing: "modifying any
  production routing file is out of scope **for this increment**: a
  diff that touches one is a defect".
- `plan.md` decision 10 — "E1 adds no runtime authority."
- `plan.md` Test Strategy, *Injection seam* and *No-runtime-change* —
  where the guard was specified as asserting that **the increment's**
  diff touches no production routing file.
- `origin-alignment-2026-08-25-1100.md` verdict block and the T7
  closure sections, which record decision 10's proof at merge.
- `shared/schemas/verification.schema.json` — the closed verifier-kind
  vocabulary the correction aligns to.

## Working claim

E1 is merged and unchanged in substance by this re-check. It remains the
measurement substrate: a `scenario: "hybrid-routing"` preset kind with
`arms[]`, deterministic event injection through the two named test-only
seams, the durable artifact schemas, `quality_fn: v1`, the control and
oracle selectors, and the cost/reporting contract. No routing behaviour,
no runtime authority, and no artifact schema changes here. The only
change inside this feature's own surface is the removal of one test
class and the generated bridge artifact's verifier kind.

## Findings

1. **Decision 2 was satisfied by E1 at merge.** E1 shipped without
   modifying `scripts/lib/routing-*`, `scripts/routing-cli.sh`, or
   `scripts/cooldown-supervisor.sh`. That is recorded in the
   2026-08-25 record's T7 closure sections and is not in dispute; the
   present re-check does not revisit it.

2. **The diff guard was incorrectly generalized into a permanent
   branch-wide prohibition.** `plan.md` specified a guard over *the
   increment's* diff. As implemented,
   `TestNoProductionRoutingFileTouched` diffed the **caller's entire
   branch** against `merge-base origin/master HEAD`, plus
   `git status --porcelain`. Once E1 landed on master that subject
   ceased to exist, so the test no longer measured E1 at all: it
   forbade any later branch from editing the three production routing
   paths whenever that branch also touched
   `scripts/benchmark_runner/**`. It fired on exactly such a change.
   Narrowing it would have preserved the same branch-context-dependent
   design without protecting any runtime property.

3. **Retiring it does not change the origin or the runtime contract.**
   Decisions 2 and 10 are statements about what E1 delivered, and they
   remain true of the merged artifact. Removing an after-the-fact diff
   assertion changes no preset key, no artifact schema, no selector, no
   seam, and no routing code path. The retirement is recorded with its
   date and reasoning in a new note at the end of `plan.md`, and the
   two Test Strategy bullets that referenced the guard now point at
   that note instead of contradicting it.

4. **The four durable seam safeguards remain green.**
   - the scenario drives only `CCT_SUPERVISOR_HARNESS_CMD` and
     `CCT_ROUTING_PROBE_CMD`;
   - any other seam name fails closed —
     `test_unknown_seam_is_refused_by_name`;
   - the real, unmodified `rr_classify` and `rb_probe` do the real work
     on injected transcripts — `TestClassificationParity`,
     `TestRealProbeContract`;
   - the supervisor integration test drives the generated packet through
     production routing end to end —
     `TestFullArcThroughTheRealSupervisor`, which now also asserts the
     generated `verification.yaml` declares `kind: deterministic`,
     pinning the generator correction at its owner. Mutating the
     generator back to `kind: test` fails that test at the supervisor
     itself: `packet_artifact_invalid: … fr_ref 'FR-1' has no
     deterministic 'test' verifier`.

5. **The routing-kind correction is aligned with the schema's closed
   vocabulary.** `shared/schemas/verification.schema.json` admits
   exactly `deterministic | runtime_conformance | visual`; `test` is the
   field name a deterministic verifier carries, never a kind. Both
   production sites now select on `deterministic`, matching
   `verification-common.sh`'s own freeze (`vkind[i] == "deterministic"`),
   and this feature's bridge generator emits the schema's kind. The
   correction moves the code toward the authoritative contract rather
   than away from it; it is a defect fix outside E1's scope that
   touches this feature only because E1's generator carried the same
   non-schema string.

## Mismatches / deviations from the origin sketch

- **The decision-2 guard no longer exists as an executable test.** The
  origin text's requirement — that E1 not modify production routing —
  was met at merge and is unchanged; what is gone is a post-merge
  assertion that had come to constrain unrelated callers rather than
  this increment. Recorded here and in `plan.md` so a later reader does
  not mistake the absence for an unmet requirement.
- Nothing else. No deviation is introduced in scope, surface, data
  flow, or output target relative to the 2026-08-25 verdict.

## Verification run for this re-check

- Full benchmark-runner suite: 1085 tests, OK (10 skipped);
  `TestFullArcThroughTheRealSupervisor` confirmed to run, not skip.
- Six routing suites: config 365, failover 227, tasks 160, packet 102,
  delegation 180, recovery 375 — 0 failures.
- `cooldown-supervisor` 67/67; `validate-spec.sh --all` 192/192;
  `validate-collaboration.sh`, `validate-features.sh`,
  `validate-workflows.sh`, the four `--check` generators and
  `check-doc-accuracy.sh` all clean; `git diff --check` clean.

## Verdict

Verdict: aligned
Confidence: high

The origin sources were re-read in full for this check and the
mismatch above is enumerated exhaustively. E1's delivered scope is
unchanged against #260 and #109 increment E; the retirement removes an
assertion whose subject no longer exists, and the seam contract that
actually protects production routing is intact and asserted in code.
