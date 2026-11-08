---
applyTo: "**/Dockerfile*,**/docker-compose*,**/compose*,**/*.sh,**/.github/workflows/*"
---


# Infrastructure Verification — "Build It, Run It"

## Principle

Any artifact whose correctness cannot be verified by a language-level test runner
MUST be executed before committing. This includes: Dockerfiles, docker-compose files,
shell scripts, CI workflows, launcher scripts, and hook scripts.

## Verification Commands by Artifact Type

| Artifact | Minimum Verification | Full Verification |
|----------|---------------------|-------------------|
| Dockerfile | `docker build -t verify .` | Build + run + healthcheck |
| docker-compose.yml | `docker compose config` | `docker compose up --build -d` + healthcheck + `down` |
| `.sh` script | `bash -n script.sh` | Run with `--help` or `--dry-run` if supported |
| `.github/workflows/*.yml` | `actionlint` (if available) | YAML schema validation |
| Launcher flags | Run `<launcher> --help` | Run with new flag and verify output |

## Environment Failure vs. Artifact Bug

When infrastructure verification fails, distinguish:
- **Artifact bug** (Dockerfile syntax, wrong base image, missing COPY): Fix the artifact.
- **Environment issue** (Docker daemon not running, network timeout): Report the environmental prerequisite. Do NOT suggest skipping the verification — help the user fix their environment.

## Health Probes

Docker healthchecks MUST use dedicated health endpoints (`/actuator/health`, `/healthz`,
`/health`), not business endpoints. Business endpoints may require auth, have side effects,
or return errors unrelated to service health.

## Demo Endpoints

Demo/example endpoints MUST return meaningful sample data, not empty stubs (`[]`, `null`, `{}`).
Verify each endpoint with a test request and confirm the response is non-empty and
structurally correct.

## Multiplexer-Aware Verification

When the project uses a terminal multiplexer (detected via `claude-code`, `$TMUX`, or `$CMUX_WORKSPACE_ID`):
- UI-facing features (banners, status messages) must be verified inside the active multiplexer session
- Environment variables must be passed directly to processes (not via multiplexer env injection for already-running processes)
- Test launcher flags by actually running the launcher command

## Self-Execute Test Plan

If you write a manual test plan with executable commands:
1. Execute every command yourself
2. Report the output of each command
3. Fix any failures before declaring done
4. Do NOT hand an unverified test plan to the user

## Shown Commands Are Checked

Every command a page shows gets the cheapest real check that applies before it
is committed, whether or not CI runs it. "Not executed in CI" is a label, not an
exemption: wiki-studio 0.8.1 shipped the quickstart line
`pip install 'memkernel[wiki]==0.6.0' 'wiki-studio[mcp]==0.8.1'`, which pip
cannot resolve (memkernel 0.6.0 requires `mcp<2`, the extra needs `mcp>=2.3`);
`pip install --dry-run` would have said so in seconds (#409).

| Shown line | Cheapest real check |
|---|---|
| `pip install …`, `npm install …` | `pip install --dry-run …`, `npm install --dry-run …` — resolves, installs nothing |
| a CLI invocation | run it with `--help`, or `--dry-run` where the tool has one |
| a config block (TOML, YAML, JSON) | parse it with the language's parser |
| a shell snippet | `bash -n`, then run it in a scratch directory if it has no side effects |

Record the check beside the change (PR body or commit message) with the command
and its result, so a reviewer can see the line was resolved, not merely read.
