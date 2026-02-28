# Java Developer Tooling — Annotation Processors, Gradle Plugins & Code Generators

## Stack
- Java 21, Spring Boot 3.x (for runtime module and demo app)
- Build: Gradle (Kotlin DSL), multi-module project
- Annotation Processing: JSR 269 (javax.annotation.processing)
- Code Generation: JavaPoet (Palantir fork)
- MCP: Spring AI MCP SDK, Model Context Protocol Java SDK
- OpenAPI: swagger-models (io.swagger.v3), springdoc-openapi
- Testing: JUnit 5, compile-testing (Google), Testcontainers (demo)
- Publishing: Maven Central via Gradle publishing plugin

## Architecture
```
├── build.gradle.kts                 # Root build file (allprojects config)
├── settings.gradle.kts              # Module declarations + plugin management
├── gradle/
│   ├── libs.versions.toml           # Version catalog — SINGLE SOURCE OF TRUTH
│   └── publishing.gradle.kts        # Shared publishing config
├── modules/
│   ├── annotations/                 # Annotation definitions (zero dependencies)
│   │   └── src/main/java/
│   │       └── .../annotations/     # @AgenticExposed, @AgentVisible, etc.
│   ├── processor/                   # JSR 269 annotation processor
│   │   ├── src/main/java/
│   │   │   └── .../processor/
│   │   │       ├── AgenticProcessor.java       # AbstractProcessor implementation
│   │   │       ├── model/                      # Internal representation of scanned types
│   │   │       ├── generator/                  # JavaPoet-based code generators
│   │   │       │   ├── DtoGenerator.java       # Safe DTO record generation
│   │   │       │   ├── McpToolGenerator.java   # MCP @Tool class generation
│   │   │       │   ├── RestControllerGenerator.java
│   │   │       │   └── OpenApiGenerator.java   # OpenAPI 3.x spec generation
│   │   │       └── util/                       # TypeMirror helpers, field scanning
│   │   ├── src/main/resources/
│   │   │   └── META-INF/services/
│   │   │       └── javax.annotation.processing.Processor
│   │   └── src/test/java/                      # Compile-testing tests
│   ├── runtime/                     # Spring Boot auto-configuration
│   │   └── src/main/java/
│   │       └── .../runtime/
│   │           ├── autoconfigure/   # Spring Boot auto-config classes
│   │           ├── mcp/             # MCP server configuration
│   │           └── security/        # PII interceptors, audit logging
│   └── gradle-plugin/              # Gradle plugin (optional, wraps APT config)
│       └── src/main/java/
│           └── .../plugin/          # Plugin, Extension, Tasks
├── demo/                            # Demo application (consumer of the framework)
│   ├── src/main/java/
│   │   └── .../demo/
│   │       ├── entity/              # Annotated business entities
│   │       ├── service/             # @AgenticExposed service methods
│   │       └── generated/           # ← OUTPUT: generated DTOs, tools, controllers
│   └── build.gradle.kts            # Applies the plugin / annotation processor
├── demo-frontend/                   # Generated Next.js app (from OpenAPI spec)
│   ├── src/
│   └── package.json
├── docs/
│   ├── annotation-guide.md          # Developer guide for annotation usage
│   ├── processor-internals.md       # How the annotation processor works
│   └── migration-guide.md           # Upgrading between versions
└── specs/                           # SDD artifacts and lessons learned
```

## Module Architecture Rules
> **Non-negotiable.** These enforce the layered architecture.

- `annotations` → ZERO external dependencies (only java.lang.annotation)
- `processor` → depends on `annotations` (compile-only), JavaPoet, AutoService
- `runtime` → depends on `annotations` (runtime), Spring AI MCP, Spring Web
- `gradle-plugin` → depends on nothing at runtime; configures processor + runtime
- `demo` → depends on `annotations` + `processor` (annotationProcessor) + `runtime`
- NEVER add Spring or any framework dependency to `annotations` module
- NEVER add runtime dependencies to `processor` (it runs at compile time only)

## Annotation Processing Rules
- Processor extends `AbstractProcessor` and is registered via `@AutoService(Processor.class)`
- Processor must handle `MirroredTypeException` when reading Class<?> annotation values
- Processor declares `AGGREGATING` incremental type for Gradle incremental builds
- Generated sources go to `build/generated/sources/annotationProcessor/java/main/`
- All generated files include `@Generated("ai.adam.processor")` annotation
- Generated code NEVER imports internal/private types from the consumer project
- Processor must walk superclass chain for inherited `@AgentVisible` fields
- Processor emits compile warnings (Messager.NOTE) for suspicious PII field names

## Code Generation Rules
- Use JavaPoet (Palantir `com.palantir.javapoet`) for ALL Java source generation
- NEVER use string concatenation or template engines for Java code
- Generated DTOs use Java records (Java 16+)
- Generated MCP tools use Spring AI `@McpTool` / `@McpToolParam` annotations
- Generated REST controllers use standard Spring `@RestController` / `@GetMapping`
- All generated mapping code is null-safe (handle nullable entity fields)
- OpenAPI specs generated via swagger-models (io.swagger.v3:swagger-models)

## Gradle Plugin Rules
- Plugin ID follows reverse domain: `ai.adam.gradle-plugin`
- Plugin creates extension object for user configuration
- Plugin auto-adds `annotations` to `implementation` configuration
- Plugin auto-adds `processor` to `annotationProcessor` configuration
- Plugin auto-adds `runtime` to `implementation` configuration
- Plugin configures IntelliJ IDEA source directories for generated code
- Plugin NEVER modifies user's existing source sets or compilation settings

