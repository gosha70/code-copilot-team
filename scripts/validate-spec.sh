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

# Admission's throwaway test worktree (#193): tracked globally so an
# interrupt/kill during the suite run never leaves a registered worktree
# in the USER'S repo or a stray temp dir behind.
ADMISSION_WT=""
ADMISSION_WT_PARENT=""
ADMISSION_WT_REPO=""
admission_wt_cleanup() {
  if [[ -n "$ADMISSION_WT" ]]; then
    git -C "${ADMISSION_WT_REPO:-.}" worktree remove --force "$ADMISSION_WT" >/dev/null 2>&1 || rm -rf "$ADMISSION_WT"
  fi
  if [[ -n "$ADMISSION_WT_PARENT" ]]; then
    rm -rf "$ADMISSION_WT_PARENT"
  fi
  ADMISSION_WT=""; ADMISSION_WT_PARENT=""; ADMISSION_WT_REPO=""
  return 0
}
trap admission_wt_cleanup EXIT INT TERM

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

# admission_toml_get <file> <section> <key> — same minimal TOML reader
# the provider scripts use (canonical copy: scripts/providers-health.sh);
# duplicated because admission must not depend on sourcing a runner.
admission_toml_get() {
  local file="$1" section="$2" key="$3"
  awk -v section="$section" -v key="$key" '
      /^\[/ { current = $0; gsub(/[\[\] ]/, "", current) }
      current == section && $0 ~ "^" key " *=" {
          val = $0
          sub(/^[^=]*= */, "", val)
          gsub(/^"|"$/, "", val)
          print val
          exit
      }
  ' "$file"
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

  # T4: capture admission start time for --result-file duration accounting.
  local _admission_start_epoch
  _admission_start_epoch=$(date +%s)
  # #242 finding 5: the evaluator healthcheck EXECUTES operator config,
  # so it may only run when every check before it passed.
  local _fails_at_entry=$TOTAL_FAIL

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
  #      resolve; runtime_conformance (C2, #242 FR-3) → the criterion
  #      must be real here, and the evaluator's availability+capability
  #      is checked against the effective config after the config gate
  #      (check 7b — a verifier something depends on cannot be
  #      unavailable).
  local ver_ok=true
  while IFS=$'\t' read -r fr _; do
    local nvers
    nvers="$(printf '%s\n' "$parsed" | awk -F'\t' -v fr="$fr" '$1 == "VER" && $2 == fr' | wc -l | tr -d ' ')"
    if [[ "$nvers" -eq 0 ]] && printf '%s\n' "$parsed" | grep -q "^FR	$fr\$"; then
      fail "$id: $fr has an entry but zero parsed verifiers (layout is part of the contract — regenerate via the draft generator; see shared/schemas/verification.schema.json)"
      ver_ok=false
    fi
  done <<< "$frs"
  while IFS=$'\t' read -r _ fr kind target _metric; do
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
        # The mapping itself is admissible since C2 (#242). A placeholder
        # criterion still refuses — a verifier nothing defines verifies
        # nothing.
        if [[ -z "$target" || "$target" == TODO* ]]; then
          fail "$id: $fr runtime_conformance criterion is a placeholder ('${target:-empty}') — write the real conformance criterion"
          ver_ok=false
        fi
        ;;
      *)
        fail "$id: $fr verifier has unknown kind '$kind' (deterministic|runtime_conformance)"
        ver_ok=false
        ;;
    esac
  done < <(printf '%s\n' "$parsed" | awk -F'\t' '$1 == "VER"')
  if [[ "$ver_ok" == "true" ]]; then pass "$id: every verifier resolves to something executable"; fi

  # 6. Unverifiable phrasing lint — on the AUTHORITATIVE spec text.
  #    C2 (#242 finding 3): such phrasing IS admissible when that FR
  #    carries a concrete runtime_conformance verifier — the evaluator
  #    is exactly the thing that can decide it. Deterministic-only FRs
  #    still refuse.
  local lint_ok=true
  while IFS=$'\t' read -r fr stmt; do
    if printf '%s' "$stmt" | grep -qiE 'user confirms|looks good|verify manually'; then
      if printf '%s\n' "$parsed" | awk -F'\t' -v fr="$fr" \
          '$1 == "VER" && $2 == fr && $3 == "runtime_conformance" { found = 1 } END { exit found ? 0 : 1 }'; then
        :  # carried by a runtime_conformance verifier — admissible in C2
      else
        fail "$id: $fr is phrased unverifiably ('user confirms'/'looks good'/'verify manually') and no runtime_conformance verifier carries it — map one or rephrase"
        lint_ok=false
      fi
    fi
  done <<< "$frs"
  if [[ "$lint_ok" == "true" ]]; then pass "$id: no unverifiably-phrased requirements"; fi

  # 7. Automation config: dedicated validator + declared unattended
  #    profile (explicit caps are enforced by the validator, #191).
  # The EFFECTIVE config: the driver's --config override / resume
  # snapshot when given, else the feature's own automation.json.
  # Admission over a config the run does not use proves nothing.
  local autocfg="${ADMISSION_CONFIG:-$spec_dir/automation.json}" autocfg_ok=false
  if [[ ! -f "$autocfg" ]]; then
    fail "$id: automation config missing ($autocfg) — unattended admission requires the full config surface"
  elif ! bash "$REPO_DIR/scripts/validate-automation-config.sh" "$autocfg" >/dev/null 2>&1; then
    fail "$id: automation.json fails validate-automation-config.sh (run it directly for the violations)"
  elif [[ "$(jq -r '.profile // "advisory"' "$autocfg" 2>/dev/null)" != "unattended" ]]; then
    fail "$id: automation.json profile is not 'unattended' — admission is the unattended bar; attended profiles do not use it"
  else
    autocfg_ok=true
    pass "$id: automation.json valid, profile unattended, caps explicit"
  fi

  # 7b. Conformance availability + capability (#242 FR-3, handoff item 2).
  #     REQUIRED is derived from the finalized artifact (the same parse
  #     admission validated above — never a re-read): any FR mapped to
  #     runtime_conformance. When required, the EFFECTIVE config must name
  #     an evaluator that resolves in providers.toml, DECLARES
  #     conformance_command (health alone is not capability — a healthy
  #     reviewer-only provider can only fabricate runtime evidence), and
  #     passes its healthcheck. No fallback chain: the gate freezes THIS
  #     evaluator id, so admission screens exactly it.
  local conf_required=false
  if printf '%s\n' "$parsed" | vc_conformance_required_parsed; then
    conf_required=true
  fi
  # Health is EXECUTED later (8b): resolving and validating the
  # declaration here is pure file inspection; running the healthcheck is
  # operator-command execution and must wait for governance (finding 5).
  local conf_health_eval="" conf_health_cmd=""
  if [[ "$conf_required" == "true" ]]; then
    local profile_toml="${CCT_PROVIDER_PROFILE:-$HOME/.code-copilot-team/providers.toml}"
    if [[ "$autocfg_ok" != "true" ]]; then
      fail "$id: conformance is required (runtime_conformance mapping) but the automation config was rejected above — evaluator availability cannot be verified"
    elif ! jq -e '.verification.conformance | type == "object"' "$autocfg" >/dev/null 2>&1; then
      fail "$id: runtime_conformance mapping requires verification.conformance in automation.json (evaluator + app contract) — the block is missing"
    else
      local conf_eval
      conf_eval="$(jq -r '.verification.conformance.evaluator // empty' "$autocfg" 2>/dev/null)"
      if [[ -z "$conf_eval" ]]; then
        fail "$id: verification.conformance.evaluator is missing — admission cannot screen an unnamed evaluator"
      elif [[ ! -f "$profile_toml" ]]; then
        fail "$id: provider profile not found ($profile_toml) — evaluator '$conf_eval' cannot resolve"
      elif ! grep -o '^\[providers\.[^]]*' "$profile_toml" 2>/dev/null | sed 's/^\[providers\.//' | grep -qxF "$conf_eval"; then
        fail "$id: evaluator '$conf_eval' does not resolve in providers.toml"
      else
        local conf_cmd conf_hc
        conf_cmd="$(admission_toml_get "$profile_toml" "providers.$conf_eval" "conformance_command")"
        conf_hc="$(admission_toml_get "$profile_toml" "providers.$conf_eval" "healthcheck")"
        if [[ -z "$conf_cmd" ]]; then
          fail "$id: evaluator '$conf_eval' is a reviewer-only provider — it declares no conformance_command, so it cannot exercise a running application (health is not capability); declare conformance_command in providers.toml or configure a capable evaluator"
        elif [[ "$conf_cmd" != *"{review_request}"* ]]; then
          # Finding 4: the declaration is only a capability if the command
          # can actually RECEIVE the frozen request document.
          fail "$id: evaluator '$conf_eval' declares conformance_command without the {review_request} placeholder — it cannot receive the frozen conformance request, so the declaration is not a capability"
        else
          pass "$id: conformance evaluator '$conf_eval' resolves, declares conformance_command"
          conf_health_eval="$conf_eval"
          conf_health_cmd="$conf_hc"
        fi
      fi
    fi
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

  # 8b. Evaluator healthcheck (#242 finding 5) — this EXECUTES an
  #     operator-configured command, so it runs only when governance
  #     passed AND no check so far has failed: a draft plan, a stale
  #     origin, or a sha-drifted artifact must never trigger it.
  if [[ -n "$conf_health_eval" ]]; then
    if [[ "$governance_ok" != "true" || "$TOTAL_FAIL" -gt "$_fails_at_entry" ]]; then
      echo "  [SKIP] $id: evaluator healthcheck not executed — earlier checks failed (nothing executes for a refused feature)"
    elif [[ -n "$conf_health_cmd" ]] && ! bash -c "$conf_health_cmd" >/dev/null 2>&1; then
      fail "$id: evaluator '$conf_health_eval' failed its healthcheck ($conf_health_cmd)"
    else
      pass "$id: conformance evaluator '$conf_health_eval' is healthy"
    fi
  fi

  # 9. test.command exists and passes on the BASE ref (§11) — an
  #    executing check, so it runs LAST and only when the config
  #    (check 7) and governance (check 8) already passed: admission
  #    never executes a command from a rejected or ungoverned feature.
  #    Executed in a THROWAWAY git worktree of HEAD when the project is
  #    a git repo: suites that emit artifacts (coverage, build output)
  #    must never dirty the real tree — the driver's clean-worktree
  #    preflight would otherwise abort the run admission just admitted.
  #    Bounded where timeout(1) exists (driver C-5 convention).
  if [[ "$autocfg_ok" == "true" && "$governance_ok" == "true" ]]; then
    local test_cmd
    test_cmd="$(jq -r '.test.command // empty' "$autocfg" 2>/dev/null)"
    if [[ -z "$test_cmd" ]]; then
      fail "$id: automation.json test.command missing — admission must prove the suite passes before any session runs"
    else
      local trc=0 admission_timeout="${CCT_ADMISSION_TEST_TIMEOUT:-600}"
      local run_dir="$project_dir"
      # CCT_ADMISSION_TEST_IN_PLACE=1 opts out of worktree isolation for
      # suites that need uncommitted/ignored files (node_modules, .env,
      # generated fixtures) — accepting that the suite may then dirty
      # the real tree.
      if [[ "${CCT_ADMISSION_TEST_IN_PLACE:-0}" != "1" ]] \
         && git -C "$project_dir" rev-parse --git-dir >/dev/null 2>&1; then
        ADMISSION_WT_PARENT="$(mktemp -d)"
        ADMISSION_WT="$ADMISSION_WT_PARENT/admission-wt"
        if git -C "$project_dir" worktree add --detach "$ADMISSION_WT" HEAD >/dev/null 2>&1; then
          run_dir="$ADMISSION_WT"
          ADMISSION_WT_REPO="$project_dir"
        else
          rm -rf "$ADMISSION_WT_PARENT"
          ADMISSION_WT=""; ADMISSION_WT_PARENT=""
        fi
      fi
      if command -v timeout >/dev/null 2>&1; then
        ( cd "$run_dir" && timeout "$admission_timeout" bash -c "$test_cmd" ) >/dev/null 2>&1 || trc=$?
      else
        ( cd "$run_dir" && bash -c "$test_cmd" ) >/dev/null 2>&1 || trc=$?
      fi
      admission_wt_cleanup
      if [[ $trc -eq 124 ]]; then
        fail "$id: test.command ('$test_cmd') exceeded the ${admission_timeout}s admission budget"
      elif [[ $trc -ne 0 ]]; then
        if [[ "$run_dir" != "$project_dir" ]]; then
          fail "$id: test.command ('$test_cmd') fails on the base ref (exit $trc) — a red base is not admissible. NOTE: admission runs the suite in a throwaway worktree of HEAD, so uncommitted and gitignored files (deps, .env, generated fixtures) are absent; commit what the suite needs, add a bootstrap step, or set CCT_ADMISSION_TEST_IN_PLACE=1"
        else
          fail "$id: test.command ('$test_cmd') fails on the current ref (exit $trc) — a red base is not admissible"
        fi
      else
        pass "$id: test.command passes on the current ref"
      fi
    fi
  else
    fail "$id: test.command not attempted — config or governance checks failed (admission never executes commands for a rejected or ungoverned feature)"
  fi

  # T4: write structured admission result when --result-file is given.
  # The driver owns the file path and validates it against the schema.
  # Write ONLY on success (all checks passed) — on failure the driver
  # handles refusal and removes the result file (FR-7a).
  if [[ -n "${ADMISSION_RESULT_FILE:-}" && "$TOTAL_FAIL" -eq 0 ]]; then
    local _adm_dur
    _adm_dur=$(( $(date +%s) - _admission_start_epoch ))
    if ! jq -n --arg path "${ADMISSION_RESULT_PATH:-fresh-unattended-noblock}" \
        --argjson exit_code 0 \
        --argjson duration_sec "$_adm_dur" \
        '{schema_version: 1, path: $path,
          admission: {test_command: {exit_code: $exit_code, duration_sec: $duration_sec}}}' \
        > "$ADMISSION_RESULT_FILE"; then
      # Fail-closed: admission passed governance but the result file cannot
      # be written (disk full, permission denied). A missing result would
      # let the driver import nothing and proceed as if admission didn't
      # contribute — exactly the silent-skip this channel exists to prevent.
      fail "admission: failed to write result file to $ADMISSION_RESULT_FILE"
    fi
  fi

  print_defers
}

