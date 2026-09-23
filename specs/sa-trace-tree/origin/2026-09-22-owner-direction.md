# Owner direction — Session Analytics gaps, slice A1 (#371)

Owner messages in this session, verbatim where quoted, 2026-09-22.

Asked whether CCT should adopt MLflow to trace and observe its actions;
after the assessment:

> Ok, based on your summary I would rather work on extending capabilities
> of "Session Analysis" rather using ML Flow. Could you please identified
> ML Flow features which we can add to CCT Session Analysis tooling?

Then:

> Can you file the feature issue to https://github.com/gosha70/code-copilot-team?

which became #371, and:

> Can you start planing the addressing the features listed in
> https://github.com/gosha70/code-copilot-team/issues/371?

Issue #371, row A1, as filed:

> **Trace tree** on the session page. Today: the Timeline is a flat list
> of turns with a boolean "tools" chip. Tool calls, tool results, file
> accesses and subagent (sidechain) turns are ingested but never served.
> Build: show tool calls with results and durations under each turn;
> nest sidechain turns under their parent. A view over existing rows.

Issue constraints: no new dependency, no new store, no change to the
privacy rules; each slice one PR under #371. Success measure for A1: "a
session page shows every tool call with its result and duration, and
subagent runs nested, for a session that has them."

On the first plan's proposal to leave per-tool durations out because they
need a schema change, the owner ruled:

> We can approach with "Session Analysis" as a green field project (I
> still not officially release it); so I am good about not worry about
> the backward compatibility - data migration

So schema changes are allowed in Session Analytics slices, an existing
store may be recreated rather than migrated, and A1 delivers the
durations the issue asked for (plan.md D2).
