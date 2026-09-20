# Owner direction — 2026-09-19 (plugin adoption, step 2)

Owner messages in the #363 session, verbatim where quoted. The full
three-step direction is also recorded, merged, in
`specs/plugin-hooks-load-fix/origin/2026-09-19-owner-direction.md`.

The reason for the work:

> And we need to evaluate, adopt, and use Plugins; Anthropic puts a lot of efforts in
> it; so it might be important for our customers ti use it.

Step 2, as the owner set it:

> 2. Package the existing skills, agents and commands from their authoritative sources.
>    That source-of-truth decision is straightforward: generate the plugin, don't
>    maintain another authored copy. Keep setup.sh supported, and address duplicate
>    hooks and plugin-namespaced commands when both installation paths coexist. No
>    broad redesign is needed.

Step 3 stays separate:

> 3. Evaluate one skill afterwards—not as a prerequisite for adoption.
> ...
> Paid evaluation remains a separate authorization

After step 1 (PR #364) and P1+P2 (PR #365) were merged:

> Start planning the plugin adoption step
