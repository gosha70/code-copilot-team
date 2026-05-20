# Aider Backend Verification Record

Pinned version: **aider 0.86.2**
Verified: 2026-05-19 (captured live on the maintainer's machine; transcript below)
Purpose: Per #41's backend verification gate — pins the exact headless
invocation surface for `aider` at `aider 0.86.2` before the backend code
ships. If a future pinned version's flags differ, this record is refreshed
and the backend implementation is updated to match it.

## Version

```
$ aider --version
aider 0.86.2
```

Install path on the capture machine: `/Users/gosha/.local/bin/aider`
(package: `aider-chat` on PyPI).

## Verified argv (the contract)

```
aider [--model <m>]
      --yes-always
      --no-auto-commits
      --no-dirty-commits
      --no-gitignore
      --no-git
      --no-check-update
      --no-stream
      --chat-history-file <attempt_dir>/aider.chat.history.md
      --llm-history-file  <attempt_dir>/aider.llm.history.txt
      [--edit-format <fmt>]      # only when CCT_AIDER_EDIT_FORMAT is set
      --message-file <attempt_dir>/aider-message.txt
```

The prompt is delivered via `--message-file`; Aider has no codex-style `-`
stdin mode. Message + history + transcript files live in `attempt_dir`
(= `ctx.worktree.parent`), never in `worktree`, so `run.py`'s `_write_diff`
(which excludes only `.venv`) does not see them in the scored diff.

### Flag contract

| Flag | Required | Rationale |
|---|---|---|
| `--yes-always` | always | The auto-confirm flag. **B0 catch:** `--yes` does not exist in Aider; using it would error. |
| `--no-auto-commits` | always | Default is auto-commit. Forced off so Aider does not create commits in the scored worktree. |
| `--no-dirty-commits` | always | Default is on. Forced off so Aider does not commit pre-existing dirty state. |
| `--no-gitignore` | always | Default adds `.aider*` to `.gitignore`. Forced off so the worktree's `.gitignore` is not modified. **B3 capture proved this alone is insufficient** when the dir is non-git (Aider also creates a `.git/` repo); `--no-git` is the actual fix. |
| `--no-git` | always | **B3 capture finding.** In a non-git directory, real Aider creates a `.git/` repo as part of session startup, polluting the scored worktree. `--no-git` (default: enabled; flag disables) yields `Git repo: none` and `Repo-map: disabled` in the transcript. Apples-to-apples caveat below + #46. |
| `--no-check-update` | always | Default checks PyPI for a newer Aider on every run. Forced off for hermeticity. |
| `--no-stream` | always | Streaming is **display-only** in 0.86.2 (does not change what is sent to the model or how edits are applied). Forced off so the end-of-run token/cost summary is reliably present in stdout for the parser. |
| `--chat-history-file <p>` / `--llm-history-file <p>` | always | Redirect Aider's history artifacts out of `worktree` and into `attempt_dir` so the scored diff stays clean. |
| `--message-file <p>` | always | Prompt delivery — Aider has no stdin-prompt mode. |
| `--model <m>` | iff non-empty | Mirrors codex: only emitted when `ctx.model` is set. |
| `--edit-format <fmt>` | iff `CCT_AIDER_EDIT_FORMAT` set | Methodology fidelity: per-model default (matches Aider's leaderboard). Setting the env var records `edit_format_forced=true` in metadata. |

### Flags NOT present (intentional)

- **`--yes`** — does not exist; the auto-confirm flag is `--yes-always` (B0).
- **No chat-mode flag** — Aider's default `code` mode is the intended posture (the edit-making mode).
- **`--map-tokens`** — not pinned (methodology fidelity); Aider's default applies, recorded as `map_tokens_effective` in metadata when present. Under `--no-git` Aider prints `Repo-map: disabled` and the metric is legitimately `None`.
- **`--temperature`** — not an Aider CLI flag at all (Aider sets temperature internally via litellm). The backend does not pin it and does not record it.

## Transcript format

Aider emits plain text, **not JSON**. The backend captures stdout to
`attempt_dir/transcript.txt`, stderr to `attempt_dir/transcript.stderr.txt`,
and uses Aider's own `aider.chat.history.md` and `aider.llm.history.txt`
files as additional durable artifacts. Token/cost metrics are parsed
best-effort from the summary line.

| Aider line | → harness field |
|---|---|
| `Tokens: <n>[k|M]? sent, <n>[k|M]? received[, Cost: …]?` | `tokens_input`, `tokens_output` (k/M-suffix + comma + decimals supported) |
| `Model: <m> with <fmt> edit format[, …]` | `edit_format_resolved` (substring of the `Model:` line, **not** a standalone `Edit format:` line — B3 catch) |
| `Repo-map: using <n> tokens[, …]` | `map_tokens_effective` (integer) |
| `Repo-map: disabled` | `map_tokens_effective` stays `None` (legitimately disabled under `--no-git`) |
| (no `Tokens:` line — crash/early-exit) | `tokens_input` and `tokens_output` stay `None` (distinct from 0) |

`cache_read_tokens`, `cache_write_tokens` are always `None` (Aider does not
report cache metrics via the CLI). `tool_calls` is always `{}` (Aider has
no codex-style structured tool events).

## Real recorded transcript

Captured 2026-05-19 with the exact pinned argv, against a single-file
toy task (make `add(a,b)` return `a+b`):

```
──────────────────────────────────────────────────────────────────────────────────────
Aider v0.86.2
Model: anthropic/claude-sonnet-4-5 with diff edit format, infinite output
Git repo: none
Repo-map: disabled
Added m.py to the chat.

I'll update the add() function to return the sum of a and b.

m.py


 <<<<<<< SEARCH
 def add(a,b):
     return None
 =======
 def add(a,b):
     return a+b
 >>>>>>> REPLACE


Tokens: 2.7k sent, 73 received. Cost: $0.0091 message, $0.0091 session.
Applied edit to m.py
```

`transcript.stderr` was empty. **Observed exit code: `0`** — empirically
pinned (Aider's exit codes are undocumented; `failed_commands` = 0 iff
exit 0, else 1).

`m.py` after the run contained the expected `return a+b`. Edits land on
disk under `--no-git` (no commits needed). `ls -la /tmp/acap/` showed no
`.git/` or `.gitignore` created by this run — only stale artifacts from a
prior pre-`--no-git` capture (timestamps confirmed; Option-3 premise held).

## Provider routing

Aider reads provider credentials from environment variables: typically
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, and
`OPENAI_API_BASE` (for OpenAI-compatible local endpoints — e.g. vLLM,
Ollama, LM Studio). The harness records only the **presence** of each
variable as a boolean in `backend_metadata.provider_env_present` — never
the value. The harness does NOT set provider env vars; provider
configuration is the user's responsibility.

## Edit-format & comparability

Aider auto-selects an edit format per model (Claude → `diff`,
weaker models → `whole`). The backend does **not** force one (Design
Decision 3 — methodology fidelity); the resolved format is parsed from
the `Model: … with <fmt> edit format` line and recorded as
`backend_metadata.edit_format_resolved`. `CCT_AIDER_EDIT_FORMAT` is the
sole opt-in force path and sets `edit_format_forced=true` in metadata.

### Apples-to-apples caveat (`--no-git`)

Aider's published Polyglot leaderboard runs each exercise **inside a git
repo** (Aider's own benchmark harness creates one per exercise). Our
pinned `--no-git` keeps the harness worktree clean for `_write_diff`,
but disables Aider's repo-map (`Repo-map: disabled` in the transcript
above). On single-file tasks this is irrelevant; on multi-file tasks the
repo-map informs edit accuracy and a small drift vs. the leaderboard is
plausible. Tracked for empirical evaluation in
[`gosha70/code-copilot-team#46`](https://github.com/gosha70/code-copilot-team/issues/46)
(git-with-cleanup pattern: run aider with git enabled, then have the
backend finalizer remove `.git/` + revert `.gitignore`; swap to it if
the multi-file delta exceeds 5%).

## Reviewer checklist (verbatim; the 7 points from `tasks.md` TB3.1)

1. Pinned `aider --version` matches `_VERIFIED_VERSION`
   (`aider 0.86.2`); the transcript above was regenerated when the pin
   was last bumped.
2. `_build_argv` emits the contract verbatim — `--yes-always` (NOT
   `--yes`), **`--no-git` present**, `--model` iff `ctx.model` non-empty;
   `--map-tokens`/`--edit-format` absent unless `CCT_AIDER_EDIT_FORMAT`
   (then `edit_format_forced=true`); `--temperature` never (not an Aider
   flag).
3. Prompt is delivered via `--message-file` under `attempt_dir`, not via
   argv and not via stdin.
4. `--no-auto-commits --no-dirty-commits --no-gitignore --no-git` are
   always present; history files point at `attempt_dir`; post-`run()`
   the worktree has no `.aider*`, no `.git/`, and no `.gitignore`.
5. `backend_metadata` carries provider env-presence **booleans** plus
   resolved `edit_format`/`map_tokens` (no `temperature` key — not an
   Aider flag); `str(metadata)` contains no `sk-` or `Bearer ` substring.
6. `timed_out=True` is set on `subprocess.TimeoutExpired` (D5 inherited
   via `run._execute_attempt`); the parser distinguishes
   no-summary (→ `None`) from zero-tokens (→ `0`).
7. The fake-CLI suite (`tests/test_aider_backend.py`) passes per-module
   with no live CLI / no network. The fake shim simulates real Aider's
   `.git/`+`.gitignore` pollution when its argv lacks `--no-git` (the
   negative-control test exercises this), so the cleanliness assertions
   are meaningful regression guards, not no-ops.
