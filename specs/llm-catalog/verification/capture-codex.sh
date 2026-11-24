#!/usr/bin/env bash
# capture-codex.sh — S0 capture of the installed Codex CLI for #400 (FR-21, D10).
#
# Runs the installed `codex` in a throwaway home against two local stub
# endpoints (capture-stub.py beside this script) and records what reached
# which stub. No real provider, no real credential: the only credentials
# are planted sentinels. The record names the CLI version it ran against,
# so a newer Codex is re-captured by running this script again.
#
# Usage: capture-codex.sh [record.md]   (default: codex-capture.md beside it)
# Needs: codex, python3, perl (for the per-run time limit).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECORD="${1:-$HERE/codex-capture.md}"
STUB="$HERE/capture-stub.py"
LIMIT="${CAPTURE_TIMEOUT_SEC:-90}"

command -v codex >/dev/null || { echo "codex not found on PATH" >&2; exit 2; }
command -v python3 >/dev/null || { echo "python3 not found" >&2; exit 2; }
command -v perl >/dev/null || { echo "perl not found (it sets each run's time limit)" >&2; exit 2; }

W="$(mktemp -d "${TMPDIR:-/tmp}/cct-capture-codex.XXXXXX")"
case "$W" in */cct-capture-codex.*) ;; *) echo "unexpected work dir: $W" >&2; exit 2 ;; esac
STUB_PIDS=()
cleanup() {
  local pid
  for pid in ${STUB_PIDS[@]+"${STUB_PIDS[@]}"}; do kill "$pid" 2>/dev/null; done
  rm -rf -- "$W"
}
trap cleanup EXIT

H="$W/home"
mkdir -p "$H/.codex" "$W/proj" "$W/runs"
# Only the PATH entry that holds codex and node, plus the system tools.
CODEX_DIR="$(dirname "$(command -v codex)")"
RUN_PATH="$CODEX_DIR:/usr/bin:/bin"
VERSION="$(env -i HOME="$H" CODEX_HOME="$H/.codex" PATH="$RUN_PATH" codex --version 2>/dev/null | tail -1)"

start_stub() {  # start_stub <name>: sets <name>_PORT
  local name="$1" i
  python3 "$STUB" "$W/$name.jsonl" "$W/$name.port" &
  STUB_PIDS+=("$!")
  disown "$!" 2>/dev/null || true
  for i in $(seq 1 50); do [[ -s "$W/$name.port" ]] && break; sleep 0.1; done
  [[ -s "$W/$name.port" ]] || { echo "stub $name did not start" >&2; exit 2; }
  : > "$W/$name.jsonl"
  printf -v "${name}_PORT" '%s' "$(cat "$W/$name.port")"
}
start_stub A
start_stub B

# overlay <port> <wire_api>: the -c arguments FR-21 names, for provider cct-capture
overlay() {
  OVERLAY=(-c model_provider=cct-capture
           -c 'model_providers.cct-capture.name="cct capture"'
           -c "model_providers.cct-capture.base_url=\"http://127.0.0.1:$1/v1\""
           -c 'model_providers.cct-capture.env_key="CCT_CAPTURE_KEY"'
           -c "model_providers.cct-capture.wire_api=\"$2\"")
}

lines() { wc -l < "$W/$1.jsonl" | tr -d ' '; }

