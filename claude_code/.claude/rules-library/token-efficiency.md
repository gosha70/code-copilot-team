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
