#!/usr/bin/env bash
# capture-claude.sh — S4 capture of the installed Claude Code for #400
# (task B1's rest, plan amendment 4).
#
# Runs the installed `claude` in a throwaway home against a local stub
# endpoint (capture-stub.py beside this script) and records:
#   - what the binary sends for the FR-20 variables: the base URL, a bearer
#     or an x-api-key credential, the model;
#   - whether --session-id <uuid> names a new session, and the transcript
#     that proves it;
#   - the model the --output-format json result and the transcript report;
#   - whether --resume <id> keeps the id, what a --session-id already in use
#     does, which session a bare --continue takes, and that a --session-id
#     beside --resume or --continue is refused without --fork-session;
#   - the ANTHROPIC_* and CLAUDE_CODE_* names in the binary that an earlier
#     binary did not carry;
#   - which options take a value, required or optional, asked of the binary
#     itself, and how a cluster (-pr <id>) and a required value
#     (--append-system-prompt --resume <id>) are read.
# No real provider, no real credential: the only credential is a planted
# sentinel. The record names the CLI version it ran against, so a newer
# Claude Code is re-captured by running this script again.
#
# Usage: capture-claude.sh [record.md]   (default: claude-code-session-capture.md beside it)
# Needs: claude, python3, perl (each run's time limit), strings.
# The real binary is used: a shell-script wrapper on PATH (cmux ships one
# that adds its own --session-id and hooks) is skipped. CLAUDE_BIN names the
# binary outright; CAPTURE_BASELINE_BIN names the earlier binary to compare
# names with (default: the installed 2.1.329, the version the launch-first
# capture used, when it is still there).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECORD="${1:-$HERE/claude-code-session-capture.md}"
STUB="$HERE/capture-stub.py"
LIMIT="${CAPTURE_TIMEOUT_SEC:-90}"

real_claude() {  # the first claude on PATH that is not a script
  local dir f
  if [[ -n "${CLAUDE_BIN:-}" ]]; then printf '%s\n' "$CLAUDE_BIN"; return; fi
  local IFS=:
  for dir in $PATH; do
    f="$dir/claude"
    [[ -x "$f" && ! -d "$f" ]] || continue
    head -c 2 "$f" 2>/dev/null | grep -q '#!' && continue
    printf '%s\n' "$f"; return
  done
  return 1
}
CLAUDE="$(real_claude)" || { echo "no claude binary on PATH (a wrapper script does not count); set CLAUDE_BIN" >&2; exit 2; }
command -v python3 >/dev/null || { echo "python3 not found" >&2; exit 2; }
command -v perl >/dev/null || { echo "perl not found (it sets each run's time limit)" >&2; exit 2; }
command -v strings >/dev/null || { echo "strings not found" >&2; exit 2; }
CLAUDE_REAL="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$CLAUDE")"

W="$(mktemp -d "${TMPDIR:-/tmp}/cct-capture-claude.XXXXXX")"
case "$W" in */cct-capture-claude.*) ;; *) echo "unexpected work dir: $W" >&2; exit 2 ;; esac
STUB_PIDS=()
cleanup() {
  local pid
  for pid in ${STUB_PIDS[@]+"${STUB_PIDS[@]}"}; do kill "$pid" 2>/dev/null; done
  rm -rf -- "$W"
}
trap cleanup EXIT

H="$W/home"
mkdir -p "$H/.claude" "$W/proj" "$W/runs" "$W/bin"
ln -s "$CLAUDE_REAL" "$W/bin/claude"
RUN_PATH="$W/bin:/usr/bin:/bin"
VERSION="$(env -i HOME="$H" PATH="$RUN_PATH" claude --version 2>/dev/null | head -1)"
[[ -n "$VERSION" ]] || { echo "claude --version printed nothing" >&2; exit 2; }

python3 "$STUB" "$W/A.jsonl" "$W/A.port" &
STUB_PIDS+=("$!")
disown "$!" 2>/dev/null || true
for _ in $(seq 1 50); do [[ -s "$W/A.port" ]] && break; sleep 0.1; done
[[ -s "$W/A.port" ]] || { echo "the stub did not start" >&2; exit 2; }
: > "$W/A.jsonl"
PORT="$(cat "$W/A.port")"

lines() { wc -l < "$W/A.jsonl" | tr -d ' '; }

