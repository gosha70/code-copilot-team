// Artifact composition for the visual gate (#239, increment C3 of #190 §6).
//
// The driver runs this harness and READS the artifact — an agent's or a
// model's self-report is not evidence. Everything that decides what the
// artifact SAYS lives here, in pure functions, for two reasons:
//
//   1. Every write path must produce the same shape. Thirteen call sites
//      each hand-building an object is how one of them ends up reporting a
//      pass it did not earn (which is exactly the bug this increment
//      closes).
//   2. The browser-dependent paths cannot run without Playwright, so the
//      only way to assert what they write is to make the composition
//      testable on its own.
//
// The gate's rules, enforced structurally rather than by convention:
//   - `passed` is COMPUTED from the criterion verdicts, never taken from a
//     caller or from the critic.
//   - criterion IDENTITY (fr, statement_sha, criterion) is echoed from the
//     driver's frozen request by THIS code. A critic supplies a verdict and
//     evidence and nothing else; identity it invented would be unverifiable.
//   - `skip` is legal only when the run is degraded; `unreached` is legal in
//     any mode, is always red, and is never waivable.

import * as fs from 'node:fs';

export type Verdict = 'pass' | 'fail' | 'skip' | 'unreached';
export type Mode = 'full' | 'degraded';

/** One criterion as the DRIVER froze it. The harness never invents these. */
export interface FrozenCriterion {
  fr: string;
  statement_sha: string;
  criterion: string;
}

/** The driver's request document, handed over as CCT_VISUAL_REQUEST. */
export interface VisualRequest {
  criteria: FrozenCriterion[];
  url?: string;
  designMdPath?: string;
}

export interface CriterionResult extends FrozenCriterion {
  verdict: Verdict;
  evidence: string;
}

export interface Feedback {
  passed: boolean;
  mode: Mode;
  skipped: string[];
  source: string;
  critiqueSummary: string;
  actionableFixes: string[];
  criteria: CriterionResult[];
}

/**
 * Read the driver's request. Absent (manual/standalone use) → null, and the
 * harness still writes a well-formed artifact with no criteria. A present
 * but unreadable/malformed request is an ERROR, not a silent fallback: the
 * driver believes it asked a question, and answering a different one would
 * be the same class of lie this increment exists to stop.
 */
export function loadRequest(path?: string): VisualRequest | null {
  if (!path) return null;
  const raw = fs.readFileSync(path, 'utf-8');
  const req = JSON.parse(raw) as VisualRequest;
  if (!Array.isArray(req?.criteria) || req.criteria.length === 0) {
    throw new Error(`visual request ${path} carries no criteria`);
  }
  for (const c of req.criteria) {
    if (
      !c ||
      typeof c.fr !== 'string' ||
      typeof c.statement_sha !== 'string' ||
      typeof c.criterion !== 'string'
    ) {
      throw new Error(`visual request ${path} has a malformed criterion entry`);
    }
  }
  return req;
}

/**
 * Answer every frozen criterion the same way — the shape a run takes when it
 * ended before the critic could judge them individually (degraded, or one of
 * the fail-fast aborts). Identity comes from the request; the caller supplies
 * only the verdict and the reason.
 */
export function uniformCriteria(
  req: VisualRequest | null,
  verdict: Verdict,
  evidence: string,
): CriterionResult[] {
  if (!req) return [];
  return req.criteria.map((c) => ({ ...c, verdict, evidence }));
}

/**
 * Adopt a critic's per-criterion answers POSITIONALLY, keeping the driver's
 * identities. The critic is asked to return one entry per criterion in the
 * order given; anything it says about `fr` or `statement_sha` is discarded,
 * because a critic that could name identities could also invent them.
 * Returns null when the answer does not line up — the caller then fails the
 * run rather than guessing.
 */
export function adoptCriticVerdicts(
  req: VisualRequest | null,
  answers: unknown,
): CriterionResult[] | null {
  if (!req) return null;
  if (!Array.isArray(answers) || answers.length !== req.criteria.length)
    return null;
  const out: CriterionResult[] = [];
  for (let i = 0; i < req.criteria.length; i++) {
    const a = answers[i] as { verdict?: unknown; evidence?: unknown };
    // A critic may only PASS or FAIL: `skip` and `unreached` describe what
    // the harness did or did not run, which the critic cannot know.
    if (!a || (a.verdict !== 'pass' && a.verdict !== 'fail')) return null;
    const evidence =
      typeof a.evidence === 'string' && a.evidence.length > 0
        ? a.evidence
        : '(critic gave no evidence)';
    out.push({ ...req.criteria[i], verdict: a.verdict, evidence });
  }
  return out;
}

/**
 * Compose the artifact. `passed` is derived from the criteria whenever there
 * are any, so no call site can report a pass beside a skipped or unreached
 * criterion; with no request (standalone use) it falls back to the caller's
 * own claim.
 */
export function composeFeedback(input: {
  passed: boolean;
  mode: Mode;
  skipped?: string[];
  source: string;
  critiqueSummary: string;
  actionableFixes?: string[];
  criteria?: CriterionResult[];
}): Feedback {
  const criteria = input.criteria ?? [];
  const skipped = input.skipped ?? [];
  if (input.mode === 'full' && skipped.length > 0) {
    throw new Error('mode "full" cannot declare skipped checks — say degraded');
  }
  if (input.mode === 'degraded' && skipped.length === 0) {
    throw new Error('mode "degraded" must name what was skipped');
  }
  if (input.mode === 'full' && criteria.some((c) => c.verdict === 'skip')) {
    throw new Error('a "skip" verdict is only legal when the run is degraded');
  }
  return {
    passed:
      criteria.length > 0
        ? criteria.every((c) => c.verdict === 'pass')
        : input.passed,
    mode: input.mode,
    skipped,
    source: input.source,
    critiqueSummary: input.critiqueSummary,
    actionableFixes: input.actionableFixes ?? [],
    criteria,
  };
}
