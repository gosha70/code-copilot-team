# Configuration Reference

> **GENERATED — do not edit.** Run `scripts/generate-config-reference.sh` to
> regenerate. Sources of truth: `shared/schemas/automation.schema.json`,
> `shared/schemas/providers.schema.json`,
> `scripts/session_analytics/config_data/defaults.json`, and the environment
> names in `scripts/session_analytics/config.py`. To change an entry, edit
> the source — a drift guard (`--check`) fails the build if this file is stale.

Every setting the harness reads, by the file it lives in. On a machine with
the harness installed, `cct config explain <key>` answers the same questions
for one key — including the value in effect and which layer set it — and
`cct config validate` runs every validator below.

Three rules hold across all of them:

- **A key's default lives with its schema or defaults file, never in prose.**
- **Secrets are named, not stored:** a profile or config holds the *name* of
  an environment variable; the value stays in your shell.
- **More specific wins:** defaults file, then user config, then the
  environment, then command-line arguments.

## `specs/<feature-id>/automation.json`

Per-feature automation contract for an auto-build run: which phases exist,
how the branch is named, what counts as a passing test, which reviewer
gates, and the caps that stop the run. Written from
`shared/templates/sdd/automation-template.json` by `/auto-build`, validated
by `scripts/validate-automation-config.sh`. The schema is closed: an
unknown key is an error, not an ignored line.

29 of these keys carry no description in the schema; their shape is still enforced by `scripts/validate-automation-config.sh`, which refuses any key the schema does not declare.

