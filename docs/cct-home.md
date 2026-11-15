# The CCT home

Everything CCT keeps for a user lives in one directory, the **CCT home** `${CCT_HOME:-~/.cct}`, with the legacy `~/.code-copilot-team` read as a fallback through 2.1.x and `cct home migrate` to move what is left there.

```
${CCT_HOME:-~/.cct}
```

| Entry | Written by | Read by |
|---|---|---|
| `providers.toml` | `setup.sh` (seed), you | peer review, auto-build, routing, doctor, Studio |
| `routing.toml`, `routing-state.json`, `routing-probe-ledger.json` | you, the supervisor | `cct routing`, the supervisor |
| `harness.json`, `harness-stamps.jsonl` | `setup.sh`, the harness-stamp hook | Session Analytics |
| `session-analytics.json`, `session-analytics.db`, `kuzu/` | you, `cct sa setup` | Session Analytics |
| `pi/`, `config.toml` | `setup.sh --pi` | `pi-code`, the Pi runtime |

`cct home` prints the home in use and what, if anything, is still read from
the legacy location:

```
$ cct home
home: /Users/you/.cct
override: none (set CCT_HOME to use another directory)
entries:
  harness.json                 home
  providers.toml               legacy: read from /Users/you/.code-copilot-team (fallback ends in 2.2)
  routing.toml                 conflict: in both homes; the home copy is read, the legacy copy is ignored
move the legacy entries with: cct home migrate   (preview: cct home migrate --dry-run)
resolve each conflict by hand: keep one copy, then remove the other from /Users/you/.code-copilot-team
```

## The override

`CCT_HOME` is the one override. When it is set, that directory is the home
for every reader in every language, and nothing falls back to any other
location. It is the variable to set for tests, for a second installation
beside the first, or for a home on another volume.

## The legacy home and the fallback (2.1.x only)

Before 2.1 the home was `~/.code-copilot-team`. Through the 2.1.x line every
reader applies one rule, in this order:

1. `CCT_HOME` set: `$CCT_HOME/<entry>`, no fallback.
2. `~/.cct/<entry>` exists: that.
3. `~/.code-copilot-team/<entry>` exists: that (read-only fallback).
4. Otherwise `~/.cct/<entry>` is where the entry is created.

The fallback is per entry, so a half-migrated home still works, and the home
always wins when both have an entry. The rule lives in three resolvers,
`scripts/lib/cct-home.sh`, `scripts/session_analytics/home.py` and
`adapters/pi/runtime/config/home.ts`; installed scripts that run without a
checkout (the harness-stamp hook, the `claude-code` launcher, `pi-code`) carry
a verbatim copy of the bash block, which the structure suite keeps identical.

**2.2 removes the fallback.** The first 2.2 change deletes step 3; a file left
in the legacy home is then "not found", and the message names the migrate
command below. `cct doctor` and `setup.sh` warn about every entry still
served from the legacy home until then.

## Migrating

Nothing moves on its own. The one mover is:

```
cct home migrate --dry-run    # what would move, changes nothing
cct home migrate              # move every legacy entry into the home
```

`migrate` moves each entry of `~/.code-copilot-team` into the home. It never
overwrites: an entry present on both sides is left in place, reported, and the
command exits 1 so you can resolve it by hand. The move is a no-replace
operation, not a check followed by a move, so a target that appears while
`migrate` runs is also left alone and reported. A directory moves whole: its
name is claimed, then the directory is renamed onto the claim in one step, so
modes and timestamps are kept and no directory is ever left split between the
two homes (if anything lands in the claim meanwhile, the rename fails and the
legacy directory is untouched). Moving a directory needs `python3` on PATH.
When the home is on another volume, the tree is copied into a staging
directory beside the target (`.cct-migrate.*`) and published by the same
rename; the legacy copy is removed only after that. `migrate` withdraws its
own staging directory and unpublished claim on exit or a signal, and only
while the object at that path is still the one it created (same device and
inode), never a directory that has since been published there; a
`.cct-migrate.*` directory it did not create is reported and left alone.
It never deletes the legacy directory; once it is empty, remove it yourself.

The per-project directory `<repo>/.code-copilot-team/` (the Pi runtime's
project config) is not part of the user home and is unchanged by this page; its
rename is tracked separately (#411 ruled it its own issue).
