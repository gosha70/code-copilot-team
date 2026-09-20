---
max_turns: 8
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
---

My project's CLAUDE.md has this section:

## Copyright & Licensing
- **Company**: Acme Robotics Ltd
- **License**: Apache-2.0

Create a new file `src/slugify.py` with one function, `slugify(text)`, that lowercases the text, trims it, and replaces each run of non-alphanumeric characters with a single hyphen.

Don't write it to disk. Reply with the complete file contents in a single code block and nothing else.
