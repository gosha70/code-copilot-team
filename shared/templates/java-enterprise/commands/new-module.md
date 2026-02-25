Scaffold a new bounded context module. Ask for:
1. Module name (kebab-case)
2. Base package name
Then create:
- modules/{name}/build.gradle.kts with standard dependencies
- Hexagonal package structure: adapter/(in/out), application, domain, port
- A placeholder domain entity, port interface, and application service
- Unit test skeleton
- Add module to settings.gradle.kts
