# Origin alignment — session-analytics-similarity-embed (E2 slice 1)

Verdict: aligned
Confidence: high

## Origin capture

The work is named by issue #285, itself split from tracker #65 per that
tracker's own rule (one issue = one fully-addressing PR; nothing is
built against #65 directly). #285's scope is E2's first slice from the
#65 §5.4 split: the embedding pipeline only, with E2-similar
(`SIMILAR_TO`, comparison surfaces) explicitly a separate, gated issue.

## Why E2 leads the open set — the evidence trail

The ordering was NOT taken from #65's §5.2 recommendation, which argued
E3 first. It was taken from the 2026-09-02 verification comment on #65,
which re-checked the review's claims against `master` @ `54a34bd` and
found:

- the review's INFERRED claim that nothing writes
  `phase_compliance_score` is WRONG — `judge/kpis.py:37,61` computes
  and writes it today, so E3's proposed "≤100-line first slice"
  already shipped;
- only the pi adapter populates session-level `phase`
  (`adapters/pi.py:150`); for claude-code it is NULL everywhere, so
  E3's remaining work (a process model over phase sequences) is
  design-heavy over pi-only data;
- by the §0-addendum's own test ("if the process-model definition is
  still the expensive part, Tier 3 stands"), E3 stays Tier 3 and E2
  moves first.

E2's groundwork claims all verified: `session_embedding` nullable and
unpopulated, `SIMILAR_TO` unwritten, `compare_approaches` keyword-only
with a docstring naming E2 as its gap.

## Scope authority

The owner approved the bet ("yes" to: post the verification to #65,
open E2-embed, SDD bundle, plan-only PR, plan review before build).
The bundle honours the owner's #65 framing: per-enhancement issue with
its own acceptance criteria before any build; this tracker stays open.

## Decisions taken on this plan's authority (flagged for review)

- **D1 envelope-in-TEXT** (no schema change) over sidecar columns —
  provenance atomic with the vector, one write.
- **D2 resolved-model-or-no-write** — an unattributed vector is
  refused, the same rule the routing arc's FR-E10 settled.
- **D3 skip-different-model** — mixing models silently is the failure
  FR-4 exists to prevent; `--overwrite` is the explicit path.

None widens #285's acceptance criteria; D2 narrows behavior in the
honest direction.

## Correction pass after plan review (PR #286)

The review returned four P1s — contract consistency, not architecture.
The decision set (envelope-in-TEXT, resolved-model-or-no-write,
E2/E2-similar split, capture-before-parser) is unchanged.

1. **FR-1 is now an explicit allowlist** — `copilot_turn.sequence_num |
   role | content_preview`, a strict SUBSET of the judge's selection.
   The first draft said "content_preview and session metadata already
   in the store", which is wrong as a boundary: `project_path` and
   `benchmark_run_dir` are stored but not behind the E8 text-redaction
   boundary. The discriminator now plants markers in both and proves
   the allowlist, not just one raw string's absence.
2. **The zero-vector contradiction is resolved in the strict
   direction.** The plan's test strategy had said an all-zeros vector
   is persisted, while #285 and FR-3 say "never a zero-vector". The
   issue/spec reading wins: FR-9 refuses `[]`, the zero vector, NaN,
   booleans, and dim mismatches each for its own reason — and now
   validates the WHOLE envelope (schema_version, provider,
   embedded_at, model), not only the vector.
3. **The model-identity lifecycle is now an executable order** (FR-6):
   DB state first; no work → zero backend contact INCLUDING the probe;
   existing envelopes never overwritten without `--overwrite`; probe
   only when work exists; `embed()` returns
   `EmbeddingResult{vector, resolved_model}`; validate; one
   replacement write. Three contradictions this fixes: D2's premature
   "Ollama's response carries the model" (now a T3 capture question);
   `skipped_other_model` reporting (an ordinary run has no
   authoritative current identity to classify against — it reports
   `skipped_existing` with the stored-model distribution); D5's
   unconditional startup probe vs zero-call idempotency. Added: the
   overwrite-failure discriminator — a failed re-embed leaves the
   prior envelope intact.
4. **FR-8 states the loader's ACTUAL precedence** (`config.py:8`):
   `defaults.json < ~/.cct/session-analytics.json < repo-root .env <
   real env < CLI`. The first draft dropped the user-JSON layer; T1's
   layering discriminator now includes it.

Also adopted from the review: the T3 live capture uses SYNTHETIC fixed
text, never a real session payload, because the raw request/response
enters the repo.

Still plan-only; no code exists.

## Build outcome (T5 closure)

T1–T5 all landed on PR #286, each through its own review gate; four
review rounds each produced a real correction (FR-8 config discipline,
duplicate-sequence determinism, raw-scalar preservation + the registry
base_url seam). Two capture-driven narrowings deserve permanent note:

- **D2's "backend default model" delegation has nothing to delegate
  to on Ollama** — `model: ""` is a 404 (recorded). The empty-model
  case refuses pre-wire with operator guidance; the packaged default
  stays `""` on FR-8 grounds.
- **The envelope's `model` is a server-confirmed NAME/TAG, not a
  content digest.** Name equality is necessary for comparison, not
  sufficient for model-version equality; digest provenance is
  E2-similar's decision if ever wanted.

The consolidated mutation ledger re-ran whole at the final HEAD:
28/28 caught (`mutation-ledger.md`).

## What this record does NOT claim

- (Historical, from the plan stage:) no code existed at submission;
  the endpoint shape stayed unpinned until T3's capture. Both are now
  superseded by the build outcome above — kept for the record.
- Nothing here closes #65 or #285; that is the owner's decision at
  final PR review.
- No similarity behaviour exists: `SIMILAR_TO` remains unpopulated and
  nothing compares vectors. E2-similar is a separate bet.
