# Owner direction — Session Analytics gaps, slice A2 (#371)

Owner messages in this session, verbatim where quoted.

2026-09-22, after the MLflow assessment:

> Ok, based on your summary I would rather work on extending capabilities
> of "Session Analysis" rather using ML Flow. Could you please identified
> ML Flow features which we can add to CCT Session Analysis tooling?

> Can you start planing the addressing the features listed in
> https://github.com/gosha70/code-copilot-team/issues/371?

On schema changes (the green-field ruling, applies to every slice):

> We can approach with "Session Analysis" as a green field project (I
> still not officially release it); so I am good about not worry about
> the backward compatibility - data migration

Issue #371, row A2, as filed:

> **Search.** Today: the sessions route filters on a project/model
> substring only; date, tag and developer filters exist in the query
> layer but not over HTTP; the full-text search route has no Studio page.
> Build: expose date range, tag, developer, cost, model, tool and label
> filters; give full-text search a page. No new storage.

Success measure for A2 in the issue: "every filter the query layer
supports is reachable from the Studio; full-text search has a page."

The A2 bundle was written after A1 merged (PR #372, 2026-09-22 local time), as the
owner was told it would be. The owner's plan review (2026-09-22) accepted
D1–D4 and D6 with conditions, rejected the deferral of label filters
(D5) in favour of an MVP — "the packaged rubric marked this boolean label
true on at least one turn in the session, using EXISTS; named rubric
runs, human labels, counts and session-level aggregation remain out of
scope" — and required four contract corrections: an inclusive `date_to`,
the excluded-count query extended with every new filter, archive-coverage
metadata and the noise policy on `/api/search`, and a recorded note that
the Search page supersedes part of the #307 nav cut and complements Ask.
All are folded in below.
