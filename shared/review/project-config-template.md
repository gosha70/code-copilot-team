<!-- CCT-REVIEWER-PROJECT-CONFIG: project-owned — setup-reviewer.sh creates this once and never overwrites it -->
# Code Review — Project Configuration

Project-owned companion to `docs/CODE_REVIEW.md`. Fill in the placeholders;
refreshing or re-running `setup-reviewer.sh` never touches this file.

- Project: `<PROJECT_NAME>`
- Purpose: `<ONE_SENTENCE_PROJECT_PURPOSE>`
- Default branch: `<main | master | other>`
- Primary stack: `<LANGUAGES_AND_FRAMEWORKS>`
- Architecture documentation:
  - `<ARCHITECTURE_FILE>`
  - `<CONTRIBUTING_FILE>`
- Specification directory: `<specs/ | docs/specs/ | none>`
- Test command: `<TEST_COMMAND>`
- Lint command: `<LINT_COMMAND>`
- Type-check command: `<TYPECHECK_COMMAND>`
- Build command: `<BUILD_COMMAND>`
- Integration or smoke-test command: `<INTEGRATION_COMMAND>`
- Critical paths:
  - `<AUTH_PATH>`
  - `<DATA_OR_SCHEMA_PATH>`
  - `<PUBLIC_API_PATH>`
- Generated or vendored paths that should not be reviewed:
  - `<GENERATED_PATH>`
  - `<VENDORED_PATH>`