## Publishing Rules
- Version catalog (`gradle/libs.versions.toml`) is SOLE version authority
- All modules published to Maven Central with same group and version
- POM includes proper license, SCM, and developer metadata
- Release process: tag → CI builds → publishes all modules atomically
- API changes follow semantic versioning strictly

## Testing Pyramid
- Processor tests: Google compile-testing (`com.google.testing.compile`)
  - Verify generated source matches expected output
  - Verify compile errors on invalid annotation usage
  - Verify PII field warnings emit correctly
- Runtime tests: Spring Boot test slices + Testcontainers
  - Auto-configuration loads correctly
  - MCP tool registration works end-to-end
- Integration tests: Demo app builds successfully with processor
  - Generated code compiles without errors
  - MCP tools respond correctly
  - REST endpoints return PII-safe DTOs
  - OpenAPI spec validates against schema
- NEVER mock the annotation processing environment — use compile-testing

## Commands
```bash
./gradlew build                                    # build all modules
./gradlew test                                     # all tests
./gradlew :modules:processor:test                  # processor tests only
./gradlew :demo:compileJava                        # trigger generation in demo
./gradlew :demo:bootRun                            # run demo app
./gradlew publishToMavenLocal                      # publish to ~/.m2 for local testing
./gradlew :modules:processor:test --tests "*DtoGeneratorTest"  # single test class
```

## Agent Team

### Roles

| Role | Trigger | Owns |
|------|---------|------|
| **Team Lead / Framework Architect** (default) | Architecture decisions, module boundaries, API design | Overall, `annotations/`, API surfaces |
| **Annotation Processor Engineer** | JSR 269 processor, TypeMirror introspection, JavaPoet generation | `processor/` |
| **MCP & Spring AI Specialist** | MCP tool generation, Spring Boot auto-config, runtime module | `runtime/`, MCP integration |
| **Gradle Plugin Developer** | Plugin architecture, task wiring, IDE integration | `gradle-plugin/` |
| **QA & Integration Engineer** | Compile-testing, integration tests, demo validation | `**/test/`, `demo/` |

### Team Lead / Framework Architect — Default Behavior
You ARE the Team Lead. You own the framework's public API surface:
1. Annotation design: field naming, attribute types, retention policy decisions.
2. Module boundary enforcement: ensure dependency rules are never violated.
3. Generated code contracts: what the processor outputs must be stable across versions.
4. Cross-module changes (annotation change → processor update → runtime update) → coordinate, don't delegate piecemeal.
5. Single-module, single-concern tasks → delegate to specialist.
6. API backward compatibility: any public annotation or generated code shape change requires a migration path.

### Delegation Prompts
```
You are the [ROLE] on a Java developer tooling project.

Architecture: Multi-module Gradle project producing an annotation processor,
runtime library, and Gradle plugin consumed by enterprise Java applications.
Core tech: JSR 269, JavaPoet, Spring AI MCP, swagger-models.

Your task: [specific task description]

Constraints:
- annotations module has ZERO external dependencies
- processor module runs at compile time only (no runtime deps)
- Generated code must be valid standalone Java (no internal type imports)
- All generated files include @Generated annotation
- [role-specific constraints below]
- Return: code changes + summary of what was changed and why
```

### Annotation Processor Engineer
Expertise: JSR 269 (AbstractProcessor, RoundEnvironment, ProcessingEnvironment), TypeMirror/TypeElement introspection, DeclaredType unwrapping, MirroredTypeException handling, JavaPoet (TypeSpec, MethodSpec, AnnotationSpec, FieldSpec), Google AutoService, Gradle incremental annotation processing (AGGREGATING mode).
Constraints: Processor must handle all edge cases — generics (List<Entity>), inheritance chains, inner classes. Use Messager for all diagnostics (never System.out). Generated code must compile independently. Never generate code that imports processor-internal types. Test with Google compile-testing, never mock ProcessingEnvironment.

### MCP & Spring AI Specialist
Expertise: Spring AI 1.1+ MCP annotations (@McpTool, @McpToolParam), MCP Java SDK transports (STDIO, Streamable HTTP), Spring Boot auto-configuration (@AutoConfiguration, @ConditionalOnClass), MCP tool description best practices for LLM consumption, MCP security (OAuth 2.1, PKCE).
Constraints: Runtime module must work with Spring Boot auto-config (no manual wiring). Generated MCP tools must be valid @Component beans. Tool descriptions must include both what and when guidance. Support all three MCP transports. Never hard-code transport selection — use Spring properties.

### Gradle Plugin Developer
Expertise: Gradle Plugin API (Plugin<Project>, Project extensions, Task registration), Gradle configuration avoidance API (register vs create), annotation processor configuration, IntelliJ IDEA plugin model, Gradle version catalog integration, plugin publishing to Gradle Plugin Portal.
Constraints: Use configuration avoidance API exclusively. Plugin must not break if consumer uses Lombok (annotationProcessor ordering). Plugin must configure IntelliJ generated source dirs. Plugin must not force specific Gradle or Java versions beyond stated minimums. Test with Gradle TestKit.

### QA & Integration Engineer
Expertise: Google compile-testing, JUnit 5, Spring Boot Test, Testcontainers, OpenAPI schema validation, MCP client testing, compile-time assertion patterns.
Constraints: Processor tests must use compile-testing (actual javac compilation). Never mock ProcessingEnvironment or Filer. Integration tests must verify: generated code compiles, MCP tools register, REST endpoints respond, DTOs exclude PII fields, OpenAPI spec is valid. Demo app must build from clean state as smoke test.
