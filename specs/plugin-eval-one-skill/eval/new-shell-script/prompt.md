---
max_turns: 8
timeout_seconds: 240
allowed_tools: [Read, Glob, Grep, Skill]
---

My project's CLAUDE.md has this section:

## Copyright & Licensing
- **Company**: Acme Robotics Ltd
- **License**: Apache-2.0

Create a new script `scripts/backup.sh` for bash that tars the `data/` directory into `backups/data-<date>.tar.gz` and exits non-zero if `data/` is missing. It must start with a shebang line.

Don't write it to disk. Reply with the complete file contents in a single code block and nothing else.
