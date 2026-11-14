# Origin alignment check — auto-build-hill-chart (after the #449 contributor review)

Date: 2026-11-13 12:00 EST

Supersedes the 2026-11-12 06:00 record. Nosher007's review of PR #449
found that a frozen-map first write that fails parks with a ledger
already present, and the resume then refused "no frozen map", so the
park promised a recovery the next step forbade. FR-4 now refuses a
map-less resume only once a phase has started (the map is the evidence
for what those phases started against); before any phase the resuming
attempt writes the map. The contributor's test is taken as written. The
doc states that an unattended run terminates (exit 6) and needs a fresh
run. Owner rulings D1–D5 unchanged; origin sources unchanged.

Verdict: aligned
Confidence: high
