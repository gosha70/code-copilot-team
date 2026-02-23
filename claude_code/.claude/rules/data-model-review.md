# Data Model Review Gate

Review gate checklist before implementing data models. This gate occurs after planning/scaffolding, before delegating build tasks to agents.

## Review Checklist

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

## Common Data Model Pitfalls

| Pitfall | Fix |
|---------|-----|
| Ambiguous names (`name`, `value`, `data`) | Use specific, descriptive names: `accountBalance`, `taskStatus`, `eventDate` |
| Flat structure needing normalization | Extract into a separate entity with one-to-many relationship to parent |
| Flat structure with too many fields | Normalize into separate entities connected by foreign keys |
| No audit trail | Add `createdBy`, `updatedBy` fields, or a separate `AuditLog` entity |
| Hard delete only | Use soft delete with `deletedAt` timestamp; filter in queries |
| No indexes on foreign keys | Add indexes on all FK fields and commonly filtered/sorted columns |
| Enum sprawl | Use a status/type table for values that change frequently |

## Timing

This gate runs after Phase 1 (scaffolding/planning) and before Phase 2 (parallel agent delegation). Never skip it — mid-phase schema corrections cost more than upfront review.
