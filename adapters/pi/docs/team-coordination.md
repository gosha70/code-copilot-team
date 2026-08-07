# Team coordination (`/cct:team`)

Local, opt-in team coordination for the Pi adapter — the live wiring of the
already-built T8.1/T8.2 team libraries (`agents/team.ts`, `agents/team-status.ts`)
into Pi's session. This is **Slice A** of the #174 epic; the centralized,
cross-developer plane (registry, cost rollups, budget alerting, dashboard) is a
separate effort shaped in `specs/pi-team-controller/plane-shaping.md`.

```sh
/cct:team create <teamId> [--no-plan-approval] | join <memberId> |
  task <taskId> <title…> [--assign <m>] [--worker <w>] | assign <taskId> <m> |
  approve | activate | claim <taskId> | complete <taskId> | fail <taskId> |
  message <to|all> <body…> | leave | recover | shutdown [--reason …] | close |
  status | synthesize                                    # in a Pi session

pi-code team status|synthesize [--json]                  # read-only, out of session
```

## Opt-in

Teams are **off by default**. Mutating `/cct:team` commands are refused until
`agents.teams_enabled = true` (per-project or global config). Read-only
`status`/`synthesize` render whenever a valid ledger exists.

## Two-file ledger, at the canonical (primary) root

Team state is two files under the **primary** repo checkout: `.cct/team.json`
(the coordination ledger) and `.cct/team-messages.jsonl` (a redacted, polled
message append-log). It is **separate** from the worktree ledger — a task links
to a T7.3 worker only by an optional `workerId`.

**Fail-closed root.** Every command resolves the canonical root via the shared
git common dir (`primaryRepoRoot`). Run from a **linked worktree**, a command
operates on the **primary** ledger — never a per-worktree copy. If the primary
root cannot be resolved (git failure / not a repo), a mutation **refuses and
writes nothing** (audited `team.root-unresolved`); a read reports "no canonical
repository root".

## Identity: declared attribution, **not** authentication

A worker session declares its identity via two **required** env vars:

| Var | Meaning |
|---|---|
| `CCT_TEAM_ID` | the team the session claims to belong to |
| `CCT_TEAM_MEMBER_ID` | the member id the session acts as |

The actor for every actor-scoped command comes from this **declared** identity —
**never** a command argument. On every mutation the wiring re-validates, inside
the ledger lock: `CCT_TEAM_ID` **must equal** `ledger.teamId` (team binding), and
the member must be **active** right now (never a cached role/status).

> **Honest boundary:** this is **attribution, not authentication**. A co-located
> session can declare any *existing* member id of the same team, so Slice A does
> **not** prevent impersonation among cooperating local agents. Authenticated
> authorization (a controller-issued capability, or binding to the *validated*
> T7.3 worker identity) is an epic-level decision — see `plane-shaping.md`.

## Authorization tiers

| Subcommands | Requires |
|---|---|
| `create` | declared identity; `<teamId>` must equal `CCT_TEAM_ID` (bootstrap — no pre-existing membership; establishes the lead) |
| `join`, `task`, `claim`, `complete`, `fail`, `message`, `leave`, `shutdown` | an **active member** |
| `assign`, `approve`, `activate`, `recover`, `close` | the **active lead** |

- `create` never overwrites an existing or corrupt `team.json`.
- `close` is refused while any task is still `claimed`.
- The **sole active lead cannot `leave`** a non-closed team (there is no lead
  transfer in this slice) — `close` it instead.
- `message` validates the recipient (`all` or a member) and that the team is
  open, then appends (redacted) without rewriting `team.json`.

## CLI gate semantics (out of session)

`pi-code team status|synthesize` runs **outside** a Pi session, where project
config is untrusted. It renders whenever a valid ledger exists — a project-only
`agents.teams_enabled` opt-in is honored for the actual (in-session) commands but
is **unobservable** here, so `--json` reports `enabled: "true" | "unknown"`
(never an authoritative `false`) plus the standard trust note.

## Degraded by design

Pi has no team primitive, so this is coordination **state**, not execution: peers
run via the T7.2/T7.4 runners separately (the controller never spawns), messaging
is a **polled** append-log (not a live transport), and `status` is an **on-demand
snapshot** (not a live-updating UI). Every action is audited (`team.*`).