| Key | Type | Required | What it does |
|---|---|---|---|
| `schema_version` | `1` \| `2` |  |  |
| `profile` | `advisory` \| `pr` \| `merge` \| `unattended` |  |  |
| `branch` | object |  |  |
| `phases` | object |  |  |
| `build` | object |  |  |
| `test` | object |  |  |
| `verification` | object |  | #222 (increment C1 of #190) + #242 (increment C2). C1 implements `coverage`; C2 adds `conformance`; C3 (#239) adds `visual` and promotes `app` to this level — both were previously rejected by name as placeholders for the increment that would define them, and `verification.conformance.app` is now refused by name with a migration message. `test` is still rejected by name by validate-automation-config.sh rather than accepted-and-ignored (an unattended contract must not accept enforcement-looking settings that do nothing). conformance.required is DERIVED from verification.yaml per #190 §6, never operator-set. |
| `verification.conformance` | object |  | #242 (increment C2 of #190 §6): the runtime conformance evaluator. Whether conformance is REQUIRED is derived from specs/<feature>/verification.yaml (any FR mapped to kind runtime_conformance) — an operator `required` key is rejected by name. The application under test is NOT declared here — #239 moved it to verification.app so conformance and visual share ONE lifecycle. The resolved contract (evaluator, app, interface, timeout_sec, criteria set) is frozen at preflight initialisation under the C1 pinning/tamper rules. |
| `verification.conformance.evaluator` | string | yes | providers.toml provider id. The provider MUST declare `conformance_command` — an evaluator-specific command template; declaring it IS the runtime_conformance capability. A healthy reviewer-only provider is refused: reviewer health proves liveness, not the ability to exercise a running application. |
| `verification.conformance.timeout_sec` | integer | yes | Bounds the evaluator invocation, in whole seconds. Frozen with the contract; explicit — no silent default. Integer because every bound in the conformance lifecycle is enforced by integer shell arithmetic (deadlines, TERM→KILL escalation) — a fractional value the schema accepted but the driver could not compute would be an inert setting. |
| `verification.coverage` | object |  | Coverage floors. The FULLY RESOLVED contract (this block plus preset-derived values, plus the captured baseline) is frozen at preflight initialisation and is what every later gate reads — the live preset file is never re-resolved, including on resume. |
| `verification.coverage.command` | string | yes |  |
| `verification.coverage.artifact` | string | yes | Relative path inside the project. Containment is re-resolved with symlinks BEFORE deletion and again AFTER the command exits, since the driver deletes this path and the command is arbitrary project code. |
| `verification.coverage.parser` | `istanbul` \| `lcov` | yes | cobertura and jacoco are refused with 'not implemented in C1' rather than silently treated as passing. |
| `verification.coverage.baseline` | `none` \| `admission` | yes | none = greenfield: no artifact required at admission, absolute floor only. admission = brownfield: capture the base ref and enforce no-regression AND the floor. |
| `verification.coverage.min_line_pct` | number |  |  |
| `verification.coverage.min_branch_pct` | number |  |  |
| `verification.coverage.max_regression_pct` | number |  | Percentage POINTS, not relative. Required (effective, after preset resolution) for baseline 'admission'; rejected for 'none'. Governs exactly the metrics that have a configured floor. |
| `verification.coverage.floor_enforced_at` | `landing` \| `phase` |  |  |
| `verification.coverage.preset` | string |  | Names shared/templates/<preset>/verification-preset.json. Absent or unknown fails closed unless every required floor is supplied here. |
| `verification.coverage.timeout_sec` | number |  | Bounds the arbitrary coverage command. Frozen with the contract; a host with no timeout mechanism refuses a coverage-enabled run on either profile rather than pretending to bound it. |
| `verification.app` | object |  | Driver-owned app lifecycle: the driver, not the evaluator, starts and stops the application (own process group, TERM→KILL stop, output captured to the ledger). The evaluator-facing app interface is `interface` when present, else `ready.url`; command-only readiness with no `interface` is rejected by name — a capable evaluator must never be launched without an address for the app. |
| `verification.app.command` | string | yes |  |
| `verification.app.interface` | string |  | Evaluator-facing address of the running application — an absolute http(s) URL the driver PROBES to bind readiness to the launched instance. Must share ready.url's origin when both are present (validator-enforced). Resolved at freeze: `app.interface` else `ready.url`. Required when readiness is command-based. |
| `verification.app.stop_timeout_sec` | integer | yes | Whole seconds before the app stop escalates TERM → KILL (integer: enforced by shell arithmetic). |
| `verification.app.ready` | object | yes | Readiness proof, bound to the launched instance: the probe MUST fail before launch (an already-answering responder is unattributable) and must succeed within timeout_sec with the spawned process group still alive. Exactly one of url \| command. url must be an absolute http(s) URL sharing app.interface's origin when both are present (validator-enforced). |
| `verification.visual` | object |  | #239 (increment C3 of #190 §6): the UI harness the DRIVER runs at the landing gate. Whether visual verification is REQUIRED is derived from specs/<feature>/verification.yaml (any FR mapped to kind visual) — `required_when_ui_in_scope` is rejected by name, because an operator toggle over a verification requirement is an opt-out of verification. Requires verification.app: the harness needs a running application it did not start. |
| `verification.visual.command` | string | yes | The harness invocation, run in a detached throwaway worktree at HEAD under the frozen bound. It executes in a FRESH checkout without ignored build state, so it must be self-sufficient there (e.g. `npm ci && npm run copilot:review`) — the same obligation C1 places on the coverage command. |
| `verification.visual.artifact` | string | yes | Path, relative to the execution root and contained within it, where the harness writes its result. Deleted before the run and required to be a newly produced REGULAR file afterwards, so a stale verdict can never be read as this run's evidence. |
| `verification.visual.url` | string | yes | The harness's BROWSER BASE — an absolute http(s) URL, frozen and never derived: app.interface is evaluator-facing and may legally be an API base, and readiness may point at a health endpoint, so neither is a navigation base. Validated SAME-ORIGIN with the resolved app address so the harness cannot be pointed at a host the driver never launched. |
| `verification.visual.timeout_sec` | integer | yes | Bounds the harness invocation, in whole seconds. Integer because every bound in this lifecycle is enforced by integer shell arithmetic — a fractional value the schema accepted but the driver could not compute would be an inert setting. |
| `verification.visual.skip_is_failure` | boolean |  | Defaults to TRUE and is frozen with the contract: a result that is degraded, skipped, or does not declare its mode FAILS the gate even when it reports passed. Setting it false is the ONLY way a degraded result lands — an explicit, frozen, auditable choice. |
| `review` | object |  |  |
| `review.max_rounds` | integer |  | Rounds allowed PER ATTEMPT in the gating review loop (default 5). Read by the driver and passed to the runner; CCT_REVIEW_MAX_ROUNDS still overrides. The budget is per attempt so /review-decide retry can actually run another round — a cumulative ceiling made retry a no-op (#227). |
| `review.loop_timeout_sec` | integer |  | Wall-clock budget for the WHOLE review loop across rounds (default 900). Restarts when a parked run resumes, so time spent waiting for a human is not counted against it (#205). Distinct from round_timeout_sec, and from the per-provider timeout_sec in providers.toml which bounds a SINGLE reviewer invocation. |
| `caps` | object |  |  |
| `caps.wall_clock_sec` | number |  |  |
| `caps.cost_usd` | number |  |  |
| `notify` | object |  |  |
| `merge` | object |  |  |
| `routing` | object |  | #248 (increment A of #109): TRUST-ASYMMETRIC by construction — a repository may only NARROW what the user-level registry (~/.code-copilot-team/routing.toml) permits. There is deliberately NO field here that could define a profile, credential, endpoint, protocol, or capability; the validator additionally refuses those keys by name; `tier2` was promoted with #254 T6 and `recovery` with #257 D T3 (both restriction-only). Cross-checks against the registry (unknown ids, unknown route class) happen in the effective-policy merge. |
| `routing.enabled` | boolean |  |  |
| `routing.allowed_profiles` | array of string |  | Restriction only: the effective set is the INTERSECTION of these ids with the user registry's profiles. An id the registry does not define is a named violation at merge time, never a silent widen or drop. |
| `routing.default_task_route` | string |  |  |
| `routing.tier2` | object |  | #254 (increment C of #109) T6, promoted refused->implemented->behaviorally-tested. RESTRICTION ONLY: delegation_enabled=false forbids Tier-2 packet delegation for this repository; true/absent restrict nothing. A repo can never widen what the user registry permits. |
| `routing.tier2.delegation_enabled` | boolean |  |  |
| `routing.recovery` | object |  | #257 (increment D of #109), promoted refused->implemented->behaviorally-tested. RESTRICTION ONLY: false may forbid automatic wake or failback for this repository; true/absent restricts nothing. Probe cadence and health thresholds are user-registry policy and are deliberately absent here — a repo can never widen what the user registry permits. |
| `routing.recovery.wake_enabled` | boolean |  |  |
| `routing.recovery.auto_failback_enabled` | boolean |  |  |
| `unattended` | object |  |  |
| `unattended.on_review_breaker` | `terminate` |  |  |
| `unattended.on_stale_finding` | `terminate` |  |  |
| `unattended.on_origin_gate` | `terminate` |  |  |
| `unattended.budget` | object |  |  |
| `unattended.budget.meter_all_invocations` | boolean |  |  |
| `unattended.budget.estimate_unmetered` | boolean |  |  |
| `unattended.budget.estimate_usd_per_invocation` | number |  | Conservative worst-case debit for an invocation whose real cost is unmeasurable. Debits the SAME caps.cost_usd (no separate allowance); flagged estimated:true in the ledger. |

## `~/.code-copilot-team/providers.toml`

The reviewers available on this machine and the default pairings. Seeded by
`setup.sh` from `shared/templates/provider-profile-template.toml`; validated
by `scripts/validate-providers-profile.sh`.

**Two parsing rules that bite.** The profile parser keeps everything after
`=` as the value, so a trailing `# comment` on a value line becomes part of
it. It also keeps TOML escape sequences literally, so a healthcheck needs
`curl --oauth2-bearer $VAR` rather than an escaped `-H` header.

### Per provider — `[providers.<name>]`

| Key | Type | Required | What it does |
|---|---|---|---|
| `type` | see `provider_type` | yes |  |
| `command` | string |  | Command template for cli/custom providers. {review_request} is replaced with the request file's path and {model} with the model name. Send the tool's own chatter to stderr or /dev/null: stdout is parsed. |
| `conformance_command` | string |  | Command template for a runtime conformance evaluator (auto-build). Must carry the {review_request} placeholder. |
| `timeout_sec` | integer |  | Max seconds for one invocation (default 300). |
| `healthcheck` | string |  | Command that exits 0 when the provider is reachable. Quoting note: the profile parser keeps TOML escapes literally, so pass a bearer token with `curl --oauth2-bearer $VAR`, not an escaped -H header. |
| `model` | string |  | Model name sent with the request, or substituted into {model}. |
| `base_url` | string |  | API base for openai-compatible providers, including the version path (…/v1). |
| `api_key_env` | string |  | NAME of the environment variable holding the key. Never the key. Export it where non-interactive shells see it (~/.zshenv). |
| `host` | string |  | host:port for ollama providers (default localhost:11434). |
| `max_tokens` | integer |  | Response token budget (default 4096). A reasoning model needs headroom beyond its hidden reasoning, or disable_thinking. |
| `temperature` | number |  | Sampling temperature (default 0.1). |
| `disable_thinking` | boolean |  | Turn the model's hidden reasoning off. Sends BOTH chat_template_kwargs.enable_thinking=false (vLLM) and thinking.type=disabled (DeepSeek); a server that rejects one with a 400 is asked again without it. Compared exactly, so the value must be bare `true` with no trailing comment. |
| `price_usd_per_mtok_input` | number |  | Peak, cache-miss input rate per million tokens. Set both rates to make the provider metered; the ledger then debits measured cost instead of the run's per-invocation estimate. |
| `price_usd_per_mtok_output` | number |  | Peak, cache-miss output rate per million tokens. |
| `version` | string |  | Free-text note about the server or CLI build; recorded with the provider fingerprint. |

### Top level

| Key | Type | Required | What it does |
|---|---|---|---|
| `[copyright] company` | string |  | Company name stamped into the copyright header of generated source files. Empty until setup.sh prompts for it on an interactive install. |
| `[defaults] peer_for` | object |  | Subject name to the provider that reviews it when --peer-review names none. Every value must be a declared provider. |
| `[defaults] fallback_chain` | object |  | Subject name to the providers tried in order when the peer fails its healthcheck, or (since #190 D1) ran and produced no review. Never consulted after a verdict. |

## Session analytics — `~/.cct/session-analytics.json` and the environment

Layered: `config_data/defaults.json`, then `~/.cct/session-analytics.json`,
then the repo-root `.env`, then real environment variables, then CLI
arguments. The Studio's Settings page writes the same keys. An API key is
stored by name in the environment, never in the config file.

| Key | Default | Environment variable |
|---|---|---|
| `dsn` | *(empty)* |  |
| `embedding.backend` | `"ollama"` | `CCT_SA_EMBED_BACKEND` |
| `embedding.input_cap_chars` | `8000` |  |
| `embedding.model` | *(empty)* | `CCT_SA_EMBED_MODEL` |
| `embedding.ollama_url` | `"http://localhost:11434"` |  |
| `embedding.workers` | `1` | `CCT_SA_EMBED_WORKERS` |
| `judge.api_key` | *(empty)* | `CCT_SA_JUDGE_API_KEY` |
| `judge.base_url` | *(empty)* | `CCT_SA_JUDGE_BASE_URL` |
| `judge.by_copilot.aider.backend` | `"ollama"` |  |
| `judge.by_copilot.aider.model` | *(empty)* |  |
| `judge.by_copilot.claude-code.backend` | `"ollama"` |  |
| `judge.by_copilot.claude-code.model` | *(empty)* |  |
| `judge.default.backend` | `"ollama"` |  |
| `judge.default.model` | *(empty)* |  |
| `judge.ollama_url` | `"http://localhost:11434"` |  |
| `judge.workers` | `2` | `CCT_SA_JUDGE_WORKERS` |
| `kuzu_path` | *(empty)* | `CCT_SA_KUZU_PATH` |
| `benchmark_runs_root` | *(empty)* | `CCT_SA_BENCHMARK_RUNS_ROOT` |
| `pricing.models.claude-haiku-4-8.cache_read` | `0.08` |  |
| `pricing.models.claude-haiku-4-8.cache_write` | `1.0` |  |
| `pricing.models.claude-haiku-4-8.currency` | `"USD"` |  |
| `pricing.models.claude-haiku-4-8.effective_date` | `"2026-05-01"` |  |
| `pricing.models.claude-haiku-4-8.input` | `0.8` |  |
| `pricing.models.claude-haiku-4-8.output` | `4.0` |  |
| `pricing.models.claude-opus-4-8.cache_read` | `1.5` |  |
| `pricing.models.claude-opus-4-8.cache_write` | `18.75` |  |
| `pricing.models.claude-opus-4-8.currency` | `"USD"` |  |
| `pricing.models.claude-opus-4-8.effective_date` | `"2026-05-01"` |  |
| `pricing.models.claude-opus-4-8.input` | `15.0` |  |
| `pricing.models.claude-opus-4-8.output` | `75.0` |  |
| `pricing.models.claude-sonnet-4-8.cache_read` | `0.3` |  |
| `pricing.models.claude-sonnet-4-8.cache_write` | `3.75` |  |
| `pricing.models.claude-sonnet-4-8.currency` | `"USD"` |  |
| `pricing.models.claude-sonnet-4-8.effective_date` | `"2026-05-01"` |  |
| `pricing.models.claude-sonnet-4-8.input` | `3.0` |  |
| `pricing.models.claude-sonnet-4-8.output` | `15.0` |  |
| `project_ids` | `[]` |  |
| `redaction_mode` | `"code"` | `CCT_SA_REDACTION` |
| `routing_calibration.distance_metric` | `"l2_v1"` |  |
| `routing_calibration.k` | `5` |  |
| `routing_calibration.k_min` | `3` |  |
| `routing_calibration.max_false_downgrade_rate` | `0.05` |  |
| `routing_calibration.min_coverage` | `0.8` |  |
| `routing_calibration.min_sets` | `3` |  |
| `routing_calibration.min_sufficiency` | `0.95` |  |
| `routing_calibration.min_tasks` | `10` |  |
| `routing_calibration.min_trials` | `3` |  |
| `routing_calibration.policy_source` | *(empty)* |  |
| `routing_calibration.repo_policy_source` | *(empty)* |  |
| `routing_calibration.root` | *(empty)* |  |
| `routing_calibration.tier_floor` | `"tier1"` |  |
| `routing_calibration.vote_epsilon` | `1e-06` |  |
| `routing_evidence_roots` | `[]` |  |
| `sessions.noise.min_turns` | `3` | `CCT_SA_NOISE_MIN_TURNS` |
| `sessions.noise.min_duration_seconds` | `60` | `CCT_SA_NOISE_MIN_DURATION_SECONDS` |
| `sessions.noise.path_patterns` | `["/cct-probe", "/private/var/folders/", "/tmp/"]` | `CCT_SA_NOISE_PATH_PATTERNS` |
| `auto_build.ledger_root` | `".cct"` |  |
| `auto_build.active_window_seconds` | `900` |  |
| `similarity.threshold` | `0.55` | `CCT_SA_SIMILARITY_THRESHOLD` |
| `similarity.top_k` | `5` | `CCT_SA_SIMILARITY_TOP_K` |
| `sources.aider` | `"~"` |  |
| `sources.claude-code` | `"~/.claude/projects"` |  |
| `team.active_window_seconds` | `300` |  |
| `team.budgets.team_daily_usd` | *(empty)* | `CCT_SA_BUDGET_TEAM_DAILY_USD` |
| `team.budgets.team_monthly_usd` | *(empty)* | `CCT_SA_BUDGET_TEAM_MONTHLY_USD` |
| `team.budgets.developer_daily_usd` | *(empty)* | `CCT_SA_BUDGET_DEVELOPER_DAILY_USD` |
| `team.budgets.project_daily_usd` | *(empty)* | `CCT_SA_BUDGET_PROJECT_DAILY_USD` |
| `team.runaway.recent_minutes` | `60` | `CCT_SA_RUNAWAY_RECENT_MINUTES` |
| `team.runaway.max_turns_recent` | `300` | `CCT_SA_RUNAWAY_MAX_TURNS_RECENT` |
| `team.runaway.recent_turns` | `50` | `CCT_SA_RUNAWAY_RECENT_TURNS` |
| `team.runaway.max_error_share` | `0.5` | `CCT_SA_RUNAWAY_MAX_ERROR_SHARE` |
| `team.runaway.min_turns_for_error_share` | `20` | `CCT_SA_RUNAWAY_MIN_TURNS_FOR_ERROR_SHARE` |
| `team.runaway.max_cost_recent_usd` | `20` | `CCT_SA_RUNAWAY_MAX_COST_RECENT_USD` |

A key with no variable is set in the config file or the Studio's
Settings page only. A variable that selects for a whole block — the
default judge, for instance — is listed under the tables rather than
guessed onto one row.

### Environment variables with no defaults entry

Read directly by the code that needs them (paths, ids, and the
runtime toggles that have no stored default):

- `CCT_DEVELOPER_ID`
- `CCT_HARNESS_STAMPS`
- `CCT_SA_DB`
- `CCT_SA_DSN`
- `CCT_SA_JUDGE_BACKEND`
- `CCT_SA_JUDGE_MODEL`
- `CCT_SA_ROUTING_EVIDENCE_ROOTS`
- `CCT_SA_TEAM_ACTIVE_WINDOW`
- `CCT_SA_TEAM_ALIASES`

### Environment prefixes

Completed per key by the code that reads them:

- `CCT_SA_CALIBRATION_<KEY>`
- `CCT_SA_SOURCE_<KEY>`

## Where the rest lives

- **Claude Code session settings** (`~/.claude/settings.json`, hooks wiring,
  permissions) — [Setup Cookbook](../adapters/claude-code/docs/claude-code-setup-cookbook.md)
  and [Permissions Guide](../adapters/claude-code/docs/permissions-guide.md).
- **Pi's TOML config** — [Pi Configuration Reference](../adapters/pi/docs/configuration-reference.md).
- **Review and auto-build runtime switches** (`CCT_REVIEW_DIFF_MAX_LINES`,
  `CCT_PEER_REVIEW_ENABLED`, and the rest of the `CCT_*` namespace) — named
  where they are used, in [Auto code review setup](auto-code-review-setup.md)
  and the [auto-build skill](../shared/skills/auto-build-loop/SKILL.md).
