---
applyTo: "**"
---


# Token Efficiency

Practices to minimise token waste across all sessions.

## Context Management

- Do not re-send large context blocks. Reference existing files by path instead.
- Use /compact when context window grows large.
- Load only relevant file sections, not entire large files.
- One task per session where practical. Flush context between unrelated tasks.

## Output Format

- Return diffs, not full file rewrites.
- Keep explanations concise — bullets over paragraphs.
- Do not repeat information the user already knows.
- Do not generate boilerplate unless asked.

## File References

- When prior context is needed, read doc_internal/CONTEXT.md (if it exists in the project) rather than re-generating from scratch.
- For architecture context, reference doc_internal/ARCHITECTURE.md rather than re-explaining the system.

## Task Budgets (Opus 4.7, public beta — API only)

An advisory token budget for the **full agentic loop**, not a single request. Currently public beta on Opus 4.7 via the API; not available in Claude Code or Cowork at launch.

- Set via `output_config.task_budget: {type: "tokens", total: N}` in the API request.
- Minimum `total`: **20,000 tokens**.
- The model sees a running countdown of the budget and self-regulates: prioritizes higher-value work first, finishes gracefully as the budget approaches zero rather than getting cut off mid-thought.
- **Advisory, not enforced.** `max_tokens` is still the hard cap per individual request. `task_budget` shapes behavior across the loop; it does not stop a request from completing.

How it composes with `effort`:

- `effort` controls **depth per step** (how hard Claude thinks about each turn).
- `task_budget` controls **breadth across the loop** (how much total work Claude attempts before wrapping up).
- Use both together for long agentic runs where you care about end-to-end token cost.

## `/btw` — Side Questions Without Polluting Context

Opus 4.7 introduces `/btw <question>` for quick sidebar questions that **never enter conversation history**.

- The answer appears in a dismissible overlay.
- Conversation context, cache breakpoints, and the running task remain untouched.

**Important — `/btw` has no tool access.** It cannot read files, run bash, search the codebase, or call MCP tools. It can only answer from what is **already in the current conversation context** (files Claude has already read, prior tool output, system prompts, loaded memory). If the information you need isn't already in context, `/btw` cannot fetch it.

**Good `/btw` questions** (answerable from existing context):

- "What did that error message say again?"
- "What was the function signature we discussed earlier?"
- "Remind me what option we picked for the auth flow?"
- "Summarize what's in the file you just read."

**Not good for `/btw`** (require tools, ask as a normal turn instead):

- "Which file is `Foo` defined in?" — needs grep.
- "What's the latest version of package X?" — needs network.
- "Read file Y and tell me…" — needs Read.

If the answer requires fresh tool work, ask it as a normal turn so the lookup runs and the result becomes part of the conversation record.

## Prompt Caching Discipline

Per Anthropic's April 30 2026 guidance, prompt caching is the single most important token optimization for Claude Code workflows. Specific rules to keep cache hit rates high:

- **Don't switch thinking modes mid-session.** Toggling between `adaptive` and `enabled`/`disabled` breaks per-message cache breakpoints. Pick one and stay with it. (See `opus-4-7-features.md` § Caching Awareness.)
- **Use `ENABLE_PROMPT_CACHING_1H=1` for sessions over 30 minutes.** Default 5-minute TTL evicts warm cache between turns when you take a break. (See `opus-4-7-features.md` § Prompt Caching.)
- **Use `/clear` between unrelated tasks.** Stale context wastes cache and degrades performance — the cache stays warm only for context that's actually still being used.
- **Reference files by path, don't paste their contents back in.** Re-pasted content has no cache history; a path reference re-uses the prior read's cache entry.
