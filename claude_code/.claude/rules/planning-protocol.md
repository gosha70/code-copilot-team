# Planning Protocol

## Ask Before Implementing

### Data Model Decisions
- Field granularity: single combined field vs split into components?
- Normalization: flat fields on parent entity vs separate related entity?
- Status/type fields: which enum values are needed?
- Relationships: one-to-many vs many-to-many? Optional vs required?
- Audit fields: `createdAt`, `updatedAt`, `deletedAt`, `createdBy`?

### Output Format Decisions
- Column names and headers
- Row structure (per day? per item? per transaction?)
- Grouping and aggregation
- File format (CSV, JSON, PDF, in-app table)

### UI Layout Decisions
- Image positioning relative to text
- Section ordering and above-the-fold content
- Interactive element behavior (buttons, toggles, dropdowns)
- Responsive behavior and collapse rules

### Auth & Access Decisions
- Auth strategy: password, magic link, OAuth, passkeys?
- Who can access what: roles, admin sections, guest access?
- Account requirement: registration mandatory or optional?
- Session behavior: duration, remember me?

## How to Ask

Keep questions concise and decision-oriented. Present options with tradeoffs:

"Before I create the Profile model, two decisions:
1. Name: single `displayName` field, or split into components?
2. Location: flat fields on Profile, or a separate entity (supports multiple entries)?"

## When NOT to Ask

- Implementation details the user shouldn't decide (function names, internal structure)
- Obvious best practices (parameterized queries, password hashing, input validation)
- Things already decided in CLAUDE.md, design docs, or earlier conversation
- Style/formatting covered by lint rules

## Data Model Review Gate

Before any agent writes entity code or migrations:

1. **Confirm entities** — all identified, names unambiguous, missing fields accounted for
2. **Validate granularity** — compound values split or combined? Nested data normalized or flat?
3. **Check relationships** — one-to-many vs many-to-many confirmed, cascade rules defined, nullable FKs intentional
4. **Prevent mid-phase schema changes** — once agents begin parallel work, schema changes ripple. If unavoidable: pause all agents, update schema, regenerate ORM client, then resume.
