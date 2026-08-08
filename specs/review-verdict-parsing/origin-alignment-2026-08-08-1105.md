# Origin Alignment Check — review-verdict-parsing

Date: 2026-08-08 11:05
Trigger: plan.md and spec.md revised after the user's P1 on PR #203; the
previous record (`origin-alignment-2026-08-08-1015.md`) is stale.

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/200.
- The user's P1 review of PR #203 (verbatim below), which reproduced both
  inverse-order cases locally and told me not to merge.

## Origin claim (the user's P1, verbatim)

> Prompt echo can still forge PASS when it arrives after the model
> answer. The fix picks the last `### Verdict` block, but both runners
> still make the prompt itself parseable as a verdict block. … Because
> output is merged with `2>&1`, stdout/stderr ordering is not a safe
> contract. … The fix needs to make echoed prompts unparseable regardless
> of ordering. At minimum: remove/avoid literal parseable verdict
> examples from the request text and add regressions where the prompt
> echo appears after the actual answer. For the parser, prefer a stricter
> contract around the actual verdict line and reject instruction/example
> blocks.

## Working claim

A verdict is a bare `PASS`/`FAIL`/`INCONCLUSIVE` alone on the line after
a line holding only `### Verdict`; anything else after the heading ends
the block without yielding a verdict. Both requests describe that shape
in prose and never instantiate it, so an echoed request is inert at any
position. One implementation (`scripts/lib/review-verdict.sh`) serves
both runners. Regressions cover echo-after-answer in both runners, a
verdict word on the heading line, and a provider whose entire output is
the real request echoed verbatim.

## Mismatches

- none against the P1.

Each of the user's three requirements is met and pinned: literal
parseable verdict examples are gone from both requests (the peer-review
one was mine, introduced in the previous commit and worse than what it
replaced); regressions place the echo after the answer in both runners;
and the parser now rejects instruction and example blocks structurally
rather than by position. All new assertions were verified to fail against
`827dfae`, the commit the P1 was raised on.

The one requirement deliberately read narrowly: the `FINDING|<severity>|…`
example stays in the round runner's request. It is not a *verdict*
example, it is already inert (the placeholder-shape filter drops it, with
a passing regression), and removing it would degrade reviewer format
compliance for no security gain.

## Verdict

Verdict: aligned
Confidence: high
