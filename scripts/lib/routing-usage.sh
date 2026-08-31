#!/usr/bin/env bash
# routing-usage.sh — routed usage/cost evidence (#273, increment G of
# #109; acceptance criterion C30).
#
# THE GOVERNING RULE: unknown stays unknown. No token count is
# invented, and no USD is claimed because a cost cap or an estimate
# exists. A quantity the backend cannot expose is recorded as null with
# an explicit status/basis — never omitted, never zero, never inferred.
#
# Four anti-forgery rules, each from a reproduced defect in the first
# implementation of this file. They are the whole substance here:
#
#   1. PROVENANCE. Usage is read ONLY from a backend's authoritative
#      result event, parsed as JSON. The first version byte-grepped the
#      capture, so a `type=assistant` line claiming 777 tokens and
#      $9.99 was recorded as fact. Any event may *mention* these field
#      names; only one event *reports* them.
#   2. COMPLETE BUCKETS. A cost is computed only when every token
#      bucket carrying a NON-ZERO rate is present. The first version
#      zero-filled absent buckets, so a transcript with only
#      output_tokens priced as if input were 0 — understating cost
#      while looking authoritative.
#   3. VALIDATED PRICING. Rates resolve through the existing config
#      loader, with its documented layering and validation. The first
#      version picked the first file containing `pricing.models` and
#      read it with raw jq, so a partial EUR override replaced the
#      defaults, missing rates became 0, and the result was labelled
#      USD/computed.
#   4. VERIFIED IDENTITY. Pricing uses the EFFECTIVE (served) model
#      only. The first version fell back to the requested model, which
#      contradicts #109's C13 finding that requested never proves
#      served.
#
# What this deliberately does NOT read: the driver's cost CAP and
# unmetered-estimate accounting. Those are budget control, not
# observation; the #109 acceptance audit refused to let them satisfy
# C30 by implication. An OBSERVED aggregate the driver publishes is a
# different thing and is consumed via the `driver-aggregate` backend.

# Authoritative result event per backend — fixed by observation from
# the shipped parsers, not by guesswork.
#   claude-code  .type == "result"          usage + total_cost_usd
#   codex        .type == "turn.completed"  usage
#   pi           .type == "usage"           the event itself
#   driver-aggregate  .type == "cct.routed_usage"
#       the auto-build driver's own published per-invocation record.
#       The supervisor's main path wraps the driver, whose stdout is a
#       console log and NOT a backend result stream, so usage there is
#       joined from this artifact rather than scraped from log text.
RU_EVENT_CLAUDE="result"
RU_EVENT_CODEX="turn.completed"
RU_EVENT_PI="usage"
RU_EVENT_DRIVER="cct.routed_usage"

# Token field aliases WITHIN the authoritative event.
RU_KEYS_INPUT="input_tokens prompt_tokens tokens_input"
RU_KEYS_OUTPUT="output_tokens completion_tokens tokens_output"
RU_KEYS_CACHE_READ="cache_read_input_tokens cache_read_tokens cached_input_tokens"
RU_KEYS_CACHE_WRITE="cache_creation_input_tokens cache_creation_tokens cache_write_input_tokens"
RU_KEY_COST="total_cost_usd"

RU_RATE_UNIT=1000000   # rates are per 1,000,000 tokens

_ru_repo_root() { (cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd); }

# ru_event_type <backend> -> the authoritative event type, or empty for
# an unknown backend (which yields no usage at all — never a guess).
ru_event_type() {
    case "$1" in
        claude-code|claude)  printf '%s' "$RU_EVENT_CLAUDE" ;;
        codex)               printf '%s' "$RU_EVENT_CODEX" ;;
        pi)                  printf '%s' "$RU_EVENT_PI" ;;
        driver-aggregate)    printf '%s' "$RU_EVENT_DRIVER" ;;
        *)                   printf '' ;;
    esac
}

