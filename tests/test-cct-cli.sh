#!/usr/bin/env bash

# test-cct-cli.sh — the `cct` front door (#214 Phase 5).
#
# `cct` composes what other scripts own; these assertions check the composing:
# that every command is reachable, that `features` reports the catalog
# faithfully (including without PyYAML, which this repository does not
# require), and that a bad argument fails loudly instead of printing nothing.
#
# Run from the repo root:
#   bash tests/test-cct-cli.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CCT="$REPO_DIR/scripts/cct"
CATALOG="$REPO_DIR/shared/features/catalog.yaml"
PASS=0
FAIL=0

assert() {
  local name="$1" condition="$2"
  if eval "$condition"; then
    echo "  PASS: $name"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name"; FAIL=$((FAIL + 1))
  fi
}

echo "=== cct CLI ==="

assert "cct is executable" "[[ -x '$CCT' ]]"
HELP=$(bash "$CCT" help)
for c in features list routing doctor config help; do
  assert "help documents: $c" "grep -qE '^  $c ' <<<\"\$HELP\""
done
# Capture, then grep: these commands exit nonzero by design, and under
# `set -o pipefail` the pipeline inherits that even when grep matches.
UNKNOWN_OUT=$(bash "$CCT" no-such-command 2>&1 || true)
RC=0; bash "$CCT" no-such-command >/dev/null 2>&1 || RC=$?
assert "an unknown command exits 2" "[[ '$RC' == '2' ]]"
assert "an unknown command suggests the real ones" \
  "grep -q 'Did you mean: features' <<<\"\$UNKNOWN_OUT\""

# ── features: faithful to the catalog ────────────────────────
N=$(ruby -ryaml -e 'puts YAML.load_file(ARGV[0])["features"].size' "$CATALOG")
OUT=$(bash "$CCT" features)
assert "features lists every feature ($N)" "[[ \$(grep -c . <<<\"\$OUT\") -ge $N ]]"
assert "features says where maturity is defined" "grep -q 'docs/maturity.md' <<<\"\$OUT\""

JSON=$(bash "$CCT" features --json)
assert "features --json is valid JSON with every feature" \
  "python3 -c \"
import json, sys
d = json.loads(sys.stdin.read())
sys.exit(0 if len(d) == $N else 1)\" <<<\"\$JSON\""

# The catalog is YAML and this repository does not require PyYAML, so the
# fallback reader must agree with a real parser — field for field, not just
# in count. A block list (prerequisites) was dropped silently by the first
# version of that reader.
ruby -ryaml -rjson -e 'puts JSON.generate(YAML.load_file(ARGV[0])["features"])' "$CATALOG" > "$REPO_DIR/.cct-test-ruby.json"
bash "$CCT" features --json > "$REPO_DIR/.cct-test-mine.json"
assert "the fallback YAML reader matches a real parser, field for field" \
  "python3 -c \"
import json, re, sys
a = json.load(open('$REPO_DIR/.cct-test-ruby.json'))
b = json.load(open('$REPO_DIR/.cct-test-mine.json'))
norm = lambda v: re.sub(r'\\\\s+', ' ', v).strip() if isinstance(v, str) else v
bad = [(x.get('id'), k) for x, y in zip(a, b) for k in set(x) | set(y)
       if norm(x.get(k)) != norm(y.get(k))]
if bad:
    print(bad[:3], file=sys.stderr)
sys.exit(0 if not bad and len(a) == len(b) else 1)\""
rm -f "$REPO_DIR/.cct-test-ruby.json" "$REPO_DIR/.cct-test-mine.json"

assert "prerequisites survive the fallback reader" \
  "bash '$CCT' features --feature peer-review | grep -q 'prerequisites'"

# ── filters ──────────────────────────────────────────────────
for adapter in claude-code pi aider; do
  assert "filter --adapter $adapter returns features" \
    "[[ \$(bash '$CCT' features --adapter $adapter --json | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))') -gt 0 ]]"
done
assert "filter --maturity stable returns only stable features" \
  "[[ \$(bash '$CCT' features --maturity stable --json | python3 -c \"
import json, sys
d = json.load(sys.stdin)
print(len({f['maturity'] for f in d}))\") -eq 1 ]]"

