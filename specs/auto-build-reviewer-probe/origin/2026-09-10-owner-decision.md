# Origin: the owner's decision on increment D scoping, 2026-09-10

Context: four real unattended runs of `team-developer-aliases` on
2026-09-09 (ledgers under `.cct/auto-build*`; the Runs tab, #333). Runs 1
and 3 ended `terminated_policy` / `provider_unavailable` after the gating
reviewer passed its configured healthcheck (`codex --version`,
`curl -sf …/v1/models`) and then could not produce a verdict in the
first round: $8.77 and about 1h 52m across the two.

The scoping memo (doc_internal/plans/190-increment-d-scoping-2026-09-10.md)
recommended a reviewer probe at admission instead of increment D. The
owner, 2026-09-10:

> The scoping satisfies the next step; it doesn't oblige us to build D.
>
> I recommend the reviewer probe first: one small request through the
> actual gating-reviewer path, requiring a parseable verdict. That checks
> readiness, not review quality.
>
> Keep run 4 as calibration evidence without adding machinery. Then run
> the next real feature and reconsider D against the additional
> evidence—not a mandatory five-run threshold.
>
> Leave D deferred, not rejected. No new issue or broader recovery design
> needed.
