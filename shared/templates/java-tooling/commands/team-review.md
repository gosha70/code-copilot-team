Run a comprehensive review of the project. Check:

1. **Module boundaries**: annotations has zero deps, processor has no runtime deps, dependency flow is correct.
2. **Annotation processor**: handles generics, inheritance, MirroredTypeException, emits proper diagnostics.
3. **Generated code quality**: includes @Generated, compiles standalone, null-safe mapping, no internal type imports.
4. **PII safety**: verify @AgentVisible whitelist pattern — unannotated fields must be absent from generated DTOs.
5. **API backward compatibility**: check for breaking changes to public annotations or generated code shapes.
6. **Test coverage**: compile-testing for processor, integration tests for demo, Spring Boot test slices for runtime.
7. **Publishing readiness**: version catalog consistent, POM metadata complete, all modules on same version.

```bash
./gradlew build test
./gradlew :modules:processor:test --tests "*"
./gradlew :demo:compileJava
```
