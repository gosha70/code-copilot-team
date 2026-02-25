# Enterprise Java Full-Stack Application

## Stack
- Java 21, Spring Boot 3.x
- Build: Gradle (Kotlin DSL), multi-module project
- Databases: PostgreSQL (primary OLTP), MongoDB (documents), Redis (cache)
- Messaging: Apache Kafka (event streaming), RabbitMQ (task/command queues)
- API: GraphQL (schema-first, DGS framework or Spring GraphQL)
- Frontend: React 18+, TypeScript, Apollo Client
- Containerization: Docker Compose (dev), Kubernetes (prod)

## Architecture
```
├── build.gradle.kts                # Root build file
├── settings.gradle.kts             # Module declarations
├── api-schema/                     # GraphQL schema (.graphqls files) — THE CONTRACT
├── modules/
│   ├── common/                     # Shared kernel (value objects, events, utils)
│   ├── domain-a/                   # Bounded context A (hexagonal architecture)
│   │   ├── src/main/java/.../
│   │   │   ├── adapter/
│   │   │   │   ├── in/web/         # GraphQL resolvers (driving adapters)
│   │   │   │   ├── in/messaging/   # Kafka/RabbitMQ consumers
│   │   │   │   ├── out/persistence/# JPA repositories, entities
│   │   │   │   ├── out/messaging/  # Kafka producers, RabbitMQ publishers
│   │   │   │   └── out/cache/      # Redis cache adapters
│   │   │   ├── application/        # Use cases / application services
│   │   │   ├── domain/             # Domain model (entities, value objects, events)
│   │   │   └── port/               # Port interfaces (in + out)
│   │   └── src/test/
│   └── domain-b/                   # Bounded context B (same structure)
├── infra/
│   ├── docker-compose.yml
│   ├── docker-compose.test.yml
│   └── k8s/
├── frontend/                       # React + TypeScript + Apollo
│   ├── src/
│   │   ├── generated/              # GraphQL codegen output (DO NOT EDIT)
│   │   ├── components/
│   │   ├── pages/
│   │   ├── graphql/                # .graphql operation files
│   │   └── hooks/
│   ├── codegen.ts
│   └── package.json
└── db/
    └── migration/                  # Flyway migrations (V001__, V002__, ...)
```

## Hexagonal Architecture Rules
- Domain layer: ZERO framework dependencies (no Spring annotations)
- Application layer: orchestrates domain; depends only on port interfaces
- Adapters: implement ports; all framework coupling lives here
- Never bypass the service/application layer from controllers/resolvers
- Dependencies flow inward: adapter → application → domain

## Database Conventions
- Flyway migrations: sequential numbering (V001__description.sql)
- All entities: audit fields (created_at, updated_at, created_by, version)
- JPA entities in adapter layer only; domain entities are plain POJOs
- No raw SQL in application code; use Spring Data repositories or jOOQ
- Redis cache keys: `{service}:{entity}:{id}`, TTL always explicit
- Cache strategy: cache-aside for reads; invalidate on write

## Messaging Conventions
- Kafka topics: `{domain}.{entity}.{event}` (e.g., orders.order.created)
- Kafka: Avro serialization with Schema Registry ← UPDATE if using JSON/Protobuf
- Every consumer MUST be idempotent (deduplicate by event ID)
- Dead-letter topics: `{original-topic}.DLT`
- Consumer groups: `{service-name}-{consumer-purpose}`
- RabbitMQ: use for command/reply patterns; Kafka for event streaming
- JMS: legacy only; wrap behind port interface for future migration

