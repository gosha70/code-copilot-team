# Origin alignment — routing-effective-endpoint (final C30 gap)

Verdict: aligned
Confidence: high

## Origin capture

The work is named by #109's acceptance criterion C30, whose sixth
component — "effective endpoint … accurately recorded" — is the last
unmet one, and by §11's stronger phrasing: "Sanitized upstream endpoint
— **not only a loopback proxy**."

The scoping evidence is
`specs/routing-usage-evidence/audit-109-closure-2026-08-31.md`, merged
as `2af68f0` in PR #276. That audit re-derived C30 from merged code
after Increment G, found 5 of 6 met, and **withdrew the earlier verdict
that counted the endpoint as met** — the first audit had cited
"`endpoint_ref` resolved and journaled", and journaling a reference is
not recording the endpoint.

PR #277 (merged `0a9ba3a`) then recorded the CONFIGURED launch origin
and explicitly declined closure for gatewayed, codex and login-mode
profiles.

## Issue provenance, stated because the target moved

#273 was **rewritten on 2026-09-01**. It originally scoped routed
usage/cost evidence; that work landed in PR #275, and the closure audit
moved the remaining boundary to the endpoint. The rewrite preserves the
original text in a details block on the issue so the change of target
is auditable rather than silent. This plan implements the rewritten
issue.

## The finding this record exists to carry

Before any design was proposed, the merged tree was surveyed for
anything from which the effective upstream could be derived. Nothing
qualifies:

- `backends/claude_code.py:147` reads `provider_endpoint` from
  `os.environ["ANTHROPIC_BASE_URL"]` — the variable the harness itself
  set. That is the same configured value #277 already declined to call
  effective, read back from the environment.
- `backends/codex.py:204-221` returns a config path and a provider
  KEY, never a resolved endpoint.
- `backends/pi.py` records no endpoint.
- No recorded fixture carries an endpoint, host or served-by field, and
  nothing in the tree captures HTTP response headers. CCT shells out to
  CLI binaries and never sees the HTTP layer.

**C30 as written therefore requires a new observation seam.** It cannot
be satisfied by better use of the data CCT already collects. Surfacing
that during design — rather than discovering it after building
something — is the explicit instruction this increment was given, and
it is why the plan's first deliverable is a decision rather than code.

## Scope authority

The owner directed: rewrite #273 to the effective-endpoint contract
first; branch from post-#279 master; build the bundle against the
merged #276 audit and the #277 limitation rather than the earlier
August 31 audit; keep the scope extremely narrow; refuse `endpoint_ref`
and the configured `upstream_origin` as proof where a gateway
intervenes; and **not fabricate observability** for codex, login mode
or gateways — surfacing an absent seam instead.

## The decision, and the amendment it produced

The owner chose **O1 + O4**, with O4 governing and O1 as telemetry
completion rather than the thing that makes C30 effective.

**O2 was rejected as architecturally insufficient**, correcting this
plan's first draft, which had called it "the only option that genuinely
answers the gateway case". It is not: a proxy between CCT's CLI and a
gateway proves only that the CLI reached the gateway, never the later
hop to the provider, and for an arbitrary remote gateway that hop
cannot be instrumented at all. It fails on generality before cost.

**#109 was amended BEFORE any implementation**, per the owner's
sequencing. C30's endpoint component and the §11 clause "sanitized
upstream endpoint — not only a loopback proxy" are struck through and
superseded, with the originals preserved and the reason recorded. The
criteria count is unchanged at 33.

The amendment is a CORRECTION, not a weakening: it replaces an
unimplementable observation requirement with a stricter truthfulness
contract — configured origin *with provenance*, plus an explicit
effective-upstream verification state that a configured value can never
satisfy. The owner's framing is recorded verbatim in the spec: "do not
weaken C30 to simply say configured endpoint is good enough — that
would recreate the same semantic mistake under new wording."

## A hazard found while grounding the design

The plan initially proposed reusing `_resolve_codex_config` for O1.
Reading it first showed that it selects **the first key under
`[model_providers]`** — arbitrary dict order — while the routing
supervisor actually passes `-c model_provider=<id>` from the routed
profile (`cooldown-supervisor.sh:1498, 1915`), and nothing in the tree
reads the config's top-level `model_provider` at all.

Reusing that helper would therefore have attributed one provider's
`base_url` to a run codex routed through another: a fabricated fact
wearing a provenance label, which is worse than the `null` it replaces.
FR-E12 now fixes the resolution order and forbids the heuristic.

## Deviation from the parent

The parent criterion itself is amended (T1), which is the deviation —
taken on the owner's explicit instruction, recorded on #109 rather than
only here, and required by FR-E6 to be cited in the final audit. No
deviation is taken on this plan's own authority.

