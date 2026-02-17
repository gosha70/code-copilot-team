# Delegation Best Practices

Guidelines for effectively delegating work to specialized agents.

## When to Pause for User Input

Don't delegate blindly. Pause and ask the user when:

**Design Ambiguity** — Missing entities, unclear relationships, multiple valid approaches with different tradeoffs, vague requirements ("make it user-friendly").

**Breaking Changes** — Major refactors affecting multiple parts, schema changes requiring data migration, API contract changes that break existing clients.

**Missing Credentials** — Database connection strings, SMTP/email server details, API keys for third-party services.

**Dependency Conflicts** — Version incompatibilities, need to downgrade from bleeding-edge to stable, peer dependency warnings.

**Security Decisions** — Auth strategy (password vs magic link vs OAuth), data retention policies, permission model (RBAC vs ABAC), encryption requirements.

**Architecture Choices** — Monorepo vs multi-repo, API style (REST vs GraphQL vs RPC), database type (SQL vs NoSQL), hosting model (serverless vs traditional).

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
Agent A: Write schema/models (one writer for shared definitions)
Agent B: Implement product service (owns product files only)
Agent C: Implement order service (owns order files only)
```

### 2. Share Read-Only Context

All agents should read from the same source of truth:

- **Data model/schema** — single canonical definition
- **API contracts/types** — shared interface definitions
- **Design documents** — requirements and architecture decisions
- **Shared utilities** — common helpers, component library

### 3. Validate Integration After Completion

After all parallel agents finish:

```bash
# Run your stack's type checker (examples for common stacks)
# TypeScript:  npx tsc --noEmit
# Python:      mypy src/
# Java:        mvn compile
# Go:          go vet ./...

# Run your linter
# JS/TS:  npm run lint
# Python: ruff check .
# Java:   mvn checkstyle:check

# Build and run
# Node:   npm run dev
# Python: python -m flask run (or equivalent)
# Java:   mvn spring-boot:run
```

### 4. Test Agent Interactions

Don't just test each agent's output in isolation. Verify integration points:

- Frontend calls backend APIs correctly
- Auth protects routes that should be protected
- Database queries return expected data
- Forms validate and submit correctly

## Delegation Anti-Patterns

| Anti-Pattern | Problem | Fix |
|---|---|---|
| **Over-delegation** | 5 agents for a 3-file change; coordination overhead exceeds value | Implement directly or use one focused agent |
| **Under-specification** | "Make the UI better" — too vague | Specify exact files, components, and acceptance criteria |
| **Sequential when parallel** | Blocking on agents unnecessarily | Run independent agents in parallel |
| **Parallel when sequential** | Frontend starts before backend defines contracts | Define contracts first, then delegate in dependency order |

## Optimal Delegation Patterns

### Contract-First Delegation

1. **Define interfaces first** — types, API shapes, component props, database schema
2. **Delegate implementation** — each agent implements against the contract
3. **Validate integration** — type check, build, run together

```
# Pseudocode — adapt to your stack

# Step 1: Define contract (you or architecture agent)
CreateOrderInput:
    items: list of {productId: string, quantity: number}
    customerId: optional string
    shippingAddressId: optional string

# Step 2: Delegate
Backend agent → implements orderService.createOrder(input)
Frontend agent → implements order form calling the API

# Step 3: Validate they work together
```

### Phase-Based Parallelism

```
Phase 1: Scaffolding (sequential — foundational setup)
    ↓
Phase 2: Foundation (parallel — independent modules)
    - Database schema / models
    - Router / API structure
    - Layout shell / UI framework
    ↓
Phase 3: Features (parallel — after contracts defined)
    - Auth
    - Business logic services
    - User-facing UI
    ↓
Phase 4: Integration (parallel — different domains)
    - Admin UI
    - Background jobs / async tasks
    ↓
Phase 5: QA (sequential — tests everything together)
    - Unit tests
    - Integration tests
    - E2E tests
```

### Progressive Enhancement

Start minimal, enhance in later phases:

```
Phase 1: Core flow (happy path only)
Phase 2: Error handling and validation
Phase 3: Edge cases and boundary conditions
Phase 4: Performance optimization
Phase 5: Polish and UX improvements
```

Don't try to build everything perfectly in one phase.

## Communication Between Agents

Agents **cannot** communicate directly. Coordinate through shared artifacts:

- **Schema/model files** — single source of truth for data model
- **Type definitions** — shared types in a common directory
- **API contracts** — exported router/endpoint definitions
- **Documentation** — README, ARCHITECTURE.md with conventions

### Team Lead Responsibilities

As the orchestrating agent (Team Lead), you:

1. **Define clear task boundaries** for each agent
2. **Resolve conflicts** when agents produce incompatible outputs
3. **Validate integration** after parallel work completes
4. **Report status** to the user with clear summaries

## When to Use Teams vs Sequential vs Direct

| Approach | When |
|---|---|
| **Parallel team** | Multiple independent features, clear domain boundaries, time savings matter |
| **Sequential agents** | Each step depends on previous output, exploratory work, complex decisions needing human input between steps |
| **Direct (no agents)** | Simple single-file changes, quick fixes, high coordination overhead relative to task size |
