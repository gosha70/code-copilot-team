# Common Pitfalls & Solutions

Cross-cutting issues that arise during multi-agent builds, regardless of stack.

## Build & Dependencies

| Issue | Root Cause | Prevention | Solution |
|-------|-----------|-----------|----------|
| Bleeding-edge version breaks tooling | Used pre-release/beta version of a core dependency | Pin stable versions in project setup | Downgrade to latest stable release |
| Missing runtime dependency | Agent generated code requiring a package it didn't install | Agents should install dependencies as part of their task | Check error logs, install missing packages |
| Build passes but runtime fails | Only ran static analysis, not the actual dev server | Always run the dev server after changes | Add build verification to phase workflow |
| "Module not found" at runtime | New dependency added in code but not in package manifest | Install immediately after code generation | Check console output, install missing packages |

## Environment & Configuration

| Issue | Root Cause | Prevention | Solution |
|-------|-----------|-----------|----------|
| App crashes on startup | No local config file exists | Create local config from template in Phase 1 | Copy template file and fill in values |
| Service connection refused | Service not running or wrong credentials in config | Verify service setup before running migrations | Start the service, verify connection string |
| Config validation fails | Local config missing required variables | Use startup validation with clear error messages | Add missing variables to local config |
| Works locally, fails in CI | Different runtime versions or missing env vars | Pin versions, document all required env vars | Align CI environment with local setup |

## Data Model & Schema

| Issue | Root Cause | Prevention | Solution |
|-------|-----------|-----------|----------|
| Mid-phase schema changes | Design doc missing entity details | Data model review gate before build phase | Pause agents, update schema, regenerate ORM client, resume |
| Schema migration fails | Database doesn't exist or permissions wrong | Test connection before running migrations | Create database, fix credentials |
| ORM/code generation fails | Schema syntax error or version incompatibility | Validate schema before generation | Fix schema errors, check tool version |
| Ambiguous field names | Generic names like "name", "value", "data" | Review field granularity in data model gate | Use specific, descriptive names: `accountBalance`, `taskStatus`, `eventDate` |

## Agent Coordination

| Issue | Root Cause | Prevention | Solution |
|-------|-----------|-----------|----------|
| Type/compile errors after parallel agents | Agents made incompatible changes | Ensure non-overlapping file ownership | Run type checker after all agents complete, fix conflicts |
| Duplicate work | Two agents implement the same feature | Clear task boundaries in delegation | Review task assignments before spawning agents |
| Missing integration | Agent A expects an API that Agent B didn't create | Define interfaces/contracts before delegating | Create stubs/placeholders, implement in next phase |
| Schema drift | One agent changed the data model mid-phase | Lock schema before parallel work begins | Regenerate ORM client, update dependent code |

## Authentication & Security

| Issue | Root Cause | Prevention | Solution |
|-------|-----------|-----------|----------|
| Plain passwords in database | No hashing implemented | Always hash with bcrypt/argon2; or use passwordless auth | Migrate to hashed passwords |
| Secrets committed to git | Config file not in .gitignore | Verify .gitignore during scaffolding | Remove from git history, rotate secrets, fix .gitignore |
| Auth route crashes | Missing auth dependencies | Install auth-related packages during setup | Check error logs, install missing packages |
| SMTP/email fails | Using account password instead of app-specific password | Document credential setup requirements | Generate app-specific password per provider docs |

## Testing & Validation

| Issue | Root Cause | Prevention | Solution |
|-------|-----------|-----------|----------|
| Tests pass but app crashes | Tests don't cover real runtime paths | Always run the dev server, not just tests | Add integration/e2e tests for critical flows |
| API returns data but UI is empty | Frontend not wired to backend correctly | Verify integration after parallel agents | Check API calls, verify data binding |
| Form submits but nothing happens | Missing error handling in mutations | Add error states to all forms | Log errors, show user-friendly messages |
| Layout breaks on mobile | Only tested desktop viewport | Test at multiple breakpoints | Use responsive utilities, test mobile-first |

## Performance & Optimization

| Issue | Root Cause | Prevention | Solution |
|-------|-----------|-----------|----------|
| Slow page/endpoint response | Missing caching, large payloads, N+1 queries | Use framework built-in optimizations | Profile, add caching, optimize queries |
| Slow database queries | Missing indexes on foreign keys and filter columns | Add indexes in schema during data model review | Add indexes on FK fields and common query patterns |
| Memory leaks | Database/HTTP client not reused (new connection per request) | Use singleton/pool pattern for clients | Share client instance across requests |
| Deployment timeouts | Synchronous blocking operations | Use async patterns, queue long-running tasks | Move heavy work to background jobs |

## Git & Deployment

| Issue | Root Cause | Prevention | Solution |
|-------|-----------|-----------|----------|
| Merge conflicts in generated files | Multiple agents or developers ran code generation | Designate one owner for generated files | Resolve manually, regenerate cleanly |
| Build fails in CI but passes locally | Different runtime versions | Pin versions in project config, use version manager | Align versions, add version config file |
| Migrations fail in production | Database state diverged from expected | Never edit migrations manually after applying | Roll back, fix locally, push clean migration |
| Secrets exposed in logs | Logging config values or sensitive data | Sanitize logs, never log secrets | Remove from logs, rotate exposed secrets |

## SDD Workflow

| Issue | Root Cause | Prevention | Solution |
|-------|-----------|-----------|----------|
| Build agent skips spec gate | `plan.md` missing `spec_mode` frontmatter | Always emit `plan.md` from Plan phase, even for `spec_mode: none` | Re-run Plan agent to emit properly formatted `plan.md` |
| Same mistake repeated across projects | No knowledge capture mechanism | Consult and append to `specs/lessons-learned.md` during builds | Review `specs/lessons-learned.md` at session start |
| Spec has unresolved ambiguities | `[NEEDS CLARIFICATION]` markers left in `spec.md` | Resolve all markers via clarifying questions before completing Plan | Return to Plan phase, resolve markers, re-approve |
| Lessons-learned file missing | Never initialized from template | Copy `shared/templates/sdd/lessons-learned-template.md` to `specs/lessons-learned.md` during project init | Create the file manually from the template |
