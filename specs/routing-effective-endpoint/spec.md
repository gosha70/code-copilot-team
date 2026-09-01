# Spec: effective upstream endpoint evidence (final C30 gap)

The last unmet component of #109's acceptance criterion C30.

> "Tokens, costs, failed verifier commands, repair cycles, **effective
> endpoint**, and effective model are accurately recorded."

Conjunctive. The closure audit at `2af68f0` (PR #276), re-derived from
merged code, found **5 of 6 met**; the effective endpoint is the sole
remaining component.

## What is already recorded, and why it is not enough

PR #277 populated `upstream_origin` with the **configured launch
origin** — sanitized to scheme/host/port, credentials and path stripped
— and deliberately declined to call it closure:

- a **gateway** URL records the gateway, not the provider behind it,
  while #109 §11 asks for the upstream "**not only a loopback proxy**";
- **codex** records `null` — it resolves through `model_provider` in
  codex configuration, so `ANTHROPIC_BASE_URL` does not route it;
- **login-mode** records `null` — no base URL is wired.

## The governing finding

A survey of the merged tree establishes that **CCT collects no evidence
from which the effective upstream can be derived, for any backend**:

| Source | What it holds | Observed? |
|---|---|---|
| `backends/claude_code.py` | `os.environ["ANTHROPIC_BASE_URL"]` — the variable the harness itself set | no |
| `backends/codex.py` | `config_toml_path`, `provider_id` — configuration keys | no |
| `backends/pi.py` | nothing | — |
| anywhere | HTTP response headers / served-by signal | **not captured** |

CCT shells out to CLI binaries and never sees the HTTP layer. C30 as
written therefore requires a **new observation seam**; it cannot be
satisfied by better use of existing data.

## Requirements

**FR-E1 — the design decision is the first deliverable.** No seam is
built before the choice among the candidates below is made and recorded
with its reasoning. Implementing one and discovering afterwards that it
does not answer the gateway case would repeat, in subtler form, the
"reference == effective endpoint" mistake this arc already made once.

**FR-E2 — never fabricate observability.** Where the effective upstream
cannot be learned for a backend or configuration, the record is `null`
with an explicit reason. A plausible-looking value is worse than an
honest absence, because it reads as evidence.

**FR-E3 — a configured value is never proof of the effective upstream**
when a gateway may sit in between. Neither `endpoint_ref` nor the
configured `upstream_origin` may be relabelled as effective.

**FR-E4 — sanitized evidence only.** Scheme, host, optional port. No
credentials, path, query or fragment, in any new field or journal line.

**FR-E5 — distinguish the two facts.** If both are recorded, the
configured origin and the effective upstream are separate fields with
separate semantics; one must never silently stand in for the other.

**FR-E6 — the amendment is explicit, and is a correction not a
weakening.** The original C30 endpoint wording is SUPERSEDED, with the
reason recorded: it requires information outside CCT's observation
boundary for opaque gateways. The final audit concludes 33/33 against
the AMENDED contract, citing the amendment and the evidence survey that
justifies it. It must never state that the original requirement became
met.

## The decision (owner, 2026-09-01): O1 + O4

**O4 governs; O1 is telemetry completion, not the thing that makes C30
effective.**

**O2 is REJECTED as architecturally insufficient, not merely
expensive.** A proxy between CCT's CLI and `localhost:8787` proves the
CLI connected to `localhost:8787`. It cannot see the *later* hop the
gateway makes to Anthropic, DeepSeek or OpenAI. Making O2 literal would
require CCT to instrument the gateway's outbound connection too, which
for an arbitrary remote gateway is impossible. It is not a general
solution at any price.

**O3 stays opportunistic.** There is no standardized provider-reported
effective-upstream signal across these CLIs. It may become available;
nothing depends on it.

## The amended contract

C30's endpoint component is superseded, because as written it requires
information outside CCT's observation boundary for opaque gateways. It
is replaced by a STRONGER truthfulness contract — not by "configured is
good enough", which would recreate the same semantic mistake under new
wording.

**FR-E7 — configured fact and observed fact are separate fields.**

```text
upstream_origin:         sanitized origin | null
upstream_origin_source:  profile_base_url | profile_base_url_env
                         | codex_model_provider | backend_default | none
effective_upstream:
  origin:   null
  status:   verified | unverifiable
  evidence: provider_reported | none
```

Provenance values are CLOSED and semantically specific. A vague
`configured` would make later audits weaker precisely where they need to
be strong: `codex_model_provider` and `profile_base_url_env` are
different facts with different trust, and an audit must be able to tell
them apart without reading code.

**FR-E8 — provenance is recorded, not implied.** A configured origin
carries *how* CCT learned it:

| Value | Means |
|---|---|
| `profile_base_url` | a registry `base_url` literal |
| `profile_base_url_env` | a registry `base_url_env`, resolved |
| `codex_model_provider` | codex `[model_providers.<id>].base_url` for the provider ACTUALLY selected |
| `backend_default` | a default CCT can positively establish |
| `none` | no origin |

`backend_default` is used ONLY when CCT can actually establish which
default applied. Where it cannot, the value is `none` — an assumed
default is an assumption, and this contract exists to stop assumptions
being recorded as facts.

**FR-E12 — codex provenance follows codex's ACTUAL selection.** The
routing supervisor passes `-c model_provider=<id>` from the routed
profile, and that override decides which provider codex uses. Any
resolution must follow that same selection. Resolution order:

1. the `model_provider` the supervisor passed for THIS attempt;
2. otherwise the config's top-level `model_provider`;
3. otherwise `none`.

**"The first key under `[model_providers]`" is not a valid fallback.**
The existing `_resolve_codex_config` helper uses exactly that
heuristic, and it is arbitrary dict order: with two providers
configured it can attribute provider B's `base_url` to a run codex
routed through provider A. That would be a fabricated fact wearing a
provenance label — the precise failure this increment exists to
prevent — so this feature must not reuse that helper's selection.

**FR-E13 — no raw backend configuration becomes evidence.** Only the
sanitized origin and the closed provenance value are persisted. Never
the config path, credentials, headers, query parameters, or any other
provider configuration.

**FR-E9 — a configured origin is never an observed upstream.** A
configured origin, gateway, proxy, backend default or endpoint
reference must never be represented as an observed effective upstream.
`effective_upstream.status` is `unverifiable` unless authoritative
provider-reported evidence exists, in which case the origin is recorded
separately with `evidence: provider_reported`.

**FR-E10 — codex resolves its configured origin.** From the
`[model_providers.<id>].base_url` of the provider selected per FR-E12,
sanitized by the same rules as #277, recorded with
`upstream_origin_source: codex_model_provider`. This removes an
unnecessary `null` without pretending it identifies the server that
ultimately handled inference — it improves `upstream_origin` ONLY, and
never touches `effective_upstream`.

**FR-E11 — login mode is explicit.** Where CCT knows only a backend
default, either record it as `backend_default` or leave the origin
null. Either way `effective_upstream.status` stays `unverifiable`.

## Constraints

- **Narrow by construction.** Only the endpoint component of C30. No
  routing-policy change, no #268, no three-backend chain.
- **Reuse the existing plumbing.** `upstream_origin`, its sanitizer and
  the three `rr_result` call sites already exist; a second parallel
  path would be a defect, not a feature.
- **Sanitizer parity.** Any new value passes the same origin-only
  sanitization, including the http(s) restriction added in #277.
- **Backward compatible.** A profile for which nothing new can be
  learned must behave exactly as it does today.

## Non-goals

- Inferring an endpoint from timing, DNS, or network observation
  outside a seam explicitly chosen under FR-E1.
- Making #109 close. Only the re-audit can do that, and only if the
  endpoint component is genuinely met — or genuinely amended under
  FR-E6.
