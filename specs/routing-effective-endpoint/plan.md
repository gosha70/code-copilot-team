---
spec_mode: lightweight
feature_id: routing-effective-endpoint
status: draft
date: 2026-09-01
risk_category: observability
justification: >
  The deliverable that matters here is a DESIGN DECISION about an
  observation seam that does not yet exist, not a code change of known
  shape. spec_mode=none would leave that decision undocumented, and a
  full bundle would over-specify an implementation nobody has chosen
  yet. lightweight carries the Requirements and Constraints the gates
  can check, and the evaluation below carries the reasoning — which is
  the actual work product until a seam is picked.
origin:
  type: issue
  issue: 273
  parent: 109
  references:
    - "#273 (rewritten 2026-09-01) — retargeted from routed usage/cost evidence to the effective upstream endpoint after the closure audit moved the boundary; the original text is preserved in a details block on the issue"
    - "#109 acceptance criterion C30 — the effective endpoint is the last of its six components"
    - "#109 §11 telemetry — 'Sanitized upstream endpoint — not only a loopback proxy', the clause a configured gateway URL does not satisfy"
    - "specs/routing-usage-evidence/audit-109-closure-2026-08-31.md at merged 2af68f0 (PR #276) — re-derived C30 from merged code, found 5/6, and WITHDREW the earlier verdict that counted the endpoint as met"
    - "PR #277 (merged 0a9ba3a) — recorded the CONFIGURED launch origin and explicitly declined closure for gatewayed, codex and login-mode profiles"
    - "scripts/benchmark_runner/backends/claude_code.py:147 — provider_endpoint is os.environ.get('ANTHROPIC_BASE_URL'), the variable the harness itself set: configured, not observed"
    - "scripts/benchmark_runner/backends/codex.py:204-221 — _resolve_codex_config returns a config path and a provider KEY, never a resolved endpoint"
---

# Plan: effective upstream endpoint evidence (final C30 gap)

## The work product is a decision

This increment does not begin with code. The survey below establishes
that no seam exists; choosing one is the deliverable, and building it
is the follow-on. Picking a seam before that choice is recorded is the
specific failure mode this plan exists to prevent — the arc already
recorded a *reference* as an *effective endpoint* once, and the subtler
version of that mistake is to build a seam that still cannot see past a
gateway and call C30 closed.

## What was surveyed, and what it establishes

Every place CCT could learn an endpoint from, at merged `f07b062`:

