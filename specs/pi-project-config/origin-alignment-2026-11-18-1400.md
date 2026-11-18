# Origin alignment check — pi-project-config (D4 condition)

Date: 2026-11-18

Supersedes the 1300 record. The owner added a condition to D4: "If #460
misses the 2.1.0 release, the old location is read through the release
after the one #460 ships in. Projects always get at least one full
minor release to migrate, and the CHANGELOG states the removal
version." D4 and FR-9 now state it, and the origin record quotes it.
When #460 ships in 2.1.0 (the last tag is `v2.0.0`; #411 sits in
Unreleased), the removal is 2.2, together with the user-home fallback,
as before. No other requirement or task changed.

## Mismatches

None.

Verdict: aligned
Confidence: high
