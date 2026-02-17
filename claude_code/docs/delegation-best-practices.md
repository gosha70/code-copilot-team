# Delegation Best Practices

Guidelines for effectively delegating work to specialized agents.

## When to Pause for User Input

Don't delegate blindly. Pause and ask the user when:

### Design Ambiguity
- Missing entities or unclear relationships in data model
- Multiple valid implementation approaches with different tradeoffs
- Unclear requirements ("make it user-friendly" without specifics)

### Breaking Changes
- Major refactors affecting multiple parts of the codebase
- Schema changes that require data migration
- API contract changes that break existing clients

### Missing Credentials
- Database connection strings needed for migrations
- SMTP server details required for email testing
- API keys for third-party services

### Dependency Conflicts
- Version incompatibilities between packages
- Need to downgrade from bleeding-edge to stable
- Peer dependency warnings that might break functionality

### Security Decisions
- Password-based auth vs magic links vs OAuth
- Data retention policies (how long to keep PII)
- Permission models (role-based vs attribute-based)
- Encryption requirements

### Architecture Choices
- Monorepo vs multi-repo
- REST vs GraphQL vs tRPC
- SQL vs NoSQL
- Serverless vs traditional hosting

## Agent Handoff Protocol

When multiple agents work in parallel:

### 1. Ensure Non-Overlapping File Ownership

Bad (conflicts inevitable):
```
Agent A: Implement product service
Agent B: Implement order service (also touches product code)
```

Good (clear boundaries):
```
Agent A: Write Prisma schema (everyone reads, one writes)
Agent B: Implement product service (owns src/server/services/product.service.ts)
Agent C: Implement order service (owns src/server/services/order.service.ts)
```

### 2. Share Read-Only Context

All agents should read from the same source of truth:
- Prisma schema (data model)
- tRPC router types (API contracts)
- Design documents (requirements)
- Shared component library (UI patterns)

### 3. Validate Integration After Completion

After all parallel agents finish:
```bash
# Full type check across codebase
npx tsc --noEmit

# Lint all files
npm run lint

# Build and run
npm run dev

# Test critical integrations
# - Frontend calls backend APIs
# - Auth protects admin routes
# - Database queries work
```

### 4. Test Agent Interactions

Don't just test each agent's output in isolation:
- **Frontend + Backend**: UI calls tRPC procedures correctly
- **Auth + Routes**: Protected routes actually require authentication
- **Services + Database**: Queries return expected data
- **Forms + Validation**: User input is validated and sanitized

## Delegation Anti-Patterns

### Over-Delegation
Spawning too many agents for a simple task increases coordination overhead.

**Bad**: 5 agents for a feature that touches 3 files
**Good**: 1 focused agent or implement directly

### Under-Specification
Vague task descriptions lead to incorrect implementations.

**Bad**: "Make the UI better"
**Good**: "Add loading states to product cards, show error messages on form submission, make buttons 44px tall for touch targets"

### Sequential When Parallel Would Work
Blocking on agents unnecessarily.

**Bad**: Agent A → wait → Agent B → wait → Agent C
**Good**: Agents A, B, C in parallel (if no dependencies)

### Parallel When Sequential Is Required
Running agents in parallel when one depends on another's output.

**Bad**: Frontend agent starts before backend defines API contracts
**Good**: Backend defines contracts → Frontend implements against them

## Optimal Delegation Patterns

### Phase-Based Parallelism

```
Phase 1: Scaffolding (sequential, foundational)
  ↓
Phase 2: Foundation (parallel, independent modules)
  - Database schema
  - Router structure
  - Layout shell
  ↓
Phase 3: Features (parallel after contracts defined)
  - Auth
  - Business services
  - Public UI
  ↓
Phase 4: Admin & Jobs (parallel, different domains)
  - Admin UI
  - Background jobs
  ↓
Phase 5: QA (sequential, tests everything)
  - Unit tests
  - Integration tests
  - E2E tests
```

### Contract-First Delegation

1. **Define interfaces first** (types, API shapes, component props)
2. **Delegate implementation** to specialized agents
3. **Validate integration** (type check, run together)

Example:
```typescript
// Step 1: Define contract (you or architecture agent)
type CreateOrderInput = {
  items: Array<{ productId: string; quantity: number }>;
  customerId?: string;
  addressId?: string;
};

// Step 2: Delegate to agents
// Backend agent: implements orderService.createOrder(input)
// Frontend agent: calls trpc.order.create.useMutation()

// Step 3: Validate they work together
```

### Progressive Enhancement

Start with minimal working version, enhance in later phases:

```
Phase 1: Core flow (happy path only)
Phase 2: Error handling
Phase 3: Edge cases
Phase 4: Performance optimization
Phase 5: Polish & UX improvements
```

Don't try to build everything perfectly in one phase.

## Communication Between Agents

Agents **cannot** communicate directly. Coordinate through shared artifacts:

### Shared Artifacts
- **Prisma schema**: Single source of truth for data model
- **TypeScript types**: Shared type definitions in `src/types/`
- **API contracts**: tRPC router exports (`AppRouter` type)
- **Documentation**: README, ARCHITECTURE.md with conventions

### Team Lead Responsibilities
As the orchestrating agent (team lead), you:
1. **Define clear task boundaries** for each agent
2. **Resolve conflicts** when agents produce incompatible outputs
3. **Validate integration** after parallel work completes
4. **Report status** to the user with clear summaries

## When to Use Teams vs Sequential Agents

### Use Teams (parallel) when:
- Multiple independent features to implement
- Clear domain boundaries (frontend vs backend vs QA)
- Time savings matter (work in parallel)

### Use Sequential agents when:
- Each step depends on the previous one's output
- Exploratory work (research then implement)
- Complex decisions requiring human input between steps

### Implement directly (no agents) when:
- Simple single-file changes
- Quick fixes or tweaks
- High coordination overhead relative to task size
