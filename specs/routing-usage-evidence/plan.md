---
spec_mode: lightweight
feature_id: routing-usage-evidence
status: draft
date: 2026-08-31
risk_category: observability
justification: >
  Adds one additive block to the normalized routing result plus a small
  extraction/pricing-read library. Genuine new contract surface, so
  spec_mode=none would under-document it; a full bundle would
  over-document a single observability hole whose contract the owner
  fixed in advance and whose boundary the acceptance audit drew
  precisely. lightweight carries the Requirements and Constraints the
  gates can check, and the decisions below carry the reasoning the code
  cannot state for itself.
origin:
  type: issue
  issue: 273
  parent: 109
  references:
    - "#273 issue body — the usage/cost block contract, the unknown-stays-unknown rule with its five-case table, the acceptance discriminator, and the explicit out-of-scope list"
    - "#109 acceptance criterion C30 — 'Tokens, costs, failed verifier commands, repair cycles, effective endpoint, and effective model are accurately recorded' — the LAST unmet criterion"
    - "specs/routing-context-limit/audit-109-2026-08-31.md at merged commit d7d6694 — the acceptance audit that found 32/33 met and C30 PARTIAL, and that established the remaining gap is routed-attempt token/cost observability specifically"
    - "d7d6694 (merged via PR #274, merge commit 2360705) — the durable record this increment remediates; it deliberately landed BEFORE any implementation"
    - "scripts/session_analytics/cost.py + config.py — the EXISTING pricing contract this reuses: per-1M rates, effective_date as price version, NULL-never-zero for unknown/unpriced"
    - "scripts/benchmark_runner/backends/{claude_code,codex,pi}.py — the recorded parsers that fix the token field aliases by observation rather than assumption"
---

# Plan: routed usage/cost evidence (Increment G of #109)

## Why this exists, and why it is small

The acceptance audit walked all 33 criteria and found exactly one
blocking gap. This increment closes that gap and stops. The issue and
the audit both name what must NOT be folded in; the boundary is
unusually crisp and holding it is part of the deliverable.

## Decisions

**D1 — one price table, read not copied.** Pricing comes from the
existing configured table (`session_analytics/config_data/defaults.json`
`.pricing.models`, overridable per the established config layering).
The routing shell reads it; it does not embed rates, extend the rate
schema, or add a second source of truth. This satisfies the repo rule
against hard-coded structured data and keeps a single pricing contract
for the whole system.

**D2 — the four-state basis is the whole point.** `reported`,
`computed`, `unpriced` and `unavailable` are distinct because collapsing
them is precisely how fabricated precision enters. An explicit, durable
`unpriced`/`unavailable` IS accurate recording when a backend cannot
expose the quantity; what fails C30 is having no contract at all.

**D3 — the cost cap is not a usage source.** The driver's
`.totals.cost_usd` / `.totals.cost_estimated_usd` and the unmetered
estimate path are budget accounting, not observation. Nothing here
reads them. This is the specific "satisfying the criterion by
implication" the audit refused, so it is a named prohibition rather
than an oversight to avoid.

**D4 — aliases are fixed by observation.** The accepted key names come
from the three shipped backend parsers, not from what an API might
plausibly emit. Codex reports `cached_input_tokens` and no USD; Claude
Code reports `total_cost_usd` and `cache_creation_input_tokens`; pi
reports `cache_read_tokens`. Guessing extra aliases would be inventing
contract.

**D5 — `unavailable` means nothing was reported, not "subscription".**
Reconciled after review, because the first wording and the code
disagreed. The rule is about FABRICATION, not about billing model:

- a USD figure the backend itself states on its authoritative result
  event is recorded as `basis=reported`. `reported` asserts only that
  the backend stated it — it makes no claim that the figure is a billed
  marginal cost. Suppressing a number the backend actually reported
  would discard real evidence;
- where nothing is reported and nothing can be computed, the record is
  `unavailable`. Subscription execution with no attributable
  per-request cost is the common case, and it lands there naturally.

A `0.00` is never written for either case: zero would be a false claim
of a free request.

**D6 — schema compatibility follows increment F.** The block is
additive and optional in schema version 1, so pre-G records stay valid;
the runtime boundary requires it on newly produced documents and
refuses an unknown future version rather than reading it optimistically.