## Correction pass after plan review (PR #280)

The owner reviewed the bundle before implementation and returned two
contract P1s. Both were documentation defects in this bundle, not
changes of direction — the decision (O1 + O4, O4 governing) and the
#109 amendment are untouched.

1. **One provenance vocabulary.** `plan.md` had carried the first
   draft's `explicit_config` / `backend_config` aliases beside
   `spec.md`'s closed set, and its test strategy allowed login mode to
   record "`backend_default` or null" where FR-E8 requires an
   *establishable* default. `spec.md` is now the single definition;
   `plan.md` and `tasks.md` reference FR-E7/E8 instead of restating it,
   the aliases are named as prohibited, and FR-E11 is corrected to
   `upstream_origin: null` / `upstream_origin_source: none` for login
   mode — matching what T3 already required.

2. **`effective_upstream` is a closed state machine.** It had been
   described as three fields with independent vocabularies, with
   `origin` typed as always `null`. FR-E7 now states exactly two valid
   states, requires the four off-contract combinations to be refused,
   and types `origin` as *sanitized origin | null* so a future
   provider-reported signal populates the contract rather than changing
   it. Mutations E7-M1…E7-M4 must each fail for a distinct reason.

FR-E12 step 2 additionally gained its missing precondition: the
top-level `model_provider` fallback applies only when **no launch
override was issued**. An override naming a provider absent from
`[model_providers]` resolves to `none` — falling back would record the
provider codex did not use, which is the same fabrication FR-E12
exists to prevent.

Still no production code at this point; the bundle remains plan-only.

## The O1 withdrawal (T4 review, 2026-09-01)

The hazard this record was created to carry — that
`_resolve_codex_config` picks the FIRST key under `[model_providers]`
— turned out to be the smaller of two problems with reading codex
configuration.

The larger one: `${CODEX_HOME:-$HOME/.codex}/config.toml` is not
codex's configuration, it is one LAYER of it. Verified from the shipped
codex-cli 0.147.0 — `--profile` layers `$CODEX_HOME/<name>.config.toml`
on top of the base user config, and `--ignore-user-config` excludes the
base file entirely. Reading that layer could record `base_url` X while
codex resolved the same selected provider to Y.

**O1 is therefore WITHDRAWN, and FR-E10 amended**: codex records
`null` / `none`. This is a narrowing of what the increment SHIPS, not
of what it CLAIMS — the amended C30 asks for accurate recording, and an
honest `null` is accurate where a plausible endpoint would not be. O4,
which governs, is unaffected; O1 was recorded from the start as
telemetry completion rather than as the thing that makes C30 truthful.

The deviation is taken on the owner's explicit instruction, after they
identified the layering. It is recorded here and in the amended FR-E10
rather than only in a commit message, and the T5 audit must cite it:
the audit must state that codex's endpoint is recorded as unestablished
— never that it was resolved.

## Bundle consistency pass after the withdrawal

The withdrawal was recorded correctly in FR-E10 and in T4's status, but
`plan.md` and `tasks.md` still carried the PRE-withdrawal T4
requirements as though active — "the launch override decides which
provider codex uses", "this feature resolves from the launch-time
selection", "Done when provider A's origin is recorded". A reader would
have found two contradictory stories with no marker saying which
governs.

Those are rewritten to the single governing one: **T4 investigated
codex configured-origin resolution, proved CCT cannot establish it from
one configuration layer, withdrew the resolver, and mutation-pins
`null` / `none` against plausible-but-unproven configuration values.**
FR-E12 is marked DORMANT rather than deleted — it binds whatever one
day implements a resolution, and governs nothing that ships.

The amendment dates also read 2026-09-02. The work and its commits
happened on 2026-09-01, matching this plan's frontmatter; corrected.

Docs only. No production behaviour changed in this pass.

## What this record does NOT claim

- No code has been written. The survey is a read of the merged tree at
  `f07b062`; no seam has been built, chosen, or prototyped.
- No live backend was invoked. The conclusion that no served-by signal
  exists rests on the shipped parsers and recorded fixtures, not on a
  live capture — a live run against a gateway could in principle reveal
  a signal none of the fixtures contain, which is exactly why option O3
  is marked "blocked on evidence" rather than rejected.
- Nothing here makes #109 closable. Only the re-audit can, and only
  against the AMENDED contract — the audit must never state that the
  original requirement became met.
- No production code has been written at the time of this record. This
  bundle is submitted for plan review first, deliberately, because a
  subtle schema mistake here would become another "configured ==
  observed" overclaim encoded in runtime artifacts.
