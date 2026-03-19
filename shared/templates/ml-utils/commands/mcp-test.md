Run MCP server integration test:
1. Start the MCP server in stdio mode
2. List available tools and resources; verify tool count is under 10
3. Read the health MCP resource and verify it returns valid status
4. For each registered tool: send a minimal valid request, verify response schema
5. Test reference-based flow: store an item, search for it, retrieve full content by ref_id
6. Report: tool count, resource count, response times, any schema violations or errors
