Add a new code generator to the annotation processor. Generators produce Java source files or resource files from scanned annotations. Requires:
1. Create a new generator class in `modules/processor/src/main/java/.../generator/`.
2. Use JavaPoet (TypeSpec, MethodSpec, AnnotationSpec) for all code generation — never string templates.
3. Wire the generator into `AgenticProcessor.process()` at the appropriate phase.
4. Add compile-testing tests with both positive cases (correct generation) and negative cases (invalid input → clear error).
5. Verify generated output compiles standalone and integrates with the demo app.

All generated files must include `@Generated("ai.adam.processor")` annotation.

$ARGUMENTS
