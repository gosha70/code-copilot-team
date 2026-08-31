# Spec: routed usage/cost evidence (Increment G of #109)

Increment G closes the **last** unmet #109 acceptance criterion, and
nothing else.

**C30** — "Tokens, costs, failed verifier commands, repair cycles,
effective endpoint, and effective model are accurately recorded" — is
conjunctive. The acceptance audit at `d7d6694` found four of six
recorded on the routed path and **tokens and costs absent entirely**:
there is no usage or accounting contract on a routed attempt to be
accurate or inaccurate.

## Requirements

**FR-G1 — a usage block on every new routed result.** Each newly
produced routed attempt carries:

```text
usage:
  tokens: { input, output, cache_read, cache_write,
            status: reported | unavailable }
  cost:   { usd, basis: reported | computed | unpriced | unavailable,
            price_version }
```

**FR-G2 — unknown stays unknown.** No token count is invented and no
USD is claimed because a cost cap or estimate exists. A quantity the
backend cannot expose is recorded as `null` with an explicit status or
basis — never omitted, never zero, never inferred.

**FR-G3 — tokens are read from the attempt's own transcript.**
Extraction tolerates the field-name variants the three shipped backends
actually emit (see Constraints), and is grounded in the recorded
parsers rather than invented.

**FR-G4 — cost precedence, most authoritative first.**

| Basis | When |
|---|---|
| `reported` | the backend states a USD figure for this attempt |
| `computed` | tokens are known AND the configured price table prices this model |
| `unpriced` | the model is known but has no price entry |
| `unavailable` | no tokens and no reported cost — nothing to price |

`price_version` is non-null exactly for `computed` (the rate's
`effective_date`) and may be non-null for `reported` when the backend
supplies one.

**FR-G5 — never zero for unknown.** An unpriced or unavailable cost is
`null`. Zero means a genuine zero, never absence.

**FR-G6 — bound to the attempt.** The usage block belongs to the
attempt/profile/effective-identity it was observed from, exactly as
increment F's observations are.

**FR-G7 — one price table.** Pricing is read from the existing
configured table, never a second copy embedded in the routing shell.

**FR-G8 — provenance.** Usage is read ONLY from the backend's
authoritative result event, parsed as JSON: `result` (claude-code),
`turn.completed` (codex), `usage` (pi), `cct.routed_usage` (the
driver-published aggregate). An unknown backend yields nothing. A
non-authoritative event may mention these field names; it never
reports them.

**FR-G9 — complete buckets.** A cost is computed only when every token
bucket carrying a non-zero rate is present in the evidence. Otherwise
the cost is `unavailable` while the partial token evidence is
retained. Absent buckets are never zero-filled.

**FR-G10 — validated pricing.** Rates resolve through the existing
config loader, with its documented deep-merge layering and its
validation (required rates, single-currency table). A partial override
merges over the defaults; a table that mixes currencies or omits a
required rate is refused, never silently defaulted to zero.

**FR-G11 — verified identity.** Pricing uses the EFFECTIVE (served)
model only. A requested model never proves what served the request, so
an unverified identity yields `unavailable`.

**FR-G13 — stdout is the only usage source.** Usage is read from the
backend's STDOUT stream. Stderr may contain well-formed JSON — echoed
prompts, diagnostics — that is indistinguishable from an authoritative
event once merged, so it never feeds usage. A combined view remains
available for failure classification.

**FR-G14 — staging, and its stated limit.** The evidence file is
staged outside the durable location and promoted by REPLACEMENT after
the child exits, so the durable artifact does not exist during the run
and forged content at that path cannot survive. This is NOT a security
boundary against a hostile same-user child, which inherits `TMPDIR`
and can write the staged file; that would require a capability the
child cannot name or a separate uid/namespace.

**FR-G12 — the wrapper boundary.** Where the supervisor wraps the
auto-build driver, the captured stream is a console log and not a
backend result stream. Usage there is joined from an aggregate the
driver publishes from its own parsed result envelope. Accounting-shaped
log text is never evidence.

## Constraints

- **Reuse, do not duplicate, the pricing contract.** Semantics already
  exist and are correct: per-1M rates, `effective_date` as the price
  version, NULL (never 0) for unknown/unpriced. G reads the same
  configured table; it does not add a pricing engine, extend the rate
  schema, or change analytics.
- **Backend field aliases are fixed by observation**, taken from the
  shipped parsers:

  | Field | Accepted keys |
  |---|---|
  | input | `input_tokens`, `prompt_tokens`, `tokens_input` |
  | output | `output_tokens`, `completion_tokens`, `tokens_output` |
  | cache_read | `cache_read_input_tokens`, `cache_read_tokens`, `cached_input_tokens` |
  | cache_write | `cache_creation_input_tokens`, `cache_creation_tokens`, `cache_write_input_tokens` |
  | cost | `total_cost_usd` |

- **Schema compatibility, as increment F established it.** The usage
  block is additive and optional in schema version 1 so pre-G records
  stay valid; completeness is enforced at the runtime boundary that
  only sees newly produced documents. An unknown future version is
  refused, never read as today's shape.
- **Backward compatible by construction.** A backend that reports
  nothing, and a configuration with no price table, must both produce a
  well-formed record rather than a failure.

## Non-goals

Explicitly out of scope, per the issue and the audit:

- the Claude Code → DeepSeek → Codex chain (no #109 criterion requires
  it — established by the audit at `d7d6694`);
- #268 (pytest collecting polyglot fixture stubs);
- generalized session-analytics work, or any change to how analytics
  ingests or computes;
- provider-pricing enhancements: no new rates, no rate-schema change,
  no pricing UI;
- any further routing-policy behaviour.
