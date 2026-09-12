# Auto code review — setup cookbook

How to have a second model review your work automatically: which
reviewer, what goes in the provider profile, how to prove it works
before it gates a run, how to turn it on per session and per
unattended build, and where to read the result. Everything here was
done and verified on real runs (2026-09-09 → 12); nothing is planned.

The README's [Peer Review (Multi-Copilot)](../README.md#peer-review-multi-copilot)
section describes the mechanism; this page is the ordered setup.

## 1. What "auto code review" is here

A **reviewer** is a second provider that receives a review request —
the diff, the recent commits, the spec artifacts — in a read-only
sandbox and must answer in a fixed format ending in one bare verdict
line: `PASS`, `FAIL` or `INCONCLUSIVE`. The runner
(`scripts/review-round-runner.sh`) parses that, records the findings,
and the caller acts:

- In an **interactive session** started with `--peer-review`, the
  build agent runs `/review-submit` when the work is done; on FAIL it
  addresses the findings and resubmits; on PASS `/phase-complete` may
  proceed.
- In an **auto-build run** (`scripts/auto-build-loop.sh`), the gating
  reviewer named in `automation.json` reviews each phase; FAIL spawns a
  bounded fix session; PASS lets the phase land; INCONCLUSIVE with no
  blocking finding stops the run for review recovery.

The same profile, runner and format serve both.

## 2. Choose a reviewer

| Reviewer | Type | Notes |
|---|---|---|
| A hosted OpenAI-compatible API (DeepSeek, OpenAI, …) | `openai-compatible` | Cheapest and fastest of the three in practice; needs an API key; can be **measured** (§6). |
| A local model behind vLLM or LM Studio (the DGX Spark) | `openai-compatible` | No key, no bill; must have thinking turned off for reasoning models (§3). |
| A CLI (Codex CLI, Claude Code headless) | `cli` | Reviews with the tool's own permissions; `--version` passing does not mean `exec` works — the probe (§4) is what tells you. |

Any reviewer needs two things you can verify before a run: it answers
a request in the required format (the probe), and it can do so on a
request the size of a real review (the diff limit, §7).

## 3. The provider profile

Providers live in `~/.code-copilot-team/providers.toml` (seeded by
`setup.sh`; the annotated template is
`shared/templates/provider-profile-template.toml`). The file holds the
**name** of the key's environment variable, never the key.

### 3.1 A hosted API — DeepSeek, as configured on 2026-09-11

```toml
[providers.deepseek]
type = "openai-compatible"
base_url = "https://api.deepseek.com/v1"
api_key_env = "DEEPSEEK_API_KEY"
model = "deepseek-flash"
timeout_sec = 600
# Thinking is on by default and, on a review-sized request, ran to
# 122k characters at 32768 tokens with no answer: turn it off.
disable_thinking = true
max_tokens = 16384
temperature = 0.1
# Peak, cache-miss rates for deepseek-flash (see §6).
price_usd_per_mtok_input = 0.30
price_usd_per_mtok_output = 1.20
healthcheck = "curl -sf --oauth2-bearer $DEEPSEEK_API_KEY https://api.deepseek.com/v1/models"
```

Put the key where every shell reads it, including the non-interactive
ones the driver spawns:

```bash
echo 'export DEEPSEEK_API_KEY="sk-…"' >> ~/.zshenv
```

Two things learned the hard way:

- The profile parser keeps TOML escape sequences literally, so a
  healthcheck with `-H "Authorization: Bearer …"` inside double quotes
  does not work. `curl --oauth2-bearer $VAR` sends the same header
  without quoting.
- `disable_thinking = true` sends both vLLM's
  `chat_template_kwargs.enable_thinking=false` and DeepSeek's
  `thinking.type=disabled`; each server ignores the other's field, and
  a server that rejects one with a 400 is asked again without it.

### 3.2 A local model — the DGX Spark's vLLM

```toml
[providers.spark]
type = "openai-compatible"
base_url = "http://192.168.1.23:8001/v1"
model = "qwen38-27b"
timeout_sec = 900
max_tokens = 8192
temperature = 0.1
# Qwen3 otherwise spends the budget on hidden reasoning.
disable_thinking = true
healthcheck = "curl -sf http://192.168.1.23:8001/v1/models"
```

Serving the model is covered by the DGX Spark cookbooks
(`docs/dgx-spark/`). Unmetered: every invocation is debited at the
run's conservative estimate (§6).

### 3.3 A CLI

```toml
[providers.codex]
type = "cli"
command = "codex exec --color never -s read-only --skip-git-repo-check - < {review_request} 2>/dev/null"
timeout_sec = 300
healthcheck = "codex --version"
```

`{review_request}` is replaced with the request file's path. The
`2>/dev/null` matters: a CLI that echoes its prompt to stderr would
merge the request into the stream the runner parses.

### 3.4 Default peer and fallback chain

```toml
[defaults]
# What --peer-review uses when no name is given.
peer_for.claude = "deepseek"
# Tried in order when the peer fails.
fallback_chain.claude = ["spark"]
```

Comments go on their own lines: the profile parser keeps everything
after `=` as the value, so a trailing `# …` on a value line becomes
part of the provider name or makes `disable_thinking = true` fail its
exact comparison.