# run <label> <env assignments...> -- <codex args...>
run() {
  local label="$1"; shift
  local envs=()
  while [[ $# -gt 0 && "$1" != "--" ]]; do envs+=("$1"); shift; done
  shift
  local a0 b0; a0=$(lines A); b0=$(lines B)
  ( cd "$W/proj" && env -i HOME="$H" CODEX_HOME="$H/.codex" PATH="$RUN_PATH" "${envs[@]+"${envs[@]}"}" \
      perl -e 'alarm shift; exec @ARGV' "$LIMIT" codex "$@" \
      < /dev/null > "$W/runs/$label.out" 2> "$W/runs/$label.err" )
  echo "$?" > "$W/runs/$label.rc"
  tail -n +"$((a0 + 1))" "$W/A.jsonl" > "$W/runs/$label.A"
  tail -n +"$((b0 + 1))" "$W/B.jsonl" > "$W/runs/$label.B"
}

# summary <label>: one block of facts about a run, as markdown
summary() {
  python3 - "$W/runs" "$1" "$H" "$W" "$CODEX_DIR" <<'PY'
import json, os, sys
d, label, home, work, bindir = sys.argv[1:6]
def scrub(text):  # no local path in the record: the home, the work dir and the CLI's directory abbreviated
    return text.replace(home, "~").replace(work, "<work>").replace(bindir, "<codex dir>")
read = lambda ext: scrub(open(os.path.join(d, f"{label}.{ext}"), encoding="utf-8", errors="replace").read())
rc = read("rc").strip()
def has_model_key(o):
    if isinstance(o, dict):
        return any(k == "model" or has_model_key(v) for k, v in o.items())
    if isinstance(o, list):
        return any(has_model_key(v) for v in o)
    return False

events, texts, thread, errors, models = [], [], None, [], []
for line in read("out").splitlines():
    try:
        e = json.loads(line)
    except ValueError:
        continue
    events.append(e.get("type"))
    if e.get("type") == "thread.started":
        thread = e.get("thread_id")
    item = e.get("item") or {}
    if item.get("type") == "agent_message":
        texts.append(item.get("text"))
    if item.get("type") == "error":
        errors.append(item.get("message", "")[:160])
    if has_model_key(e):
        models.append(e.get("type"))
print(f"- exit {rc}; events: {', '.join(t for t in events if t) or 'none'}")
if thread:
    print(f"- thread id: `{thread}`")
if texts:
    print(f"- agent message: {texts[-1]!r}")
for err in errors:
    print(f"- error item: {err}")
print(f"- events with a `model` field: {', '.join(models) if models else 'none'}")
for stub in ("A", "B"):
    reqs = [json.loads(l) for l in read(stub).splitlines() if l.strip()]
    if not reqs:
        print(f"- stub {stub}: no request")
    for r in reqs:
        print(f"- stub {stub}: {r['method']} {r['path']} | protocol {r['protocol']} | model {r['model']!r} | auth {r['auth'] or 'none'}")
err = [l.strip() for l in read("err").splitlines() if l.strip() and "Reading additional input" not in l]
if err and rc != "0" and not events:
    print("- error: " + " / ".join(err[:4])[:400])
elif err and rc != "0":
    print(f"- stderr, last line: {err[-1][:200]}")
PY
}

# ── the runs ─────────────────────────────────────────────────────────
KEY=CCT_CAPTURE_KEY=capture-planted-credential

overlay "$A_PORT" responses
run q1 "$KEY" -- exec --skip-git-repo-check --json -m capture-model "${OVERLAY[@]}" "say ok"
THREAD="$(python3 -c 'import json,sys
for l in open(sys.argv[1]):
    try: e=json.loads(l)
    except ValueError: continue
    if e.get("type")=="thread.started": print(e["thread_id"]); break' "$W/runs/q1.out")"

overlay "$A_PORT" chat
run q2chat "$KEY" -- exec --skip-git-repo-check --json -m capture-model "${OVERLAY[@]}" "say ok"
overlay "$A_PORT" bogus
run q2bogus "$KEY" -- exec --skip-git-repo-check --json -m capture-model "${OVERLAY[@]}" "say ok"

cat > "$H/.codex/capture.config.toml" <<TOML
model = "profile-model"
model_provider = "cct-capture"

[model_providers.cct-capture]
name = "cct capture (profile)"
base_url = "http://127.0.0.1:$A_PORT/v1"
env_key = "CCT_CAPTURE_KEY"
wire_api = "responses"
TOML
run q3profile "$KEY" -- exec --skip-git-repo-check --json -p capture "say ok"
run q3both "$KEY" -- exec --skip-git-repo-check --json -p capture -c 'model="cli-model"' "say ok"
overlay "$B_PORT" responses
run q3switch "$KEY" -- exec --skip-git-repo-check --json -p capture "${OVERLAY[@]}" "say ok"
rm -f -- "$H/.codex/capture.config.toml"

if [[ -n "$THREAD" ]]; then
  run q5bare "$KEY" -- exec resume --skip-git-repo-check --json "$THREAD" "again"
  overlay "$A_PORT" responses
  run q5same "$KEY" -- exec resume --skip-git-repo-check --json -m capture-model "${OVERLAY[@]}" "$THREAD" "again"
  overlay "$B_PORT" responses
  run q5other "$KEY" -- exec resume --skip-git-repo-check --json -m capture-model "${OVERLAY[@]}" "$THREAD" "again"
fi

AMBIENT=(OPENAI_API_KEY=capture-ambient-credential "OPENAI_BASE_URL=http://127.0.0.1:$B_PORT/v1")
overlay "$A_PORT" responses
run q7overlay "$KEY" "${AMBIENT[@]}" -- exec --skip-git-repo-check --json -m capture-model "${OVERLAY[@]}" "say ok"
run q7native "${AMBIENT[@]}" -- exec --skip-git-repo-check --json -m capture-model "say ok"

SESSION_FILE="$(find "$H/.codex/sessions" -name "*${THREAD:-none}*.jsonl" 2>/dev/null | head -1)"
SESSION_FACTS="$(python3 - "$SESSION_FILE" <<'PY'
import json, sys
path = sys.argv[1]
if not path:
    print("- no session file was found for the first run's thread id")
    sys.exit()
meta = ctx = None
for line in open(path, encoding="utf-8"):
    e = json.loads(line)
    p = e.get("payload") or {}
    if e.get("type") == "session_meta" and meta is None:
        meta = p
    if e.get("type") == "turn_context" and ctx is None:
        ctx = p
name = path.split("/sessions/", 1)[-1]
print(f"- file: `$CODEX_HOME/sessions/{name.rsplit('/', 1)[0]}/rollout-<time>-<thread id>.jsonl`")
if meta:
    print(f"- `session_meta`: id `{meta.get('id')}`, model_provider `{meta.get('model_provider')}`, cli_version `{meta.get('cli_version')}`")
if ctx:
    print(f"- `turn_context`: model `{ctx.get('model')}`")
PY
)"
HELP_SESSION="$(for sub in "" exec "exec resume" resume fork; do
  env -i HOME="$H" CODEX_HOME="$H/.codex" PATH="$RUN_PATH" codex $sub --help 2>&1 | grep -E -- '--session-id|--thread-id' ; done | sort -u)"

