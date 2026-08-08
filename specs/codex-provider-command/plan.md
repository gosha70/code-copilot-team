---
spec_mode: none
feature_id: codex-provider-command
risk_category: bugfix
justification: |
  Non-security bug fix (#199): the shipped provider template (and the
  README block users copy from) configures the Codex reviewer with flags
  removed from the CLI. Config/doc change plus a guard test; no runtime
  logic changes. spec_mode none per the spec-workflow table for bug fixes.
status: approved
date: 2026-08-08
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/199
  origin_claim: |
    Bug #199: "provider template ships dead codex flags (--quiet/--prompt-file
    removed; use codex exec)". `shared/templates/provider-profile-template.toml`
    line 55 ships `command = "codex --quiet --prompt-file {review_request}"`.
    Neither flag exists in current Codex (verified by EXECUTING codex-cli
    0.147.0, not just reading help). Non-interactive runs are `codex exec`.
    A user who copies the template gets an immediate flag error from every
    codex review round. Proposed fix: `command = "codex exec - < {review_request}"`
    (or an equivalent that survives the runner's `bash -c` and
    `{review_request}` substitution), keep `healthcheck = "codex --version"`,
    and re-verify by executing one real review round against the installed
    CLI — not just `--help`.
  urls:
    - https://github.com/gosha70/code-copilot-team/pull/198#issuecomment-review
---

# Plan: replace the dead codex reviewer command (#199)

The template and the README block it mirrors now ship:

```toml
command = "codex exec --color never -s read-only --skip-git-repo-check - < {review_request} 2>/dev/null"
```

The issue proposed `codex exec - < {review_request}`. A recorded capture
against the installed CLI (`specs/codex-provider-command/verification/codex-reviewer-capture.md`)
shows that form is **not sufficient** — it fails two ways the flag audit
could not reveal, which is exactly why the issue demanded execution over
`--help`:

1. **It never runs.** The runner deletes `.git` from its snapshot sandbox
   so a reviewer cannot touch the real repo, and codex refuses to start
   outside a git repo: `Not inside a trusted directory and
   --skip-git-repo-check was not specified.` Every round would fail.
2. **It would forge PASS verdicts.** `codex exec` echoes the entire prompt
   *and* the final message to stderr, and the runner captures the provider
   with `bash -c "$cmd" 2>&1`. The runner anchors on the FIRST
   `^### Verdict` and scans to the next blank line — in the merged stream
   that is the echoed *instruction* line "State exactly one of: PASS, FAIL,
   or INCONCLUSIVE", so `grep -oiE 'PASS|FAIL|INCONCLUSIVE' | head -1`
   returns PASS. Captured live: the model returned **FAIL**, the runner
   parsed **PASS**. The echoed template line also parses as a phantom
   finding (`severity=<severity>`, `category=<category>`, `file=<file>`),
   and every real finding is duplicated.

`2>/dev/null` keeps codex's prompt echo out of the parsed stream; stdout
alone is exactly the final message, correctly line-anchored and free of
ANSI. `-s read-only` matches the reviewer contract (the runner already
exports `CCT_READ_ONLY=true` and strips credentials from the child env).
`--color never` is belt-and-braces for the text contract.

Cost of `2>/dev/null`: codex's own diagnostics are dropped. A failing
codex still exits non-zero, and the runner already converts a non-zero
provider exit into `VERDICT=FAIL`, so failures surface as a failed round
rather than silently. `healthcheck = "codex --version"` is unchanged and
still catches a missing or broken install before a round starts.

## Scope

- `shared/templates/provider-profile-template.toml` — the shipped command.
- `README.md` — the same block, which users copy (the issue named only the
  template; the README carried an identical dead command).
- `tests/test-peer-review.sh` — the TOML fixture stopped exemplifying the
  dead flags. No assertion reads the command value.
- `tests/test-shared-structure.sh` — a guard test, because the template had
  **no** test coverage at all, which is how a dead command shipped and
  survived. It asserts the removed flags are absent and the required
  elements present, for codex and for every other `type = "cli"` provider.

## Out of scope (filed separately)

The runner's verdict parser takes the FIRST `^### Verdict` and treats any
`^FINDING|` line as a finding. That makes ANY prompt-echoing CLI provider —
not just codex — able to forge a PASS and inject a phantom finding. The
template fix closes it for codex; the parser hardening (anchor on the LAST
verdict block, ignore literal `<severity>` template lines) is a separate
change to shared review logic and is filed as its own issue.