The chain is consulted twice: when the peer fails its **healthcheck**
before a round, and — since #190 D1 — when the peer **ran and produced
no review** (a broken CLI, a reasoning model with no content left). A
verdict from the first reviewer is final; the chain exists for "no
review", never for a second opinion. Both invocations are recorded.

## 4. Prove it works: the probe

Before a reviewer gates anything, send it one real request through the
same path a round uses — the same resolution, adapter, sandbox, timeout
and parser — and require a parseable verdict:

```bash
scripts/review-round-runner.sh . --probe --peer deepseek --subject claude --out /tmp/probe.json
jq '{provider, verdict, duration_sec, invocation_cost_usd, error}' /tmp/probe.json
```

Exit 0 means a verdict came back (any of the three). Exit 2 means
nothing in the chain passed its healthcheck. Exit 3 means the provider
ran and no verdict could be parsed — the answer's tail is in the file.
Unattended auto-build runs do this automatically at admission (#334).

The probe checks **readiness, not capacity**: its request is one line
long. A reviewer that answers it can still fail a review-sized request
if its output budget is spent on reasoning (why `disable_thinking` and
`max_tokens` above) or if the diff it is shown is cut short (§7).

## 5. Turn it on

### 5.1 Per interactive session

```bash
claude-code --peer-review deepseek ~/dev/repo/my-app   # explicit
claude-code --peer-review ~/dev/repo/my-app            # the profile's default peer
claude-code --peer-review-off ~/dev/repo/my-app        # off for this session
```

The launcher exports `CCT_PEER_REVIEW_ENABLED=true` and the peer into
the session; the build agent runs `/review-submit` after the work and
the stop hook enforces it at phase completion. In a session started
without the flag, the same round can be run by hand with the runner
(this is what `/review-submit` does):

```bash
mkdir -p .cct/review
jq -n --argjson start "$(date +%s)" '{current_round:0, attempt:1, loop_start:$start,
  feature_id:"my-feature", phase:"build", subject_provider:"claude", peer_provider:"deepseek",
  review_scope:"both", target_ref:"my-branch", last_verdict:null, findings:{}}' > .cct/review/state.json
CCT_REVIEW_BASE_REF=origin/master CCT_REVIEW_DIFF_MAX_LINES=4000 scripts/review-round-runner.sh .
```

### 5.2 Per auto-build run

In `specs/<feature>/automation.json`, the `review` block names the
gating reviewer; advisory lenses have `"gating": false` and never gate
or fall back:

```json
"review": {
  "reviewers": [
    { "provider": "deepseek", "specialization": "correctness", "scope": "both", "gating": true }
  ],
  "max_rounds": 3,
  "round_timeout_sec": 900,
  "loop_timeout_sec": 600
}
```

The driver probes the gating reviewer at admission, debits every
invocation, falls back once per round on "no review", and stops for
recovery on an inconclusive verdict.

## 6. Cost

- A reviewer with `price_usd_per_mtok_input` and
  `price_usd_per_mtok_output` set is **measured**: the adapter prices
  the response's token usage at those rates and the ledger debits that
  figure. Configure the provider's peak, cache-miss rates; the result is
  a conservative calculated cost, never the exact bill when caching or
  off-peak discounts apply. A DeepSeek review round measured $0.004–
  $0.006 on the runs of 2026-09-11/12.
- A reviewer without rates is **unmetered** and debited at the run's
  conservative per-invocation estimate (`unattended.budget.estimate_usd_per_invocation`,
  default $2). That is what the Spark costs the ledger, not the bill.
- A failed invocation is debited like any other (#336); a round that
  fell back debits both.

## 7. The diff limit

The runner shows the reviewer at most `CCT_REVIEW_DIFF_MAX_LINES` lines
of diff (default 500). A normal small feature exceeds that; a reviewer
shown a truncated diff will, if honest, answer INCONCLUSIVE (run 6,
2026-09-12). Set the limit for the session or the run:

```bash
CCT_REVIEW_DIFF_MAX_LINES=4000 scripts/auto-build-loop.sh my-feature
```

DeepSeek's context is a million tokens; 4000 lines is not a strain.

## 8. Where the result is

- `.cct/review/findings-round-N.json` — the parsed round: verdict,
  findings (`severity|category|file|line_hint|description|suggested_fix`),
  the reviewer that answered, `fallback` when one happened, the
  measured cost.
- `specs/<feature>/collaboration/build-review.md` — the artifact the
  runner writes on PASS (plan consults write `plan-consult.md`). Commit
  it with the work; on the runs of this week, the pre-fix review was
  committed unchanged as evidence and the fixes followed in their own
  commit.
- The Studio **Runs** tab (`session-analytics runs`) — for auto-build
  runs: the probe's answer, any fallback, the review rounds per phase,
  cost with the estimated portion distinct, and the human verdict you
  set on the resulting PR.

## 9. Check-list

1. Provider entry in `providers.toml`; key exported in `~/.zshenv`.
2. `providers-health.sh --provider <name>` → usable.
3. `review-round-runner.sh . --probe --peer <name> --out f.json` → exit 0.
4. `peer_for.claude` and `fallback_chain.claude` set.
5. `CCT_REVIEW_DIFF_MAX_LINES` sized for your diffs.
6. Rates set if the provider bills per token.
7. `--peer-review` on the session, or the `review` block in
   `automation.json` for a run.
