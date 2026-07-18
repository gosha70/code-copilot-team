# Gate 2 — verdict-correctness run (T4.5, load-bearing)

Run: `20260718T020744Z-cct-dogfood-memkernel-claude-code-001` · benchmark
`cct-dogfood-memkernel` (memkernel#3 spec-first dogfood, fixture pinned at
memkernel `f4c3a578…`) · backend `claude-code` · model `sonnet` · `--runs 3`
· executed 2026-07-18 (UTC). GitHub Actions unavailable; verification local.

## Success criterion

Per (run, attempt) pair, the harness `tests_passed` verdict must match the
maintainer's independent read of the produced `specs/memory-brain/spec.md`
for **≥80%** of pairs (3/3 in practice with `--runs 3`).

## Results — 3/3 agreement (100%): **GATE 2 PASS**

| Attempt | Harness | Maintainer read | Hard checks | Best-effort |
|---|---|---|---|---|
| run-001 (128.9s) | pass | **pass** | 9/9 ✓ | ruff/mypy/pytest skipped (toolchain absent — fixture design) |
| run-002 (109.7s) | pass | **pass** | 9/9 ✓ | same |
| run-003 (114.6s) | pass | **pass** | 9/9 ✓ | same |

## Maintainer-read notes (the substantive half)

Each produced spec (committed as `produced-spec.md` per attempt) was read
against memkernel#3 §7 for the "structurally-correct-but-substantively-weak"
failure class the reviewer rules name as the verifier-too-lenient signal.
**That class did not materialize.** All three specs carry genuine substance,
not just the seven grepped headers:

- a 4-tier memory model with per-tier volatility/searchability/cost policies
  and an explicit migration mapping from today's memkernel types;
- a lifecycle state machine covering 9 operations with trigger/gate/
  provenance contracts and CONCRETE thresholds (demote: 90-day age + 1/quarter
  recall floor; archive: 365 days; both per-project configurable);
- a routing rubric with classifier signals, an override parameter, and an
  explicit degraded-mode failure behavior;
- a typed `SynthesisEngine` Protocol with policy/result/health types, one-shot
  working-set semantics, and a `NullSynthesisEngine` first implementation;
- honest out-of-scope and a sequencing note that defers issues #3/#5/#6.

The three attempts are near-identical in content (different wrapping/length:
205/340/200 lines) — run-to-run consistency is itself favorable signal for
verdict stability.

**No calibration-set data for #34's verifier-too-lenient class emerged from
this run** (nothing weak passed). The gate's conclusion: for this fixture,
harness verdicts can be trusted.

## Notes

- `session_id` null on all attempts (bare-mode invocation) — same E9
  correlate implication as Gate 1.
- `worktree/` snapshots not committed; each attempt's produced spec is
  preserved as `produced-spec.md`, and `diff.patch` carries the change
  record.
- Full `transcript.json` files are deliberately NOT committed: they carry
  local/session metadata (absolute temp paths, session ids, MCP/plugin
  status, usage metadata) beyond what the evidence policy needs. The
  produced spec + prompt + diff + score + stats + verify output fully
  support the Gate 2 judgment.
