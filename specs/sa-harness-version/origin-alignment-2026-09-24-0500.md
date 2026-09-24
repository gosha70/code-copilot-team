# Origin alignment check — sa-harness-version (A4a, after PR review)

Checked 2026-09-24 05:00, after the owner's review of PR #375 and the
fixes for it. Supersedes the 03:30 record; origin and claims unchanged
except as the three findings sharpen them.

Origin: specs/sa-harness-version/origin/2026-09-24-owner-direction.md
(now including the PR review) and issue #371, row A4.

What the review corrected, and where it now stands:

1. The hook is registered on the path setup.sh actually installs:
   HOOKS_CONFIG (fresh settings) and both ensure_hook_command call
   sites (--sync and the full-install merge). The repo's settings.json
   was never what setup.sh writes. Pinned by a test that extracts the
   real HOOKS_CONFIG and ensure_hook_command from setup.sh and runs
   them against a temp settings file: present once fresh, once after
   two merges into an existing file, in the existing matcher group,
   permissions preserved.
2. The store keeps the stored fact over the incoming one, fills only
   NULLs, and marks mixed when both are non-null and differ (the
   reader's between-lines rule, applied between store and ledger).
   Pinned: ingest A, replace the ledger with B only, re-ingest → A
   kept, providers filled, mixed; a repeat changes nothing.
3. The ledger path is environment-only (CCT_HARNESS_STAMPS, the name
   the hook reads); the JSON key and its default are removed. Pinned:
   the env moves the loader, the default holds without it, the
   defaults file has no key, the hook reads the same name.

Verdict: aligned
Confidence: high
