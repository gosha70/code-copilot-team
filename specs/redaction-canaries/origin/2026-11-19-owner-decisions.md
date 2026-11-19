# Owner decisions for #457 (session of 2026-11-19)

Three questions were put to the owner after the redaction inventory of
`scripts/session_analytics`. The answers, verbatim:

1. **Studio and quickstart ingest skip the redaction config.** Asked how to
   handle it relative to #457. Answer: "Separate bug, fix first" (filed as
   #473, fixed in PR #474).
2. **Which paths the canary tests cover.** Options were judge-bound only,
   everything off-machine, or everything including API/export. Answer:
   "Everything off-machine": ingest previews plus every path that sends
   session text out (per-turn judge, analysis transcript + steering + harness
   stamp, Ask, embeddings, MCP).
3. **The stale-mode gap.** Most outbound paths send whatever mode was stored
   at ingest, so a project tightened to metadata-only later still sends its
   old previews until re-ingest. Asked whether that is in #457's scope.
   Answer: "In scope": #457 also adds a current-config floor (stricter_mode)
   to every outbound path, with canary tests that tighten a project after
   ingest.
