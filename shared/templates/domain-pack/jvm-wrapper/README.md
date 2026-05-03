# JVM Wrapper

Thin Maven Central artifact that ships the pack content under `domain-pack/`
JAR resources and exposes a loader API mirroring the Python wrapper.

## Build

```bash
./gradlew build           # compiles, runs tests
./gradlew test            # tests only
./gradlew publishToMavenLocal   # local install for downstream testing
```

The build script reads `name` and `version` from `../content/manifest.yaml` —
do **not** hardcode them here. Bump the manifest, then build.

## Loader API

```java
import com.example.domainpack.PackLoader;

var manifest = PackLoader.manifest();
var entries = PackLoader.entries();
var version = PackLoader.version();
```

Mirror this surface in `python-wrapper/src/<pack>/loader.py`. Diverging the
two APIs is a defect.
