/**
 * Security audit log (spec C-9 / NFR-015; authored).
 *
 * Appends JSONL records for security-relevant decisions: decision, rule,
 * origin, actor, timestamp, runtime mode, override. Secrets never enter
 * records (values are rule names + paths/commands, never file contents
 * or credentials). Location: <CCT_HOME>/pi/audit.log (user scope).
 */

import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

export interface AuditRecord {
  ts: string;
  mode: string; // tui | print | json | rpc | unknown
  actor: string; // e.g. "tool_call:bash"
  decision: string; // deny | ask->deny | ask->fail | relaxed-by-override | ...
  rule: string | null;
  subject: string; // path or normalized command (truncated)
  origin: string; // permissions | protected-path | sdd-gate | security-floor | trust
}

/** Modes the launcher may report via CCT_PI_MODE. */
export const PI_MODES = ["tui", "print", "json", "rpc"] as const;

/**
 * Resolve the audit mode label (T5.4). CCT_PI_MODE — set by the launcher from
 * the Pi invocation flags — is authoritative. When absent/invalid (e.g. the
 * runtime is run without the launcher), fall back to the prior two-value label.
 * Reporting only: never affects an allow/deny decision.
 */
export function resolveAuditMode(interactive: boolean): string {
  const m = process.env.CCT_PI_MODE;
  if (m && (PI_MODES as readonly string[]).includes(m)) return m;
  return interactive ? "tui" : "headless";
}

export function auditLogPath(): string {
  const home = process.env.CCT_HOME ?? path.join(os.homedir(), ".code-copilot-team");
  return path.join(home, "pi", "audit.log");
}

export function audit(record: Omit<AuditRecord, "ts">): void {
  try {
    const file = auditLogPath();
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const full: AuditRecord = {
      ts: new Date().toISOString(),
      ...record,
      subject: record.subject.slice(0, 400),
    };
    fs.appendFileSync(file, JSON.stringify(full) + "\n");
  } catch {
    /* auditing must never crash enforcement; doctor reports write failures */
  }
}
