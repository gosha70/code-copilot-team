#!/usr/bin/env bash
# capture-pi.sh — S0 capture of the installed Pi CLI for #400 (FR-22, D11).
#
# Runs the installed `pi` headless in a throwaway home against two local
# stub endpoints (capture-stub.py beside this script) and records what
# reached which stub, where sessions were written and what Pi changed in
# its agent directory. No real provider, no real credential: the only
# credentials are planted sentinels, and every run sets PI_OFFLINE=1. The
# record names the CLI version it ran against, so a newer Pi is
# re-captured by running this script again.
#
# Usage: capture-pi.sh [record.md]   (default: pi-capture.md beside it)
# Needs: pi, python3, perl (for the per-run time limit).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECORD="${1:-$HERE/pi-capture.md}"
STUB="$HERE/capture-stub.py"
LIMIT="${CAPTURE_TIMEOUT_SEC:-90}"

command -v pi >/dev/null || { echo "pi not found on PATH" >&2; exit 2; }
command -v python3 >/dev/null || { echo "python3 not found" >&2; exit 2; }

W="$(mktemp -d "${TMPDIR:-/tmp}/cct-capture-pi.XXXXXX")"
case "$W" in */cct-capture-pi.*) ;; *) echo "unexpected work dir: $W" >&2; exit 2 ;; esac
STUB_PIDS=()
cleanup() {
  local pid
  for pid in "${STUB_PIDS[@]}"; do kill "$pid" 2>/dev/null; done
  rm -rf -- "$W"
}
trap cleanup EXIT

H="$W/home"
USER_AGENT="$H/.pi/agent"
mkdir -p "$USER_AGENT" "$W/proj" "$W/runs"
PI_DIR="$(dirname "$(command -v pi)")"
RUN_PATH="$PI_DIR:/usr/bin:/bin"
VERSION="$(env -i HOME="$H" PATH="$RUN_PATH" PI_OFFLINE=1 pi --version 2>/dev/null | tail -1)"
DOCS="$(cd "$PI_DIR" && cd "$(dirname "$(readlink pi)")" && while [[ ! -f package.json && "$PWD" != "/" ]]; do cd ..; done; pwd)/docs"

start_stub() {  # start_stub <name>: sets <name>_PORT
  local name="$1" i
  python3 "$STUB" "$W/$name.jsonl" "$W/$name.port" &
  STUB_PIDS+=("$!")
  disown "$!" 2>/dev/null || true
  for i in $(seq 1 50); do [[ -s "$W/$name.port" ]] && break; sleep 0.1; done
  : > "$W/$name.jsonl"
  printf -v "${name}_PORT" '%s' "$(cat "$W/$name.port")"
}
start_stub A
start_stub B

# The user's own Pi setup: a provider of theirs on stub B, chosen by default in settings.json.
cat > "$USER_AGENT/models.json" <<JSON
{"providers": {"user-local": {"baseUrl": "http://127.0.0.1:$B_PORT/v1", "api": "openai-completions",
  "apiKey": "\$USER_LOCAL_KEY", "models": [{"id": "user-model"}]}}}
JSON
cat > "$USER_AGENT/settings.json" <<JSON
{"defaultProvider": "user-local", "defaultModel": "user-model"}
JSON
cp "$USER_AGENT/models.json" "$W/user-models.orig.json"

# A CCT provider entry, in the three protocols Pi documents.
cct_providers() {  # cct_providers <port>
  cat <<JSON
"cct-chat": {"baseUrl": "http://127.0.0.1:$1/v1", "api": "openai-completions", "apiKey": "\$CCT_CAPTURE_KEY", "models": [{"id": "capture-model"}]},
"cct-responses": {"baseUrl": "http://127.0.0.1:$1/v1", "api": "openai-responses", "apiKey": "\$CCT_CAPTURE_KEY", "models": [{"id": "capture-model"}]},
"cct-messages": {"baseUrl": "http://127.0.0.1:$1", "api": "anthropic-messages", "apiKey": "\$CCT_CAPTURE_KEY", "models": [{"id": "capture-model"}]},
"cct-nokey": {"baseUrl": "http://127.0.0.1:$1/v1", "api": "openai-completions", "models": [{"id": "capture-model"}]}
JSON
}

