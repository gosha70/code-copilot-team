Implement a new feature end-to-end. Ask for:
1. Feature description
2. Which bounded context(s) it belongs to
Then coordinate the team:
- Team Lead: update GraphQL schema in api-schema/
- Java Backend Developer: implement resolvers, services, domain logic
- Data & Messaging Engineer: create migrations, set up events if needed
- Frontend Developer: add GraphQL operations, build UI components
- QA Engineer: write tests at every layer
- DevOps: update Docker/k8s if new services needed
Present implementation plan before starting.
