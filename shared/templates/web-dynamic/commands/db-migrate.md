Create and apply a database migration:
1. Ask what schema change is needed
2. Edit prisma/schema.prisma
3. Run npx prisma migrate dev --name {description}
4. Verify migration SQL looks correct
5. Update any affected TypeScript types
6. Run tests to check for breaking changes
