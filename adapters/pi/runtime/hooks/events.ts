/**
 * Neutral lifecycle-event schema + Pi->CCT translators (T5.1, FR-010).
 *
 * Pi emits a small set of lifecycle events; CCT hooks are expressed in the
 * neutral vocabulary shared with the Claude Code adapter (PreToolUse, ...).
 * This module defines the adapter-agnostic event record, the Pi->CCT mapping
 * matrix with an explicit support level, and pure translators for the two
 * events Pi is verified to emit (session_start, tool_call).
 *
 * Boundary (verified — specs/pi-harness-adoption/design-t51-events.md): only
 * SessionStart and PreToolUse are `supported`; Notification is `degraded`
 * (outbound ctx.ui.notify only); PostToolUse / Stop / PreCompact / PostCompact
 * are `unsupported`. Unsupported/degraded events are reported and audited,
 * never approximated — the shell-hook adapter refuses to run for them.
 */

export type CctHookEvent =
  | "PreToolUse"
  | "PostToolUse"
  | "Stop"
  | "Notification"
  | "SessionStart"
  | "PreCompact"
  | "PostCompact";

export type SupportLevel = "supported" | "degraded" | "unsupported";

export type EventPhase = "pre" | "post" | "session" | "notify";

export interface SessionInfo {
  interactive: boolean;
  mode: string;
}

/** Adapter-agnostic lifecycle event produced by a translator (FR-010). */
export interface CctLifecycleEvent {
  event: CctHookEvent;
  phase: EventPhase;
  tool?: string;
  matcher?: string; // Claude Code matcher, e.g. "Edit|Write" | "Bash"
  input?: Record<string, unknown>;
  result?: Record<string, unknown>; // PostToolUse only (unsupported today)
  cwd: string;
  session: SessionInfo;
  origin: "pi";
  support: SupportLevel;
}

export interface HookMapping {
  event: CctHookEvent;
  piSource: string | null; // verified Pi event name, or null when none
  support: SupportLevel;
  note: string;
}

/**
 * Pi->CCT mapping matrix (FR-010). The boundary is the T5.1 source-read result:
 * only session_start and tool_call are verifiable Pi events, so only
 * SessionStart and PreToolUse are `supported`. Rows may only flip to
 * supported/degraded if a future Pi build is confirmed to emit the event.
 */
export const HOOK_MAPPINGS: HookMapping[] = [
  {
    event: "SessionStart",
    piSource: "session_start",
    support: "supported",
    note: "1:1 with Pi session_start",
  },
  {
    event: "PreToolUse",
    piSource: "tool_call",
    support: "supported",
    note: "Pi tool_call fires pre-execution and can veto — exact PreToolUse semantics",
  },
  {
    event: "Notification",
    piSource: null,
    support: "degraded",
    note: "ctx.ui.notify is outbound-only; no inbound notification event to hook",
  },
  {
    event: "PostToolUse",
    piSource: null,
    support: "unsupported",
    note: "no observable Pi post-tool/result event",
  },
  {
    event: "Stop",
    piSource: null,
    support: "unsupported",
    note: "no observable Pi turn-end event",
  },
  {
    event: "PreCompact",
    piSource: null,
    support: "unsupported",
    note: "no observable Pi compaction event",
  },
  {
    event: "PostCompact",
    piSource: null,
    support: "unsupported",
    note: "no observable Pi compaction event",
  },
];

const SUPPORT_BY_EVENT: Record<string, SupportLevel> = HOOK_MAPPINGS.reduce(
  (acc, m) => {
    acc[m.event] = m.support;
    return acc;
  },
  {} as Record<string, SupportLevel>,
);

export function supportOf(event: CctHookEvent): SupportLevel {
  return SUPPORT_BY_EVENT[event] ?? "unsupported";
}

/** Claude Code tool-name + matcher for a Pi tool name (write/exec veto set). */
const TOOL_MATCHER: Record<string, string> = {
  edit: "Edit|Write",
  write: "Edit|Write",
  bash: "Bash",
};

const CC_TOOL_NAME: Record<string, string> = {
  edit: "Edit",
  write: "Write",
  bash: "Bash",
};

/** Translate Pi `session_start` to the neutral SessionStart event. */
export function translateSessionStart(
  cwd: string,
  session: SessionInfo,
): CctLifecycleEvent {
  return {
    event: "SessionStart",
    phase: "session",
    cwd,
    session,
    origin: "pi",
    support: supportOf("SessionStart"),
  };
}

/** Translate Pi `tool_call` to the neutral PreToolUse event. */
export function translateToolCall(
  toolName: string,
  input: Record<string, unknown>,
  cwd: string,
  session: SessionInfo,
): CctLifecycleEvent {
  const tool = String(toolName ?? "").toLowerCase();
  return {
    event: "PreToolUse",
    phase: "pre",
    tool,
    matcher: TOOL_MATCHER[tool],
    input,
    cwd,
    session,
    origin: "pi",
    support: supportOf("PreToolUse"),
  };
}

/**
 * Serialize a lifecycle event to the Claude-Code-shaped stdin JSON the existing
 * `.sh` hooks read (`.tool_name`, `.tool_input.file_path`, `.tool_input.command`,
 * `.hook_event_name`, `.cwd`). Pi input keys (path/file_path/filePath, cmd) are
 * normalized to the Claude Code field names so the scripts run unmodified.
 */
export function toClaudeStdin(ev: CctLifecycleEvent): string {
  const input = ev.input ?? {};
  const filePath = input.file_path ?? input.path ?? input.filePath;
  const command = input.command ?? input.cmd;
  const toolInput: Record<string, unknown> = {};
  if (filePath != null) toolInput.file_path = filePath;
  if (command != null) toolInput.command = command;
  const payload: Record<string, unknown> = {
    hook_event_name: ev.event,
    cwd: ev.cwd,
    tool_input: toolInput,
  };
  if (ev.tool) payload.tool_name = CC_TOOL_NAME[ev.tool] ?? ev.tool;
  return JSON.stringify(payload);
}

/** Human-readable mapping lines for doctor / `/cct:hooks` (FR-010 reporting). */
export function hookMappingReport(): string[] {
  return HOOK_MAPPINGS.map(
    (m) =>
      `  ${m.event}: ${m.support}` +
      (m.piSource ? ` (<- ${m.piSource})` : "") +
      ` — ${m.note}`,
  );
}
