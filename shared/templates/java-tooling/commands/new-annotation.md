Add a new annotation to the framework. Requires:
1. Define the annotation in `modules/annotations/` with proper @Target, @Retention(RUNTIME), and Javadoc.
2. Update the processor in `modules/processor/` to recognize and handle the new annotation.
3. Add compile-testing tests verifying correct generation and error cases.
4. Update the demo app to exercise the new annotation.
5. Update `docs/annotation-guide.md` with usage examples.

Ensure the annotations module remains zero-dependency. The new annotation must not break existing processor behavior — run full test suite to verify.

$ARGUMENTS
