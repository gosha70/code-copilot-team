# Clarification Protocol

Rules for when to ask clarifying questions instead of making assumptions.

## Always Ask Before Implementing

### Data Model Decisions

Before creating or modifying entity fields, confirm with the user:

- **Field granularity**: Single combined field vs split into components? (e.g., one field vs multiple for compound values)
- **Normalization**: Flat fields on the parent entity vs a separate related entity?
- **Status/type fields**: Enum values — which states are needed? Will they change over time?
- **Relationships**: One-to-many vs many-to-many? Optional vs required?
- **Audit fields**: Which standard fields? (`createdAt`, `updatedAt`, `deletedAt`, `createdBy`?)

Don't assume the simplest representation. Compound fields that seem fine early often need to be split later for filtering, sorting, or reporting.

### Output Format Decisions

Before generating reports, exports, or formatted output:

- **Column names**: Confirm exact headers (e.g., "Count" vs "Total" vs "Amount").
- **Row structure**: What does each record represent (per day? per item? per transaction?)?
- **Grouping**: How should data be aggregated?
- **File format**: CSV, JSON, PDF, or in-app table?

Generating the wrong format costs a full rebuild. Asking costs one message.

### UI Layout Decisions

Before implementing visual components:

- **Image positioning**: Left/right of text? Above/below? Full-width banner?
- **Section ordering**: What content is above the fold? What can the user scroll to?
- **Interactive elements**: Buttons, toggles, dropdowns — confirm behavior on click.
- **Responsive behavior**: Mobile-first or desktop-first? What collapses on small screens?

### Auth & Access Decisions

Before implementing authentication or authorization:

- **Auth strategy**: Password-based? Magic link? OAuth? Passkeys?
- **Who can access what**: Admin-only sections? Guest access? Role-based?
- **Account requirement**: Is registration mandatory or optional?
- **Session behavior**: How long should sessions last? Remember me?

Auth decisions are expensive to change after implementation. Get them right upfront.

## How to Ask

Keep clarifying questions concise and decision-oriented:

**Bad**: "I'm going to implement the user profile model. There are several fields to consider including name representation, location storage, contact information format, and various audit fields. What are your preferences for each of these aspects?"

**Good**: "Before I create the Profile model, two quick decisions:
1. Name: single `displayName` field, or split into components?
2. Location: flat fields on Profile, or a separate entity (supports multiple entries)?"

Present the options with their tradeoffs. Let the user decide quickly.

## When NOT to Ask

Don't ask about:

- **Implementation details** the user shouldn't need to decide (internal function names, variable names, file organization within conventions).
- **Obvious choices** where there's a clear best practice (use parameterized queries, hash passwords, validate inputs).
- **Things already decided** in the project CLAUDE.md, design docs, or earlier in the conversation.
- **Style/formatting** that's covered by the project's lint/style rules.

The goal is to ask about decisions that affect **user-facing behavior** or **data model shape**, not about code internals.

## Data Model Review Gate

Review gate checklist before implementing data models. This gate occurs after planning/scaffolding, before delegating build tasks to agents.

### Review Checklist

Before any agent writes entity code or migration scripts:

1. **Review entity relationships with user.**
   - Are all entities identified? Are names unambiguous?
   - Are missing fields accounted for (audit trails, soft deletes)?
   - Have edge cases been discussed (nullable fields, optional relationships)?

2. **Confirm field granularity.**
   - Compound values: single combined field vs split into components? (e.g., `displayName` vs separate parts)
   - Nested data: flat fields on parent entity vs separate related entity?
   - Contact/reference fields: plain string vs structured object (with type, label, metadata)?
   - Date precision: date-only vs datetime vs datetime with timezone?

3. **Validate relationships.**
   - One-to-many vs many-to-many: confirmed with user?
   - Nullable foreign keys: intentional or missing constraint?
   - Cascade rules: what happens when parent is deleted?
   - Self-referential relations: are they needed (e.g., categories, org charts)?

4. **Standard fields on all entities.**
   - `id` — primary key (UUID or auto-increment, per project convention)
   - `createdAt` — timestamp, auto-set on creation
   - `updatedAt` — timestamp, auto-set on modification
   - `deletedAt` — nullable timestamp for soft delete (if applicable)

5. **Keep schema and design documentation in sync.**
   - Schema file (ORM schema, SQL DDL, or migration scripts) must match the design doc.
   - If one changes, the other must be updated before delegating further work.

6. **Prevent mid-phase schema changes.**
   - Once agents begin parallel work, schema changes ripple across all agents.
   - If a schema change is unavoidable: pause all agents, update schema, regenerate ORM client, then resume.

### Common Data Model Pitfalls

| Pitfall | Fix |
|---------|-----|
| Ambiguous names (`name`, `value`, `data`) | Use specific, descriptive names: `accountBalance`, `taskStatus`, `eventDate` |
| Flat structure needing normalization | Extract into a separate entity with one-to-many relationship to parent |
| Flat structure with too many fields | Normalize into separate entities connected by foreign keys |
| No audit trail | Add `createdBy`, `updatedBy` fields, or a separate `AuditLog` entity |
| Hard delete only | Use soft delete with `deletedAt` timestamp; filter in queries |
| No indexes on foreign keys | Add indexes on all FK fields and commonly filtered/sorted columns |
| Enum sprawl | Use a status/type table for values that change frequently |

### Timing

This gate runs after Phase 1 (scaffolding/planning) and before Phase 2 (parallel agent delegation). Never skip it — mid-phase schema corrections cost more than upfront review.
