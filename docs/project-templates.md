# Project Templates

The eleven stack templates, what each one's agent team looks like, and the CI workflow each ships.

![Agent Team Delegation](images/agent-team-roles.png)

| Template | Stack | Agent Team |
|---|---|---|
| `ml-rag` | Python · FAISS/Chroma · Neo4j/NetworkX | Team Lead, RAG Engineer, KG Engineer, Data Analyst, QA |
| `ml-langchain` | Python · LangChain/LangGraph/LangSmith | Team Lead, Agent Developer, Integration Engineer, QA & Eval |
| `ml-app` | Python · FastAPI · LiteLLM · Next.js/React | Team Lead, Backend Dev, Frontend Dev, ML/AI Engineer, QA |
| `ml-utils` | Python · MCP SDK · Chroma/Qdrant · tree-sitter | Team Lead, MCP Engineer, Retrieval Engineer, Storage Engineer, QA |
| `ml-n8n` | Python · n8n · REST/webhooks | Team Lead, Workflow Designer, Python Developer, QA & DevOps |
| `java-enterprise` | Spring Boot · Kafka · GraphQL · React | Team Lead, Backend Dev, Frontend Dev, Data & Messaging, QA, DevOps |
| `web-static` | Astro/Next.js/Hugo · Tailwind | Team Lead, Frontend Dev, Content & SEO, QA |
| `web-dynamic` | Next.js/Remix · Node/Python · PostgreSQL | Team Lead, Frontend Dev, Backend Dev, QA, DevOps |
| `java-tooling` | Java 21 · Gradle · JSR 269 · JavaPoet · Spring AI MCP | Team Lead, APT Engineer, MCP Specialist, Plugin Dev, QA |
| `gradle-plugin` | Kotlin · Gradle 8 · `Plugin<Project>` · TestKit matrix · Plugin Portal | Team Lead, Plugin Eng, Functional Test Eng, Build & Release |
| `domain-pack` | Versioned content (TBX/JSON-LD/CSV) · Maven Central + PyPI dual publish | Team Lead, Content Curator, JVM Wrapper Eng, Python Wrapper Eng, Release & CI |

> **`ui-harness`** — an add-on bundle (not a stack) that layers the [UI Design Harness](../README.md#ui-design-harness) onto any web project: `DESIGN.md` + DTCG tokens + the `harness/` visual-review runner.

### Bundled CI Workflows

Each template ships a `.github/workflows/` file so CI is wired up the moment the consumer adds their toolchain manifest.

| Stack | Workflow file | What it runs |
|---|---|---|
| `ml-app`, `ml-rag`, `ml-langchain`, `ml-n8n`, `ml-utils` | `python.yml` | ruff · mypy · pytest --cov · matrix: 3.10, 3.11, 3.12 |
| `java-enterprise`, `java-tooling` | `gradle.yml` | `./gradlew build check test` · matrix: JDK 17, 21 · optional `publish-staging` on tags |
| `web-static`, `web-dynamic` | `node.yml` | lint · typecheck · test · matrix: Node 20, 22 · auto-detects npm/yarn/pnpm |
| `domain-pack` | `pack-content.yml` + `pack-publish.yml` | manifest + content schema validation on PR · coordinated Maven Central + PyPI publish on tag |
| `gradle-plugin` | `gradle-plugin.yml` | unit tests · TestKit functional matrix (Gradle 8.5/8.10/current) · sample-consumer smoke · Plugin Portal publish on tag |

**Auto-skip on empty project.** Each workflow's job is gated on a toolchain marker (`pyproject.toml` / `setup.py` / `setup.cfg` for Python, `package.json` for Node, `gradlew` for Gradle — the wrapper, since build steps invoke `./gradlew`). A freshly bootstrapped project with no marker yet gets a green skip rather than a red failure. The job activates as soon as the consumer adds the marker file. Gradle projects that have build scripts but no wrapper get a notice nudging them to run `gradle wrapper`.

**Matrix override via `workflow_dispatch`.** Every workflow accepts a manual trigger with an optional version input (e.g. `python-version: "3.12"` or `node-version: "20"`). Leave it blank to run the full matrix; set it to a specific version to run that one only.

**Dual-branch trigger.** All workflows fire on push to `master` or `main` — whichever convention a project uses.

**Bootstrap path.** `claude-code init <type>` copies `.github/workflows/` into the new project automatically. `claude-code sync` keeps the workflow file up to date alongside `remediation.json` and commands.
