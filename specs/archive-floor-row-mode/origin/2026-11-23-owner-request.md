# Origin: the owner's request, 2026-11-23

Relayed in session after the review of PR #513 (export applies each
project's current settings) found the gap. The owner's words:

> The build matches the spec, but the reviewer found a floor gap. After a
> project is tightened and ingest --full runs, the session's recorded mode
> equals the current one, so the floor stops applying, while
> trace_documents rows keep their own older mode. Export then writes 5
> canaries in trace_documents with no markers and no stderr line. A plain
> archive doesn't rewrite them; archive --full does.
>
> The same state leaks on the v2.1.0 tag through four off-machine paths:
> session analysis, Ask search_text, Ask session_turns and MCP
> get_session_details.
>
> (2) Fix it in the shared policy in its own PR: decide archived text by the
> trace row's own redaction_mode against the project's current mode, in
> every reader of trace_document. Add to test_canary_floor the case "ingest
> and archive under none, tighten, ingest --full, archive not re-run", which
> must fail on master. Also check stored session-analysis outputs.