# ru_events <file> — every event in the capture, as a JSON array.
#
# ONE normalizer for the reader and the driver's publisher, using the
# stream shape the shipped backend parsers already established: a
# whole-document object (pretty-printed included), a whole-document
# array, or JSONL. The first version split on newlines only, so a
# pretty-printed Claude result — the ordinary shape — parsed as nothing
# and every value silently became `unavailable`.
ru_events() {
    local file="$1" out
    [[ -r "$file" ]] || { printf '[]'; return 0; }
    # 1) whole document: a pretty-printed object, an array, or clean
    #    JSONL all slurp cleanly.
    if out=$(jq -s -c 'map(if type == "array" then .[] else . end)
                       | map(select(type == "object"))' "$file" 2>/dev/null); then
        printf '%s' "$out"; return 0
    fi
    # 2) LINE-WISE, SKIPPING unparseable lines. Direct claude and pi
    #    launches merge stderr into the same capture, so one diagnostic
    #    line would otherwise make jq -s reject the WHOLE stream and
    #    erase valid usage. The shipped parsers skip bad lines; so does
    #    this, or the reader would disagree with them.
    jq -R -s -c 'split("\n") | map(select(length > 0) | try fromjson catch empty)
                 | map(select(type == "object"))' "$file" 2>/dev/null \
        || printf '[]'
}

# ru_authoritative_events <file> <backend> — the events that count.
#
# The cardinality differs BY BACKEND, and conflating them is a defect:
#   driver-aggregate  ALL records. The driver publishes one per
#                     invocation, so the run total is their sum.
#   direct backends   the LAST authoritative event only, matching the
#                     shipped parsers. Summing two pi `usage` events
#                     would report 30/5 where the pi parser keeps 20/3.
#
# For claude-code there is one constrained fallback, the same one the
# shipped parser allows: a document consisting of exactly ONE object
# with no `type` key is the legacy result shape and is accepted.
# Anything richer must be typed, so the fallback cannot readmit the
# forged-event hole.
ru_authoritative_events() {
    local file="$1" backend="$2" want evs
    want=$(ru_event_type "$backend")
    [[ -n "$want" ]] || { printf '[]'; return 0; }
    evs=$(ru_events "$file")
    if [[ "$backend" == "driver-aggregate" ]]; then
        jq -c --arg want "$want" 'map(select(.type == $want))' <<< "$evs" 2>/dev/null || printf '[]'
        return 0
    fi
    jq -c --arg want "$want" --arg backend "$backend" '
        (map(select(.type == $want)) | last) as $typed
        | if $typed != null then [$typed]
          elif ($backend == "claude-code" or $backend == "claude")
               and (length == 1) and (.[0] | has("type") | not)
            then [.[0]]                       # legacy untyped result
          else [] end' <<< "$evs" 2>/dev/null || printf '[]'
}

# ru_authoritative_event <file> <backend> — the LAST authoritative
# event (single-session backends), or empty.
ru_authoritative_event() {
    local evs
    evs=$(ru_authoritative_events "$1" "$2")
    jq -c 'last // empty' <<< "$evs" 2>/dev/null || true
}

# ru_extract_tokens <file> <backend> — the tokens block.
#
# Single-session backends use their last authoritative event. The
# driver aggregate is SUMMED across every published record, and the sum
# is CONSERVATIVE: a bucket is known only if every invocation reported
# it. If any invocation is silent about a bucket, the run total for
# that bucket is unknown (null) rather than a partial sum presented as
# a whole. The publisher emits a record for every invocation including
# explicitly-absent accounting, so a missing invocation cannot masquerade
# as a complete total.
ru_extract_tokens() {
    local file="$1" backend="${2:--}" evs
    evs=$(ru_authoritative_events "$file" "$backend")
    local none='{"input":null,"output":null,"cache_read":null,"cache_write":null,"status":"unavailable"}'
    [[ "$(jq -r 'length' <<< "$evs" 2>/dev/null || echo 0)" -gt 0 ]] || { printf '%s' "$none"; return 0; }
    jq -c --argjson evs "$evs" \
        --arg ki "$RU_KEYS_INPUT" --arg ko "$RU_KEYS_OUTPUT" \
        --arg kr "$RU_KEYS_CACHE_READ" --arg kw "$RU_KEYS_CACHE_WRITE" '
        def pick($src; $keys): ($keys | split(" ")) as $ks
            | ([$ks[] | $src[.]? // empty | select(type == "number")] | first) // null;
        def buckets($ev): (($ev.usage // {}) + ($ev | with_entries(select(.value | type == "number")))) as $src
            | {input: pick($src; $ki), output: pick($src; $ko),
               cache_read: pick($src; $kr), cache_write: pick($src; $kw)};
        ($evs | map(buckets(.))) as $all
        | (["input","output","cache_read","cache_write"]
           | map({key: ., value: (. as $b
               | if ($all | all(.[$b] != null))
                 then ($all | map(.[$b]) | add)
                 else null end)})
           | from_entries)
        | . + {status: (if (.input // .output // .cache_read // .cache_write) == null
                        then "unavailable" else "reported" end)}' <<< 'null'
}

# ru_reported_cost <file> <backend> — a USD figure the backend itself
# stated on its authoritative event, or empty.
ru_reported_cost() {
    local evs
    evs=$(ru_authoritative_events "$1" "${2:--}")
    [[ "$(jq -r 'length' <<< "$evs" 2>/dev/null || echo 0)" -gt 0 ]] || return 0
    # CONSERVATIVE, like the token sum: a run total exists only when
    # EVERY invocation reported a figure. One silent invocation makes
    # the total unknown rather than an understated partial sum.
    jq -r --arg k "$RU_KEY_COST" '
        if all(.[$k]? | type == "number" and . >= 0)
        then (map(.[$k]) | add) else empty end' <<< "$evs" 2>/dev/null || true
}

# ru_rate <model> [override-json-file] -> the validated rate object,
# or empty.
# Resolved through the EXISTING config loader so the documented
# layering, required-field validation and currency checks all apply —
# never a raw read of whichever file happens to contain rates.
# rc 0 + JSON  : a validated rate for this model
# rc 0 + empty : a valid table that simply does not list the model
# rc 2 + empty : the resolver or the configuration FAILED — a distinct
#                outcome that must never be read as "unpriced", because
#                a broken price table is an operator error, not a fact
#                about the model. Non-USD is refused here rather than
#                stored in a field named `usd`.
ru_rate() {
    local model="$1" override="${2:-}"
    [[ -n "$model" && "$model" != "-" ]] || return 0
    PYTHONPATH="$(_ru_repo_root)/scripts${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -c '
import json, sys
try:
    from session_analytics.config import load_config
    extra = None
    if len(sys.argv) > 2 and sys.argv[2]:
        with open(sys.argv[2], encoding="utf-8") as fh:
            extra = json.load(fh)
    # extra_overrides DEEP-MERGES over defaults and the user config, so
    # a partial rate block layers onto the shipped rates instead of
    # replacing them — and the whole merged entry is then validated.
    r = load_config(extra_overrides=extra).pricing.rate_for(sys.argv[1])
except Exception as exc:
    sys.stderr.write("price-resolver: %s: %s\n" % (type(exc).__name__, exc))
    sys.exit(2)
if r is None:
    sys.exit(0)          # valid table, model simply not listed
if r.currency != "USD":
    sys.stderr.write("price-resolver: rate for %r is %s, not USD\n" % (sys.argv[1], r.currency))
    sys.exit(2)
json.dump({"currency": r.currency, "effective_date": r.effective_date,
           "input": r.input, "output": r.output,
           "cache_read": r.cache_read, "cache_write": r.cache_write}, sys.stdout)
' "$model" "$override"
}

# ru_cost <tokens-json> <effective-model|-> <reported-usd|->
#
# Precedence, most authoritative first:
#   reported     the backend stated a USD figure on its own result event
#   computed     the model identity is VERIFIED, a validated rate
#                exists, and every bucket with a non-zero rate is
#                present in the evidence
#   unpriced     the verified model has no price entry
#   unavailable  anything else — no verified identity, no tokens, or
#                incomplete buckets for the rates that apply
#
# An unpriced or unavailable cost is null, NEVER 0: zero means a
# genuine zero. Where no USD figure is reported and none can be
# computed — subscription execution with no per-request marginal cost
# being the common case — the record says `unavailable` rather than
# fabricating 0.00.
# The optional 4th argument is a price-table override used ONLY by
# direct unit tests. It is an explicit parameter, never an ambient
# environment variable: production callers pass nothing, so no
# undocumented variable in the process environment can displace price
# resolution.
ru_cost() {
    local tokens="$1" model="${2:--}" reported="${3:--}" override="${4:-}"
    if [[ -n "$reported" && "$reported" != "-" ]]; then
        jq -nc --arg u "$reported" '{usd:($u|tonumber), basis:"reported", price_version:null}'
        return 0
    fi
    local unavailable='{"usd":null,"basis":"unavailable","price_version":null}'
    [[ "$(jq -r '.status' <<< "$tokens")" == "reported" ]] || { printf '%s' "$unavailable"; return 0; }
    # VERIFIED identity only: a requested model never proves what served
    # the request (#109 C13), so it must not price one.
    [[ -n "$model" && "$model" != "-" ]] || { printf '%s' "$unavailable"; return 0; }
    local rate rrc=0
    rate=$(ru_rate "$model" "$override" 2>/dev/null) || rrc=$?
    if [[ "$rrc" -ne 0 ]]; then
        # A broken or non-USD price table is an OPERATOR error, not a
        # fact about the model. Refusing by name keeps it distinct from
        # `unpriced`, which asserts a valid table that simply does not
        # list this model.
        echo "routing-usage: price resolution FAILED for model '$model' (exit $rrc) — refusing to record this as 'unpriced', which would hide a broken price table" >&2
        return 3
    fi
    if [[ -z "$rate" ]]; then
        jq -nc '{usd:null, basis:"unpriced", price_version:null}'
        return 0
    fi
    # COMPLETE BUCKETS: every bucket with a non-zero rate must be
    # present, or the total would silently understate.
    if ! jq -e --argjson t "$tokens" --argjson r "$rate" '
            ["input","output","cache_read","cache_write"]
            | all(. as $b | (($r[$b] // 0) == 0) or (($t[$b] // null) != null))' \
            >/dev/null 2>&1 <<< '{}'; then
        printf '%s' "$unavailable"
        return 0
    fi
    jq -nc --argjson t "$tokens" --argjson r "$rate" --argjson unit "$RU_RATE_UNIT" '
        (((($t.input      // 0) * $r.input)
        + (($t.output     // 0) * $r.output)
        + (($t.cache_read // 0) * $r.cache_read)
        + (($t.cache_write// 0) * $r.cache_write)) / $unit) as $usd
        | {usd:$usd, basis:"computed", price_version:$r.effective_date}'
}

# ru_usage <file> <backend> <effective-model|-> — the composed block.
ru_usage() {
    local file="$1" backend="${2:--}" model="${3:--}" tokens cost reported rc=0
    tokens=$(ru_extract_tokens "$file" "$backend")
    reported=$(ru_reported_cost "$file" "$backend")
    # A price-resolution failure PROPAGATES; it must not be flattened
    # into a usage block that looks merely unpriced.
    cost=$(ru_cost "$tokens" "$model" "${reported:--}") || rc=$?
    [[ "$rc" -eq 0 ]] || return "$rc"
    jq -nc --argjson t "$tokens" --argjson c "$cost" '{tokens:$t, cost:$c}'
}

# ru_doc_invariant <usage-json> — the shape a NEW record must satisfy.
# Enforced at the runtime boundary rather than in the JSON schema, so
# pre-G records stay valid. STRICT: exact key sets, non-negative
# integer tokens, `reported` iff at least one value exists, numeric
# non-negative USD, and the full basis/value/version relationships.
ru_doc_invariant() {
    jq -e '
        (type == "object") and ((keys_unsorted | sort) == ["cost","tokens"])
        and (.tokens | type == "object")
        and ((.tokens | keys_unsorted | sort)
             == ["cache_read","cache_write","input","output","status"])
        and (.cost | type == "object")
        and ((.cost | keys_unsorted | sort) == ["basis","price_version","usd"])
        # tokens: null, or a non-negative INTEGER
        and (. as $d | ["input","output","cache_read","cache_write"]
             | all(. as $b | ($d.tokens[$b] == null)
                   or (($d.tokens[$b] | type == "number")
                       and ($d.tokens[$b] >= 0)
                       and (($d.tokens[$b] | floor) == $d.tokens[$b]))))
        # status is exactly the presence of evidence, both ways
        and (((.tokens.input // .tokens.output
               // .tokens.cache_read // .tokens.cache_write) != null)
             == (.tokens.status == "reported"))
        and ((.tokens.status == "reported") or (.tokens.status == "unavailable"))
        and (. as $d | ["reported","computed","unpriced","unavailable"]
             | index($d.cost.basis) != null)
        # usd: null, or a non-negative number
        and ((.cost.usd == null)
             or ((.cost.usd | type == "number") and (.cost.usd >= 0)))
        and ((.cost.price_version == null) or (.cost.price_version | type == "string"))
        # unknown is NULL, never 0
        and (if (.cost.basis == "unpriced" or .cost.basis == "unavailable")
             then (.cost.usd == null and .cost.price_version == null)
             else true end)
        # a stated or computed cost must carry a value
        and (if (.cost.basis == "reported" or .cost.basis == "computed")
             then .cost.usd != null else true end)
        # a computed cost must carry its pricing provenance
        and (if .cost.basis == "computed" then .cost.price_version != null
             else true end)
        ' >/dev/null 2>&1 <<< "$1"
}
