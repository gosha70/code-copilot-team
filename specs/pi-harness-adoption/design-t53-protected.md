# T5.3 Design Read — package-install protection + network policy (FR-009)

Status: **design read — paused for decisions before implementation.**
Scope: make `security.allow_package_install` and `security.deny_network`
actually enforce, at the exec-tool command path. The other T5.3 items
(canonicalization, symlink defenses, git protection, secret-path protection)
already exist; only these two are declared-but-dead (tasks.md T5.3 note).

## 1. Where the flags are declared today (and unused)

- `loader.ts` BUILTIN_DEFAULTS: `security.allow_package_install = true`,
  `security.deny_network = false`, `security.fail_closed = true`.
- `profiles.ts`: `air-gapped` sets `deny_network = true`; `peer-reviewer` sets
  `allow_package_install = false`; `ci` sets `sandbox_required = true`.
- `floor.ts` SECURITY_FLOOR: `deny_network`/`fail_closed` = `bool-or`,
  `allow_package_install` = `bool-and` — floor already lets a trusted project
  STRENGTHEN (deny more) but not weaken. No enforcement change needed there.
- `lint.ts`: both keys recognized (drift guard satisfied).
- **Read by no enforcement point.** `security.fail_closed` is likewise unused
  (only appears in a CLI help string) — T5.3 gives it its first real role.

Consequence: on default config (`allow_package_install=true`, `deny_network=false`,
`fail_closed=true`), enforcement bites **only** for profiles/overrides that flip
the flags (peer-reviewer, air-gapped). Default users see no new blocking.

## 2. Current exec-tool path

`index.ts` `tool_call` handler, `EXEC_TOOLS = {bash}`: takes the command, runs
`checkCommand(rules, command)` (permissions.ts). `checkCommand` uses
`splitCommands()` (chained/quoted/substitution-aware) and matches each piece
against `commandsDeny` (prefix, word-boundary) then `commandsAsk`. Verdicts feed
`block(...)` which audits `{mode, actor, decision, rule, subject, origin}`.

T5.3 adds two new classifiers invoked on the **same per-piece loop**, gated on
the two flags, before returning allow.

## 3. Classification — avoiding overblock (the core question)

### Package-install (block when `allow_package_install === false`)
Match **manager binary + install subcommand**, never the manager alone:

| Manager | Install verbs (first non-flag arg) |
|---|---|
| npm | install, i, ci, add, update |
| yarn | add, install (bare `yarn` = install) |
| pnpm | add, install, i |
| pip / pip3 / `python -m pip` / `uv pip` | install |
| poetry | add, install |
| cargo | install, add |
| go | get, install |
| gem | install |
| apt / apt-get | install |
| brew | install |
| pipx | install |
| bundle | install, add |
| composer | install, require |

Negative controls that must **not** match: `npm run build`, `npm test`,
`cargo build`, `go build`, `pip --version`, `python app.py`, `make`, `git commit`.
The manager+verb rule handles these (verb slot is `run`/`build`/`--version`/etc).

### Network (block when `deny_network === true`)
Match known network CLI binaries + network git subcommands:
`curl`, `wget`, `nc`/`ncat`/`netcat`, `ssh`, `scp`, `sftp`, `telnet`, `ftp`,
`rsync`, and `git {clone,fetch,pull,push,remote}`. Local git
(`status,commit,add,diff,log,checkout,branch`) never matches. Package installs
also hit the network, so under `deny_network` they are caught by BOTH classifiers
(fine — deny wins).

### Normalization
Strip a leading `sudo ` / `env VAR=val ...` prefix before classifying (prevents
`sudo npm install` bypass). Reuse `normalizeCommand()` (whitespace) and
`splitCommands()` (chained pieces) — no new command parser.

## 4. fail-open / fail-closed + audit

The classifiers give a definite match / no-match for known cases. Genuinely
**ambiguous** cases (see decisions) resolve via `security.fail_closed`:
- `fail_closed = true`  → ambiguous-but-plausible install/network under a
  restricting flag ⇒ **deny** (record `decision: deny`, `rule:
  security.<flag>`, add `(fail-closed)` to the reason).
