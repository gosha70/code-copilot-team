# Origin — the owner's follow-up, 2026-11-21

Captured from the owner's own messages in the session of 2026-11-21, while
the 2.1.0 release PR (#492) was open. Recorded under `specs/` for the same
reason as the 2026-11-07 transcript.

## 1. The question

> Why we "cct" does not support "init" - claude-code init ml-rag
> ~/projects/my-rag-app   # start from a template?

The assistant answered that #410 put only one launcher command under
`cct`: `start`. FR-1 of this spec adds `cct start`, which passes every
argument to the installed launcher; renaming the launcher itself was
rejected because `claude-code` is the adapter id. The launcher's other
commands (`init`, `sync`, `list`, `build`) were never discussed, and the
README's "Working in a project" block shows the seam: `claude-code init`
and `claude-code sync` beside `cct start --llm`. It noted that
`cct start init …` already works because `cct start` passes its arguments
through, that `init` and `sync` could pass through the same way, and that
the template list needs another name because `cct list` is the feature
index.

## 2. The ruling

The owner pasted the README block (and a screenshot of it rendered) and
wrote:

> Then, README must be updated and old commands must be replaced with
> their new alternatives !!!

Read as: every command a user is told to type for the launcher is spelled
with `cct`, and where `cct` has no such command yet, it gains one. The
launcher itself keeps working under its own name, as FR-1's constraint
already states.
