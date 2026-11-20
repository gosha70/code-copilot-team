# The CCT home

Everything CCT keeps for a user lives in one directory, the **CCT home** `${CCT_HOME:-~/.cct}`, with the legacy `~/.code-copilot-team` read as a fallback through 2.1.x and `cct home migrate` to move what is left there.

```
${CCT_HOME:-~/.cct}
```

| Entry | Written by | Read by |
|---|---|---|
| `providers.toml` | `setup.sh` (seed), you | peer review, auto-build, routing, doctor, Studio |
| `routing.toml`, `routing-state.json`, `routing-probe-ledger.json` | you, the supervisor | `cct routing`, the supervisor |
| `llms.toml` | you | `cct start --llm`, `cct llm` ([llm-catalog.md](llm-catalog.md)) |
| `harness.json`, `harness-stamps.jsonl` | `setup.sh`, the harness-stamp hook | Session Analytics |
| `session-analytics.json`, `session-analytics.db`, `session-analytics-graph` | you, `./scripts/session-analytics setup` and `ingest` | Session Analytics |
| `pi/` | `setup.sh --pi` | `pi-code`, the Pi runtime |
| `config.toml` | you | `pi-code`, the Pi runtime (the global layer) |

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
3. `~/.code-copilot-team/<entry>` exists: that (the fallback; reads and writes both go there).
4. Otherwise `~/.cct/<entry>` is where the entry is created.

`<entry>` is the top-level name: `pi/audit.log` goes wherever `pi/` lives, so a
first write never creates a `~/.cct/pi` that would shadow a legacy `pi/`. The
fallback is per entry, so a half-migrated home still works, and the home
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
Nor does it delete anything a writer is still using. Each file, and each
directory moved across filesystems, is first renamed to a private
`.cct-migrate-aside.*` name beside it, which fixes the object being moved.
On the same filesystem a directory is renamed straight onto its claim in the
home and a file is hard-linked from its private name, so a writer holding
either open keeps writing to the moved object, and only the private name is
removed.
A writer that replaces the legacy entry meanwhile creates a new one at the
original name, which is kept and reported as a conflict.

Across filesystems (`CCT_HOME` on another volume) the entry is copied and
published in the home, and the home copy is read from then on, but the
legacy copy is **never deleted**: no check can rule out a writer changing it
after the copy. It goes back under its original name (or, if a writer
recreated that name, stays under its private name, whose path is printed),
and `migrate` exits 1 so you compare the two and remove the legacy one by
hand. An interrupted run puts an unpublished entry back; one it could not
put back is reported by `cct home`, `cct home migrate` and `cct doctor`
(also when `CCT_HOME` is set).
It never deletes the legacy directory; once it is empty, remove it yourself.

**Do not paste `migrate`'s output back into a terminal.** Versions before
this fix printed `moved: x -> /path/x`; pasted into zsh or bash, the `>`
opens `/path/x` for writing before the unknown command `moved:` fails, and
the file just migrated is left empty (#463). Output now reads
`moved x into /path` and carries no `>`, `<`, `|`, `;`, `&`, `$` or
backtick, but a terminal is still the wrong place for it.

## Recovering an emptied file

On the same filesystem `migrate` moves a file by renaming or hard-linking
it, never by writing its content, so a migrated file keeps its original
bytes and its original birth time, and a file that is empty after a migrate
was emptied afterwards. Across filesystems the home copy is a new file with
the original bytes, and the legacy original is kept beside it.

1. **Confirm.** `ls -la ~/.cct` shows the size; on macOS,
   `stat -f '%N born=%SB modified=%Sm size=%z' ~/.cct/*` shows that an
   emptied file still has its old birth time and a new modification time.
2. **Restore from a backup** taken before the empty timestamp (Time
   Machine, or a copy on another machine), into `~/.cct/`.
3. **Rebuild a provider profile** when there is no backup. The profile holds
   provider settings and the *names* of key variables, never the keys:
   `docs/auto-code-review-setup.md` has the DeepSeek, DGX Spark and Codex
   blocks and the `[defaults]` block; the template
   `shared/templates/provider-profile-template.toml` has the rest. Earlier
   Claude Code or Codex sessions that opened the file may hold its values
   (`~/.claude/projects/*/*.jsonl`, `~/.codex/sessions/`). Check
   `[defaults]` yourself: it decides which provider reviews your code.
   Validate with `bash scripts/validate-providers-profile.sh <file>` before
   copying it to `~/.cct/providers.toml`.
4. **Reseed from the template** as a last resort: remove the empty
   `~/.cct/providers.toml` (setup does not overwrite an existing file, even
   an empty one), run `bash scripts/setup.sh --sync`, and re-add your
   providers.
5. **Drop emptied state files** such as `routing-probe-ledger.json`; the
   routing commands recreate them.

A project's committed Pi configuration is not part of the user home: it is
`<repo>/.cct.toml`, with the personal `<repo>/.cct.local.toml` and the
`<repo>/.cct-init.json` manifest beside it (#460). The older
`<repo>/.code-copilot-team/` files are moved with `pi-code migrate`; see
`adapters/pi/docs/configuration-reference.md`.
