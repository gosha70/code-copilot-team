/**
 * Concurrency + recursion caps for the subagent child-session runner (T7.2,
 * FR-011). Pi provides no fork/parallel primitive and no recursion detection,
 * so these bounds are CCT-first-party. They read the SAME config leaves the
 * autonomous profile already defines (`autonomy.max_concurrency`,
 * `autonomy.max_recursion`) — this module only resolves + enforces them.
 *
 * Pure + independently testable: a semaphore that bounds concurrent spawns, and
 * a depth guard that refuses recursion past the limit. No spawn here; the runner
 * (child-session.ts) consults these.
 */

/** Defaults matching the `autonomous` profile (config/profiles.ts). */
export const DEFAULT_MAX_CONCURRENCY = 4;
export const DEFAULT_MAX_RECURSION = 2;

export interface AgentCaps {
  maxConcurrency: number;
  maxRecursion: number;
}

/** Env var carrying the current subagent nesting depth into a child process. */
export const AGENT_DEPTH_ENV = "CCT_AGENT_DEPTH";

interface AutonomyConfigShape {
  autonomy?: {
    max_concurrency?: unknown;
    max_recursion?: unknown;
  };
}

function positiveInt(v: unknown, fallback: number): number {
  return typeof v === "number" && Number.isInteger(v) && v > 0 ? v : fallback;
}

/** Resolve caps from a loaded config object, falling back to the defaults. */
export function resolveCaps(
  config: AutonomyConfigShape | undefined,
): AgentCaps {
  const a = config?.autonomy;
  return {
    maxConcurrency: positiveInt(a?.max_concurrency, DEFAULT_MAX_CONCURRENCY),
    maxRecursion: positiveInt(a?.max_recursion, DEFAULT_MAX_RECURSION),
  };
}

/**
 * A subagent at `depth` may spawn a child (depth+1) only while depth+1 does not
 * exceed `maxRecursion`. depth 0 is the root session; with maxRecursion 2 the
 * legal child depths are 1 and 2, and a depth-2 agent may not spawn further.
 */
export function recursionExceeded(
  depth: number,
  maxRecursion: number,
): boolean {
  return depth + 1 > maxRecursion;
}

/**
 * Minimal async counting semaphore. `acquire()` resolves with a release fn once
 * a slot is free; callers MUST release (use try/finally). Bounds how many child
 * sessions run at once — pi has no such primitive.
 */
export class Semaphore {
  private available: number;
  private readonly waiters: Array<() => void> = [];

  constructor(max: number) {
    this.available = Math.max(1, Math.floor(max));
  }

  async acquire(): Promise<() => void> {
    if (this.available > 0) {
      this.available -= 1;
      return this.makeRelease();
    }
    await new Promise<void>((resolve) => this.waiters.push(resolve));
    this.available -= 1;
    return this.makeRelease();
  }

  private makeRelease(): () => void {
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.available += 1;
      const next = this.waiters.shift();
      if (next) next();
    };
  }
}
