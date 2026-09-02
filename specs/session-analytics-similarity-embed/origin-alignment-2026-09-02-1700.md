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

## What this record does NOT claim

- No code exists. The bundle is submitted plan-first, before any
  implementation, per the gate discipline this repo uses.
- No live Ollama call has been made. The embeddings endpoint shape is
  deliberately UNPINNED until T3's recorded capture — asserting it
  from memory is the mistake the recorded-capture rule exists to
  prevent.
- Nothing here closes #65 or #285.
