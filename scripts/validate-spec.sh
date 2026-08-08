#!/usr/bin/env bash

# validate-spec.sh — Validate SDD artifacts in specs/*/ directories
#
# Checks that each spec directory conforms to the spec_mode declared
# in its plan.md YAML frontmatter, per shared/skills/spec-workflow/SKILL.md.
#
# Usage:
#   validate-spec.sh [--feature-id ID | --all]
#   Default: --all

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# CCT_SPECS_DIR overrides the default specs/ root (same pattern as
# check-origin-alignment.sh; used by the auto-build driver and tests).
SPECS_DIR="${CCT_SPECS_DIR:-$REPO_DIR/specs}"

TOTAL_PASS=0
TOTAL_FAIL=0

# ── Helpers ──────────────────────────────────────────────────

# Extract a YAML frontmatter field value from a file.
# Expects --- delimited frontmatter at the top of the file.
extract_frontmatter_field() {
  local file="$1" field="$2"
  # `|| true` after grep so a missing field returns empty without
  # tripping `set -e + pipefail` in callers.
  sed -n '/^---$/,/^---$/p' "$file" \
    | { grep "^${field}:" || true; } \
    | head -1 \
    | sed "s/^${field}:[[:space:]]*//" \
    | sed 's/^"\(.*\)"$/\1/' \
    | sed "s/^'\(.*\)'$/\1/" \
    | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

pass() {
  echo "  [PASS] $1"
  TOTAL_PASS=$((TOTAL_PASS + 1))
}

fail() {
  echo "  [FAIL] $1"
  TOTAL_FAIL=$((TOTAL_FAIL + 1))
}

# ── Per-spec validation ──────────────────────────────────────

validate_spec_dir() {
  local spec_dir="$1"
  local id
  id="$(basename "$spec_dir")"
  local plan="$spec_dir/plan.md"

  echo "--- $id ---"

  # plan.md must exist
  if [[ ! -f "$plan" ]]; then
    fail "$id: plan.md not found"
    return
  fi

  # Extract required frontmatter fields
  local spec_mode feature_id justification status
  spec_mode="$(extract_frontmatter_field "$plan" "spec_mode")"
  feature_id="$(extract_frontmatter_field "$plan" "feature_id")"
  justification="$(extract_frontmatter_field "$plan" "justification")"
  status="$(extract_frontmatter_field "$plan" "status")"

  # origin: must be present (top-level frontmatter key). The
  # check-origin-alignment.sh script does the deeper structural check;
  # here we only verify the convention is followed at all.
  # See shared/skills/origin-confirmation/SKILL.md.
  # `|| true` suppresses pipefail when grep finds no match.
  local has_origin
  has_origin="$(sed -n '/^---$/,/^---$/p' "$plan" | grep -cE '^origin:' || true)"
  if [[ "${has_origin:-0}" -eq 0 ]]; then
    fail "$id: origin: missing from plan.md frontmatter (see shared/skills/origin-confirmation/SKILL.md)"
    return
  fi

  # spec_mode must be present and valid
  if [[ -z "$spec_mode" ]]; then
    fail "$id: spec_mode missing from plan.md frontmatter"
    return
  fi

  if [[ "$spec_mode" != "full" && "$spec_mode" != "lightweight" && "$spec_mode" != "none" ]]; then
    fail "$id: spec_mode '$spec_mode' is not valid (must be full, lightweight, or none)"
    return
  fi

  # feature_id must be present
  if [[ -z "$feature_id" ]]; then
    fail "$id: feature_id missing from plan.md frontmatter"
    return
  fi

  # status must be present and valid
  if [[ -z "$status" ]]; then
    fail "$id: status missing from plan.md frontmatter"
    return
  fi

  if [[ "$status" != "draft" && "$status" != "approved" ]]; then
    fail "$id: status '$status' is not valid (must be draft or approved)"
    return
  fi
  pass "$id: plan.md frontmatter valid (spec_mode=$spec_mode, status=$status)"

  # Mode-specific validation
  case "$spec_mode" in
    full)
      # spec.md must exist
      if [[ ! -f "$spec_dir/spec.md" ]]; then
        fail "$id: spec.md required for spec_mode=full but not found"
        return
      fi

      # spec.md must have User Scenarios, Requirements, Constraints sections
      local missing_sections=""
      grep -q '## User Scenarios' "$spec_dir/spec.md" || missing_sections="$missing_sections User Scenarios,"
      grep -q '## Requirements' "$spec_dir/spec.md" || missing_sections="$missing_sections Requirements,"
      grep -q '## Constraints' "$spec_dir/spec.md" || missing_sections="$missing_sections Constraints,"

      if [[ -n "$missing_sections" ]]; then
        fail "$id: spec.md missing required sections:$missing_sections"
        return
      fi

      # No unresolved [NEEDS CLARIFICATION] markers
      # Match actual markers: [NEEDS CLARIFICATION]: ... or [NEEDS CLARIFICATION: ...]
      # but not descriptive references like "has unresolved [NEEDS CLARIFICATION] markers"
      if grep -qE '\[NEEDS CLARIFICATION\]:|\[NEEDS CLARIFICATION:' "$spec_dir/spec.md"; then
        fail "$id: spec.md has unresolved [NEEDS CLARIFICATION] markers"
        return
      fi

      # tasks.md must exist
      if [[ ! -f "$spec_dir/tasks.md" ]]; then
        fail "$id: tasks.md required for spec_mode=full but not found"
        return
      fi

      pass "$id: spec_mode=full artifacts valid"
      ;;

    lightweight)
      # spec.md must exist
      if [[ ! -f "$spec_dir/spec.md" ]]; then
        fail "$id: spec.md required for spec_mode=lightweight but not found"
        return
      fi

      # spec.md must have Requirements and Constraints sections
      local missing_sections=""
      grep -q '## Requirements' "$spec_dir/spec.md" || missing_sections="$missing_sections Requirements,"
      grep -q '## Constraints' "$spec_dir/spec.md" || missing_sections="$missing_sections Constraints,"

      if [[ -n "$missing_sections" ]]; then
        fail "$id: spec.md missing required sections:$missing_sections"
        return
      fi

      # No unresolved [NEEDS CLARIFICATION] markers
      # Match actual markers: [NEEDS CLARIFICATION]: ... or [NEEDS CLARIFICATION: ...]
      # but not descriptive references like "has unresolved [NEEDS CLARIFICATION] markers"
      if grep -qE '\[NEEDS CLARIFICATION\]:|\[NEEDS CLARIFICATION:' "$spec_dir/spec.md"; then
        fail "$id: spec.md has unresolved [NEEDS CLARIFICATION] markers"
        return
      fi

      pass "$id: spec_mode=lightweight artifacts valid"
      ;;

    none)
      # justification must be non-empty
      if [[ -z "$justification" ]]; then
        fail "$id: justification required in plan.md frontmatter for spec_mode=none"
        return
      fi

      # spec.md must NOT exist
      if [[ -f "$spec_dir/spec.md" ]]; then
        fail "$id: spec.md must NOT exist for spec_mode=none"
        return
      fi

      pass "$id: spec_mode=none artifacts valid"
      ;;
  esac
}