## What ships

- `scripts/lib/routing-usage.sh` — token extraction across the observed
  aliases, price-table lookup, and cost-basis resolution. One library so
  the launch chains cannot drift.
- `routing-result.schema.json` + `rr_result` — the additive `usage`
  block, with the runtime invariant extended to require it on new
  records and to enforce basis/price_version consistency.
- `cooldown-supervisor.sh` — the delegate and reconcile sites compose
  from the backend's own result stream; the main site joins the
  driver-published aggregate instead, because what it captures is the
  driver's console output.
- `auto-build-loop.sh` — `publish_routed_usage`, emitting a
  `cct.routed_usage` record from the backend's parsed result envelope
  at the single `run_session` dispatch point.

## Corrections from the contract review

Six P1 findings, each reproduced before being fixed. Together they are
the substance of this increment: the first implementation had every
field in place and still turned unverified evidence into authoritative
accounting.

**D7 — provenance.** Usage is read only from a backend's authoritative
result event, parsed as JSON. The first version byte-grepped the whole
capture, so a `type=assistant` line claiming 777 tokens and $9.99 was
recorded as fact. Any event may *mention* these field names; only one
event *reports* them. An unknown backend has no authoritative event and
therefore yields nothing.

**D8 — complete buckets.** A cost is computed only when every bucket
carrying a NON-ZERO rate is present. The first version zero-filled the
absent ones, so an output-only transcript priced as though input were
zero — understating cost while looking authoritative. Partial token
evidence is still retained; only the cost becomes `unavailable`.

**D9 — validated pricing.** Rates resolve through the existing config
loader, so its deep-merge layering and validation both apply. The first
version picked the first file containing `pricing.models` and read it
with raw jq: a partial override REPLACED the defaults, missing rates
became 0, and the result was labelled USD/computed even for a EUR
table. `ru_rate` takes an optional override path purely so this
layering is behaviourally testable without touching a real HOME.

**D10 — verified identity.** Pricing uses the EFFECTIVE (served) model
only. The first version fell back to the requested model, contradicting
#109's own C13 finding — established in the merged audit — that
requested never proves served. An unverified identity yields
`unavailable`.

**D11 — the wrapper boundary.** The supervisor's main path wraps the
auto-build driver, whose stdout is a console log, not a backend result
stream. Scraping it would find nothing or, worse, match
accounting-shaped log text. The driver now publishes a
`cct.routed_usage` record from its own parsed result envelope, at its
single `run_session` dispatch point, and the supervisor joins that
artifact. Emitted only when the supervisor asks, and ALWAYS one record
per invocation — including EXPLICIT ABSENCE when the envelope carries
no accounting, because a missing record would let a partial sum look
like a complete run total.

**D12 — a strict runtime invariant.** The first version accepted a
non-integer token value, and a `reported` cost carrying a null figure.
The boundary now pins exact key sets, non-negative integer tokens,
`status` matching the presence of evidence in both directions,
non-negative numeric USD, and the full basis/value/version
relationships.

## Corrections from the second review round

The wrapper-boundary fix (D11) introduced six defects of its own, each
reproduced before being fixed. They are recorded because the pattern
matters: adding an evidence CHANNEL created new ways for unverified
data to become authoritative.

**D13 — one stream normalizer, matching the shipped parsers.** The
reader split on newlines only, so an ordinary PRETTY-PRINTED Claude
result — and a JSON-array stream — parsed as nothing, and every value
silently became `unavailable`. `ru_events` now uses the same
slurp-and-flatten normalization the backend parsers established, and
the driver's publisher calls the same reader instead of carrying a
second, divergent parser.

**D14 — the aggregate is a RUN total, conservatively summed.** The
driver appends one record per `run_session`, but the reader took only
the last, reporting one session as though it were the whole run. Tokens
and cost now sum across every published record, and the sum is
conservative: if any invocation is silent about a bucket, the run total
for that bucket is UNKNOWN rather than an understated partial presented
as complete. The publisher emits a record for every invocation
including explicit absence, so a missing record cannot masquerade as a
complete total.

