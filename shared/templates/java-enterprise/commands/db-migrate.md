Create a new database migration:
1. Find the latest migration number in db/migration/
2. Ask what the migration should do
3. Create the next numbered migration file (V{N+1}__description.sql)
4. Write the SQL (with rollback comment block)
5. Run ./gradlew flywayMigrate to apply
6. Verify with flywayInfo