# Under --adapter the last column must answer "what does MY tool do with
# this?" — it printed the globally enforcing adapters, so an Aider user was
# told "claude-code, pi" and nothing about Aider (#360 review).
PI_OUT=$(bash "$CCT" features --adapter pi)
AIDER_OUT=$(bash "$CCT" features --adapter aider)
assert "--adapter pi marks an enforced feature as enforced by pi" \
  "grep -q 'Spec-driven development.*enforced by pi' <<<\"\$PI_OUT\""
assert "--adapter pi marks an advisory feature as advisory in pi" \
  "grep -q 'Shape-Up product bets.*advisory in pi' <<<\"\$PI_OUT\""
assert "--adapter aider never claims another adapter's enforcement" \
  "! grep -qE 'claude-code|enforced by' <<<\"\$AIDER_OUT\""
assert "--adapter aider marks its features advisory" \
  "grep -q 'advisory in aider' <<<\"\$AIDER_OUT\""
assert "the filtered footer names the adapter" \
  "grep -q 'features delivered by aider' <<<\"\$AIDER_OUT\""
UNFILTERED=$(bash "$CCT" features)
assert "unfiltered output still lists the enforcing adapters" \
  "grep -q 'Spec-driven development.*claude-code, pi' <<<\"\$UNFILTERED\""

RC=0; bash "$CCT" features --adapter no-such-adapter >/dev/null 2>&1 || RC=$?
assert "an unknown adapter exits 2 and names the known ones" "[[ '$RC' == '2' ]]"
ADAPTER_ERR=$(bash "$CCT" features --adapter no-such-adapter 2>&1 || true)
assert "the unknown-adapter error lists the adapters" \
  "grep -q 'claude-code' <<<\"\$ADAPTER_ERR\""
RC=0; bash "$CCT" features --feature no-such-feature >/dev/null 2>&1 || RC=$?
assert "an unknown feature exits 2" "[[ '$RC' == '2' ]]"

# ── the detail view carries the catalog's fields ─────────────
DETAIL=$(bash "$CCT" features --feature auto-build)
for field in maturity since guide adapters; do
  assert "detail shows $field" "grep -q '$field' <<<\"\$DETAIL\""
done
assert "detail marks an unsupported adapter, not a blank" "grep -qE 'cursor +—' <<<\"\$DETAIL\""

# ── doctor (#214 Phase 5.2) ──────────────────────────────────
# --no-network everywhere: a test must not depend on a provider being up.
DOCTOR=$(bash "$CCT" doctor --no-network 2>&1 || true)
assert "doctor reports the tool checks" "grep -q 'Tools' <<<\"\$DOCTOR\""
assert "doctor reports the repository registries" "grep -q 'feature catalog' <<<\"\$DOCTOR\""
assert "doctor reports adapters" "grep -q 'Adapters' <<<\"\$DOCTOR\""
assert "doctor skips healthchecks when asked" "grep -q 'no-network' <<<\"\$DOCTOR\""

# The rule this command must never break: a key's NAME and whether it is set,
# never the value. A sentinel value must not appear anywhere in the output.
SENTINEL_PROFILE="$(mktemp -d)/providers.toml"
cat > "$SENTINEL_PROFILE" <<'TOML'
[providers.hosted]
type = "openai-compatible"
base_url = "https://api.example.com/v1"
api_key_env = "CCT_DOCTOR_TEST_KEY"
healthcheck = "true"
TOML
SECRET_OUT=$(CCT_PROVIDER_PROFILE="$SENTINEL_PROFILE" CCT_DOCTOR_TEST_KEY="sk-SENTINELdoNOTprint" \
  bash "$CCT" doctor --no-network 2>&1 || true)
assert "doctor names the key variable" "grep -q 'CCT_DOCTOR_TEST_KEY' <<<\"\$SECRET_OUT\""
assert "doctor says the variable is set" "grep -qE 'CCT_DOCTOR_TEST_KEY.*set' <<<\"\$SECRET_OUT\""
assert "doctor never prints the key itself" "! grep -q 'SENTINELdoNOTprint' <<<\"\$SECRET_OUT\""
UNSET_OUT=$(CCT_PROVIDER_PROFILE="$SENTINEL_PROFILE" bash -c "unset CCT_DOCTOR_TEST_KEY; bash '$CCT' doctor --no-network" 2>&1 || true)
assert "doctor flags an unset key variable" "grep -qE 'CCT_DOCTOR_TEST_KEY.*not set' <<<\"\$UNSET_OUT\""
rm -rf "$(dirname "$SENTINEL_PROFILE")"

