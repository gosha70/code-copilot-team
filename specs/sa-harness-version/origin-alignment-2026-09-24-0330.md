# Origin alignment check — sa-harness-version (A4a built)

Checked 2026-09-24 03:30, after the A4a build and before review.
Supersedes the 00:40 record; origin and claims unchanged, this record
confirms the built A4a artifact against them. A4b is not built.

Origin: specs/sa-harness-version/origin/2026-09-24-owner-direction.md
(the owner's messages, the green-field ruling, the A1–A3 rulings, and
the 2026-09-24 review) and issue #371, row A4.

Origin claim (A4a part):
> Capture the harness at SessionStart, join at ingest; earliest stamp
> plus a mixed flag; full sha; instructions_digest; hook excluded from
> the plugin; six columns; the session header shows the stamp.

Working claim (as built):
> adapters/claude-code/.claude/hooks/harness-stamp.sh (setup.sh-only,
> not in CC_PLUGIN_HOOKS; registered under SessionStart in
> settings.json); setup.sh write_harness_json on install and --sync
> with the full `git rev-parse HEAD`; six nullable columns on
> copilot_session, _SCHEMA_VERSION 10, six _REQUIRED_COLUMNS entries;
> harness_stamps.read_ledger (sanitised, earliest by recorded_at then
> file order, mixed on any later difference, cached per
> path/mtime/size); the Claude Code adapter reads `version` and joins
> by native session id (a second CLI version → mixed); upsert_session
> writes the six; _SESSION_COLS serves them; the header lists the five
> facts with the sha/digests shortened and full on hover, "mixed —
> earliest stamp shown", or "Harness: unstamped".

Each clause against the artifact: SessionStart capture — the hook and
settings.json; join at ingest — claude_code._harness + store; earliest
+ mixed — harness_stamps._read, tested for identical and differing
lines and for two CLI versions; full sha — write_harness_json,
HARNESS_SHA_HEX_CHARS = 40 validated on read; instructions_digest —
the hook's file set and the column name; plugin exclusion —
TestInstallSurface reads generate.sh and plugin/hooks/hooks.json; six
columns — 001_core.sql, db.py; header — SessionHeader.HarnessFacts and
five states-check states.

Verified on a scratch store built from two of the owner's real
transcripts with a ledger written by the real hook on this machine:
real CLI versions (2.1.263, 2.1.274), the real instructions and
providers digests, one session mixed as constructed, ~/.cct untouched,
the owner's instance untouched.

Differences from the origin: none beyond those in the 00:40 record.

Verdict: aligned
Confidence: high