# ── the record ───────────────────────────────────────────────────────
{
  echo "# Capture — Codex CLI for #400 (S0)"
  echo
  echo "Generated by \`capture-codex.sh\` on $(date -u +%Y-%m-%d) (UTC) against **${VERSION:-codex (version unknown)}** ($(uname -sr))."
  echo "Re-run the script to re-capture a newer CLI; this file is its output."
  echo
  echo "Every run: \`env -i\`, a throwaway \`HOME\` and \`CODEX_HOME\`, \`codex exec --json\` with stdin from \`/dev/null\`, two local stub endpoints A and B. The credential named by \`env_key\` is the planted value \`capture-planted-credential\`; ambient variables carry \`capture-ambient-credential\`."
  echo
  echo "Two runs have no overlay: the bare resume in section 5 and the last run in section 7. They reach Codex's default provider at \`api.openai.com\` with no credential and are refused there (401); nothing else leaves the machine."
  echo
  echo "## 1. Nested \`-c model_providers.*\` overrides (D10)"
  echo
  echo "\`-c model_provider=cct-capture\` plus \`model_providers.cct-capture.{name,base_url,env_key,wire_api}\`, \`wire_api = \"responses\"\`, base URL stub A:"
  echo
  summary q1
  echo
  echo "## 2. \`wire_api\` values"
  echo
  echo "### \`wire_api = \"chat\"\`"
  echo
  summary q2chat
  echo
  echo "### \`wire_api = \"bogus\"\`"
  echo
  summary q2bogus
  echo
  echo "## 3. \`--profile\` layering"
  echo
  echo "\`\$CODEX_HOME/capture.config.toml\` sets \`model = \"profile-model\"\` and the cct-capture provider on stub A."
  echo
  echo "### \`-p capture\` alone"
  echo
  summary q3profile
  echo
  echo "### \`-p capture -c model=\"cli-model\"\`"
  echo
  summary q3both
  echo
  echo "### \`-p capture\` plus the overlay naming stub B"
  echo
  summary q3switch
  echo
  echo "## 4. The model in \`exec --json\` and in the session file"
  echo
  echo "Section 1 lists the \`exec --json\` events that carry a \`model\` field. The session file the first run wrote:"
  echo
  echo "$SESSION_FACTS"
  echo
  echo "## 5. \`codex exec resume <thread id>\`"
  echo
  if [[ -n "$THREAD" ]]; then
    echo "### Without the overlay"
    echo
    summary q5bare
    echo
    echo "### With the same overlay (stub A)"
    echo
    summary q5same
    echo
    echo "### With an overlay naming stub B"
    echo
    summary q5other
  else
    echo "Not run: the first run reported no thread id."
  fi
  echo
  echo "## 6. Choosing a new session's id"
  echo
  if [[ -n "$HELP_SESSION" ]]; then
    echo "Options found in \`--help\`:"; echo; echo '```'; echo "$HELP_SESSION"; echo '```'
  else
    echo "No \`--session-id\` or \`--thread-id\` option in the help of \`codex\`, \`exec\`, \`exec resume\`, \`resume\` or \`fork\`. Codex generates the id; \`exec --json\` reports it as \`thread.started.thread_id\`, and it names the session file."
  fi
  echo
  echo "## 7. Ambient \`OPENAI_API_KEY\` and \`OPENAI_BASE_URL\` (FR-30)"
  echo
  echo "\`OPENAI_API_KEY=capture-ambient-credential\`, \`OPENAI_BASE_URL\` naming stub B."
  echo
  echo "### With the overlay naming stub A"
  echo
  summary q7overlay
  echo
  echo "### Without the overlay"
  echo
  summary q7native
} > "$RECORD"

echo "wrote $RECORD (${VERSION:-codex version unknown})"
