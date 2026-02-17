# Data Model Review Protocol

Before implementing a data model from a design doc (before Phase 2):

## Review Gate Checklist

1. **Review entity relationships** with user:
   - "Does Customer need an Address entity for delivery?"
   - "Should we split `name` into `firstName`/`lastName`?"
   - "Are there any missing entities or fields?"
   - "Do we need audit trails (createdBy, updatedBy)?"
   - "Which entities need soft delete (deletedAt)?"

2. **Confirm field granularity**:
   - Full name vs first/last name split
   - Single address line vs street/city/state/zip
   - Phone number formatting (single field vs country code + number)
   - Date vs datetime precision

3. **Validate relationships**:
   - One-to-many vs many-to-many
   - Nullable foreign keys (optional relations)
   - Cascade delete vs set null vs restrict
   - Self-referential relationships (parent/child)

4. **Standard fields on all entities**:
   - `id` (cuid or uuid)
   - `createdAt` (DateTime)
   - `updatedAt` (DateTime)
   - `deletedAt` (DateTime, nullable, for soft delete)

5. **Update both Prisma schema AND system design doc in sync** when changes are made
   - Never let schema drift from documentation
   - System design doc is source of truth for stakeholders
   - Prisma schema is source of truth for implementation

6. **Prevent mid-phase schema changes** that ripple across multiple agents:
   - Resolve ambiguities upfront
   - Get user sign-off on data model
   - Lock schema before delegating to parallel agents
   - If changes are needed mid-phase, pause all agents and re-sync

## Common Data Model Pitfalls

| Issue | Example | Solution |
|-------|---------|----------|
| **Ambiguous names** | `name` field without context | `firstName`/`lastName` or `fullName` with clear semantics |
| **Missing address** | Customer without delivery address | Add `Address` entity with 1:N relationship |
| **Flat structure** | All order data in one table | Normalize: `Order` + `OrderItem` + `InventoryBatch` |
| **No audit trail** | Can't track who changed what | Add `createdBy`, `updatedBy`, or `AuditLog` entity |
| **Hard delete** | Lost data when records deleted | Use soft delete with `deletedAt` timestamp |
| **No indexes** | Slow queries on foreign keys | Add `@@index` on FK fields and filter columns |

## Timing

This gate happens **after Phase 1 scaffolding, before delegating Phase 2 work**.

Phase 1 sets up the project structure. Phase 2 implements the data model and routers. The review gate prevents wasted work and reduces thrash.
