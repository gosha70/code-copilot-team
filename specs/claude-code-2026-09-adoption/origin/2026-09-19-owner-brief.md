# Owner brief — 2026-09-19 (session start, issue #363)

Verbatim scope section of the owner's session brief. The issue body
(#363) is the other half of the origin.

> ## Scope — exactly this, in this order
> 1. P1: add `effort` to the frontmatter of the 14 shipped agents, matching what the
>    global manifest already prescribes (Research/Plan/Review high, Build medium,
>    narrow utility agents low).
> 2. P2: add this week's version-gated CLI facts to shared/skills/opus-4-7-features/SKILL.md.
> P1 and P2 ship together as one slice. That slice is the deliverable.
>
> NOT in scope unless I say so in chat:
> - P3 (`claude plugin eval`). It costs money. Do not run it. If you think it is worth
>   doing, state a budget in one line and wait.
> - Renaming the features skill. It is loaded by name in tests, docs and several
>   generated adapter surfaces. Give me a one-paragraph recommendation with the list of
>   files a rename touches, and wait for my decision. Do not rename on your own.
> - `omitClaudeMd`. Declined on purpose in the issue. Record the decision where the
>   issue says, nothing more.
> - The "environmental" items. No work.

Verification instructions from the same brief:

> Verify, do not assume: the issue's open risk is whether an unknown frontmatter key
> is inert on older CLI versions. Check the Claude Code docs or the CLI itself and
> tell me what you found before shipping P1. Same for every CLI fact you add in P2:
> confirm the version gate from a source, do not copy it from the issue.

> Answer the issue's open question with a recommendation: should the manifest prose
> point at the frontmatter so the two cannot disagree? One source, not two.

> Single source of truth: edit the source (shared/skills/, adapters/claude-code/.claude/agents/)
> and regenerate derived copies with scripts/generate.sh and the adapter's own setup
> path. Never hand-edit a generated surface.
