# Origin alignment check — harness-studio-nav

Origin: specs/harness-studio-nav/origin/2026-10-28-harness-studio-direction.md
(the owner's messages of 2026-10-28: the "pile of crap" complaint, the
Alerts complaint, the reframe naming "Harness Studio" and the AI SDLC as
the spine, the approval "Yes, this I like. Thanks", and the build
instruction). No parent issue; the direction was set in session.

Origin claim:
> Rename the console "Harness Studio" and make the spine the AI SDLC
> rather than the session: three groups — see the system, the moving
> pieces that build, what it knows. Bring the valuable surfaces to the
> front, make the rest sub-panel options, and preserve what exists.
> Build it autonomously in separate commits on one PR with DeepSeek as
> the reviewer; the owner reviews the finished feature.

Working claim:
> specs/harness-studio-nav/{spec,plan,tasks}.md: a new `studio/lib/nav.ts`
> holding the product name, three groups over the twelve routes that
> already exist, and `activeNav()`; `NavTabs` renders two rows with
> `aria-current` on the item only; `layout.tsx` consumes both; the
> release nav gate and the docs follow the renamed labels. No route
> added, removed or redirected. Three phases, three commits.

Verdict: aligned
Confidence: high

## Where the working claim is deliberately NARROWER than the origin

The origin asks for connected parts — an alert that links to the guide
explaining alerts and to the exact setting that configures them. **This
spec does not deliver that.** It is increment 1 of three, and the
connection rule is increment 2, recorded in the spec's "Out of scope"
section with the reason: it needs stable Settings anchors, a
`settings_links` counterpart to the existing `finding_links`, and a link
pair on every card and empty state. An external review of 2026-10-28
found that treating it as downstream cleanup understated it, and the
split is the response to that finding.

This narrowing is a scope *decision*, not drift: the owner's build
instruction named the rename and the restructure, and asked for a
reviewable feature by morning. Shipping the registry in the same
unattended run would widen an overnight run into the larger half of the
work, against the project's own rule that a run must not expand its
scope.

**The owner should know that merging this PR does not resolve the Alerts
complaint.** That is increment 2.

## Assumptions carried from the external review, not from the owner

Four of the direction's open questions were unruled when this spec was
written. The spec adopts the reviewer's recommendations as assumptions,
each cheap to reverse:

- Group names Mission Control / Development / Library.
- The rename reaches the Studio only — not the repo, the `cct` CLI or
  the package name.
- Features with no Studio surface stay out of the navigation.
- Settings remains a corner utility rather than a fourth group.

A fifth question surfaced after the review, from enumerating `/learn`:
"Guides" is not one section but eight. Increment 1 therefore ships a
single Library item pointing at `/learn` and invents no anchor
semantics.

Checked 2026-10-28 against the owner's messages in session, the external
review of the direction, `studio/app/layout.tsx:21-32`,
`studio/components/NavTabs.tsx`, `tests/release/ui_checks.sh:77-88`, and
the eleven Learn sections in
`scripts/session_analytics/config_data/learn-sections.json`.