## GraphQL Conventions
- Schema-first: all types defined in `api-schema/*.graphqls`
- Schema is the contract between backend and frontend
- Codegen: backend (DGS codegen) + frontend (graphql-codegen)
- No REST endpoints except /actuator/** health checks
- Pagination: Relay-style connections (edges, nodes, pageInfo)
- Errors: use GraphQL errors with extensions for error codes

## Frontend Conventions
- All data fetching via Apollo Client (no direct REST)
- GraphQL operations in `src/graphql/` (.graphql files)
- Generated types in `src/generated/` — never edit manually
- Component library: ← UPDATE: MUI / Ant Design / shadcn
- State: Apollo cache for server state; Zustand for local UI state
- Testing: React Testing Library + MSW for GraphQL mocking

## Testing Pyramid
- Unit: JUnit 5 + Mockito, ≥80% coverage on application/domain layers
- Integration: Testcontainers (Postgres, Kafka, Redis, RabbitMQ)
- Contract: GraphQL schema validation in CI (no breaking changes)
- Frontend: RTL + MSW for component tests; Cypress for critical flows
- Performance: Gatling scripts for critical API paths ← optional

## Commands
```bash
./gradlew build                              # build all modules
./gradlew test                               # all tests
./gradlew :modules:domain-a:test             # single module tests
./gradlew bootRun -p modules/domain-a        # run single service
docker compose -f infra/docker-compose.yml up -d   # infra
cd frontend && npm install && npm run dev    # frontend
cd frontend && npm run codegen               # regenerate GraphQL types
./gradlew flywayMigrate                      # run DB migrations
```

## Agent Team

### Roles

| Role | Trigger | Owns |
|------|---------|------|
| **Team Lead / Architect** (default) | Planning, DDD decisions, cross-module coordination | Overall, `api-schema/` |
| **Java Backend Developer** | Spring Boot services, domain logic, hexagonal structure | `modules/` |
| **Frontend Developer** | React components, Apollo Client, GraphQL operations | `frontend/` |
| **Data & Messaging Engineer** | DB schemas, Flyway, Kafka, RabbitMQ, Redis | `db/`, adapter/out layers |
| **QA Engineer** | All testing, coverage, contract tests | `**/test/`, test configs |
| **DevOps / Release Engineer** | Docker, K8s, CI/CD, build config | `infra/`, Gradle files |

### Team Lead / Architect — Default Behavior
You ARE the Team Lead. You own the architecture:
1. Domain boundaries: which bounded context owns which entity/event.
2. GraphQL schema changes: you modify `api-schema/`, then delegate implementation.
3. Cross-cutting concerns (auth, logging, error handling) → handle directly or coordinate.
4. Single-module, single-layer tasks → handle directly. Cross-module → delegate.
5. After any schema change, trigger both Backend and Frontend agents to update codegen.

### Delegation Prompts
```
You are the [ROLE] on an enterprise Java full-stack project.

Architecture: Hexagonal (ports & adapters) within DDD bounded contexts.
API: GraphQL schema-first. Schema in api-schema/*.graphqls is THE CONTRACT.
Messaging: Kafka for events, RabbitMQ for commands.

Your task: [specific task description]

Constraints:
- Domain layer has ZERO framework dependencies
- Dependencies flow inward: adapter → application → domain
- Never bypass the application layer
- [role-specific constraints below]
- Return: code changes + summary of what was changed and why
```

### Java Backend Developer
Expertise: Spring Boot 3, JPA/Hibernate, DGS/Spring GraphQL resolvers, Kafka/RabbitMQ producers and consumers, hexagonal architecture, domain modeling.
Constraints: domain layer = plain POJOs (no Spring annotations). JPA entities in adapter layer only. All business logic in application services (not resolvers or consumers). Every public method in application layer must be tested.

### Frontend Developer
Expertise: React 18+, TypeScript, Apollo Client, GraphQL operations, component architecture, responsive design, state management (Apollo cache + Zustand).
Constraints: all data via Apollo Client (no REST). GraphQL operations in `src/graphql/`. Never edit `src/generated/` (codegen output). Run `npm run codegen` after schema changes. Component tests with RTL + MSW.

### Data & Messaging Engineer
Expertise: PostgreSQL, MongoDB, Redis, Flyway migrations, Kafka (Avro, Schema Registry, consumer groups, DLT), RabbitMQ (exchanges, queues, bindings), jOOQ.
Constraints: all schema changes via Flyway migration files. Every Kafka consumer must be idempotent (event ID dedup). Redis keys follow `{service}:{entity}:{id}` pattern with explicit TTL. Dead-letter queues for all consumers. Test with Testcontainers.

### QA Engineer
Expertise: JUnit 5, Mockito, Testcontainers, React Testing Library, MSW, Cypress, GraphQL contract testing, Gatling.
Constraints: run existing tests first. Unit test coverage ≥80% on application/domain. Integration tests use Testcontainers (never real external services). Contract tests validate GraphQL schema backward compatibility. Frontend tests mock GraphQL via MSW.

### DevOps / Release Engineer
Expertise: Docker, Docker Compose, Kubernetes manifests, Gradle build optimization, CI/CD pipelines, health checks, monitoring.
Constraints: every service has Dockerfile + health endpoint. Docker Compose for local dev must start all deps. K8s manifests in `infra/k8s/`. Build must pass all tests before release. Tag releases with semantic versioning.