- `fail_closed = false` → ambiguous ⇒ **allow**.

New audit origins: `package-policy`, `network-policy`. Every block (and every
fail-closed ambiguous block) is audited via the existing `audit()` with
`subject` = the offending command piece. No secret leakage (command text only,
already truncated to 400 chars).

These are policy **denials**, not interactive asks (the flags are booleans:
`deny_network=true` means deny). Headless resolution does not apply — nothing is
gated on a prompt.

## 5. Ambiguities — decisions needed BEFORE implementation

- **A. `npx` / `bunx` / `pnpm dlx` / `uvx` (download-and-run).** They fetch a
  package (install-ish) AND use the network. Recommend: classify as **both**
  package-install and network, so they block under either restricting flag.
  Confirm — or treat as ambiguous (fail_closed-governed) instead?
- **B. deny_network = command-name denylist, NOT a sandbox (P5).** A program that
  opens a socket without a known network binary (e.g. `python fetch.py`) is NOT
  caught. Recommend: enforce the denylist and **report** the boundary honestly
  (doctor/audit note), never imply true network isolation. `sandbox_required` is
  the separate sandbox concern. Confirm.
- **C. Hard `deny` vs `ask`.** Recommend hard `deny` (flags are booleans;
  `fail_closed` governs only the ambiguous tail). Confirm — or make violations
  `ask` (interactive) with headless deny?
- **D. `fail_closed` gets its first enforcement role** (ambiguous-command
  disposition). Confirm this is the intended semantics for the currently-unused
  flag, or keep T5.3 to definite matches only and leave `fail_closed` unused.
- **E. git-network under `deny_network`.** Block `git clone/fetch/pull/push/remote`
  when `deny_network=true` (overlaps existing `git push --force` deny — fine).
  Confirm scope, esp. whether `git push`/`pull` (not just `--force`) should block
  only under deny_network.
- **F. `sudo`/`env` prefix stripping** before classification. Recommend yes.
  Confirm.

## 6. Proposed surface (pending approval)

- New module `adapters/pi/runtime/policy/protected-ops.ts`:
  `classifyPackageInstall(piece) -> {match, manager, ambiguous}` and
  `classifyNetwork(piece) -> {match, tool, ambiguous}` (pure).
- `permissions.ts`: extend `PermissionRuleSet` with `denyNetwork: boolean`,
  `allowPackageInstall: boolean`, `failClosed: boolean` (populated in
  `rulesFromConfig`); add `checkExecPolicy(rules, command)` returning a
  `PermissionVerdict` (or fold into `checkCommand`).
- `index.ts` exec path: call the new check after `checkCommand`, before allow;
  block + audit with the new origins.
- Doctor line + `/cct:hooks`-style report? (report the active exec policy).
- **No config schema change** (keys already exist) → T1.7 drift guard untouched.

## 7. Fixtures/tests before flipping live

- Package-install positives (each manager+verb) blocked when
  `allow_package_install=false`; negatives (`npm run build`, `cargo build`, `go
  build`, `pip --version`, `python app.py`, `git commit`) allowed.
- Network positives (curl/wget/nc/ssh/scp/sftp/telnet/ftp/rsync/git-network)
  blocked when `deny_network=true`; local git + ordinary commands allowed.
- Chained: `echo hi && npm install` blocked; `echo hi && ls` allowed.
- `sudo npm install` / `env X=1 pip install` blocked (prefix stripped).
- Ambiguous (`npx foo`, unknown manager) → fail_closed deny vs fail_open allow.
- **Default-config regression guard**: with defaults
  (`allow_package_install=true`, `deny_network=false`) NOTHING new blocks.
- Audit assertions: origin `package-policy` / `network-policy`, correct rule.
- Floor: trusted project may strengthen (`deny_network=true`) but a
  non-relaxation layer cannot weaken it.

## Decision checklist for approval

1. A (npx/bunx classification), 2. B (denylist-not-sandbox boundary + reporting),
3. C (deny vs ask), 4. D (fail_closed role), 5. E (git-network scope),
6. F (sudo/env stripping). Confirm each (or adjust), then I implement narrowly
with the fixtures above and flip enforcement on only for the flags' non-default
values.
