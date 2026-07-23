---
description: A fixture command carrying Claude-only frontmatter keys.
argument-hint: <file> [--force]
allowed-tools: Bash(git:*), Read, Edit
model: claude-3-5-haiku
disable-model-invocation: true
---

# Fixture

Operate on $ARGUMENTS, or the first argument $1 when given.