# A key pasted into api_key_env must never be echoed. The valid-name case
# above was the only one tested, and an INVALID one printed the field verbatim
# — a credential in the terminal and in CI logs (#361 review).
BAD_PROFILE="$(mktemp -d)/providers.toml"
cat > "$BAD_PROFILE" <<'TOML'
[providers.hosted]
type = "openai-compatible"
base_url = "https://api.example.com/v1"
api_key_env = "sk-SENTINELpastedKEYnotAname"
healthcheck = "true"
TOML
BAD_OUT=$(CCT_PROVIDER_PROFILE="$BAD_PROFILE" bash "$CCT" doctor --no-network 2>&1 || true)
assert "an api_key_env holding a key is never echoed" "! grep -q 'SENTINELpastedKEY' <<<\"\$BAD_OUT\""
assert "it is reported as not a variable name" "grep -q 'not a variable name' <<<\"\$BAD_OUT\""
assert "it says how many characters were redacted" "grep -qE '[0-9]+ characters, redacted' <<<\"\$BAD_OUT\""
assert "it tells the user to rotate the key" "grep -q 'rotate it' <<<\"\$BAD_OUT\""
BAD_JSON=$(CCT_PROVIDER_PROFILE="$BAD_PROFILE" bash "$CCT" doctor --no-network --json 2>&1 || true)
assert "the JSON output does not leak it either" "! grep -q 'SENTINELpastedKEY' <<<\"\$BAD_JSON\""
rm -rf "$(dirname "$BAD_PROFILE")"

# Healthchecks must run against the profile doctor validated, and a healthy
# provider must not read as a failure: the summary line "0 failed" did.
HEALTH_PROFILE="$(mktemp -d)/providers.toml"
cat > "$HEALTH_PROFILE" <<'TOML'
[providers.alive]
type = "cli"
command = "true < {review_request}"
healthcheck = "true"

[providers.dead]
type = "cli"
command = "true < {review_request}"
healthcheck = "false"
TOML
HEALTH_OUT=$(CCT_PROVIDER_PROFILE="$HEALTH_PROFILE" bash "$CCT" doctor 2>&1 || true)
assert "a healthy provider from the given profile is reported reachable" \
  "grep -q 'alive healthcheck.*reachable' <<<\"\$HEALTH_OUT\""
assert "a failing provider from the given profile is reported failed" \
  "grep -q 'dead healthcheck.*healthcheck failed' <<<\"\$HEALTH_OUT\""
assert "healthchecks use the profile given, not the default" \
  "! grep -qE '(deepseek|spark) healthcheck' <<<\"\$HEALTH_OUT\""
ONLY_OK_PROFILE="$(mktemp -d)/providers.toml"
printf '[providers.alive]\ntype = "cli"\ncommand = "true < {review_request}"\nhealthcheck = "true"\n' > "$ONLY_OK_PROFILE"
OK_OUT=$(CCT_PROVIDER_PROFILE="$ONLY_OK_PROFILE" bash "$CCT" doctor 2>&1 || true)
OK_RC=0; CCT_PROVIDER_PROFILE="$ONLY_OK_PROFILE" bash "$CCT" doctor >/dev/null 2>&1 || OK_RC=$?
assert "an all-healthy profile does not make doctor fail" "[[ '$OK_RC' == '0' ]]"
assert "the health summary line is not read as a failure" "! grep -q '0 failed healthcheck' <<<\"\$OK_OUT\""
rm -rf "$(dirname "$HEALTH_PROFILE")" "$(dirname "$ONLY_OK_PROFILE")"

# A missing profile is a warning, not a failure: peer review is optional.
ABSENT=$(CCT_PROVIDER_PROFILE="/nonexistent/providers.toml" bash "$CCT" doctor --no-network 2>&1 || true)
assert "a missing provider profile warns rather than fails" "grep -q 'peer review is off' <<<\"\$ABSENT\""

# An adapter that is not installed is absent, not broken — cct assumes nothing.
assert "an advisory adapter is reported as nothing to probe" \
  "grep -qE 'cursor.*nothing to probe' <<<\"\$DOCTOR\""