# ── CLI ──────────────────────────────────────────────────────

MODE="all"
FEATURE_ID=""
UNATTENDED=false
ADMISSION_CONFIG=""
ADMISSION_RESULT_FILE=""
ADMISSION_RESULT_PATH=""

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
    --config)
      # #193 P1: admission must validate the EFFECTIVE config — the one
      # the run will actually use (the driver's --config override or its
      # frozen resume snapshot) — never a default file the run ignores.
      ADMISSION_CONFIG="${2:?--config requires a path}"
      shift 2
      ;;
    --result-file)
      # T4: admission writes its structured result here when it passes.
      ADMISSION_RESULT_FILE="${2:?--result-file requires a path}"
      shift 2
      ;;
    --result-path)
      # T4: path discriminator the admission result should carry.
      ADMISSION_RESULT_PATH="$2"
      shift 2
      ;;
    *)
      echo "Usage: validate-spec.sh [--feature-id ID | --all] [--unattended [--config <path>] [--result-file <path> --result-path <path>]]"
      exit 1
      ;;
  esac
done

if [[ "$UNATTENDED" == "true" && "$MODE" != "single" ]]; then
  echo "Usage: --unattended requires --feature-id <id> (admission is per-feature)"
  exit 1
fi
if [[ -n "$ADMISSION_CONFIG" && "$UNATTENDED" != "true" ]]; then
  echo "Usage: --config is only meaningful with --unattended (admission's effective config)"
  exit 1
fi
if [[ -n "$ADMISSION_RESULT_FILE" && "$UNATTENDED" != "true" ]]; then
  echo "Usage: --result-file is only meaningful with --unattended (admission result)"
  exit 1
fi
if [[ -n "$ADMISSION_RESULT_PATH" && -z "$ADMISSION_RESULT_FILE" ]]; then
  echo "Usage: --result-path requires --result-file"
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
