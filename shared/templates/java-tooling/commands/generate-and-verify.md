Trigger annotation processing in the demo module to generate all outputs (DTOs, MCP tools, REST controllers, OpenAPI spec), then verify the generated code compiles and matches expected patterns. List all generated files with a summary of what each contains.

```bash
./gradlew :demo:clean :demo:compileJava
find demo/build/generated -name "*.java" -o -name "*.json" | sort
```