RC=0; bash "$CCT" doctor --adapter no-such-adapter >/dev/null 2>&1 || RC=$?
assert "an unknown adapter exits 2" "[[ '$RC' == '2' ]]"
ONLY=$(bash "$CCT" doctor --adapter pi 2>&1 || true)
assert "--adapter runs only that adapter's section" "! grep -q 'Tools' <<<\"\$ONLY\""

DOCTOR_JSON=$(bash "$CCT" doctor --no-network --json 2>&1 || true)
assert "doctor --json is valid and carries a status" \
  "python3 -c \"
import json, sys
d = json.loads(sys.stdin.read())
sys.exit(0 if d['status'] in ('ok', 'warn', 'fail') and d['checks'] else 1)\" <<<\"\$DOCTOR_JSON\""

# ── config (#214 Phase 5.3) ──────────────────────────────────
KEYS=$(bash "$CCT" config explain --list)
assert "explain --list names the automation keys" "grep -q '^caps.cost_usd$' <<<\"\$KEYS\""
assert "explain --list names the provider keys" "grep -q 'providers.<name>.model' <<<\"\$KEYS\""
assert "explain --list names the analytics keys" "grep -q '^analytics.judge.workers$' <<<\"\$KEYS\""
assert "explain --list --json is a JSON array" \
  "bash '$CCT' config explain --list --json | python3 -c \"
import json, sys
d = json.load(sys.stdin)
sys.exit(0 if isinstance(d, list) and len(d) > 50 else 1)\""

# Descriptions come from the schemas; nothing is retyped in the CLI.
CAP=$(bash "$CCT" config explain providers.\<name\>.disable_thinking)
assert "explain uses the schema's own description" "grep -q 'hidden reasoning' <<<\"\$CAP\""
assert "explain names the file the key lives in" "grep -q 'providers.toml' <<<\"\$CAP\""

# §7: a provider-owned setting is reported as externally resolved.
MODEL=$(bash "$CCT" config explain providers.\<name\>.model)
assert "a provider-owned key says who owns it" "grep -q 'owner     the provider' <<<\"\$MODEL\""
assert "a provider-owned key says it resolves externally" "grep -q 'resolved externally' <<<\"\$MODEL\""
CCT_OWNED=$(bash "$CCT" config explain caps.cost_usd)
assert "a cct-owned key does not claim external ownership" "! grep -q 'owner     the provider' <<<\"\$CCT_OWNED\""

# An analytics key shows its default and the layer in effect.
WORKERS=$(bash "$CCT" config explain analytics.judge.workers)
assert "an analytics key shows its default" "grep -qE 'default   [0-9]' <<<\"\$WORKERS\""
assert "an analytics key shows the layer in effect" "grep -q 'set by' <<<\"\$WORKERS\""

# Partial keys help rather than guess; unknown keys fail.
AMBIG=$(bash "$CCT" config explain cost 2>&1 || true)
assert "an ambiguous key lists the candidates" "grep -q 'caps.cost_usd' <<<\"\$AMBIG\""
RC=0; bash "$CCT" config explain cost >/dev/null 2>&1 || RC=$?
assert "an ambiguous key exits 2" "[[ '$RC' == '2' ]]"
RC=0; bash "$CCT" config explain no.such.key >/dev/null 2>&1 || RC=$?
assert "an unknown key exits 2" "[[ '$RC' == '2' ]]"
UNIQUE=$(bash "$CCT" config explain wall_clock_sec)
assert "an unambiguous partial key resolves" "grep -q 'caps.wall_clock_sec' <<<\"\$UNIQUE\""

# validate delegates; it must report per validator, and survive a bad profile.
VALIDATE=$(bash "$CCT" config validate 2>&1 || true)
assert "validate reports the feature catalog" "grep -q 'feature catalog' <<<\"\$VALIDATE\""
assert "validate reports the capability registry" "grep -q 'capability registry' <<<\"\$VALIDATE\""
assert "validate reports the provider profile" "grep -q 'provider profile' <<<\"\$VALIDATE\""
VALIDATE_JSON=$(bash "$CCT" config validate --json 2>&1 || true)
assert "validate --json is valid JSON" \
  "python3 -c \"