lines() { wc -l < "$W/$1.jsonl" | tr -d ' '; }
digest() { python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest()[:16])' "$1"; }

# run <label> <env assignments...> -- <pi args...>
run() {
  local label="$1"; shift
  local envs=()
  while [[ $# -gt 0 && "$1" != "--" ]]; do envs+=("$1"); shift; done
  shift
  local a0 b0; a0=$(lines A); b0=$(lines B)
  ( cd "$W/proj" && env -i HOME="$H" PATH="$RUN_PATH" PI_OFFLINE=1 USER_LOCAL_KEY=capture-planted-credential \
      "${envs[@]+"${envs[@]}"}" perl -e 'alarm shift; exec @ARGV' "$LIMIT" pi -p --mode json "$@" \
      < /dev/null > "$W/runs/$label.out" 2> "$W/runs/$label.err" )
  echo "$?" > "$W/runs/$label.rc"
  tail -n +"$((a0 + 1))" "$W/A.jsonl" > "$W/runs/$label.A"
  tail -n +"$((b0 + 1))" "$W/B.jsonl" > "$W/runs/$label.B"
}

summary() {  # summary <label>
  python3 - "$W/runs" "$1" "$(dirname "$DOCS")" "$H" "$W" <<'PY'
import json, os, sys
d, label, package, home, work = sys.argv[1:6]
def scrub(text):  # no local path in the record: the package, the home and the work dir abbreviated
    return text.replace(package, "<pi package>").replace(home, "~").replace(work, "<work>")
read = lambda ext: scrub(open(os.path.join(d, f"{label}.{ext}"), encoding="utf-8", errors="replace").read())
rc = read("rc").strip()
session, models, text, errors = None, set(), "", []
for line in read("out").splitlines():
    try:
        e = json.loads(line)
    except ValueError:
        continue
    if e.get("type") == "session":
        session = e.get("id")
    m = e.get("message") or {}
    if m.get("role") == "assistant" and m.get("model"):
        models.add((m.get("provider"), m.get("model"), m.get("api")))
    if e.get("type") == "message_end" and m.get("role") == "assistant":
        for part in m.get("content") or []:
            if part.get("type") == "text":
                text = part.get("text", "")
        if m.get("errorMessage"):
            errors.append(m["errorMessage"][:200])
print(f"- exit {rc}" + (f"; session `{session}`" if session else ""))
for prov, model, api in sorted(models, key=str):
    print(f"- assistant message: provider `{prov}`, model `{model}`, api `{api}`")
if text:
    print(f"- reply: {text!r}")
for err in errors:
    print(f"- error in the message: {err}")
for stub in ("A", "B"):
    reqs = [json.loads(l) for l in read(stub).splitlines() if l.strip()]
    if not reqs:
        print(f"- stub {stub}: no request")
    for r in reqs:
        print(f"- stub {stub}: {r['method']} {r['path']} | protocol {r['protocol']} | model {r['model']!r} | auth {r['auth'] or 'none'}")
err = [l.strip() for l in read("err").splitlines() if l.strip()]
if err:
    print("- stderr: " + " / ".join(err[:3])[:300])
PY
}

session_files() {  # session_files <dir>: the session files under it, home and work dir abbreviated
  local found
  found="$(find "$1" -name '*.jsonl' 2>/dev/null | sed -e "s#^$H#~#" -e "s#^$W#<work>#" -e 's#/--[^/]*--/#/<cwd>/#' | sort)"
  echo "${found:-(none)}"
}

KEY=CCT_CAPTURE_KEY=capture-planted-credential

# P1: the protocols, with $VAR interpolated from the child environment only.
mkdir -p "$W/agent-proto"
printf '{"providers": {%s}}\n' "$(cct_providers "$A_PORT")" > "$W/agent-proto/models.json"
for p in chat responses messages; do
  run "p1$p" "$KEY" "PI_CODING_AGENT_DIR=$W/agent-proto" -- --no-session --provider "cct-$p" --model capture-model "say ok"
done

# P2: an unknown provider.
run p2 "$KEY" "PI_CODING_AGENT_DIR=$W/agent-proto" -- --no-session --provider no-such-provider --model capture-model "say ok"

# P3: a new session with an id the launcher chose.
SID="0c0a1e5e-0000-4000-8000-000000000001"
run p3 "$KEY" "PI_CODING_AGENT_DIR=$W/agent-proto" -- --session-id "$SID" --provider cct-chat --model capture-model "say ok"
P3_FILES="$(session_files "$W/agent-proto")"

# P4: a launch-scoped overlay that links the user's files (FR-22 option a).
OV="$W/overlay"
mkdir -p "$OV" "$USER_AGENT/sessions"
python3 - "$USER_AGENT/models.json" "$OV/models.json" "$A_PORT" <<'PY'
import json, sys
src, dst, port = sys.argv[1], sys.argv[2], sys.argv[3]
data = json.load(open(src))
data["providers"]["cct-capture"] = {"baseUrl": f"http://127.0.0.1:{port}/v1", "api": "openai-completions",
                                    "apiKey": "$CCT_CAPTURE_KEY", "models": [{"id": "capture-model"}]}
json.dump(data, open(dst, "w"))
PY
ln -s "$USER_AGENT/settings.json" "$OV/settings.json"
ln -s "$USER_AGENT/sessions" "$OV/sessions"
[[ -f "$USER_AGENT/auth.json" ]] || echo '{}' > "$USER_AGENT/auth.json"
ln -s "$USER_AGENT/auth.json" "$OV/auth.json"
OV_BEFORE="$(cd "$OV" && ls -A | sort | tr '\n' ' ' | sed 's/ $//')"
SID4="0c0a1e5e-0000-4000-8000-000000000004"
run p4a "$KEY" "PI_CODING_AGENT_DIR=$OV" -- --session-id "$SID4" --provider cct-capture --model capture-model "say ok"
run p4b "$KEY" "PI_CODING_AGENT_DIR=$OV" -- --no-session "say ok"
OV_AFTER="$(cd "$OV" && ls -A | sort | tr '\n' ' ' | sed 's/ $//')"
OV_LINKS="$(for e in settings.json auth.json sessions; do
  if [[ -L "$OV/$e" ]]; then echo "\`$e\` still a link"; else echo "\`$e\` REPLACED by a regular entry"; fi; done | paste -sd ';' - | sed 's/;/; /g')"
P4_FILES="$(session_files "$USER_AGENT")"
run p4c "$KEY" -- --session-id "$SID4" "again"
run p4cflags "$KEY" -- --session-id "$SID4" --provider user-local --model user-model "again"
OV2="$W/overlay2"
mkdir -p "$OV2" "$W/session-store"
cp "$OV/models.json" "$OV2/models.json"
run p4d "$KEY" "PI_CODING_AGENT_DIR=$OV2" "PI_CODING_AGENT_SESSION_DIR=$W/session-store" -- --provider cct-capture --model capture-model "say ok"
P4D_FILES="$(session_files "$W/session-store")"
P4D_OV2="$(cd "$OV2" && ls -A | sort | tr '\n' ' ' | sed 's/ $//')"
USER_MODELS_AFTER_OVERLAY="$(digest "$USER_AGENT/models.json")"

# P5: an owned merge into the user's models.json (FR-22 option b).
python3 - "$USER_AGENT/models.json" "$A_PORT" <<'PY'
import json, sys
path, port = sys.argv[1], sys.argv[2]
data = json.load(open(path))
data["providers"]["cct-capture"] = {"baseUrl": f"http://127.0.0.1:{port}/v1", "api": "openai-completions",
                                    "apiKey": "$CCT_CAPTURE_KEY", "models": [{"id": "capture-model"}]}
json.dump(data, open(path, "w"), indent=2)
PY
MERGED_BEFORE="$(digest "$USER_AGENT/models.json")"
run p5cct "$KEY" -- --no-session --provider cct-capture --model capture-model "say ok"
run p5user "$KEY" -- --no-session "say ok"
MERGED_AFTER="$(digest "$USER_AGENT/models.json")"
cp "$W/user-models.orig.json" "$USER_AGENT/models.json"

# P6: ambient credentials beside a CCT entry.
run p6key "$KEY" OPENAI_API_KEY=capture-ambient-credential "PI_CODING_AGENT_DIR=$W/agent-proto" -- --no-session --provider cct-chat --model capture-model "say ok"
run p6nokey OPENAI_API_KEY=capture-ambient-credential "PI_CODING_AGENT_DIR=$W/agent-proto" -- --no-session --provider cct-nokey --model capture-model "say ok"
run p6msg ANTHROPIC_API_KEY=capture-ambient-credential "PI_CODING_AGENT_DIR=$W/agent-proto" -- --no-session --provider cct-messages --model capture-model "say ok"

CRED_VARS="$(grep -E '^\| [^|]+ \| `[A-Z0-9_]+`' "$DOCS/providers.md" 2>/dev/null | sed -E 's/^\| [^|]+ \| ([^|]+) \|.*/\1/' | grep -oE '`[A-Z0-9_]+`' | tr -d '`' | sort -u | tr '\n' ' ' | sed 's/ $//')"
DIST="$(dirname "$DOCS")/dist"
WRITES="$(for f in core/settings-manager.js core/auth-storage.js; do
  grep -nE 'writeFileSync\(|renameSync\(|lockSync\(' "$DIST/$f" 2>/dev/null | sed -E "s#^([0-9]+):[[:space:]]*#  - \`$f:\1\`: \`#; s#\$#\`#"; done)"

