# ML/AI — n8n Workflow Automation

## Stack
- n8n (self-hosted via Docker) for workflow orchestration
- Python 3.11+ for custom logic (FastAPI microservices)
- Node.js for n8n custom nodes (when needed)
- PostgreSQL for n8n backend + application data
- Redis for caching and job queues

## Project Structure
```
├── CLAUDE.md
├── docker-compose.yml          # n8n + Postgres + Redis + app services
├── workflows/                  # Exported n8n workflow JSON files
│   ├── production/             # Active production workflows
│   └── templates/              # Reusable workflow templates
├── services/                   # Python microservices called by n8n
│   ├── ml-service/             # ML inference endpoints
│   ├── data-service/           # Data processing endpoints
│   └── shared/                 # Shared libraries
├── custom-nodes/               # Custom n8n nodes (TypeScript)
├── credentials/                # Credential type definitions (not secrets!)
├── config/                     # Environment configs
└── tests/
```

## n8n Conventions
- Every workflow exported to `workflows/` as JSON (version controlled)
- Workflow naming: `{domain}-{action}-{version}` (e.g., `orders-sync-v2`)
- Use sub-workflows for reusable logic (DRY principle)
- Error handling: every workflow must have an error trigger node
- Webhook endpoints: document in README with method, path, expected payload
- Credentials: use n8n credential store, never hardcode in workflow JSON

## Integration Patterns
- n8n → Python service: HTTP Request node to FastAPI endpoints
- Python service → n8n: webhook triggers for async callbacks
- Scheduled workflows: use Cron trigger, document schedule in workflow notes
- Data passing: prefer JSON payloads; binary data via temporary S3/MinIO URLs
- Rate limiting: implement in Python service, not n8n (more control)

## Python Service Rules
- Each service: independent FastAPI app with its own Dockerfile
- Pydantic models for all request/response schemas
- Health check endpoint at /health for Docker Compose
- Async handlers for any I/O-bound operations
- Structured logging (JSON format) for aggregation

## Testing
- n8n workflows: manual test via n8n UI, document test cases in workflow notes
- Python services: pytest (unit + integration)
- Integration: docker-compose test profile with mock external services
- Workflow validation: script to check all workflows have error handlers

## Commands
```bash
docker compose up -d                      # start everything
docker compose logs -f n8n                # n8n logs
docker compose exec n8n n8n export:workflow --all --output=workflows/  # export
poetry -C services/ml-service run pytest  # test ML service
```

## Agent Team

### Roles

| Role | Trigger | Owns |
|------|---------|------|
| **Team Lead** (default) | Planning, integration architecture, review | Overall coordination |
| **Workflow Designer** | n8n workflow creation/modification, node config | `workflows/`, `custom-nodes/` |
| **Python Developer** | Microservice code, ML logic, API endpoints | `services/` |
| **QA & DevOps Engineer** | Testing, Docker, CI/CD, monitoring | `tests/`, `docker-compose.yml`, `config/` |

### Team Lead — Default Behavior
You ARE the Team Lead. You own integration architecture:
1. How n8n workflows connect to Python services (webhook contracts).
2. Data flow design between workflow nodes and microservices.
3. Simple changes within one domain → handle directly. Cross-domain → delegate.
4. Always verify workflow JSON exports are committed after changes.

### Delegation Prompts
```
You are the [ROLE] on an n8n + Python microservices project.

Project conventions:
- [paste relevant section from this CLAUDE.md]

Your task: [specific task description]

Constraints:
- Follow all conventions above
- Document any new webhook endpoints or workflow triggers
- Return: changes + summary of integration points affected
```

### Workflow Designer
Expertise: n8n workflow design, node configuration, sub-workflow patterns, error handling nodes, webhook/cron triggers, custom node development (TypeScript).
Constraints: every workflow has error trigger node. Export to `workflows/` after changes. Use sub-workflows for reuse. Document webhooks in README. Never hardcode credentials.

### Python Developer
Expertise: FastAPI, Pydantic, async Python, ML model serving, Docker.
Constraints: each service is independent FastAPI app with Dockerfile. Pydantic models for all schemas. Health check at `/health`. Async handlers for I/O. Structured JSON logging.

### QA & DevOps Engineer
Expertise: pytest, Docker Compose, CI/CD, monitoring, workflow validation scripts.
Constraints: run tests before deploying. Docker-compose test profile for integration tests. Validate all workflows have error handlers. Monitor service health endpoints.