import json, sys
d = json.loads(sys.stdin.read())
sys.exit(0 if isinstance(d, list) and d and 'status' in d[0] else 1)\" <<<\"\$VALIDATE_JSON\""
BROKEN="$(mktemp -d)/providers.toml"
printf '[providers.x]\ntype = "cli"\n' > "$BROKEN"
RC=0; CCT_PROVIDER_PROFILE="$BROKEN" bash "$CCT" config validate >/dev/null 2>&1 || RC=$?
assert "an invalid profile makes validate exit 1" "[[ '$RC' == '1' ]]"
BROKEN_OUT=$(CCT_PROVIDER_PROFILE="$BROKEN" bash "$CCT" config validate 2>&1 || true)
assert "the failing validator's first finding is shown" "grep -q 'command' <<<\"\$BROKEN_OUT\""
rm -rf "$(dirname "$BROKEN")"
RC=0; bash "$CCT" config validate --config /nonexistent/automation.json >/dev/null 2>&1 || RC=$?
assert "a missing automation config exits 2" "[[ '$RC' == '2' ]]"

# ── explain must never print a credential (#362 review) ──────
SA_CONFIG="$(mktemp -d)/session-analytics.json"
printf '{"judge": {"api_key": "sk-SENTINELdoNOTprintTHIS"}}' > "$SA_CONFIG"
KEY_OUT=$(CCT_SA_USER_CONFIG="$SA_CONFIG" bash "$CCT" config explain analytics.judge.api_key 2>&1 || true)
KEY_JSON=$(CCT_SA_USER_CONFIG="$SA_CONFIG" bash "$CCT" config explain analytics.judge.api_key --json 2>&1 || true)
assert "explain never prints a credential (human)" "! grep -q 'SENTINELdoNOTprint' <<<\"\$KEY_OUT\""
assert "explain never prints a credential (json)" "! grep -q 'SENTINELdoNOTprint' <<<\"\$KEY_JSON\""
assert "explain says the value is redacted" "grep -q '(redacted)' <<<\"\$KEY_OUT\""
assert "explain marks the key as a credential" "grep -q 'never the value' <<<\"\$KEY_OUT\""
assert "the json marks it sensitive" "grep -q '\"sensitive\": true' <<<\"\$KEY_JSON\""
assert "a dsn is treated as a credential too" \
  "bash '$CCT' config explain analytics.dsn --json | grep -q '\"sensitive\": true'"
assert "an ordinary key is not redacted" \
  "! bash '$CCT' config explain analytics.judge.workers --json | grep -q 'redacted'"
rm -rf "$(dirname "$SA_CONFIG")"

# ── the value in effect must respect every layer ─────────────
# Reading only defaults and the user file reported the default for a key an
# exported variable or a .env had already changed.
ENV_OUT=$(CCT_SA_JUDGE_WORKERS=7 bash "$CCT" config explain analytics.judge.workers 2>&1 || true)
assert "an exported variable is the value in effect" "grep -q 'in effect \"7\"' <<<\"\$ENV_OUT\""
assert "and the environment is named as the layer" "grep -q 'set by the environment' <<<\"\$ENV_OUT\""
assert "the controlling variable is shown" "grep -q 'CCT_SA_JUDGE_WORKERS' <<<\"\$ENV_OUT\""

# .env precedence, against a fixture repository so the developer's own .env
# cannot decide whether this passes.
FIXTURE=$(mktemp -d)
mkdir -p "$FIXTURE/scripts/session_analytics/config_data" "$FIXTURE/shared/schemas"
for f in config.py constants.py; do
  ln -s "$REPO_DIR/scripts/session_analytics/$f" "$FIXTURE/scripts/session_analytics/$f"
done
ln -s "$REPO_DIR/scripts/session_analytics/config_data/defaults.json" \
      "$FIXTURE/scripts/session_analytics/config_data/defaults.json"