**D15 — publication is backend-specific.** A generic
`result`/`turn.completed` selector dropped pi entirely, whose
authoritative event is `usage`: the published record carried cost and
no tokens. Publication now resolves the event type through the shared
`ru_event_type` mapping.

**D16 — a broken price table is refused, not called `unpriced`.** All
resolver failures were swallowed and returned success-with-empty, so a
mixed-currency configuration was indistinguishable from a valid table
that simply lacks the model. `ru_rate` now separates three outcomes —
valid rate, valid-but-unlisted, and resolver/configuration FAILURE —
and a failure refuses by name (rc 3) rather than being recorded as a
fact about the model. A non-USD rate is refused rather than stored in a
field named `usd`.

**D17 — the invariant is now an actual boundary.** `rr_doc_invariant`
existed, was strict, and was called only by tests: `rr_result`
constructed and returned its document without ever invoking it, so a
malformed block could still be persisted. `rr_result` now builds into a
local, validates, and emits only on success — refusing rather than
degrading to `unavailable`, which would disguise a defect as missing
evidence.

**D18 — the evidence channel is private, and its failures are loud.**
The artifact path was exported into the driver's environment and
therefore inherited by every backend and tool subprocess, any of which
could have written the artifact the supervisor treats as authoritative
driver evidence. The driver now captures it into a non-exported
variable and unsets the exported one before any backend launches.
Publication no longer swallows write errors with `|| true`: a failure
on a REQUESTED channel is an accounting failure, and must stay
distinguishable from a backend that reported nothing.

## Corrections from the third review round

**D19 — failures must propagate through the real chain.** Both refusal
paths returned a status nobody read. `run_session` passed the
publisher's exit code to callers that ignore it, and the driver has no
`set -e`, so a successful session continued with its accounting
silently missing; the supervisor assigned `rr_result`'s output without
checking, so a refusal became an incidental `set -e` exit instead of a
disposition. The driver now `dispose`s `cost_accounting_failed`, and
all three supervisor sites route failure through `rt_refuse` with a new
closed-enum member, `routing_usage_evidence_unresolved` — its own
member because unresolvable evidence is neither a provider-availability
event nor a task failure, and folding it into
`routing_unknown_failure` would hide a broken price table among genuine
provider faults.

**D20 — cardinality is per backend.** Summing every authoritative event
changed direct-backend semantics: two pi `usage` events reported 30/5
where the shipped pi parser keeps the last, 20/3. Only
`driver-aggregate` records are summed; a direct capture selects its
backend-defined terminal event.

**D21 — the legacy untyped Claude result is read.** Parsing the
document was not enough: authoritative filtering still demanded
`type=result`, so the shipped `transcript-openai-shape.json` — which
the existing Claude parser explicitly supports — produced entirely
unavailable usage. A document of exactly ONE object with no `type` key
is now accepted for claude, the same constrained fallback the shipped
parser allows. The constraint matters: anything richer must be typed,
so the fallback cannot readmit the forged-event hole D7 closed.

**D22 — the test seam is a parameter, not ambient state.** The price
override was read from the process environment by production code,
letting an undocumented variable displace price resolution. It is now
an explicit optional argument used only by direct unit tests;
production callers pass nothing.

## Corrections from the fourth review round

**D23 — the evidence channel is isolated by NAMESPACE and LIFETIME,
not by hiding a variable.** Unsetting the exported path (D18) only hid
the name. `RT_DIR` sits inside the backend's own worktree and
`started-N.json` reveals the attempt number before launch, so a
predictable `usage-N.jsonl` there was both discoverable and appendable
by the child. The channel is now an unpredictable path outside that
tree, promoted into the durable location only AFTER the child exits —
and promotion REPLACES rather than merges, so a record forged at the
durable path cannot survive into the evidence either.

**D24 — one diagnostic line must not erase valid usage.** `jq -s`
rejects the entire capture when any line is not JSON, and direct claude
and pi launches merge stderr into the same stream: a single warning
turned a valid pi capture from 20/3 into `unavailable`. That also
contradicted the claim of matching the shipped parsers, which skip
unparseable lines. `ru_events` now falls back to line-wise parsing that
skips bad lines. The authoritative-event requirement still applies
afterwards, so tolerance does not readmit the forgery hole: noise
followed by a `type=assistant` line still yields nothing.

