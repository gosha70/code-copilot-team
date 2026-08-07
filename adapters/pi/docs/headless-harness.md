# Headless harness recipes (#179)

Drive the **enforced** harness (CCT runtime loaded, all gates active) from
scripts, internal platforms, or CI — no TUI. Built on the surface this
harness has verified end-to-end: **`pi --mode json`** (the same mechanism
the T7.2 subagent runner uses in production).

## One-shot enforced run

```bash
pi-code -- --mode json -p "Run the test suite and summarize failures" --no-session
```

Everything after `--` reaches pi unmodified; `pi-code` loads the CCT
enforcement runtime via `--extension` first, so permission rules,
protected paths, and audit apply to the headless run exactly as they do
interactively. Exit codes and signals are pi's own (`pi-code` `exec`s).

`--no-session` keeps one-shot runs from accumulating session state; drop
it if you want the run resumable.

## Reading the result

`--mode json` emits JSON lines; the final result envelope carries (the
T10.3 contract, the same fields the subagent runner parses):

```json
{ "type": "result", "subtype": "success", "total_cost_usd": 0.0123, "session_id": "..." }
```

```bash
out="$(pi-code -- --mode json -p "…" --no-session)" || { echo "run failed: $?"; exit 1; }
echo "$out" | jq -r 'select(.type == "result") | "\(.subtype) cost=\(.total_cost_usd)"'
```

A nonzero exit is a failed run regardless of any envelope; treat "no
envelope in the output" as an error too (both rules mirror the runner).

## Minimal CI job (GitHub Actions shape)

```yaml
jobs:
  agent-task:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-node@v4
        with: { node-version: "22" }
      - name: Install pi + the CCT harness
        run: |
          npm install -g @earendil-works/pi-coding-agent
          ./adapters/pi/setup.sh
      - name: Enforced headless run
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          pi-code -- --mode json -p "$TASK_PROMPT" --no-session | tee run.jsonl
          jq -e 'select(.type=="result") | .subtype == "success"' run.jsonl > /dev/null
```

For unattended postures (ask-resolution, sandbox requirements) see
[unattended-runs.md](unattended-runs.md); for worker isolation use
`pi-code worktree run` ([worktree-workers.md](worktree-workers.md)).

## About `pi --mode rpc`

pi also ships an RPC mode (`docs/rpc.md` in the pi package) for
long-lived, bidirectional programmatic control. **This harness has not
exercised it** — the recipes above are the CCT-verified path. If you adopt
RPC mode directly, you are on pi's contract, not this harness's; the CCT
runtime still loads via `--extension`, but none of the harness's headless
semantics documented here (envelope parsing, exit-code rules) have been
validated against it.

## Guardrails in headless runs

The [extension template](../resources/extension-template/README.md)
composes with headless runs: auto-discovery applies when the project is
trusted in the headless environment; otherwise pass a **pinned, absolute**
`--extension` path you control (see the template README's security note
about explicit paths bypassing the trust gate — in CI, the pinned path is
the appropriate form).
