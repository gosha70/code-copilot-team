#!/usr/bin/env bash
# Stub backend for subprocess tests.
# Echoes a fixed valid BackendResponse (accept, incident page type) inside a
# ```json fence and exits 0. Used to exercise the subprocess path without a
# real copilot CLI present in CI.

cat <<'EOF'
```json
{
  "version": 1,
  "disposition": "accept",
  "reason": "Test backend always accepts; deterministic output for CI.",
  "page_type": "incident",
  "slug": "stub-test-source",
  "title": "Stub Test Source",
  "draft_markdown": "---\npage_type: incident\nslug: stub-test-source\ntitle: Stub Test Source\nstatus: draft\nlast_reviewed: 2026-05-04\nsources:\n  - path: stub-source.md\n    sha: abc1234\n---\n\n# Stub Test Source\n\n## What happened\n\n(Stub placeholder.)\n\n## Why it happened\n\n(Root cause placeholder.)\n\n## What we changed\n\n(Remediation placeholder.)\n\n## How to recognize a recurrence\n\n(Recurrence signals placeholder.)\n",
  "sources": [{"path": "stub-source.md", "sha": "abc1234"}]
}
```
EOF
