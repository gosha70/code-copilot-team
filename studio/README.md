# Session Analytics Studio

Next.js + Tailwind + Cytoscape UI for the Copilot Session Analytics pipeline
(CCT issue #63). Pure presentation — it never touches a database directly; all
reads go through the FastAPI backend on `127.0.0.1`.

## Run

```bash
# 1. Start the API (and this Studio) from the repo root:
./scripts/session-analytics serve            # API :8765 + Studio :3000

# …or run the Studio standalone against an already-running API:
cd studio
npm install
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8765 npm run dev
```

## Tabs

| Tab | Contents |
|-----|----------|
| **Dashboard** | Session/turn/tool/error counters, sessions-by-copilot & by-day, tool usage, sentiment distribution. |
| **Sessions** | Searchable session table → detail. |
| **Session Detail** | **Insights** (turn timeline + heuristic badges), **Agent Tuning** (assessment + copy-ready config), **Prompt Coaching** (per-user-turn issues). |
| **Knowledge Graph** | Cytoscape explorer (tap-to-expand), node counts, read-only Cypher IDE with templates. |
| **Analysis** | The 5-step pipeline wizard; triggers the LLM-Judge step. |
| **Routing** | Shadow-mode routing analysis (E2 of #109): E1 evidence sets (valid, `invalid_evidence` with sanitized code, explanatory empty state), the report's arms/metric-vector/cost/per-task figures, Pareto frontier or its withholding reason, and per-task shadow recommendations — actual-vs-suggested with explicit divergence, three visually distinct outcomes (`insufficient_data` is "cannot conclude", never rendered like `no_change_recommended`), confidence grade + full basis, and followable evidence locators that open their referenced artifact coordinate in place. Read-only: nothing feeds back into live routing. |
| **Agents** | Discover / upload / manage agent configs. |
| **Settings** | Data sources + Test Connection, LLM-Judge config, source roots. |

The raw DSN is never sent to the browser — `/api/settings` returns the dialect
only. The Routing tab likewise never sees a filesystem path: evidence roots
surface as `{configured, root_count}`, sets are addressed by opaque content
id, and decision-bearing figures render in round-trip precision, never
display-rounded.
