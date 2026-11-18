# Origin alignment check — one-harness-home (FR-3 amended after review)

Date: 2026-11-15 (filed `1500` so it follows the 1400 record; the checker
orders records by name).

Supersedes the 1400 record. FR-3 and FR-4 are rewritten as clean
normative text (no superseded rule kept beside the new one); this record
holds the history. The amendment comes from the owner's review of
PR #456 at `13e4f1d`: FR-3's precedence is decided on the top-level
entry, the first segment of the relative path, and the fallback serves
writes as well as reads. The per-path rule let a first nested write
(`pi/audit.log` under a legacy `pi/`) create `~/.cct/pi`, which then
shadowed the legacy runtime directory with no doctor or setup notice.

Origin: issue #411 asks for one home, a one-release fallback and no
silent moves. Splitting a directory across the two homes is a silent
partial move by another name, so the amendment tightens the rule toward
the issue's intent; it adds no behaviour the issue did not ask for.
FR-4 already required a file found through the fallback to be rewritten
in place; the entry rule extends that to new files inside a
fallback-served directory.

FR-9 gains one sentence: display-only occurrences in code are listed one
by one in a baseline and compared as a multiset. The review showed that
exempting every `~/.cct` occurrence by meaning let executable forms such
as `cat ~/.cct/providers.toml` through; the baseline makes each new
occurrence a reviewed change, which is what FR-9 already promised.

## Mismatches

None. The 1400 record's build findings and the 13:00 record's rulings
stand.

Verdict: aligned
Confidence: high