printf 'CCT_SA_JUDGE_WORKERS=5\n' > "$FIXTURE/.env"
DOTENV=$(python3 -c "
import sys
sys.path.insert(0, '$REPO_DIR/scripts/lib')
import analytics_layers
from pathlib import Path
print(analytics_layers.resolve('judge.workers', Path('$FIXTURE'), environ={}))
")
assert ".env sets the value when nothing is exported" "grep -q \"'value': '5'\" <<<\"\$DOTENV\""
assert "and .env is named as the layer" "grep -q '.env (\$CCT_SA_JUDGE_WORKERS)' <<<\"\$DOTENV\""
EXPORTED=$(python3 -c "
import sys
sys.path.insert(0, '$REPO_DIR/scripts/lib')
import analytics_layers
from pathlib import Path
print(analytics_layers.resolve('judge.workers', Path('$FIXTURE'), environ={'CCT_SA_JUDGE_WORKERS': '9'}))
")
assert "an exported variable beats .env" "grep -q \"'value': '9'\" <<<\"\$EXPORTED\""
DEFAULTED=$(python3 -c "
import sys
sys.path.insert(0, '$REPO_DIR/scripts/lib')
import analytics_layers
from pathlib import Path
import os
os.remove('$FIXTURE/.env')
print(analytics_layers.resolve('judge.workers', Path('$FIXTURE'), environ={}))
")
assert "with no override the default is reported as such" "grep -q \"'layer': 'defaults.json'\" <<<\"\$DEFAULTED\""
rm -rf "$FIXTURE"

# ── the database key has two names (#362 review) ─────────────
# config.py reads CCT_SA_DB then the legacy CCT_SA_DSN *within each layer*, so
# a process-level legacy name beats a .env of the new one. Treating dsn as
# unpaired made explain report an empty default while the runtime used the
# exported value.
DB_ENV=$(CCT_SA_DB=sqlite:///synthetic.db bash "$CCT" config explain analytics.dsn 2>&1 || true)
assert "an exported CCT_SA_DB is the layer in effect" "grep -q 'set by the environment' <<<\"\$DB_ENV\""
assert "and the variable is named" "grep -q 'CCT_SA_DB' <<<\"\$DB_ENV\""
assert "a dsn value stays redacted even when overridden" "! grep -q 'synthetic.db' <<<\"\$DB_ENV\""
LEGACY_ENV=$(CCT_SA_DSN=sqlite:///legacy.db bash "$CCT" config explain analytics.dsn 2>&1 || true)
assert "the legacy CCT_SA_DSN is honoured too" "grep -q 'CCT_SA_DSN' <<<\"\$LEGACY_ENV\""

ALIAS_FIXTURE=$(mktemp -d)
mkdir -p "$ALIAS_FIXTURE/scripts/session_analytics/config_data"
for f in config.py constants.py; do
  ln -s "$REPO_DIR/scripts/session_analytics/$f" "$ALIAS_FIXTURE/scripts/session_analytics/$f"
done
ln -s "$REPO_DIR/scripts/session_analytics/config_data/defaults.json" \
      "$ALIAS_FIXTURE/scripts/session_analytics/config_data/defaults.json"
printf 'CCT_SA_DB=dotenv-new.db\n' > "$ALIAS_FIXTURE/.env"

# The resolver reads the real environment when none is passed, so each case is
# one variable in front of the command.
{
  echo "import sys"
  echo "sys.path.insert(0, '$REPO_DIR/scripts/lib')"
  echo "import analytics_layers"
  echo "from pathlib import Path"
  echo "print(analytics_layers.resolve('dsn', Path('$ALIAS_FIXTURE')))"
} > "$ALIAS_FIXTURE/resolve.py"

PROCESS_LEGACY=$(CCT_SA_DSN=process-legacy.db python3 "$ALIAS_FIXTURE/resolve.py")
DOTENV_ONLY=$(env -u CCT_SA_DB -u CCT_SA_DSN python3 "$ALIAS_FIXTURE/resolve.py")
BOTH_EXPORTED=$(CCT_SA_DB=new.db CCT_SA_DSN=legacy.db python3 "$ALIAS_FIXTURE/resolve.py")
assert "a process legacy name beats a .env of the new name" "grep -q 'process-legacy.db' <<<\"\$PROCESS_LEGACY\""
assert "with nothing exported the .env value wins" "grep -q 'dotenv-new.db' <<<\"\$DOTENV_ONLY\""
assert "the new name wins over the legacy one in the same layer" "grep -q \"'value': 'new.db'\" <<<\"\$BOTH_EXPORTED\""
assert "the alias order comes from config.py, not a list typed here" "grep -q 'env_db' '$REPO_DIR/scripts/lib/analytics_layers.py'"
rm -rf "$ALIAS_FIXTURE"

# One pairing rule for the CLI and the generated reference.
assert "the reference and the CLI share the pairing module" \
  "grep -q 'analytics_layers' '$REPO_DIR/scripts/lib/config_reference.py'"

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="
[[ $FAIL -gt 0 ]] && exit 1
exit 0
