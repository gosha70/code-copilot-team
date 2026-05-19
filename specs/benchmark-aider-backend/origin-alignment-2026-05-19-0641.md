# Origin-Alignment Record — benchmark-aider-backend

Date: 2026-05-19 06:41 UTC
Gate: build-entry (B0 preflight — spec corrected before any backend code)
Origin: gosha70/code-copilot-team#41 (issue body + 2026-05-19 user clarifications)
Supersedes: origin-alignment-2026-05-19-0332.md (plan-approval gate)

## Why this record exists

Phase A's plan-approval record (0332) remains valid for intent. B0
preflight (the sanctioned "confirm Aider CLI facts, do not assume"
step) verified the flag contract against Aider's authoritative options
reference and caught two factual errors in the committed spec bundle.
This record supersedes 0332 so the gate reflects the corrected,
reality-grounded spec.

## B0 corrections (accuracy fixes, NOT scope/intent changes)

1. **Auto-confirm flag: `--yes` → `--yes-always`.** The Phase-1
   research had it backwards; the options reference confirms
   `--yes-always` is the only auto-confirm flag and `--yes` does not
   exist. Corrected in spec.md (argv contract), plan.md (verification
   outline), tasks.md (TB1.1, reviewer-checklist items 2 & the
   "Flags NOT present" line). This is exactly the error B0 exists to
   catch before the backend is written.
2. **`--temperature` is not an Aider CLI flag.** Aider sets
   temperature internally (litellm); it is neither pinnable nor
   observable via the CLI. Removed from the argv "not-pinned" framing
   and from the `backend_metadata` schema; reframed as an
   Aider-internal comparability note. The methodology-fidelity
   principle is unchanged in substance (we still pin nothing
   model/edit/repo-map-behavior-bearing).

Also confirmed by B0 (no change needed): `--no-stream` is
display/rendering only (safe to pin); `--no-gitignore` is correct and
its necessity is reinforced (Aider adds `.aider*` to `.gitignore` by
default — another `run.py::_write_diff` pollution vector); the
leaderboard methodology re-scan surfaced nothing to pin beyond the
already-documented 9 invariants (per-model edit format, 2-attempt
pass@1/pass@2, 225-task pool; temperature/retries left at defaults).

## Assessment

- Intent and deliverables: unchanged from 0332 — mirror codex; one PR
  fully closes #41; bench.py / dogfood-subset / aider_polyglot adapter
  still OUT.
- The B0 corrections make the spec MORE faithful to the real CLI; they
  are accuracy fixes, not divergences. The six forced
  codex-template departures remain as documented.
- Out-of-scope list intact; no creep.

(spec.md § Sources also re-pointed from the scripting page to the
authoritative `config/options.html` flag reference and annotated the
confirmed-absent `--yes`/`--temperature` — same B0 correction, no
intent change.)

Verdict: aligned
Confidence: high
