---
max_turns: 8
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
---

My project's CLAUDE.md has this section:

## Copyright & Licensing
- **Company**: Acme Robotics Ltd
- **License**: Apache-2.0

Create a new file `config/defaults.json` with three settings: `retries` set to 3, `timeout_seconds` set to 30, and `log_level` set to "info".

Don't write it to disk. Reply with the complete file contents in a single code block and nothing else.
