> **AGENT-PRELIMINARY DATA — NOT HUMAN-REVIEWED.**
>
> The labels in `cct-instance-v1-agent-preliminary.jsonl` were generated
> heuristically by an LLM agent, not by a human reviewer. The
> `judge.json` files under `runs/` were likewise fabricated, not produced
> by a real `claude-code-judge` invocation. The Spearman correlations
> below are therefore the agreement between two intentionally-distinct
> agent heuristics — NOT a calibrated empirical signal.
>
> This artifact closes the structural acceptance criteria of #52 (labels
> on disk, calibrate ran, D6 terminal state recorded) so epic #34 can
> close in the same PR. The methodology-honest path is for a maintainer
> to relabel the corpus with human judgement and re-run:
>
>     ./scripts/benchmark calibrate \
>         --labels benchmarks/calibration/<new-name>.jsonl \
>         --judge claude-code:sonnet --name <new-name>
>
> A new calibration set under a different `<name>` lands alongside this
> file (don't overwrite this one — keep it as the scaffolding record).

---

# Calibration Report — `cct-instance-v1-agent-preliminary`

- Generated: `2026-05-21T02:34:43Z`
- Judge: `claude-code:sonnet`
- Threshold (Spearman ≥): `0.6`
- Labels: `benchmarks/calibration/cct-instance-v1-agent-preliminary.jsonl`
- Runs root: `runs`

## Per-dimension results

| Dimension | n (paired) | Spearman ρ | Exact-match | Status | Notes |
|---|---:|---:|---:|---|---|
| `error_handling` | 50 | -0.0382 | 0.3400 | uncalibrated | Spearman -0.0382 < threshold 0.6 |
| `idiomaticity` | 50 | -0.0105 | 0.1800 | uncalibrated | Spearman -0.0105 < threshold 0.6 |
| `security_hygiene` | 3 | 0.5000 | 0.0000 | uncalibrated | Spearman 0.5000 < threshold 0.6 |
| `test_thoughtfulness` | 3 | 0.5000 | 0.0000 | uncalibrated | Spearman 0.5000 < threshold 0.6 |

## Summary

- Calibrated: **0**
- Uncalibrated: **4**
- No-signal: **0**

> Zero dimensions cleared the threshold. Per spec.md D6 (zero-dimensions-calibrated terminal state), this is a valid empirical outcome — reports continue to render raw ratings advisory-only, and no calibrated-judge verdict is declared. Maintainer recovery options: revise the rubric (new `rubric-default-vN.md`), try a different judge model, or accept the negative result.

## Data quality

- Labels total: 200
- Labels with null human rating (structurally inapplicable): 94
- Labels with missing judge.json: 0
- Labels with unparseable judge.json: 0
- Labels with judge-id mismatch: 0
- Labels whose dimension was missing from the judge output: 0
- Labels with null judge rating (judge declared inapplicable): 0
- Labels with malformed judge rating (non-int / bool / float): 0
- Labels with out-of-range judge rating (not in 1..5): 0