# run <label> <env assignments...> -- <claude args...>
run() {
  local label="$1"; shift
  local envs=()
  while [[ $# -gt 0 && "$1" != "--" ]]; do envs+=("$1"); shift; done
  shift
  local a0; a0=$(lines)
  ( cd "$W/proj" && env -i HOME="$H" PATH="$RUN_PATH" \
      ANTHROPIC_BASE_URL="http://127.0.0.1:$PORT" ANTHROPIC_MODEL=capture-main \
      DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
      "${envs[@]+"${envs[@]}"}" \
      perl -e 'alarm shift; exec @ARGV' "$LIMIT" claude "$@" \
      < /dev/null > "$W/runs/$label.out" 2> "$W/runs/$label.err" )
  echo "$?" > "$W/runs/$label.rc"
  tail -n +"$((a0 + 1))" "$W/A.jsonl" > "$W/runs/$label.A"
}

# summary <label>: one block of facts about a run, as markdown
summary() {
  python3 - "$W/runs" "$1" "$H" "$W" <<'PY'
import json, os, sys
d, label, home, work = sys.argv[1:5]
scrub = lambda t: t.replace(home, "~").replace(work, "<work>")
read = lambda ext: scrub(open(os.path.join(d, f"{label}.{ext}"), encoding="utf-8", errors="replace").read())
rc = read("rc").strip()
out = read("out").strip()
print(f"- exit {rc}")
try:
    res = json.loads(out) if out else None
except ValueError:
    res = None
if isinstance(res, dict):
    print(f"- result: {res.get('result')!r}; is_error: {res.get('is_error')}; session_id: `{res.get('session_id')}`")
    models = sorted((res.get("modelUsage") or {}).keys())
    print(f"- models in the JSON result (`modelUsage`): {', '.join(models) or 'none'}")
elif out:
    print(f"- stdout: {out[:300]!r}")
for r in (json.loads(l) for l in read("A").splitlines() if l.strip()):
    print(f"- stub: {r['method']} {r['path']} | protocol {r['protocol']} | model {r['model']!r} | auth {r['auth'] or 'none'}")
err = [l.strip() for l in read("err").splitlines() if l.strip()]
if err:
    print("- stderr: " + " / ".join(err[:3])[:400])
PY
}

# transcripts: every session file the runs left, with the models it records
transcripts() {
  python3 - "$H/.claude/projects" "$H" "$W" <<'PY'
import json, os, re, sys
root, home, work = sys.argv[1:4]
# Claude Code names a project's directory after its path, every other
# character a dash: abbreviated, so a re-run writes the same record.
slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(os.path.join(work, "proj")))
scrub = lambda t: t.replace(home, "~").replace(work, "<work>").replace(slug, "<project>")
found = []
for dirpath, _, files in os.walk(root):
    for f in sorted(files):
        if f.endswith(".jsonl"):
            found.append(os.path.join(dirpath, f))
if not found:
    print("- no transcript under ~/.claude/projects")
for p in found:
    models, sessions, n = set(), set(), 0
    for line in open(p, encoding="utf-8", errors="replace"):
        n += 1
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("sessionId"):
            sessions.add(e["sessionId"])
        m = (e.get("message") or {}).get("model") if isinstance(e.get("message"), dict) else None
        if m:
            models.add(m)
    print(f"- `{scrub(p)}`: {n} lines; sessionId {', '.join(f'`{s}`' for s in sorted(sessions)) or 'none'}; "
          f"assistant model {', '.join(sorted(models)) or 'none'}")
PY
}

# ── the runs ─────────────────────────────────────────────────────────
BEARER=ANTHROPIC_AUTH_TOKEN=capture-planted-credential
APIKEY=ANTHROPIC_API_KEY=capture-planted-credential
uuid() { python3 -c 'import uuid; print(uuid.uuid4())'; }
S1="$(uuid)"; S2="$(uuid)"; S3="$(uuid)"
ASK=(-p "Reply with the single word OK." --output-format json --max-turns 1)

run new-bearer "$BEARER" -- "${ASK[@]}" --session-id "$S1"
run new-apikey "$APIKEY" -- "${ASK[@]}" --session-id "$S2"
run resume "$BEARER" -- "${ASK[@]}" --resume "$S1"
run reused-id "$BEARER" -- "${ASK[@]}" --session-id "$S1"
run continue "$BEARER" -- "${ASK[@]}" --continue
run fork "$BEARER" -- "${ASK[@]}" --resume "$S1" --fork-session --session-id "$S3"
# S4's safety for a new session rests on these two: an id given beside
# --resume or --continue, without --fork-session, is refused, so the id a
# --llm launch generates can never name a session that is resumed.
S4="$(uuid)"; S5="$(uuid)"
run resume-with-id "$BEARER" -- "${ASK[@]}" --resume "$S1" --session-id "$S4"
run continue-with-id "$BEARER" -- "${ASK[@]}" --continue --session-id "$S5"
# The arguments as Claude Code's option parser reads them, which the
# launcher reads the same way: a letter that takes a value takes the next
# argument (-pr <S1> is -p -r <S1>) or the rest of its cluster (-pr<S1>);
# an option that requires a value takes the next argument whatever it is,
# so --append-system-prompt --resume <S1> makes <S1> a prompt.
run cluster-next "$BEARER" -- "${ASK[@]}" -pr "$S1"
run cluster-attached "$BEARER" -- "${ASK[@]}" "-pr$S1"
run value-swallows "$BEARER" -- -p --output-format json --max-turns 1 --append-system-prompt --resume "$S1"
# The new session it starts, named <S6> in the record, as the others are.
S6="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("session_id") or "")' "$W/runs/value-swallows.out" 2>/dev/null)"
[[ -n "$S6" ]] || S6="no-session-id-in-the-run-$$"   # matches nothing in the record

# ── the options that take a value ────────────────────────────────────
# Every option name the binary holds, asked of the binary itself, in the
# throwaway home and with the runs' own settings: the stub for an endpoint,
# the planted credential, no autoupdater and no nonessential traffic. A
# probe of an option the parser reads ends in a parse error, an unknown
# option last, so commander stops before any action:
#   P1 <opt>=v --zu1       the error names --zu1, or reports the value v:
#                          <opt> takes a value; names <opt>=v: it takes none
#   P2 <opt> --zu1 --zu2   the error names <opt>: unknown; --zu1: no value, or
#                          an optional one; --zu2, or --zu1 read as the
#                          value: a required one
#   P3 -L=v --zu1          (a letter that P2 left open) the error names
#                          --zu1: an optional value; -=: none
# An entry mode the binary takes before its parser (it runs instead of a
# session) gives no parse error: its P2 runs it, under the same settings and
# the time limit, and the record lists it as such.
probe() {  # <args...>: the binary's first lines for them
  ( cd "$W/proj" && env -i HOME="$H" PATH="$RUN_PATH" TERM=dumb \
      ANTHROPIC_BASE_URL="http://127.0.0.1:$PORT" ANTHROPIC_AUTH_TOKEN=capture-planted-credential \
      DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
      perl -e 'alarm shift; exec @ARGV' 20 claude "$@" < /dev/null 2>&1 | head -3 )
}
named() { [[ "$1" == *"unknown option '$2"* ]]; }   # <output> <arg>: the parse error names it
took() { named "$1" --zu2 || { [[ "$1" == *--zu1* ]] && ! named "$1" --zu1; }; }   # <P2 output>: --zu1 was read as the value
arity() {  # <option> -> required | optional | none | unknown | early | unresolved
  local o="$1" p
  if [[ "$o" == --* ]]; then
    p=$(probe "$o=v" --zu1)
    if named "$p" "$o=v"; then
      p=$(probe "$o" --zu1 --zu2)
      if named "$p" "$o'"; then echo unknown; elif named "$p" --zu1; then echo none; else echo early; fi
      return
    fi
    p=$(probe "$o" --zu1 --zu2)
    # Only a parse error naming --zu1 shows that the next argument was left
    # alone; anything else (a probe that timed out, say) is for a person.
    if took "$p"; then echo required; elif named "$p" --zu1; then echo optional; else echo unresolved; fi
    return
  fi
  p=$(probe "$o" --zu1 --zu2)
  if named "$p" "$o'"; then echo unknown; return; fi
  if took "$p"; then echo required; return; fi
  if ! named "$p" --zu1; then echo unresolved; return; fi
  p=$(probe "$o=v" --zu1)
  if named "$p" --zu1; then echo optional
  elif [[ "$p" == *"unknown option '-"* ]]; then echo none
  else echo unresolved; fi
}
# The names: every quoted option definition in the binary, the main
# command's and its subcommands' alike (a subcommand's is unknown to the main
# command), and every letter. --help, --version, -h and -v print and exit.
{ LC_ALL=C grep -a -o -E '"(-[a-zA-Z], )?--[a-z][a-zA-Z0-9-]*(, --[a-z][a-zA-Z0-9-]*)?( (<[^">]*>|\[[^"\]]*\]))?"' "$CLAUDE_REAL" 2>/dev/null \
    | grep -o -E -- '--[a-zA-Z][a-zA-Z0-9-]*' | grep -v -x -E -- '--help|--version' | sort -u
  for l in a b c d e f g i j k l m n o p q r s t u w x y z A B C D E F G H I J K L M N O P Q R S T U V W X Y Z; do printf -- '-%s\n' "$l"; done
} > "$W/optnames"
while IFS= read -r o; do printf '%s\t%s\n' "$o" "$(arity "$o")"; done < "$W/optnames" > "$W/arity"
opts() {  # the names of one kind, each in backticks, or "none"
  local o
  o=$(awk -F'\t' -v k="$1" '$2 == k { print $1 }' "$W/arity" | sort | paste -sd' ' - | sed 's/\([^ ]*\)/`\1`/g')
  printf '%s\n' "${o:-none}"
}
count() { awk -F'\t' -v k="$1" '$2 == k' "$W/arity" | wc -l | tr -d ' '; }

# ── the variable names ───────────────────────────────────────────────
BASELINE="${CAPTURE_BASELINE_BIN:-$HOME/.local/share/claude/versions/2.1.329}"
names() { strings "$1" 2>/dev/null | grep -oE '\b(ANTHROPIC|CLAUDE_CODE)_[A-Z0-9_]+\b' | sort -u; }
names "$CLAUDE_REAL" > "$W/names.now"
if [[ -f "$BASELINE" ]]; then
  BASE_VERSION="$(basename "$BASELINE")"
  names "$BASELINE" > "$W/names.base"
  comm -13 "$W/names.base" "$W/names.now" > "$W/names.added"
  comm -23 "$W/names.base" "$W/names.now" > "$W/names.removed"
fi

# ── the record ───────────────────────────────────────────────────────
{
  echo "# Capture — Claude Code sessions and the FR-20 variables (#400 S4)"
  echo
  echo "Recorded $(date -u +%Y-%m-%d) by \`specs/llm-catalog/verification/capture-claude.sh\` with \`$VERSION\`,"
  echo "the real binary (\`claude\` on \`PATH\`, a wrapper script skipped), in a throwaway home under"
  echo "\`env -i\`, against one local stub (\`capture-stub.py\`). The only credential is the planted"
  echo "sentinel \`capture-planted-credential\`; no request left the machine for a model. Each run is"
  echo "headless: \`-p \"Reply with the single word OK.\" --output-format json --max-turns 1\` and the flags named. Session ids are generated per run:"
  echo "\`<S1>\` and \`<S2>\` below."
  echo
  echo "## 1. A new session named by \`--session-id\`, through a bearer credential"
  echo; summary new-bearer | sed "s/$S1/<S1>/g; s/$S2/<S2>/g"; echo
  echo "## 2. A new session through an \`x-api-key\` credential"
  echo; summary new-apikey | sed "s/$S1/<S1>/g; s/$S2/<S2>/g"; echo
  echo "## 3. \`--resume <S1>\`"
  echo; summary resume | sed "s/$S1/<S1>/g; s/$S2/<S2>/g"; echo
  echo "## 4. \`--session-id <S1>\` again, an id already in use"
  echo; summary reused-id | sed "s/$S1/<S1>/g; s/$S2/<S2>/g"; echo
  echo "## 5. A bare \`--continue\`"
  echo; summary continue | sed "s/$S1/<S1>/g; s/$S2/<S2>/g"; echo
  echo "## 6. \`--resume <S1> --fork-session --session-id <S3>\`"
  echo; summary fork | sed "s/$S1/<S1>/g; s/$S2/<S2>/g; s/$S3/<S3>/g"; echo
  echo "## 7. \`--resume <S1> --session-id <S4>\`, without \`--fork-session\`"
  echo; summary resume-with-id | sed "s/$S1/<S1>/g; s/$S4/<S4>/g"; echo
  echo "## 8. \`--continue --session-id <S5>\`, without \`--fork-session\`"
  echo; summary continue-with-id | sed "s/$S1/<S1>/g; s/$S5/<S5>/g"; echo
  echo "## 9. The transcripts the runs left"
  echo; transcripts | sed "s/$S1/<S1>/g; s/$S2/<S2>/g; s/$S3/<S3>/g; s/$S4/<S4>/g; s/$S5/<S5>/g; s/$S6/<S6>/g"; echo
  echo "## 10. Variable names"
  echo
  if [[ -n "${BASE_VERSION:-}" ]]; then
    echo "\`strings\` over this binary and over the $BASE_VERSION binary, filtered to \`ANTHROPIC_*\` and"
    echo "\`CLAUDE_CODE_*\`: $(wc -l < "$W/names.now" | tr -d ' ') names now, $(wc -l < "$W/names.base" | tr -d ' ') in $BASE_VERSION."
    echo
    echo "Added since $BASE_VERSION: $(paste -sd' ' "$W/names.added" | sed 's/\([A-Z0-9_]*\)/`\1`/g; s/` `/`, `/g')"
    [[ -s "$W/names.added" ]] || echo "none"
    echo
    echo "Gone since $BASE_VERSION: $(paste -sd' ' "$W/names.removed" | sed 's/\([A-Z0-9_]*\)/`\1`/g; s/` `/`, `/g')"
    [[ -s "$W/names.removed" ]] || echo "none"
  else
    echo "No earlier binary to compare with (\`CAPTURE_BASELINE_BIN\`); $(wc -l < "$W/names.now" | tr -d ' ') names now."
  fi
  echo
  echo "## 11. The minimum version (FR-20)"
  echo
  echo "Not run, and not measured by this script: Claude Code's documentation, \"Tool search through"
  echo "an LLM gateway\" (https://code.claude.com/docs/en/mcp#tool-search-through-a-gateway), read"
  echo "2026-11-25, says Claude Code retries a request without tool search after a 400 or 422 from"
  echo "v2.1.305 on. That is the version the #399 work pinned, and the rule table's \`min_version\` for"
  echo "\`claude-code\`."
  echo
  echo "## 12. The options that take a value"
  echo
  echo "Every quoted option definition in the binary ($(wc -l < "$W/optnames" | tr -d ' ') names with the letters), asked of the binary"
  echo "itself in the throwaway home, with the runs' settings above. A probe of an option the parser"
  echo "reads ends in a parse error, an unknown option last, so its action never runs:"
  echo "\`<option>=v --zu1\` (does it take a value?), \`<option> --zu1 --zu2\` (is it known, and is a"
  echo "value required, so that the next argument is read as it whatever it is?), and for a letter"
  echo "\`-L=v --zu1\` (is the value optional?). An entry mode the binary takes before its parser gives no"
  echo "parse error, so its probe runs it, within the time limit; the list below names them. The"
  echo "launcher reads a launch's arguments with these two lists"
  echo "(\`LLM_CC_OPTS_REQUIRED\` and \`LLM_CC_OPTS_OPTIONAL\`); every other option takes none, and one"
  echo "Claude Code does not know is its own error, so it starts no session."
  echo
  echo "Require a value ($(count required)): $(opts required)"
  echo
  echo "Take an optional value ($(count optional)): $(opts optional)"
  echo
  echo "Take none: $(count none). Unknown to the main command (a subcommand's, or not an option): $(count unknown)."
  echo
  echo "Handled before the option parser, so that the probe ran them instead of failing to parse ($(count early)): $(opts early)"
  echo
  echo "Unresolved, a probe without the parse error that would settle it ($(count unresolved)): $(opts unresolved)"
  echo
  echo "## 13. \`-pr <S1>\` and \`-pr<S1>\`"
  echo
  echo "A letter that takes a value takes the next argument, or the rest of its cluster: \`-pr <S1>\` is"
  echo "\`-p -r <S1>\`, and \`-pr<S1>\` is \`-p -r<S1>\`."
  echo; summary cluster-next | sed "s/$S1/<S1>/g"; echo
  summary cluster-attached | sed "s/$S1/<S1>/g"; echo
  echo "## 14. \`--append-system-prompt --resume <S1>\`"
  echo
  echo "An option that requires a value takes the next argument whatever it is: \`--resume\` is the"
  echo "system prompt here, and \`<S1>\` the prompt, so the session is a new one, \`<S6>\`."
  echo; summary value-swallows | sed "s/$S1/<S1>/g; s/$S6/<S6>/g"
} > "$RECORD"
echo "wrote $RECORD ($VERSION)"
