# Recorded capture — Codex reviewer surface (#199)

Captured 2026-08-08 against the installed CLI. This file is the ground
truth for the command in `shared/templates/provider-profile-template.toml`;
the flags were chosen from THIS capture, not from `--help` alone.

```
$ codex --version
codex-cli 0.147.0
```

## 1. The shipped flags are gone

```
$ codex --help | grep -iE 'quiet|prompt-file'
(no matches)
```

Non-interactive entry points in 0.147.0:

```
  exec            Run Codex non-interactively [aliases: e]
  review          Run a code review non-interactively
```

## 2. Why the issue's proposed command is not sufficient

### 2a. It never starts — the runner's sandbox has no `.git`

`review-round-runner.sh` copies the working tree to a snapshot and does
`rm -rf "$SNAPSHOT_DIR/workspace/.git"` so the reviewer cannot affect the
real repo. Codex refuses to run there:

```
$ cd <dir without .git> && codex exec --color never -s read-only -
Not inside a trusted directory and --skip-git-repo-check was not specified.
```

So `--skip-git-repo-check` is mandatory, not decorative.

### 2b. It forges PASS verdicts — codex echoes the prompt to stderr

The runner captures providers with `bash -c "$RESOLVED_CMD" 2>&1`. Codex
writes its session banner, **the entire prompt**, and a copy of the final
message to stderr. The runner anchors on the FIRST `^### Verdict` and
scans to the next blank line, which in the merged stream is the echoed
instruction:

```
### Verdict
State exactly one of: PASS, FAIL, or INCONCLUSIVE
```

`grep -oiE 'PASS|FAIL|INCONCLUSIVE' | head -1` therefore returns PASS.
Reproduced live with the runner's own extraction logic against a file
containing a real SQL-injection bug:

```
=== runner's verdict extraction on the MERGED stream ===
VERDICT PARSED = PASS
=== the model's ACTUAL verdict ===
FAIL
=== findings the runner would parse (severity|category|file) ===
<severity>|<category>|<file>        <-- phantom, from the echoed template line
blocking|security|query.sh
warning|correctness|query.sh
blocking|security|query.sh          <-- duplicated (stdout + stderr copy)
warning|correctness|query.sh
```

A gating reviewer would have approved code it had just failed.

## 3. The shipped command, verified

```
codex exec --color never -s read-only --skip-git-repo-check - < {review_request} 2>/dev/null
```

Same input, same extraction logic, run through `bash -c "$cmd" 2>&1`:

```
exit=0
VERDICT = FAIL                       <-- matches the model
findings parsed: blocking|security|query.sh
phantom '<severity>' lines: 0
```

Raw stdout is exactly the final message — `### Verdict` and every
`FINDING|` at line start, zero ANSI escapes — which is what the runner's
`^`-anchored parsing requires.

## 4. Flags, and why each is present

| flag | reason |
|---|---|
| `exec` | `--quiet`/`--prompt-file` no longer exist; `exec` is the non-interactive entry point (alias `e`). |
| `-` | Reads instructions from stdin, so `< {review_request}` needs no shell quoting of file contents. |
| `--skip-git-repo-check` | The runner's sandbox has `.git` removed; codex refuses to start without it (§2a). |
| `-s read-only` | A reviewer must not mutate the sandbox. Matches the runner's `CCT_READ_ONLY=true`. |
| `--color never` | The contract is parsed as text; no ANSI in the stream. |
| `2>/dev/null` | Keeps codex's prompt echo out of the `2>&1` capture (§2b). Failures still surface: codex exits non-zero and the runner converts that to `VERDICT=FAIL`. |

`healthcheck = "codex --version"` is unchanged — it still proves the CLI
is installed and runnable before a round starts.