## Corrections from the fifth review round

**D25 — stdout is the usage source; stderr never is.** Skipping
unparseable lines (D24) did not restore provenance, because the streams
were still merged: a VALID JSON diagnostic carrying `type=usage` is
indistinguishable from the backend's own event and, being last,
overrode real evidence — 20/3 became 777/12. Pretty-printed JSON plus
one diagnostic was still lost as well. Claude and pi now redirect
stderr to its own file, as codex already did for the same reason
(#199: an echoed prompt forged a PASS verdict). `$OUT` is stdout-only
and feeds `ru_usage`; classification reads a combined view so no
diagnostic is lost, and that view is tracked and scrubbed like every
other capture.

**D26 — the staging claim is NARROWED, not overstated.** `mktemp`
gives an unpredictable name, not a namespace: the backend inherits
`TMPDIR` and runs as the same user, so it can enumerate and write that
file. What staging actually buys is that the durable `usage-N.jsonl`
does not exist during the run, its name is not in the child's
environment, and promotion REPLACES rather than merges so forged
content at the predictable path is discarded. Defending against a
hostile same-user child would need a capability it cannot name (an
inherited FD closed in backend subprocesses) or a separate
uid/namespace; neither is available here. The code comment, the
assertions and their NAMES now say exactly this — the earlier
"cannot target the artifact" phrasing claimed more than the test
proved.

**D27 — the staged file is tracked, and promotion failure is named.**
`RT_USAGE_TMP` was not registered with `rt_tmp_track`, so an interrupt
between creation and promotion orphaned accounting evidence in /tmp;
and a failed `mv` fell through `set -e` instead of producing the closed
`routing_usage_evidence_unresolved` refusal. Both fixed: tracked the
moment it exists, and promotion failure refuses by name.

## Correction from the sixth review round

**D28 — codex stderr is excluded from CLASSIFICATION, not only from
usage.** Separating the streams (D25) fixed usage provenance and then
reintroduced the very hazard the code comments two lines above it
describe: the combined classification view appended codex stderr
unconditionally, so an echoed prompt could pick a failure class and
therefore the routing action. Reproduced: codex stdout alone
classifies `execution`; the same stdout plus stderr containing the
words "rate limit" classifies `rate_limited`.

`$OUT.all` is now built conditionally — stdout + stderr for claude and
pi, whose stderr carries real provider failures, and stdout ONLY for
codex, whose stderr is still scrubbed and persisted for diagnostics but
never parsed. The `legacy_hit` usage-pattern scan reads the same safe
view rather than bare stdout, so claude and pi stderr evidence is no
longer silently dropped from it either.

The existing codex assertions checked only launch redirection, which
cannot see a later concatenation; the counterfactual added here
compares the two classifications directly.

### A recorded limitation

For pi, the authoritative usage event is `usage`, which carries no USD;
pi's `total_cost_usd` appears on a separate `result` event. G does not
read cost from a different event type than the authoritative one,
because doing so would reopen the provenance hole D7 closed. A pi
invocation therefore publishes tokens with no cost, and the cost
resolves as `computed` or `unavailable` like any other. Joining those
two events is a deliberate non-goal here.

## Test strategy

The acceptance discriminator from #273, as behaviour rather than field
presence:

- a fixture reporting `input=120, output=30, cache_read=50` produces
  exactly those values in the durable result, bound to that attempt;
- pricing configured → cost recomputed from those values with
  `price_version` present;
- pricing absent → `cost_usd` null and `basis=unpriced`, never `0`;
- usage unavailable → tokens null with `status=unavailable`, never
  inferred from budget or cost-cap values;
- a backend reporting USD → `basis=reported`, outranking computation.

Then mutate away the usage propagation and the pricing provenance and
confirm the named C30 tests fail **for that reason** — not via an
incidental crash. Every new assertion is mutation-tested before it is
trusted, and any assertion that survives its mutation is treated as
tautological and fixed.

## Not planned

Nothing beyond the block: no chain test, no #268, no analytics change,
no pricing enhancement, no routing-policy behaviour. If implementation
surfaces something that looks adjacent, it is raised as a separate
finding rather than absorbed.
