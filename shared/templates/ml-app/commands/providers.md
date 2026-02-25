Check LLM provider status and connectivity:
1. Read configured provider environment variables
2. For each configured provider, attempt a minimal health check (list models or ping)
3. Report: provider name, status (connected/error), default model, estimated cost
4. If no providers are configured, show setup instructions