| Source | Holds | Effective? |
|---|---|---|
| `rt_launch_env` / `upstream_origin` (#277) | the resolved base URL CCT itself wired | no — configured |
| `backends/claude_code.py:147` | `os.environ["ANTHROPIC_BASE_URL"]` | no — the same variable, read back |
| `backends/codex.py:204` | `config_toml_path` + `provider_id` | no — configuration keys |
| `backends/pi.py` | nothing | — |
| recorded fixtures (claude / codex / pi) | no endpoint, host or served-by field | — |
| anywhere in the tree | HTTP response headers | **never captured** |

CCT executes CLI binaries and does not sit on the HTTP path. Nothing it
currently records distinguishes "the host I pointed the backend at"
from "the host that answered". That distinction *is* C30's endpoint
component.

## Options

**O1 — resolve codex's configured endpoint.**
Read `[model_providers.<id>].base_url` from codex configuration, so
codex stops recording `null`.
*Buys:* removes one `null`; small; reuses the existing sanitizer.
*Does not buy:* still configured. A codex provider pointing at a
gateway is recorded as the gateway. Does not satisfy §11.
*Honest framing:* an improvement to the CONFIGURED record, not the
effective one.

**O2 — egress observation through a CCT-owned recording proxy.**
Backends are pointed at a local proxy CCT runs; it observes the real
upstream connection and reports it.
*Buys:* ~~the only option that genuinely answers the gateway case~~
**SUPERSEDED — this first-draft claim is false.** See "The decision"
below: the proxy sees only the first hop, so it does not answer the
gateway case at all.
*Costs:* changes the execution path for every routed attempt; adds a
process to the failure surface; interacts with credentials in flight;
substantial for one telemetry field. Would need its own risk review.

**O3 — provider-reported identity.**
Capture a served-by signal if a backend or gateway emits one.
*Blocked on evidence:* no recorded fixture contains such a field, and
CCT does not read response headers. Cannot be costed until someone
shows the signal exists.

**O4 — amend the criterion.**
Accept the configured origin plus an explicit unverified marker as
satisfying C30, recorded as a deliberate narrowing of §11.
*Buys:* closes #109 honestly, ~~at the cost of a weaker criterion~~
**SUPERSEDED — this first-draft framing is wrong.** See "The decision"
below: the amended contract is STRICTER, not weaker, because it adds a
verification state a configured value can never satisfy.
*Requires:* the amendment stated in the audit, not implied.

## The decision (owner, 2026-09-01)

**O1 + O4. O4 governs; O1 is telemetry completion.**

**O2 is rejected as ARCHITECTURALLY INSUFFICIENT, not merely
disproportionate** — a correction to this plan's first draft, which
called it "the only option that genuinely answers the gateway case".
It is not. A proxy between CCT's CLI and `localhost:8787` proves the
CLI connected to `localhost:8787`; it cannot see the later hop the
gateway makes to Anthropic, DeepSeek or OpenAI. Making it literal would
require instrumenting the gateway's outbound connection, which for an
arbitrary remote gateway is impossible. So O2 fails on generality
first, and cost second — and building it would have added credential
and networking risk in exchange for a guarantee it could not give.

**O3 stays opportunistic.** No standardized provider-reported
effective-upstream signal exists across these CLIs; the same gap is
visible upstream, where `codex exec --json` does not expose a
provider-reported served-model identity either. Nothing here depends on
O3, and it may become available later.

**O4 is not "configured is good enough."** That framing would recreate
the exact semantic mistake the audits caught, in new wording. The
amendment replaces an unimplementable observation requirement with a
stronger TRUTHFULNESS contract: record the configured origin *with its
provenance*, and carry an explicit effective-upstream verification
state that is never satisfied by a configured value.

## What this is, honestly

A spec-modeling defect, not a missing feature. The original wording —
"sanitized upstream endpoint, not only a loopback proxy" — *encouraged*
the overclaim the audits later caught, because it asked for something
the architecture cannot observe and offered no way to say so. The fix
is to correct the model, not to build infrastructure that pretends the
model was right.

## What ships

1. **Amend #109 first.** C30's endpoint component and the §11 phrasing
   are superseded, with the original preserved and the reason recorded.
   No code lands before the contract it satisfies exists.
2. **`upstream_origin_source`** — provenance for the configured origin.
   The vocabulary is CLOSED and is defined once, in **FR-E7/FR-E8**;
   this plan does not restate or alias it. No synonym — `explicit_config`,
   `backend_config`, a generic `configured` — may appear in code, tests
   or journals.
3. **`effective_upstream`** — `{origin, status, evidence}`, a closed
   two-state machine defined in **FR-E7**. Every path that exists today
   is the `unverifiable` state, since no authoritative provider-reported
   signal exists.
4. **Codex configured-origin resolution** — the selected
   `[model_providers.<id>].base_url`, through #277's sanitizer, recorded
   with the provenance FR-E8 assigns it (see FR-E10/FR-E12). Removes a
   `null` without claiming it identifies the inference server.
5. Schema and runtime-boundary updates for the new fields.

## The riskiest implementation detail

Codex's provider selection. The supervisor passes
`-c model_provider=<id>` from the routed profile
(`cooldown-supervisor.sh:1498, 1915`), and that override decides which
provider codex uses. The existing `_resolve_codex_config` helper
instead takes **the first key under `[model_providers]`** — arbitrary
dict order. With two providers configured it can attribute provider
B's `base_url` to a run routed through provider A.

That would be a fabricated fact wearing a provenance label, which is
worse than the `null` it replaces. So this feature resolves from the
launch-time selection, never from that helper's heuristic, and records
`none` when the selection cannot be determined.

## Test strategy

The load-bearing rule is **configured is not observed**, and it is
mutation-pinned:

- a configured origin — whatever its FR-E8 provenance — never produces
  `effective_upstream.status: verified`;
- relabelling the configured origin into `effective_upstream.origin`
  fails a named test;
- codex resolves its configured origin with the FR-E8 provenance for
  codex (FR-E10), and that does NOT flip the verification state;
- login mode records `upstream_origin = null` and
  `upstream_origin_source = none` — never a fabricated origin, and
  never an assumed default — and stays `unverifiable` (FR-E11);
- the codex-resolved value passes the same sanitizer: credentials,
  path, query and fragment stripped, http(s) only;
- the `effective_upstream` state machine is closed: the four
  off-contract combinations named below are each refused.

Two properties hold regardless of seam: an unlearnable endpoint records
null with a reason and a test proves the null; and the configured and
effective facts stay distinct fields with a discriminator that fails if
one is relabelled as the other — the exact mistake the first audit made
in prose.

### Named mutations, each of which MUST fail

```text
configured origin copied into effective_upstream.origin
    -> fails the configured != observed discriminator

codex provider A selected, provider B base_url persisted
    -> fails the selection-fidelity discriminator

credential / path / query survives configured-origin sanitization
    -> fails

provenance removed, or collapsed to a generic "configured"
    -> fails the provenance contract

backend_default recorded where the default cannot be established
    -> fails (the value must be `none`, not an assumption)
```

The `effective_upstream` state machine is closed by FR-E7, so each
off-contract combination gets its own named mutation. All four must
fail, and each for a DIFFERENT reason — a single "shape is wrong" check
that catches all of them proves only that something is validated, not
that the two states are discriminated:

```text
E7-M1  status=verified, origin=null
    -> fails: verified asserts an origin was learned

E7-M2  status=verified, evidence=none
    -> fails: verified without provider-reported evidence is the
       overclaim this whole contract exists to prevent

E7-M3  status=unverifiable, origin=<non-null>
    -> fails: an unverified origin in the observed field is exactly the
       relabelling FR-E3 forbids

E7-M4  status=unverifiable, evidence=provider_reported
    -> fails: authoritative evidence and an unverifiable verdict cannot
       coexist
```

Each is run with `__pycache__` cleared and checked for `ERROR:` as well
as `FAIL:`, both of which have previously masked a non-discriminating
mutation in this arc.

## Not planned

#268, the three-backend chain, any routing-policy change, and any
inference of the endpoint from timing, DNS or other side channels
outside a seam chosen under FR-E1.
