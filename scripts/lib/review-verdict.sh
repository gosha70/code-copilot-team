#!/usr/bin/env bash
# review-verdict.sh — the ONE verdict parser for every review runner.
#
# Both runners capture providers with `bash -c "$cmd" 2>&1`, so a CLI that
# echoes its prompt (codex exec does) merges the review REQUEST into the
# stream that gets parsed. Stream ordering across the two file descriptors
# is not a contract: the echo can land before, after, or interleaved with
# the answer. Position-based rules ("first block", "last block") are
# therefore all unsound — a request that is parseable at all is a forged
# verdict waiting for the buffering to change.
#
# The contract instead makes the request UNPARSEABLE by construction:
#
#   a verdict block is the line `### Verdict` (alone), followed — after
#   any blank lines — by a line holding exactly one bare word: PASS,
#   FAIL, or INCONCLUSIVE, and nothing else.
#
# Request text describes that shape in prose and never instantiates it, so
# echoing the request in full yields no verdict at all, at any position.
# When several valid blocks are present (a provider that duplicates its own
# answer) the LAST wins; duplicates agree, so the choice is immaterial.
#
# Callers MUST treat empty output as INCONCLUSIVE — never as PASS.
# tests/test-review-loop.sh and tests/test-peer-review.sh cover both
# runners, including a mock that echoes the real request verbatim.

rv_extract_verdict() {
    # rv_extract_verdict <captured-output> — PASS|FAIL|INCONCLUSIVE, or empty
    printf '%s\n' "${1:-}" | awk '
        # Heading alone on its line. A trailing colon is tolerated; a
        # verdict word on the SAME line is deliberately not a match, so
        # "### Verdict: PASS, FAIL, or INCONCLUSIVE" in prose cannot arm
        # the parser.
        /^[[:space:]]*###[[:space:]]+[Vv]erdict[[:space:]]*:?[[:space:]]*$/ {
            seeking = 1
            next
        }
        seeking {
            line = $0
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
            if (line == "") next          # blank lines after the heading are fine
            gsub(/^[*`_]+|[*`_]+$/, "", line)   # tolerate **PASS**, `PASS`, _PASS_
            up = toupper(line)
            if (up == "PASS" || up == "FAIL" || up == "INCONCLUSIVE") {
                verdict = up
            }
            # Anything else — prose, an example with placeholders, a
            # sentence listing the options — ends this block WITHOUT
            # recording a verdict. That is what makes an echoed request
            # inert regardless of where it lands in the stream.
            seeking = 0
        }
        END { if (verdict != "") print verdict }
    '
}
