# Sample Consumer

This is an out-of-tree composite build that applies the plugin from the parent
project. It is **not** a subproject — its `pluginManagement.includeBuild("..")`
hook pulls the plugin in as a composite build, which mirrors how a real
consumer pulls the plugin from the Gradle Plugin Portal (minus the network
hop).

## Run end-to-end

```bash
cd sample-consumer
./gradlew exampleHello       # uses the consumer's wrapper
cat build/example/greeting.txt
```

If you don't yet have a `gradlew` in this directory, run `gradle wrapper` once
to generate one.
