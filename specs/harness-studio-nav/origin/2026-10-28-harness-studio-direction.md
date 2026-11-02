# Origin — the owner's direction, 2026-10-28

Captured from the owner's own messages in the session of 2026-10-28.
This file exists because the working notes live in `doc_internal/`,
which is gitignored and therefore reaches nobody but the machine it was
written on. The parts a spec author needs are recorded here, under
`specs/`, which is always committed.

## 1. The complaint that started it

> Right now it looks messy. Some tab shows almost empty panels; it looks
> like pile of crap. We need Identify most valuabe pieces - bring them
> at front - better discovery; then others - make sub-panel options.

And, on the specific failure that generalised into the connection rule:

> Alerts card What is the hell it is? ... I asked explicitly make thing
> integrated and helpful, but instead worked 4 month on reviewing
> hundreds commits without abiltity at the 'garbage' UI you created.
> What I would expect, a dedicated and well connected parts; in this
> case: Alert should have a shortcuts to the learning section (which is
> located in the main Learning panel) explaining about alerts, their
> goals, how to configure; also - the link to exact setting where alerts
> to configure. Instead I see hundreds different pieces.

## 2. The owner's reframe, which overturned three agent proposals

Three research agents independently proposed hiding Runs, Benchmark and
Routing as "repo-specific noise". The owner rejected all three options
and named the actual spine:

> Neither, but the logic of option B + more refined enhanced UX for
> option A - that what I like best; the difference is not 'Session is
> apine' but 'Harness/AI SDLC' is; so here are concrete suggestions you
> should expand on: Change the tool name 'Harness Studio', the
> Control/Monitoring (something like Head Quater where we see all
> system) will include Dashboard any analysis and data discovery; the
> next Processes/Development/SDLC includes actors and moving pieces what
> cretes and support the development; and finalyy Documents/Learning.
> This is a draft; so any futher investigation/refinment is welcome

Approved on sight of the sketches: "Yes, this I like. Thanks".

**Why the reframe inverts the earlier conclusion.** The feature catalog
holds 19 features. "Session analytics" is one of them and "Studio web
UI" is another, so the console was named after a single feature — which
is why everything else looked like a foreign body in it. Of roughly
fourteen SDLC features, the Studio surfaces three, and presented those
three apologetically. They are under-represented, not over-represented.

## 3. The build instruction

> Also can you setup the cli command to start a new Claude Code session
> which will autonomously build the UI refacrtoring including adjusting
> UI tool name from "Session Analyzer" to "Harness Studio" with auto
> code review done by DeepSeek? The changes should be done in seperated
> commis in one PR (Claude Code should be able create one). At the end I
> will review all finished feature tomorrow.

So: separate commits, one PR, DeepSeek as the gating reviewer, no merge
— the owner reviews.

## 4. External review of the direction, 2026-10-28

An external reviewer read the direction against the code and raised five
findings, all of which shaped this spec:

1. The connection rule was too page-grained — Team alone holds Alerts,
   developers, projects, liveness and budgets, each wanting a different
   guide and a different setting. It must bind per feature. **Deferred
   to increment 2; out of scope here.**
2. Grouped navigation needs a route map and an active-state contract
   before it is spec-ready. **FR-2, FR-3, FR-4.**
3. The Library row presented conceptual destinations as implemented
   peers. **Resolved: Library carries Guides only in increment 1.**
4. The cost understated the work: the connection rule is the feature,
   not downstream cleanup. **Resolved by splitting into increments;
   this spec is increment 1 alone.**
5. Keep the rejected drafts, but label them rejected. **Done in the
   working notes.**

Its recommended rulings, adopted here as this spec's assumptions:
Mission Control / Development / Library as group names; the rename
reaches the Studio only, not the repo, the `cct` CLI or the package;
features with no UI stay out of the navigation; Settings stays a corner
utility.

## 5. What the enumeration of Learn added

`/learn` holds eleven sections, not four. Skills, Agents and Wiki map
one-to-one onto section ids; "Guides" does not — the `guides` id is
titled "Feature guides" and seven other `doc` sections sit beside it
(`start`, `claude-code`, `pi`, `shared`, `analytics`, `dgx-spark`,
`background`). The default recorded for increment 2 is a Guides umbrella
filtered to `kind === "doc"` with those eight nested one level beneath,
rather than eight more siblings. **Increment 1 therefore ships one
Library item, `/learn` labelled "Guides", and invents no anchor
semantics.**

"Memory" appeared in the first draft of the group table and was removed:
there is no route, no Learn section and no API for it. MemKernel exists
only as an entry inside the `skills` section.
