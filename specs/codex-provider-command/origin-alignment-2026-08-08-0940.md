# Origin Alignment Check — codex-provider-command

Date: 2026-08-08 09:40
Trigger: first alignment record for this feature (gate exit 4).

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/199
  (`gh issue view 199` — full body incl. the proposed fix and the
  explicit "re-verify by executing one real review round … not just
  `--help`" instruction).
- The reporter's PR #198 review message, which scoped this work: "Use
  `codex exec`/`codex review` in a separate provider-config fix."
- The reporter's follow-up caveat: "I verified Gap A from `codex --help`
  output, not by executing the dead command (to avoid a hang). Worth a
  5-second `codex exec --help` confirmation before rewriting the
  provider line."

## Origin claim (verbatim)

> `shared/templates/provider-profile-template.toml` line 55 ships a dead
> Codex reviewer command … Neither flag exists in current Codex. …
> Non-interactive runs are `codex exec` (alias `e`) … A user who copies
> the template gets an immediate flag error from every codex review
> round. **Proposed fix:** Update the template command to the current
> surface, e.g. `command = "codex exec - < {review_request}"` (or
> `codex exec "$(cat {review_request})"` — pick whichever survives the
> runner's `bash -c` invocation and `{review_request}` substitution
> cleanly), keep `healthcheck = "codex --version"`, and re-verify by
> executing one real review round against the installed CLI (the
> recorded-capture-is-ground-truth rule) — not just `--help`.

## Working claim

The template and the README block it mirrors now ship
`codex exec --color never -s read-only --skip-git-repo-check -
< {review_request} 2>/dev/null`, with `healthcheck = "codex --version"`
unchanged. Flags were chosen from a recorded capture of a real review
round against codex-cli 0.147.0, committed as
`specs/codex-provider-command/verification/codex-reviewer-capture.md`.
The previously untested template gained guard assertions.

## Mismatches

- **The shipped command is not byte-identical to the issue's suggestion**
  (`codex exec - < {review_request}`). This is compliance with the
  origin, not divergence from it: the issue said "pick whichever survives
  the runner's `bash -c` invocation and `{review_request}` substitution
  cleanly" and mandated verification by execution. Execution showed the
  bare form does not survive — it cannot start in the runner's
  `.git`-stripped sandbox, and its stderr prompt echo makes the runner
  parse a FAIL as PASS. The extra flags are exactly what the origin's own
  verification requirement produced.
- **README.md was changed although the issue names only the template.**
  The README shipped an identical dead command that users copy. Leaving
  it would have left the reported defect live on the more-read surface;
  the standing "apply corrections globally / grep every caller" rule
  covers this.
- Scope held: the runner's verdict-parser weakness (first `^### Verdict`
  wins; literal `FINDING|<severity>|…` template lines parse as findings)
  affects any prompt-echoing cli provider, is NOT a codex-config change,
  and is filed as its own issue rather than folded in — matching the
  reporter's own instinct to split provider-config from parsing.

## Verdict

Verdict: aligned
Confidence: high
