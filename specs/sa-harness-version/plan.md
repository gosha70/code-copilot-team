---
spec_mode: lightweight
feature_id: sa-harness-version
risk_category: data
justification: |
  A hook, an install-time file, five columns with a version bump, an
  adapter join, one aggregate, one panel, two filters, tests. The
  green-field ruling makes the column change ordinary but it does force
  a store recreation, which is said up front. FR-1..FR-8 in spec.md
  state the behaviour.
status: approved
date: 2026-09-24
issue: "#371"
origin:
  issue: "#371"
  transcripts:
    - specs/sa-harness-version/origin/2026-09-24-owner-direction.md
  user_messages:
    - "2026-09-22: 'I would rather work on extending capabilities of Session Analysis rather using ML Flow'"
    - "2026-09-22: 'Can you start planing the addressing the features listed in issues/371?'"
  origin_claim: |
    Slice A4 of #371: every session carries the harness it ran under
    (cct version and sha, the installed rules/skills digest, the
    providers-profile digest, the CLI version) and the Studio groups and
    compares sessions by it (cost, turns, errors, rework, judge rates),
    so "did the new skill change anything" is answerable. Schema change
    allowed; a column on an existing table means the store is recreated
    on the owner's word.
---

# Plan: harness version + compare (A4)

Two PRs under #371 (owner's ruling, 2026-09-24): **A4a** stamp, **A4b**
compare. Same bundle; tasks.md marks which PR each task belongs to.

## The shape of it

```
adapters/claude-code/.claude/hooks/harness-stamp.sh      SessionStart: one JSON line per session into ~/.cct/harness-stamps.jsonl (setup.sh-only; NOT in CC_PLUGIN_HOOKS)
adapters/claude-code/.claude/settings.json               the hook registered under SessionStart
adapters/claude-code/setup.sh                            installs the hook; writes ~/.cct/harness.json (version, full sha, installed_at) on install and --sync
scripts/session_analytics/config_data/ddl/postgres/001_core.sql   six nullable columns on copilot_session (five facts + harness_mixed)
scripts/session_analytics/relational/db.py               _SCHEMA_VERSION 10; six entries in _REQUIRED_COLUMNS
scripts/session_analytics/constants.py                   HARNESS_* column names, dimensions, ledger filename, bounds
scripts/session_analytics/contracts.py                   RawSession.harness: Optional[HarnessStamp]
scripts/session_analytics/harness_stamps.py              read_ledger(path) → {session_id: (earliest HarnessStamp, mixed)}, sanitised on read
scripts/session_analytics/adapters/claude_code.py        cli_version(s) from `version`; stamp attached by native session id; mixed when versions differ
scripts/session_analytics/config.py                      the ledger path (CCT_HARNESS_STAMPS or the default; environment-only so the hook sees the same)
scripts/session_analytics/relational/store.py            upsert_session writes the five columns
scripts/session_analytics/api/dashboard.py               harness_aggregates(db, noise, by)
scripts/session_analytics/api/server.py                  GET /api/dashboard/harness; /api/sessions gains the closed `harness=<dim>:<value>|mixed|unstamped` filter
scripts/session_analytics/mcp/tools.py                   _SESSION_COLS gains the six; the harness filter + per-dimension facets; harness_aggregates tool
scripts/session_analytics/mcp/server.py                  the tool wrapper
studio/lib/api.ts                                        HarnessAggregates, SessionRow stamp fields, filters
studio/lib/harnessView.ts                                short digests, dimension labels, the unstamped rule (for states-check)
studio/components/HarnessPanel.tsx                       "Sessions by harness version" on the Dashboard
studio/components/SessionFilters.tsx, lib/filterView.ts  the harness filter (dimension + value, mixed, unstamped)
studio/components/SessionHeader.tsx                      the stamp facts
studio/scripts/states-check.mjs                          panel + header states
scripts/session_analytics/tests/test_harness_stamps.py   ledger reader, hook invocation, adapter join, store, aggregates
scripts/session_analytics/tests/test_api.py              route + filters
scripts/session_analytics/tests/fixtures/claude_code/…   `version` on the fixture records; a ledger fixture
scripts/session_analytics/README.md, docs (hooks table)  one section, one row
```

## Decisions

**D1 — the stamp is taken by a SessionStart hook, not at ingest.**
The issue row says "at ingest", and that is where the columns are
written; but the *facts* must be captured when the session runs.
Ingest-time capture would stamp every `--full` re-ingest of old sessions
with today's rules digest, which is the one thing a compare must never
do. Claude Code already runs two CCT SessionStart hooks and hands every
hook the `session_id`; a third hook that appends one line to a ledger
is the smallest honest source. Recommended. Alternative: capture at
ingest only for sessions newer than the last `--sync` — a guess dressed
as a fact; rejected.

**D2 — what the harness version is: five facts, not one string.**
`cct_version` + `cct_sha` (the release and the exact commit the
instructions were installed from, written by `setup.sh` to
`~/.cct/harness.json` because only the installer knows the repo; the
sha is the **full 40 characters** — it claims to identify a commit, and
a short sha is only temporarily unique; shortened for display only),
`instructions_digest` (what is actually in `~/.claude` now — rules,
skills, agents and commands, hand edits included; named for what it
covers), `providers_digest` (the routing/judge configuration in
force), `cli_version` (from the transcript, free). Each is a dimension
a person may want to group by; a single concatenated string could not
be. Digests only, never contents: the profile is API-key-adjacent.
Owner's corrections 2026-09-24: full sha, honest name.

