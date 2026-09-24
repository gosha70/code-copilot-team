# Owner direction — Session Analytics gaps, slice A3 (#371)

Owner messages in this session, verbatim where quoted.

2026-09-22:

> Ok, based on your summary I would rather work on extending capabilities
> of "Session Analysis" rather using ML Flow. Could you please identified
> ML Flow features which we can add to CCT Session Analysis tooling?

> Can you start planing the addressing the features listed in
> https://github.com/gosha70/code-copilot-team/issues/371?

The green-field ruling, which applies to every slice:

> We can approach with "Session Analysis" as a green field project (I
> still not officially release it); so I am good about not worry about
> the backward compatibility - data migration

Issue #371, row A3, as filed:

> **Feedback** as a general record. Today: `human_label` is a fixed
> nine-boolean rubric per turn, CLI-only, with no free-text field. Build:
> a `feedback` record (session, turn or tool call; name, value,
> rationale, source human/judge/code, supersedes) with a Studio control.
> The rubric becomes one named set.

Success measure for A3 in the issue: "a person can attach a named,
free-text feedback to a turn from the Studio, and it is queryable."

The A3 bundle was written after A2 merged (PR #373, 2026-09-23), as the
owner was told it would be; the owner has not yet approved it.

2026-09-23, the owner's review of the bundle (pasted; corrections
adopted verbatim in substance):

> Not approved as written. D1, D4, D5, and D6 are sound; D2 and D7 need
> correction, and D3 needs stronger invariants.
>
> D2 — do not persist `tool_call_id`. Re-ingest deletes and recreates
> every tool call, so its database ID is unstable [...] Use
> `session_ref`, `sequence_num`, `tool_sequence_num`. [...] Add a test
> proving feedback at all three levels survives re-ingest.
>
> D7 — version 9 yes; recreation no. [...] The DDL machinery already
> applies new tables in place; versions 5–7 explicitly use that
> behavior. [...] Do not manufacture a refusal or recreate the live
> store.
>
> D3 — accept supersession with these invariants: the superseded row
> must be current; it must have the same target and `name`;
> cross-source correction is allowed; a row may be superseded only
> once; enforce `UNIQUE(supersedes)` [...] Test wrong target, wrong
> name, and an attempt to branch an existing supersession.
>
> D4 — accepted [...] The route must derive the server's current
> developer through the existing configured identity precedence, never
> from the request or the session owner. Test a spoofed `source_id`
> cannot affect the stored value.
>
> D5 — accepted, with server-side typing. Rubric names require
> booleans, `rating` requires 1–5, and `note` requires text. Custom
> names may use any one supported type but must be nonblank and
> bounded. Ensure boolean detection precedes numeric detection.
>
> D6 — accepted.
>
> Also pin the detail-payload implementation to one batched feedback
> query for the whole session—no per-turn or per-tool queries.
>
> With those changes, the plan is approved [...] The live store does
> not need another rebuild.

Every evidence claim was checked against the code before the bundle
was revised: `store._delete_children` (store.py:225) deletes and
reinserts tool calls; `check_schema` (db.py:279) refuses only a missing
column from `_REQUIRED_COLUMNS`, so a new table lands in place;
`api.ts:538` addresses tool calls by `sequence_num`; `derive_developer_id`
(identity.py:119) is called only from `cli.py:441` today.