# ── Unattended admission (#193, Increment B of #190 §3+§11) ──
#
# validate-spec.sh --unattended --feature-id <id> is the admission bar
# an `unattended` auto-build run must pass before it starts. Admission
# PROVES the finalized verification.yaml is complete and faithful — it
# never authors or repairs it. All failures are reported (no fail-fast);
# §11 items owned by increment C are printed as DEFER lines so the
# bar's known extent is visible, never silently passed.

defer() {
  echo "  [DEFER] $1 (increment C)"
}

# The §11 items owned by later increments — printed on EVERY admission
# exit path (early refusals included) so the bar's known extent stays
# visible, never silently passed.
print_defers() {
  defer "coverage floors / regression baselines (greenfield 'baseline: none' handling)"
  defer "UI-in-scope DESIGN.md placeholder check + harness/ + copilot:review presence"
  defer "schema-migration allowlist"
  defer "mid-flight credential/secret enumeration (delegation-best-practices)"
}

# admission_target_ok <project_dir> <target> — a deterministic verifier
# target is genuinely executable: a path form must be an executable
# FILE (a directory or plain file verifies nothing); a command form
# must resolve to a real command that is not a no-op/builtin head, and
# every path-shaped argument (contains a slash or a script extension)
# must exist as a file. Fail-open resolution here would let
# `bash no/such/test.sh` pass because bash exists.
admission_target_ok() {
  local project_dir="$1" t="$2"
  if [[ -f "$project_dir/$t" && -x "$project_dir/$t" ]]; then
    return 0
  fi
  # A path form that exists but is not an executable file is NOT
  # rescued by command resolution.
  [[ -e "$project_dir/$t" ]] && return 1
  local head="${t%% *}"
  case "$head" in
    true|false|:|.|source|test|\[|echo|printf|cd|exit)
      return 1 ;;   # no-op / shell-builtin heads cannot execute a test
  esac
  command -v "$head" >/dev/null 2>&1 || return 1
  if [[ "$t" == "$head" ]]; then
    # A bare interpreter/pager with nothing to run verifies nothing;
    # a bare tool with its own suite semantics (make, npm, pytest) is
    # legitimate and indistinguishable statically — increment C, which
    # actually RUNS verifiers, decides those for real.
    case "$head" in
      bash|sh|zsh|dash|ksh|cat|python|python3|node|npx|perl|ruby) return 1 ;;
    esac
    return 0
  fi
  local w
  for w in ${t#* }; do
    case "$w" in
      -*) ;;
      */*|*.sh|*.py|*.js|*.ts|*.bats)
        [[ -f "$project_dir/$w" ]] || return 1 ;;
    esac
  done
  return 0
}

validate_admission() {
  local spec_dir="$1"
  local id spec artifact project_dir
  id="$(basename "$spec_dir")"
  spec="$spec_dir/spec.md"
  artifact="$spec_dir/verification.yaml"
  project_dir="$(cd "$SPECS_DIR/.." && pwd)"

  # shellcheck source=lib/verification-common.sh
  source "$REPO_DIR/scripts/lib/verification-common.sh"

  echo ""
  echo "--- $id: unattended admission (#190 §11, increment B) ---"

  # 0. Inputs must exist before any check can be decided — a missing
  #    input is a NAMED failure, never a raw tool error mid-report.
  if [[ ! -f "$spec" ]]; then
    fail "$id: spec.md missing — there is no authoritative requirement text to admit against"
    print_defers
    return
  fi

  # 1. Finalized artifact exists — a raw draft is inadmissible.
  if [[ ! -f "$artifact" ]]; then
    fail "$id: verification.yaml missing — generate a draft (scripts/generate-verification-draft.sh), map verifiers, finalize"
    print_defers
    return
  fi
  local parsed status
  parsed="$(vc_parse_artifact "$artifact")"
  status="$(printf '%s\n' "$parsed" | awk -F'\t' '$1 == "STATUS" { print $2; exit }')"
  if [[ "$status" != "finalized" ]]; then
    fail "$id: verification.yaml status is '${status:-missing}' — admission requires 'finalized' (a generated draft is not admissible)"
  else
    pass "$id: verification.yaml is finalized"
  fi

  # 2+3. Coverage in both directions + statement_sha recomputation.
  #      spec.md is the ONLY authoritative source of requirement text.
  local frs
  frs="$(vc_extract_frs "$spec")"
  if [[ -z "$frs" ]]; then
    fail "$id: no FR-N requirements found in spec.md ## Requirements — nothing to admit against"
    print_defers
    return
  fi
  local cov_ok=true sha_ok=true
  while IFS=$'\t' read -r fr stmt; do
    if ! printf '%s\n' "$parsed" | grep -q "^FR	$fr\$"; then
      fail "$id: $fr has no verification.yaml entry (coverage is mandatory — every requirement maps to >=1 verifier)"
      cov_ok=false
      continue
    fi
    local want got
    want="$(vc_fr_sha "$fr" "$stmt")"
    got="$(printf '%s\n' "$parsed" | awk -F'\t' -v fr="$fr" '$1 == "SHA" && $2 == fr { print $3; exit }')"
    if [[ -z "$got" ]]; then
      fail "$id: $fr entry has no statement_sha (the binding to spec.md is mandatory)"
      sha_ok=false
    elif [[ "$got" != "$want" ]]; then
      fail "$id: $fr statement_sha mismatch — spec.md text changed after finalization (recompute: re-finalize the artifact)"
      sha_ok=false
    fi
  done <<< "$frs"
  local phantom
  phantom="$(printf '%s\n' "$parsed" | awk -F'\t' '$1 == "FR" { print $2 }' | while read -r afr; do
      printf '%s\n' "$frs" | cut -f1 | grep -q "^$afr\$" || echo "$afr"
  done)"
  for p in $phantom; do
    fail "$id: verification.yaml entry '$p' has no matching FR in spec.md (phantom requirement)"
    cov_ok=false
  done
  if [[ "$cov_ok" == "true" ]]; then pass "$id: coverage — every FR-N mapped, no phantom entries"; fi
  if [[ "$sha_ok" == "true" ]]; then pass "$id: every statement_sha recomputes clean against spec.md"; fi

  # 4+5. Every verifier is executable NOW. deterministic → target must
  #      resolve; runtime_conformance → the §6 evaluator ships in
  #      increment C, so the mapping is inadmissible in B (a verifier
  #      something depends on cannot be unavailable).
  local ver_ok=true
  while IFS=$'\t' read -r fr _; do
    local nvers
    nvers="$(printf '%s\n' "$parsed" | awk -F'\t' -v fr="$fr" '$1 == "VER" && $2 == fr' | wc -l | tr -d ' ')"
    if [[ "$nvers" -eq 0 ]] && printf '%s\n' "$parsed" | grep -q "^FR	$fr\$"; then
      fail "$id: $fr has an entry but zero parsed verifiers (layout is part of the contract — regenerate via the draft generator; see shared/schemas/verification.schema.json)"
      ver_ok=false
    fi
  done <<< "$frs"
  while IFS=$'\t' read -r _ fr kind target; do
    case "$kind" in
      deterministic)
        if [[ -z "$target" || "$target" == TODO* ]]; then
          fail "$id: $fr deterministic verifier is a placeholder ('${target:-empty}') — map it to a real executable"
          ver_ok=false
        elif ! admission_target_ok "$project_dir" "$target"; then
          fail "$id: $fr deterministic verifier '$target' does not resolve to a genuinely executable test (needs an executable file, or a real command whose script arguments exist; directories, plain files, and no-op heads verify nothing)"
          ver_ok=false
        fi
        ;;
      runtime_conformance)
        fail "$id: $fr is mapped to runtime_conformance but the §6 evaluator is unavailable (ships in increment C) — inadmissible in B"
        ver_ok=false
        ;;
      *)
        fail "$id: $fr verifier has unknown kind '$kind' (deterministic|runtime_conformance)"
        ver_ok=false
        ;;
    esac
  done < <(printf '%s\n' "$parsed" | awk -F'\t' '$1 == "VER"')
  if [[ "$ver_ok" == "true" ]]; then pass "$id: every verifier resolves to something executable"; fi

  # 6. Unverifiable phrasing lint — on the AUTHORITATIVE spec text.
  local lint_ok=true
  while IFS=$'\t' read -r fr stmt; do
    if printf '%s' "$stmt" | grep -qiE 'user confirms|looks good|verify manually'; then
      fail "$id: $fr is phrased unverifiably ('user confirms'/'looks good'/'verify manually') — only a runtime_conformance criterion could carry it, and that is increment C"
      lint_ok=false
    fi
  done <<< "$frs"
  if [[ "$lint_ok" == "true" ]]; then pass "$id: no unverifiably-phrased requirements"; fi

  # 7. Automation config: dedicated validator + declared unattended
  #    profile (explicit caps are enforced by the validator, #191).
  local autocfg="$spec_dir/automation.json" autocfg_ok=false
  if [[ ! -f "$autocfg" ]]; then
    fail "$id: automation.json missing — unattended admission requires the full config surface"
  elif ! bash "$REPO_DIR/scripts/validate-automation-config.sh" "$autocfg" >/dev/null 2>&1; then
    fail "$id: automation.json fails validate-automation-config.sh (run it directly for the violations)"
  elif [[ "$(jq -r '.profile // "advisory"' "$autocfg" 2>/dev/null)" != "unattended" ]]; then
    fail "$id: automation.json profile is not 'unattended' — admission is the unattended bar; attended profiles do not use it"
  else
    autocfg_ok=true
    pass "$id: automation.json valid, profile unattended, caps explicit"
  fi

  # 8. Governance gates BEFORE any command execution: plan approved +
  #    origin gate <=1 (existing gates, kept). These are non-executing
  #    checks — a feature that is inadmissible on governance must never
  #    get to run its own test.command first.
  local governance_ok=true
  local plan_status=""
  if [[ -f "$spec_dir/plan.md" ]]; then
    plan_status="$(extract_frontmatter_field "$spec_dir/plan.md" "status")"
  fi
  if [[ "$plan_status" != "approved" ]]; then
    fail "$id: plan.md status is '${plan_status:-missing}' — admission requires 'approved'"
    governance_ok=false
  else
    pass "$id: plan.md approved"
  fi
  local origin_exit=0
  bash "$REPO_DIR/scripts/check-origin-alignment.sh" "$id" >/dev/null 2>&1 || origin_exit=$?
  if [[ $origin_exit -gt 1 ]]; then
    fail "$id: origin gate exit $origin_exit (needs <=1) — resolve alignment before admission"
    governance_ok=false
  else
    pass "$id: origin gate exit $origin_exit"
  fi

  # 9. test.command exists and passes on the CURRENT ref (§11) — the
  #    ONLY executing check, so it runs LAST and only when the config
  #    (check 7) and governance (check 8) already passed: admission
  #    never executes a command from a rejected or ungoverned feature.
  #    Bounded where timeout(1) exists (driver C-5 convention).
  if [[ "$autocfg_ok" == "true" && "$governance_ok" == "true" ]]; then
    local test_cmd
    test_cmd="$(jq -r '.test.command // empty' "$autocfg" 2>/dev/null)"
    if [[ -z "$test_cmd" ]]; then
      fail "$id: automation.json test.command missing — admission must prove the suite passes before any session runs"
    else
      local trc=0 admission_timeout="${CCT_ADMISSION_TEST_TIMEOUT:-600}"
      if command -v timeout >/dev/null 2>&1; then
        ( cd "$project_dir" && timeout "$admission_timeout" bash -c "$test_cmd" ) >/dev/null 2>&1 || trc=$?
      else
        ( cd "$project_dir" && bash -c "$test_cmd" ) >/dev/null 2>&1 || trc=$?
      fi
      if [[ $trc -eq 124 ]]; then
        fail "$id: test.command ('$test_cmd') exceeded the ${admission_timeout}s admission budget"
      elif [[ $trc -ne 0 ]]; then
        fail "$id: test.command ('$test_cmd') fails on the current ref (exit $trc) — a red base is not admissible"
      else
        pass "$id: test.command passes on the current ref"
      fi
    fi
  else
    fail "$id: test.command not attempted — config or governance checks failed (admission never executes commands for a rejected or ungoverned feature)"
  fi

  print_defers
}

# ── CLI ──────────────────────────────────────────────────────

MODE="all"
FEATURE_ID=""
UNATTENDED=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --feature-id)
      MODE="single"
      FEATURE_ID="$2"
      shift 2
      ;;
    --all)
      MODE="all"
      shift
      ;;
    --unattended)
      UNATTENDED=true
      shift
      ;;
    *)
      echo "Usage: validate-spec.sh [--feature-id ID | --all] [--unattended]"
      exit 1
      ;;
  esac
done

if [[ "$UNATTENDED" == "true" && "$MODE" != "single" ]]; then
  echo "Usage: --unattended requires --feature-id <id> (admission is per-feature)"
  exit 1
fi

echo "=== Validating SDD spec conformance ==="
echo ""

if [[ "$MODE" == "single" ]]; then
  # --feature-id resolves to either a top-level spec dir or a nested pitch dir.
  if [[ -d "$SPECS_DIR/$FEATURE_ID" ]]; then
    validate_spec_dir "$SPECS_DIR/$FEATURE_ID"
    if [[ "$UNATTENDED" == "true" ]]; then
      validate_admission "$SPECS_DIR/$FEATURE_ID"
    fi
  elif [[ -d "$SPECS_DIR/pitches/$FEATURE_ID" ]]; then
    validate_spec_dir "$SPECS_DIR/pitches/$FEATURE_ID"
    if [[ "$UNATTENDED" == "true" ]]; then
      validate_admission "$SPECS_DIR/pitches/$FEATURE_ID"
    fi
  else
    echo "  [FAIL] specs/$FEATURE_ID/ or specs/pitches/$FEATURE_ID/ directory not found"
    exit 1
  fi
else
  found=0
  # Top-level spec dirs (existing behavior).
  for dir in "$SPECS_DIR"/*/; do
    [[ -d "$dir" ]] || continue
    # Skip directories without plan.md (e.g. .DS_Store, the pitches/ container).
    [[ -f "$dir/plan.md" ]] || continue
    found=1
    validate_spec_dir "$dir"
  done
  # Nested pitch dirs (additive — Shape-Up support, see specs/pitches/0001-shape-up-support/).
  if [[ -d "$SPECS_DIR/pitches" ]]; then
    for dir in "$SPECS_DIR/pitches"/*/; do
      [[ -d "$dir" ]] || continue
      [[ -f "$dir/plan.md" ]] || continue
      found=1
      validate_spec_dir "$dir"
    done
  fi
  if [[ "$found" -eq 0 ]]; then
    echo "No spec directories found in specs/"
    exit 0
  fi
fi

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$TOTAL_PASS" "$TOTAL_FAIL"
echo "========================================="

if [[ $TOTAL_FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
