# /validate-content

Run all content validators locally — same gates the CI workflow `pack-content.yml` enforces.

## Procedure

```bash
# 1. Manifest schema check
python - <<'PY'
import sys, yaml
m = yaml.safe_load(open("content/manifest.yaml"))
required = ["name", "version", "schema_version", "content_format", "content_file", "licenses"]
missing = [k for k in required if k not in m]
if missing:
    print(f"manifest.yaml missing: {missing}", file=sys.stderr); sys.exit(1)
for k in ("data", "code"):
    assert k in m["licenses"], f"licenses.{k} required"
print(f"OK: {m['name']} {m['version']} ({m['content_format']})")
PY

# 2. Content file format validation
xmllint --noout content/data.tbx        # for tbx-3.0
# riot --validate content/data.ttl      # for turtle
# pyld --validate content/data.jsonld   # for json-ld

# 3. Sync round-trip — both wrapper resource dirs must update without error
bash scripts/sync-content.sh
test -f jvm-wrapper/src/main/resources/domain-pack/manifest.yaml
test -f python-wrapper/src/domain_pack/data/manifest.yaml

# 4. Both loaders parse the synced content
(cd jvm-wrapper && ./gradlew test)
(cd python-wrapper && pytest)
```

If any step fails, fix it before opening a PR. The CI workflow runs the same checks and will block merge on failure.
