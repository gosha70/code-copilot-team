# Error Reporting Template

When reporting errors to the agent, use this structured format to minimize back-and-forth debugging cycles.

## Quick Template

```
**What I did**: [action that triggered the error]
**What I expected**: [expected behavior]
**What happened**: [actual behavior]
**Error message**: [exact error text — just the relevant line, not the full stack trace]
**Browser/terminal**: [where the error appeared]
**URL**: [what page/route I was on]
```

## Example — Good Error Report

```
**What I did**: Clicked "Create New" button in the dashboard
**What I expected**: Form page to open
**What happened**: Page crashed with a white screen
**Error message**: "TypeError: Cannot read properties of undefined (reading 'map')"
**Browser/terminal**: Browser console (Chrome)
**URL**: /dashboard/items/new
```

## Example — Bad Error Report

```
It doesn't work. I get an error when I click the button.
```

This requires multiple follow-up questions (which button? which page? what error? browser or terminal?), wasting time and context tokens.

## Tips for Efficient Error Reporting

1. **Paste the specific error line**, not the entire stack trace. The agent can ask for more context if needed.
2. **Include the URL/route** — this tells the agent which component to look at.
3. **Mention where the error appeared** — browser console vs terminal vs build output.
4. **If it's a visual bug**, describe what you see vs what you expected ("the hero image fills the entire viewport; I expected it to be half-height").
5. **If the error is recurring**, note which sessions/phases it appeared in before.

## For the Agent

When receiving an error report:

1. **Don't guess.** If the report is missing key information, ask for it before attempting a fix.
2. **Check the obvious first**: Is the dependency installed? Is the config file present? Is the service running?
3. **If the same error has appeared before**, check what fixed it last time before trying a new approach.
4. **Cap debugging at 10 exchanges.** If the issue isn't resolved after 10 back-and-forth messages, suggest starting a fresh session with a clean problem description.
