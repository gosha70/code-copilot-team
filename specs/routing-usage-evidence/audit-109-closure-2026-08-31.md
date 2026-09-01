# Closure audit — #109 / #273 (C30)

- **Date:** 2026-08-31
- **Audited at:** merged `master` @ `f17c0e2` (PR #275, increment G)
- **Prior audit:** `specs/routing-context-limit/audit-109-2026-08-31.md`
  at `d7d6694` — 32/33 met, C30 PARTIAL and blocking
- **Method:** C30 re-derived from MERGED CODE and executed evidence,
  not from PR claims. The other 32 confirmed against the prior audit
  plus the bounded post-audit diff and the gates.
- **Scope exclusions (as directed):** #268 and the three-backend chain
  are out of scope; the prior audit established neither is a #109
  acceptance criterion.

## Verdict

**#109 is NOT 33/33. C30 remains PARTIAL, so neither #109 nor #273
may be marked complete.**

Five of C30's six components are met. **The effective endpoint is not
recorded anywhere** — the field designed to carry it is present,
documented, and always null.

This audit also **corrects the prior audit**, which counted the
endpoint as met. That was wrong, and inheriting it is exactly the
failure this pass existed to prevent.

## C30, component by component

> "Tokens, costs, failed verifier commands, repair cycles, effective
> endpoint, and effective model are accurately recorded."

Conjunctive: all six must hold.

| # | Component | Verdict | Evidence |
|---|---|---|---|
| 1 | tokens | **met** | executed below |
| 2 | costs | **met** | executed below |
| 3 | failed verifier commands | **met** | `cooldown-supervisor.sh:1092`, durable at `$RT_DIR/verifiers-<round>.txt` |
| 4 | repair cycles | **met** | `rounds` in `packet-outcome.json` and the provisional record (`:1167`) |
| 5 | effective endpoint | **NOT MET** | `upstream_origin` is null in every routed result |
| 6 | effective model | **met** | tri-state, journaled UNVERIFIED, mismatch refuses |

### 1 — tokens: met

A result composed from merged code:

```json
{"tokens":{"input":120,"output":30,"cache_read":50,"cache_write":0,
           "status":"reported"}}
```

Provenance holds: only a backend's authoritative event is read, from
stdout only. Aggregation is per backend — the driver aggregate sums
every published record, a direct capture takes its terminal event — and
one silent invocation makes the run total unknown rather than an
understated partial.

### 2 — costs: met

```json
{"cost":{"usd":0.4213,"basis":"reported","price_version":null}}
```

**On pi specifically**, which the directive singles out. pi's *defined
transcript contract* (`backends/pi.py:18-23`) is `result` /`usage` /
`tool`, and **carries no `total_cost_usd` at any point**. So a real pi
attempt reports no USD, and `basis=unavailable` is:

- **explicit** — a named basis, persisted, never an omitted field;
- **accurate** — nothing was reported and nothing can be computed;
- **never fabricated** — `usd` is null, not `0`.

Met.

An honest note on how this audit reached that: an earlier probe here
used a synthetic pi fixture carrying `total_cost_usd`, which made
`unavailable` look like a mislabel. That fixture invented a shape pi
does not produce. Checking pi's actual contract removed the finding —
recorded because the near-miss is the same class of error the audit
exists to catch.

**Consequence worth stating:** pi's contract has no cache-write field,
so for any model priced with a non-zero `cache_write` rate the
complete-bucket rule (FR-G9) means pi cost is in practice always
`unavailable`. That is conservative and correct — it never fabricates —
but it means pi will not produce `computed` costs. Not a defect
against C30; a real limit on what the record can say.

### 5 — effective endpoint: NOT MET

`upstream_origin` exists in the schema and is documented as "sanitized
upstream endpoint identity (host…)". **Nothing in production ever
supplies it.**

- The only producer is `rr_result`'s 9th parameter
  (`routing-result.sh:265`).
- All three supervisor call sites pass `-`, which becomes null.
- Executed against the real call pattern: `{"upstream_origin":null}`.
- A repo-wide search finds no other writer.

What IS durably recorded is the endpoint **reference**, not the
resolved host:

- `rt_launch_env` (`:483-498`) resolves `base_url` / `base_url_env` into
  the child environment, then journals **names only** —
  `wired ANTHROPIC_BASE_URL(env:CCT_LOCAL_URL)`. That is deliberate
  credential hygiene, and it means the journal records the variable
  name, never the host.
- `endpoint_ref` in the profile tuple persists as `urlenv:VAR` — again
  a reference.

So for two profiles pointing the same variable at different servers,
nothing durable distinguishes which one served the attempt. #109 §11
asks for a "sanitized upstream endpoint — **not only a loopback
proxy**", which is explicitly a request for the resolved identity; a
variable name is less than that.

**The prior audit recorded this component as met, citing
"`endpoint_ref` resolved and journaled".** Journaling the reference is
not recording the effective endpoint. That verdict is withdrawn here.

Increment G sharpened rather than caused this: with tokens, costs,
verifier failures, repair cycles and effective model now in the durable
result, the endpoint's dedicated field is the one that stayed null.

## The other 32 criteria

The post-audit diff (`d7d6694..f17c0e2`) touches seven production
paths: `routing-usage.sh` (new), `routing-result.sh`,
`routing-actions.sh`, `cooldown-supervisor.sh`, `auto-build-loop.sh`,
the result schema, and `README.md`. The `routing-actions.sh` change is
a single additive closed-enum member.

Gates re-run on the audit branch:

| Suite | Result |
|---|---|
| routing config / failover / tasks / packet / delegation / recovery | 274 · 227 · 160 · 99 · 180 · 375 — 0 failed |
| `test-cooldown-supervisor.sh` | 67 / 0 |
| `test-shared-structure.sh` | 812 / 0 |

No regression against the prior audit's findings for criteria 1–29 and
31–33; the areas G touched are precisely those the routing suites
cover, and they pass at their pins.

## Evidence limitations

Stated as limitations, not failures:

- **No live backend was invoked**, here or in increment G. Every
  provenance guarantee is proven deterministically and by mutation at
  library level. Token aliases and event shapes come from the shipped
  parsers and recorded fixtures.
- No routed run has been observed against a real provider, so the
  end-to-end join from a live backend's own output to a durable record
  is unproven by execution.
- Criteria 15–21 rest on the #254 audit plus spot re-probes, not a
  fresh line-by-line re-walk.

## What would close C30

One narrow change, not a new increment: populate `upstream_origin` with
the sanitized resolved host at the point `rt_launch_env` already
resolves it, and pass it through the existing 9th parameter — the
field, the schema and the plumbing all exist. Sanitization is already
specified ("host, never credentials or full URLs with tokens").

This audit deliberately does **not** make that change; it is
audit-only.

## Disposition

- **#109 stays OPEN** — 32 of 33, C30 blocking.
- **#273 stays OPEN** — it was opened to close C30, and C30 is not
  closed.
- Not in scope and not blocking: #268, the three-backend chain.
