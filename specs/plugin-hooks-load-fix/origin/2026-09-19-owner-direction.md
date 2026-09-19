# Owner direction — 2026-09-19 (plugin adoption, step 1)

Two owner messages in the #363 session, verbatim where quoted.

Message 1:

> And we need to evaluate, adopt, and use Plugins; Anthropic puts a lot of efforts in
> it; so it might be important for our customers ti use it.

Message 2 (after the validation failure was reported):

> adopting plugins in that order, separately from P1+P2.
> 1. Fix the existing plugin first. I reproduced the validation failure: hooks.json
>    lacks the required "hooks" wrapper. Add the validation gate and verify a harmless
>    protection hook actually fires. Runtime failure remains unconfirmed; validation
>    failure is confirmed.
> 2. Package the existing skills, agents and commands from their authoritative sources.
>    That source-of-truth decision is straightforward: generate the plugin, don't
>    maintain another authored copy. Keep setup.sh supported, and address duplicate
>    hooks and plugin-namespaced commands when both installation paths coexist. No
>    broad redesign is needed.
> 3. Evaluate one skill afterwards—not as a prerequisite for adoption. Two corrections
>    to the proposed experiment:
>    - Three cases × three runs × two arms means 18 agent runs, plus applicable graders.
>    - --max-cost-usd 5 stops subsequent runs; an in-flight run can exceed $5. Use
>      concurrency 1 and --no-publish, and describe the budget honestly before approval.
> Also bump the plugin version with the fix: cached marketplace installations use that
> version to detect updates.
> Your adoption direction is clear. Paid evaluation remains a separate authorization;
> nothing was installed or changed.

This bundle covers step 1 only. Steps 2 and 3 get their own bundles when
they start; the order and the constraints above are recorded here so a
later session can find them.
