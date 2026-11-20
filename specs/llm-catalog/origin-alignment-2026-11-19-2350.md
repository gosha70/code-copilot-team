# Origin alignment check — llm-catalog (launch-first slice, revision 7)

Date: 2026-11-19 23:50 EST

Supersedes the 2026-11-14 22:55 record. One amendment: on 2026-11-19
the owner ruled that the Claude Code launch is built before the rest of
slice A, after a shell startup file that exported one provider's
variables routed every Claude Code session on their machine to that
provider. spec.md gains revision 7 and the section "Launch-first slice
(#479, ruled 2026-11-19)"; plan.md and tasks.md gain the matching slice
sections; the approved requirements, decisions and success criteria
are otherwise unchanged and govern the slices that follow.

Origin sources: issue #400 as amended by the owner on 2026-11-10; the
owner's messages of 2026-11-19, recorded in
`origin/2026-11-19-launch-first-ruling.md`; issue #479; the repository
at `7186ff3`; the installed Claude Code 2.1.329, captured in
`verification/claude-code-capture.md`.

## What the origin asks, and what the slice does

| Origin | Slice |
|---|---|
| #400: "configure multiple named LLM targets once … and optionally select one when starting a harness" | `${CCT_HOME:-~/.cct}/llms.toml`; `--llm <target>` on `claude-code` and through `cct start` |
| #400: "If no target is selected, the harness must retain its native configured behavior" | Without `--llm` nothing runs: output, typed command, argv and environment identical to master's launcher in seven launches |
| #400: secrets out of argv, generated commands, logs and multiplexer commands | A credential is named by its variable; the typed command carries ids only; a planted value is asserted absent from everything typed, printed and logged |
| Owner, 2026-11-19: "the curennt approach of setting this globally in environment is unacceptable and harmful" | The variables are set in the one process that becomes `claude`; competing ones are removed from it |
| Owner, 2026-11-19: "I want a freedom of selecting which model to use" across "Anthropic models and others (DeepSeek, local ones - Ollama, vLLM, OpenAI)" | Targets for Anthropic by Claude Code's own login, DeepSeek, Ollama and a gateway in front of vLLM or OpenAI, in the shipped example |
| Owner, 2026-11-19: build the launch first; probes, stamps, the other launchers, Studio and routing later | Those are deferred by name in spec.md, "Launch-first slice" |

## Mismatches

None with the origin.

With the approved text there are thirteen departures, listed in
spec.md, "Launch-first slice", each with its reason. The ruling covers
two of them (the order, and a native Anthropic target). The others are
choices the slice had to make where the text was silent or, read
literally, would not launch: unverified targets launch with a notice
because the probe is deferred; resume is not enforced because no stamp
exists; the alias mapping; the Fable alias; a placeholder token for an
endpoint with no credential; a wider clear-list; two more binding
keys; `unset` instead of `env -u`; the settings `env` refusal the
capture called for; and three launcher behaviours. They are put to the
owner with the PR. None narrows what #400 promises; each can be
revisited without changing the catalog file's schema, except the two
added binding keys, which a later slice would have to keep or migrate.

Not delivered by this slice and still owed to #400: the compatibility
gate with its probe, session stamps and resume enforcement, the Codex,
Pi and Kiro launchers, project policy, routing, Studio. #400 is
recorded as closed on GitHub (by the spec PR, #444); whether to reopen
it as the umbrella is the owner's call.

Verdict: aligned
Confidence: high
