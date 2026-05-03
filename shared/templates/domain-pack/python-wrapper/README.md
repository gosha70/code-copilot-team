# Python Wrapper

Thin PyPI distribution that ships the pack content as `package_data` and
exposes a loader API mirroring the JVM wrapper.

## Build

```bash
bash ../scripts/sync-content.sh   # copy ../content into src/domain_pack/data
pip install -e ".[dev]"
pytest
python -m build                   # produces sdist + wheel in dist/
```

`name`, `version`, and `description` are read from `../content/manifest.yaml`
by `setup.py`. Bump the manifest, then build.

## Loader API

```python
from domain_pack import manifest, entries, version

m = manifest()
items = entries()
v = version()
```

Mirror this surface in `jvm-wrapper/src/main/java/com/example/domainpack/PackLoader.java`.
Diverging the two APIs is a defect.