**D2b — the hook is setup.sh-only, not in the generated plugin.** A
plugin-only session loads its instructions from `CLAUDE_PLUGIN_ROOT`,
not `~/.claude`, and has no `harness.json`: a hook there would hash the
wrong tree with confidence. `generate.sh` ships only the hooks named in
`CC_PLUGIN_HOOKS` and the plugin's `hooks.json` is authored, so leaving
the hook out is the whole change; plugin-only sessions are unstamped
and the README says so. Making the hook installation-root-aware is a
later slice if wanted. Owner's ruling 2026-09-24.

**D3 — columns on `copilot_session`, not metadata rows.** The compare
is a `GROUP BY`, the A2 filters and facets are columns, and
`_session_dict` reads columns positionally. EAV rows would need a
pivot in every reader. Cost: `_SCHEMA_VERSION` 10 and the six names in
`_REQUIRED_COLUMNS`, so **the owner's store is refused until recreated
and re-ingested with `--full`**, exactly as A1 was; sessions that ran
before the hook existed stay unstamped and the compare names them.
Said here so it is not a surprise at merge.

**D4 — the ledger is untrusted local input; earliest wins, and mixed
is a fact.** Read once per ingest, sanitised on read like
`heartbeat.py`: bounded string lengths, digests must be 64 hex
characters, the sha 40, `session_id` bounded, malformed lines skipped
with one warning per run, a missing file a no-op. A session's stamp is
its **earliest** valid line: a resumed session may span a harness
update, and last-wins would attribute its earlier turns to the newer
harness — the very error the design exists to prevent. A later line
that differs in any fact, or a transcript carrying two CLI versions,
sets `harness_mixed`; identical lines from a resume or compaction do
not. The header shows "mixed"; the compare puts mixed sessions in a
named row, under neither version. Owner's correction 2026-09-24.

**D5 — the compare inherits `developer_aggregates`' rules, with a real
judge score.** No ranking (ordered by value), unknown cost never zero
(priced sum with coverage), the degenerate case named
(`single_group`), the mixed and unstamped groups named rows. Metrics:
sessions, median turns, median tool calls, errors per 100 turns, priced
cost + coverage, and from the packaged rubric `avg_interaction_quality`
(the mean of `session_kpi.avg_interaction_quality` over sessions that
have one), rework rate and correction rate over labelled turns, each
with labelled/answered coverage. **Judge-derived metrics are NULL, not
zero, when no applicable label exists.** Owner's addition 2026-09-24.

**D6 — a Dashboard panel plus one closed filter, not a page.** The
panel is the same shape as the Developers panel and offers all five
dimensions; so that every row can link to exactly its sessions, the
sessions list takes **one closed filter** `harness=<dimension>:<value>`
with `mixed` and `unstamped` as the two named cases, plus a facet per
dimension. The session header shows the stamp. No nav entry (the #307
cut stands). Owner's correction 2026-09-24: links and filters must
agree.

**D7 — the hook never touches the model or the session.** Exit 0
always, no stdout, bounded by the settings timeout (10 s), skips when
`jq` or a sha tool is missing. It runs on every SessionStart including
resume/compaction, which appends another line; the reader keeps the
earliest and notes a difference.

**D8 — the hook is tested by direct invocation.** `tests/test-hooks.sh`
drives the real cmux and is not run by the builder (a standing host
side-effect); the new hook gets a Python test that runs it with a temp
`HOME`, a fake `~/.claude` tree and a stdin JSON.

## The split (owner's ruling, 2026-09-24)

- **A4a** — hook, installer stamp, transcript CLI version, six columns
  including `harness_mixed`, adapter join, session header. Starts
  collecting trustworthy stamps as soon as it is installed.
- **A4b** — aggregates, the closed all-dimension filter and facets, the
  Dashboard panel, the MCP surface. Reviewable on its own.

## Verification

- `unittest`: `test_harness_stamps.py` (ledger reader incl. malformed,
  unrelated, identical and differing duplicate lines; hook invocation
  with and without `harness.json`/profile, 40-hex sha, 64-hex digests;
  adapter join on the fixture incl. two CLI versions → mixed;
  `upsert_session` writes and re-ingest keeps the columns; a pre-10
  store refused; the generated `hooks.json` does not name the hook),
  and for A4b aggregates incl. the mixed and unstamped rows, unknown
  cost, NULL judge metrics, coverage, single group; `test_api.py`
  (route, `by` validation → 400, the closed `harness` filter for every
  dimension plus mixed/unstamped, facets), MCP contract.
- `states-check`: header stamp / mixed / unstamped (A4a); panel states
  (groups, mixed and unstamped rows, single group, empty) (A4b).
- `tsc --noEmit`, `next build`, `bash -n` on the hook, `shellcheck` if
  present.
- A scratch store on other ports with a ledger written by the real
  hook on this machine: sessions stamped after install, older ones
  unstamped, the panel groups them. The owner's instance is never
  restarted; **their store is recreated only on their word**, after the
  merge, and only sessions that run after the hook is installed will
  carry a stamp.
- `validate-spec.sh --all`, `check-origin-alignment.sh
  sa-harness-version`, `check-doc-accuracy.sh`, `git diff --check`,
  `scripts/generate.sh` (the plugin picks up the hook) and its sync
  check, then `/review-submit`.

## Risks

- **The stamp starts empty.** Nothing before the hook is installed is
  stamped, and the owner's own sessions will only start accruing after
  they run `setup.sh --sync`. Stated in the README and the panel.
- **A hand-edited rule changes the digest** without a version change:
  intended (the digest is what was in force), but two "same version"
  installs can differ; the panel shows both facts.
- **Hook count on SessionStart grows to three**; each is bounded and
  independent, and the hooks test suite is unchanged in kind.
- **Plugin-only users get no stamp** (D2b); the README says so, and
  the compare's unstamped row makes the gap visible rather than silent.
- **Prettier churn on `.tsx`**: diffs checked after every edit.
