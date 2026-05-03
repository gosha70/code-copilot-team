# /add-entry

Add a new entry to the pack content.

## Procedure

1. Open `content/data.tbx` (or the active content file declared in `content/manifest.yaml`).
2. Append a new `<termEntry id="t-NNNN">` block. **Pick a fresh `id`** — never reuse an existing one. Consumers may pin to it.
3. Fill in `<term>`, `<termNote type="partOfSpeech">`, `<descrip type="definition">`. If you have a verifiable source, add a `<descrip type="source">` line.
4. If this is the first content change since the last release, bump the **minor** version in `content/manifest.yaml` (additive change). If you are removing or renaming an entry, bump the **major** version instead.
5. Run schema validation locally:
   ```bash
   xmllint --noout content/data.tbx
   ```
6. Sync into both wrappers and run their test suites:
   ```bash
   bash scripts/sync-content.sh
   (cd jvm-wrapper && ./gradlew test)
   (cd python-wrapper && pytest)
   ```
7. Commit with a message that includes the entry id and the version bump.

## Refuse to merge if
- An existing entry's `id` was reused.
- The manifest version was not bumped.
- Either wrapper's test suite fails.
- The schema validator fails.