# ── the record ───────────────────────────────────────────────────────
{
  echo "# Capture — Pi CLI for #400 (S0)"
  echo
  echo "Generated by \`capture-pi.sh\` on $(date -u +%Y-%m-%d) (UTC) against **pi ${VERSION:-(version unknown)}** ($(uname -sr))."
  echo "Re-run the script to re-capture a newer CLI; this file is its output."
  echo
  echo "Every run: \`env -i\`, a throwaway \`HOME\`, \`PI_OFFLINE=1\`, \`pi -p --mode json\` with stdin from \`/dev/null\`, two local stub endpoints A and B. A CCT entry's \`apiKey\` is \`\$CCT_CAPTURE_KEY\`, set in the child environment only to the planted \`capture-planted-credential\`; ambient variables carry \`capture-ambient-credential\`."
  echo
  echo "The user's own setup in that home: \`~/.pi/agent/models.json\` has a provider \`user-local\` on stub B, and \`~/.pi/agent/settings.json\` makes it the default (\`defaultProvider: user-local\`, \`defaultModel: user-model\`)."
  echo
  echo "## 1. The three protocols, \`\$VAR\` from the child environment"
  echo
  for p in chat responses messages; do
    case "$p" in chat) api=openai-completions ;; responses) api=openai-responses ;; messages) api=anthropic-messages ;; esac
    echo "### \`api = \"$api\"\`"; echo; summary "p1$p"; echo
  done
  echo "## 2. An unknown \`--provider\`"
  echo
  summary p2
  echo
  echo "## 3. \`--session-id\` on a new session"
  echo
  echo "The launcher chose \`$SID\`."
  echo
  summary p3
  echo "- session files:"
  echo "$P3_FILES" | sed 's/^/  - /'
  echo
  echo "## 4. A launch-scoped overlay (FR-22, option a)"
  echo
  echo "\`PI_CODING_AGENT_DIR\` names a directory holding the user's providers plus \`cct-capture\` (stub A) in \`models.json\`, and links to the user's \`settings.json\`, \`auth.json\` and \`sessions/\`. Its entries before the runs: \`$OV_BEFORE\`."
  echo
  echo "### With \`--provider cct-capture\` and \`--session-id $SID4\`"
  echo
  summary p4a
  echo
  echo "### Without \`--provider\`: the user's default through the linked \`settings.json\`"
  echo
  summary p4b
  echo
  echo "- overlay entries after both runs: \`$OV_AFTER\`; $OV_LINKS. These headless runs write no setting and no login; a write from \`/settings\` or \`/login\` in an interactive overlay session is not exercised here"
  echo "- session files under the user's agent directory:"
  echo "$P4_FILES" | sed 's/^/  - /'
  echo "- the user's \`models.json\` after the overlay runs: $( [[ "$USER_MODELS_AFTER_OVERLAY" == "$(digest "$W/user-models.orig.json")" ]] && echo "unchanged" || echo "CHANGED")"
  echo
  echo "### Resuming that session natively: \`--session-id $SID4\`, no overlay"
  echo
  summary p4c
  echo
  echo "### The same, with \`--provider user-local --model user-model\`"
  echo
  summary p4cflags
  echo
  echo "### An overlay with \`PI_CODING_AGENT_SESSION_DIR\` instead of a linked \`sessions/\`"
  echo
  summary p4d
  echo "- session files under \`PI_CODING_AGENT_SESSION_DIR\`:"
  echo "$P4D_FILES" | sed 's/^/  - /'
  echo "- entries of that overlay after the run: \`$P4D_OV2\`"
  echo
  echo "## 5. An owned merge into the user's \`models.json\` (FR-22, option b)"
  echo
  echo "\`cct-capture\` (stub A) added to the user's \`models.json\` beside \`user-local\`."
  echo
  echo "### \`--provider cct-capture\`"
  echo
  summary p5cct
  echo
  echo "### No \`--provider\`: the user's default"
  echo
  summary p5user
  echo
  echo "- the merged \`models.json\` across both runs: $( [[ "$MERGED_BEFORE" == "$MERGED_AFTER" ]] && echo "unchanged by Pi" || echo "CHANGED by Pi")"
  echo
  echo "## 6. Ambient credentials (FR-30)"
  echo
  echo "### \`OPENAI_API_KEY\` beside a CCT entry with \`apiKey = \$CCT_CAPTURE_KEY\`"
  echo
  summary p6key
  echo
  echo "### \`OPENAI_API_KEY\` beside an \`openai-completions\` entry with no \`apiKey\`"
  echo
  summary p6nokey
  echo
  echo "### \`ANTHROPIC_API_KEY\` beside an \`anthropic-messages\` entry whose \`\$CCT_CAPTURE_KEY\` is unset"
  echo
  summary p6msg
  echo
  echo "## 7. Credential variables Pi's built-in providers read"
  echo
  echo "From the installed package's \`docs/providers.md\` (documented, not observed): ${CRED_VARS:-none found}"
  echo
  echo "## 8. How Pi writes \`settings.json\` and \`auth.json\`"
  echo
  echo "Read from the installed package's code, not observed: the write, rename and lock calls in its settings and auth storage."
  echo
  echo "${WRITES:-  - none found}"
  echo
  echo "A \`writeFileSync\` to a path that is a symlink writes the file the link names; a \`renameSync\` onto it would replace the link. \`proper-lockfile\` with \`realpath: false\` takes its lock beside the path as given, so a session run through an overlay locks beside the overlay's link, not beside the user's file."
} > "$RECORD"

echo "wrote $RECORD (pi ${VERSION:-version unknown})"
