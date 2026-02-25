# Phase Recap Template

Use this template after completing each major build phase to document decisions, issues, and outcomes.

---

## Phase {N}: {Phase Name}

**Date**: {YYYY-MM-DD}
**Duration**: {X hours/days}
**Team Lead**: {Agent or Human}

---

### What Was Built

**Agent/Role**: {Agent name or "Direct implementation"}

- {Summary of what this agent/role delivered}
- {Key files created or modified}
- {Notable design decisions}

**Agent/Role**: {Next agent}

- {Summary}

---

### Key Decisions

| Decision | Options Considered | Choice | Rationale |
|----------|-------------------|--------|-----------|
| {Decision topic} | {Option A, Option B} | {Chosen option} | {Why this was chosen} |

---

### Issues Encountered

| Issue | Root Cause | Resolution | Prevention |
|-------|-----------|------------|-----------|
| {Problem description} | {What caused it} | {How it was fixed} | {How to avoid next time} |

---

### Manual Steps Required

Document any steps needed outside of code generation:

- [ ] {Environment setup step}
- [ ] {Database initialization step}
- [ ] {Configuration step}
- [ ] {Dependency installation step}
- [ ] {Build verification step}

---

### Validation Checklist

- [ ] Type checking passes (zero errors)
- [ ] Linting passes (zero errors)
- [ ] Build/dev server runs successfully
- [ ] Manual smoke test completed (describe what was tested)
- [ ] All agents completed successfully
- [ ] Integration between agents verified

---

### What's Next

**Immediate next phase**: {Phase N+1 name}

**Prerequisites for next phase**:

- {What needs to be done before starting}
- {Any unresolved blockers}

**Out of scope / Deferred**:

- {Features intentionally left for later}
- {Technical debt to address eventually}

---

### Commit Summary

**Files Changed**: {Number} files ({additions} additions, {deletions} deletions)

**Commit Message**:

```
{Phase title}

{Detailed description of changes}
```

**Committed**: {Yes/No} — {Git commit hash if applicable}

---

### Lessons Learned

**What Went Well**:

- {Positive outcome or effective practice}

**What Could Be Improved**:

- {Area for optimization or better approach}

**Recommendations for Future Phases**:

- {Actionable suggestions based on this phase}

---

### Struggle Diagnosis

What was underspecified that caused rework or confusion?

| Struggle | Time Lost | Root Cause | Proposed Fix |
|----------|-----------|------------|-------------|
| {description} | {estimate} | {missing context / wrong assumption / tooling gap} | {rule or doc change to prevent recurrence} |

For each item, identify: should a rule in `shared/rules/` be updated? A template section added? A hook modified?

---

### Metrics

| Metric | Value |
|--------|-------|
| **Agents spawned** | {Number} |
| **Total tokens used** | {Approximate count} |
| **Duration** | {Hours/minutes} |
| **Files created** | {Number} |
| **Files modified** | {Number} |
| **Lines of code added** | {Approximate} |
| **Dependencies added** | {List packages} |

---

### References

**Design Documents**:

- {Link or path to system design doc}
- {Link or path to architecture doc}

**Agent Traces** (if archived):

- {Path to archived agent transcripts}

**Related PRs/Issues**:

- {Links if applicable}
