// UI-Enhancement Harness — orchestrator.
//
// Deterministic parts (identical for every copilot): boot check, screenshot per
// breakpoint, axe-core a11y gate, anti-slop rubric. Pluggable CRITIC:
//   --critic=agent  (default) → emit screenshots + request; the driving agent
//                                (e.g. Claude Code visual-reviewer) reads the PNGs
//                                and decides. Runner exits 0 after emitting.
//   --critic=vision           → call a vision LLM over HTTPS (no SDK), parse a
//                                JSON verdict, gate via exit code.
//
// Config via env: DEV_URL, ROUTES (csv), BREAKPOINTS (csv), DESIGN_MD, OUT_DIR,
// CRITIC, VISION_MODEL, ANTHROPIC_API_KEY (or VISION_API_KEY + VISION_API_URL).
import type { Browser } from 'playwright';
import { runAccessibilityAudit } from './audit.js';
import { runRubricChecks } from './rubric.js';
import {
  loadRequest, uniformCriteria, adoptCriticVerdicts, composeFeedback,
  type VisualRequest, type Mode, type CriterionResult, type Feedback,
} from './feedback.js';
import * as fs from 'node:fs';
import * as path from 'node:path';

// #239 C3: when the DRIVER runs this harness it hands over a frozen
// request (criteria + browser base + design path). Its presence is what
// makes this a gate rather than a developer convenience — every artifact
// then answers those criteria, and identity is echoed from here, never
// from a critic. Read FIRST, because the driver's values OUTRANK the
// ambient environment below.
const VISUAL_REQUEST: VisualRequest | null = loadRequest(process.env.CCT_VISUAL_REQUEST);

// The browser base and the design bar are DRIVER-OWNED under a request:
// the frozen url is validated same-origin with the app the driver
// launched, and an ambient DEV_URL winning would point the harness at a
// different instance while every path in the report still looked right
// (the exact substitution FR-12 exists to prevent). Env remains the
// source only for standalone/developer use.
const DEV_URL = VISUAL_REQUEST?.url || process.env.DEV_URL || 'http://localhost:3000';
const ROUTES = (process.env.ROUTES || '/').split(',').map((r) => r.trim()).filter(Boolean);
const BREAKPOINTS = (process.env.BREAKPOINTS || '375,768,1440')
  .split(',').map((n) => parseInt(n.trim(), 10)).filter((n) => n > 0);
const OUT_DIR = path.resolve(process.env.OUT_DIR || 'tmp/ui-review');
const DESIGN_MD = path.resolve(VISUAL_REQUEST?.designMdPath || process.env.DESIGN_MD || 'DESIGN.md');
const CRITIC = (process.env.CRITIC || 'agent').toLowerCase();
const FEEDBACK = path.join(OUT_DIR, 'critique-feedback.json');
const REQUEST = path.join(OUT_DIR, 'critique-request.json');

// `full` only once a real browser is driving. Everything before that
// point could still degrade, so the mode is decided at each write.
function emit(
  fb: Parameters<typeof composeFeedback>[0],
): Feedback {
  const out = composeFeedback(fb);
  fs.mkdirSync(OUT_DIR, { recursive: true });
  fs.writeFileSync(FEEDBACK, JSON.stringify(out, null, 2));
  return out;
}

function writeFeedback(fb: Parameters<typeof composeFeedback>[0]): void {
  emit(fb);
}

// Write an artifact the composer already produced (the vision tail
// composes once, then decides). Re-composing it would be harmless but
// would run the invariant checks against their own output.
function writeComposed(out: Feedback): void {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  fs.writeFileSync(FEEDBACK, JSON.stringify(out, null, 2));
}

function fail(fb: Parameters<typeof composeFeedback>[0]): never {
  const out = emit(fb);
  console.error(`❌ ${out.source}: ${out.critiqueSummary}`);
  out.actionableFixes.forEach((f) => console.error(`   → ${f}`));
  process.exit(1);
}

// The three fail-fast aborts below end the run BEFORE the critic judges
// anything, in a run that legitimately launched a browser. `skip` is
// illegal in full mode and pass/fail would both claim an evaluation that
// never happened, so every frozen criterion is answered `unreached`:
// always red, never waivable by skip_is_failure.
function unreached(reason: string): CriterionResult[] {
  return uniformCriteria(VISUAL_REQUEST, 'unreached', reason);
}

// Never auto-install. Dynamic import so a missing `playwright` *package* (not
// just missing browsers) degrades instead of crashing the module at load.
async function launchBrowser(): Promise<Browser | null> {
  try {
    const { chromium } = await import('playwright');
    return await chromium.launch({ headless: true });
  } catch {
    return null;
  }
}

// Degraded-mode substitute for the visual pass: a plain HTTP GET. The DOM rubric
// and screenshot critique both need a browser page, so they cannot run here.
async function httpSmoke(url: string): Promise<boolean> {
  try {
    const res = await fetch(url, { method: 'GET' });
    return res.status < 400;
  } catch {
    return false;
  }
}

async function main(): Promise<void> {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  if (fs.existsSync(FEEDBACK)) fs.unlinkSync(FEEDBACK);

  // CRITIC=agent emits a request for a human/agent to judge and exits 0
  // without ever producing a verdict artifact. Under a DRIVER request
  // that is not a mode, it is a missing capability — refuse by name
  // rather than exiting successfully with nothing to read.
  if (VISUAL_REQUEST && CRITIC === 'agent') {
    // Refuse BY NAME and write NOTHING. This mode produces a request for
    // a human reviewer, never a verdict artifact — so the honest signal
    // to a driver-owned gate is the ABSENCE of evidence, not a red
    // artifact that would imply the harness evaluated something. The
    // stale-artifact unlink above still ran, so a previous run's PASS
    // cannot be mistaken for this run's result.
    console.error('❌ Harness: CRITIC=agent cannot satisfy a driver-owned visual gate.');
    console.error('   → CRITIC=agent emits a request for a human/agent reviewer and exits; it never writes a verdict.');
    console.error('   → Run the gate with CRITIC=vision, or point verification.visual.command at a critic that answers the frozen criteria.');
    process.exit(1);
  }

  if (!fs.existsSync(DESIGN_MD)) {
    fail({
      passed: false,
      mode: 'degraded',
      skipped: ['screenshots', 'dom-rubric', 'critic'],
      source: 'Config',
      critiqueSummary: `Missing steering file ${DESIGN_MD}. The harness needs the DESIGN.md bundle.`,
      actionableFixes: ['Scaffold the ui-harness bundle (DESIGN.md + design/tokens.json) and re-run.'],
      criteria: uniformCriteria(VISUAL_REQUEST, 'unreached', `no DESIGN.md at ${DESIGN_MD} — nothing to judge the UI against`),
    });
  }
  const designMd = fs.readFileSync(DESIGN_MD, 'utf-8');

  const browser = await launchBrowser();
  if (!browser) {
    // Playwright unavailable → never auto-install. Fall back to an HTTP-200
    // smoke; the DOM rubric and screenshot critique are SKIPPED (need a browser).
    // A dead dev server still FAILS — SKIP must not become a false pass.
    const smokeUrl = DEV_URL.replace(/\/$/, '') + (ROUTES[0] || '/');
    const ok = await httpSmoke(smokeUrl);
    if (!ok) {
      fail({
        passed: false,
        mode: 'degraded',
        skipped: ['screenshots', 'dom-rubric', 'critic'],
        source: 'Harness (degraded, no Playwright)',
        critiqueSummary: `Playwright/Chromium unavailable AND HTTP smoke failed for ${smokeUrl}.`,
        actionableFixes: [`Start the dev server at ${DEV_URL}. Run \`npm run harness:init\` to enable the full visual review.`],
        criteria: uniformCriteria(VISUAL_REQUEST, 'unreached', `no browser AND the HTTP smoke failed for ${smokeUrl}`),
      });
    }
    console.warn(`⚠️  Playwright unavailable — HTTP smoke PASS for ${smokeUrl}; visual review + DOM rubric SKIPPED. Run \`npm run harness:init\` to enable.`);
    // THE hole this increment closes: an HTTP-200 smoke used to write
    // `passed: true` here, so an unattended run could ship UI nobody
    // looked at. The criteria it never evaluated are now `skip`, and
    // `passed` is derived from them — it can no longer say true.
    writeFeedback({
      passed: false,
      mode: 'degraded',
      skipped: ['screenshots', 'dom-rubric', 'critic'],
      source: 'Harness (degraded, no Playwright)',
      critiqueSummary: `Playwright/Chromium unavailable — HTTP smoke PASS for ${smokeUrl}; visual critique + DOM rubric SKIPPED.`,
      actionableFixes: [`Run \`npm run harness:init\` to install Chromium and enable the full visual review.`],
      criteria: uniformCriteria(VISUAL_REQUEST, 'skip', 'no browser available — the visual pass never ran (HTTP smoke only)'),
    });
    process.exit(0);
  }

  const shots: { label: string; file: string }[] = [];
  const rubricFlags: string[] = [];
  try {
    const page = await browser.newPage();
    for (const route of ROUTES) {
      const url = DEV_URL.replace(/\/$/, '') + route;
      for (const width of BREAKPOINTS) {
        await page.setViewportSize({ width, height: Math.round(width * 1.6) });
        try {
          await page.goto(url, { waitUntil: 'networkidle', timeout: 20000 });
        } catch {
          fail({
            passed: false,
            mode: 'full',
            source: 'Harness',
            critiqueSummary: `Could not load ${url}. Is the dev server running at ${DEV_URL}?`,
            actionableFixes: [`Start the dev server, then re-run. Override the URL with DEV_URL=...`],
            criteria: unreached(`the run aborted before the critic: ${url} would not load`),
          });
        }
        await page.waitForTimeout(400);

        // a11y gate — fail-fast, cheapest signal.
        const a11y = await runAccessibilityAudit(page);
        if (!a11y.passed) {
          fail({
            passed: false,
            mode: 'full',
            source: 'axe-core WCAG 2.2 AA gate',
            critiqueSummary: `${a11y.criticalCount} critical/serious a11y violations on ${route} @ ${width}px.`,
            actionableFixes: a11y.criticalIssues,
            // The abort's OWN reason travels as each criterion's evidence,
            // not just as actionableFixes: the driver's park message reads
            // per-criterion evidence, so a generic "the gate failed" would
            // tell the operator nothing about what to fix.
            criteria: unreached(
              `the run aborted before the critic: the a11y gate failed on ${route} @ ${width}px — ${a11y.criticalIssues.join('; ')}`,
            ),
          });
        }

        // Anti-slop rubric pre-filter.
        const rubric = await runRubricChecks(page);
        rubricFlags.push(...rubric.flags.map((f) => `${route}@${width}: ${f}`));
        if (!rubric.passed) {
          fail({
            passed: false,
            mode: 'full',
            source: 'Anti-slop rubric',
            critiqueSummary: `Hard anti-slop violation on ${route} @ ${width}px.`,
            actionableFixes: rubric.flags,
            criteria: unreached(
              `the run aborted before the critic: the anti-slop rubric failed on ${route} @ ${width}px — ${rubric.flags.join('; ')}`,
            ),
          });
        }

        const label = `${route.replace(/\W+/g, '_') || 'root'}__${width}`;
        const file = path.join(OUT_DIR, `${label}.png`);
        await page.screenshot({ path: file, fullPage: true });
        shots.push({ label, file });
      }
    }
  } finally {
    await browser.close();
  }
  console.log(`📸 Captured ${shots.length} screenshot(s) across ${ROUTES.length} route(s) × ${BREAKPOINTS.length} breakpoint(s).`);
  if (rubricFlags.length) console.log(`⚠️  ${rubricFlags.length} advisory rubric flag(s) for the critic to weigh.`);

  if (CRITIC === 'agent') {
    // Developer-facing mode only — a driver-owned run already refused it
    // at entry. The driving agent is the critic: emit a request it can
    // act on and stop.
    fs.writeFileSync(REQUEST, JSON.stringify({ designMdPath: DESIGN_MD, screenshots: shots, advisoryFlags: rubricFlags }, null, 2));
    console.log(`✅ Gates passed. Screenshots + request written to ${OUT_DIR}. Agent critic must now read the PNGs and score against DESIGN.md.`);
    process.exit(0);
  }

  // Vision critic (tool-agnostic path).
  await visionCritique(designMd, shots, rubricFlags);
}

async function visionCritique(designMd: string, shots: { label: string; file: string }[], advisory: string[]): Promise<void> {
  const apiKey = process.env.ANTHROPIC_API_KEY || process.env.VISION_API_KEY;
  const apiUrl = process.env.VISION_API_URL || 'https://api.anthropic.com/v1/messages';
  const model = process.env.VISION_MODEL || 'claude-sonnet-5';
  if (!apiKey) {
    console.warn('⚠️  CRITIC=vision but no API key (ANTHROPIC_API_KEY/VISION_API_KEY) — SKIP vision critique.');
    // Second silent-pass hole: this used to report `passed: true` for a
    // critique that never ran. Screenshots and the rubric DID run, so
    // only the critic is skipped.
    writeFeedback({
      passed: false,
      mode: 'degraded',
      skipped: ['critic'],
      source: 'Vision (skipped)',
      critiqueSummary: 'No API key — vision critique SKIPPED.',
      actionableFixes: ['Set ANTHROPIC_API_KEY (or VISION_API_KEY) so the critic can judge the screenshots.'],
      criteria: uniformCriteria(VISUAL_REQUEST, 'skip', 'no API key — the critic never judged this criterion'),
    });
    process.exit(0);
  }

  const images = shots.slice(0, 6).map((s) => ({
    type: 'image',
    source: { type: 'base64', media_type: 'image/png', data: fs.readFileSync(s.file).toString('base64') },
  }));
  const criteriaBlock = VISUAL_REQUEST
    ? `\n\n=== CRITERIA (answer EVERY one, in this exact order) ===\n${VISUAL_REQUEST.criteria
        .map((c, i) => `${i + 1}. ${c.criterion}`)
        .join('\n')}\n=== END CRITERIA ===\n`
    : '';
  const prompt = `You are an elite, hyper-critical frontend design auditor. Score these screenshots of a running UI STRICTLY against the project's committed design steering below. Look for "AI slop" tells (default accent, centered-card monotony, generic hero + 3 feature cards, emoji icons, no hierarchy, missing empty/loading states) and violations of the stated tokens, layout grammar, and Do/Don'ts.\n\n=== DESIGN.md ===\n${designMd}\n=== END ===\n\nAdvisory rubric flags from the deterministic pre-filter: ${advisory.length ? advisory.join('; ') : 'none'}.\n\nRespond with ONLY raw JSON: {"passed": boolean, "critiqueSummary": string, "actionableFixes": string[]${
    VISUAL_REQUEST
      ? ', "criteria": [{"verdict": "pass"|"fail", "evidence": string}]'
      : ''
  }}. passed=false if it reads as generic/AI-generated or violates the steering.${
    VISUAL_REQUEST
      ? ` Return EXACTLY ${VISUAL_REQUEST.criteria.length} criteria entries, one per numbered criterion above, in the same order. Do NOT echo the criterion text or any identifier — only your verdict and the evidence you observed.`
      : ''
  }${criteriaBlock}`;

  let text: string;
  try {
    const res = await fetch(apiUrl, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' },
      body: JSON.stringify({ model, max_tokens: 1024, messages: [{ role: 'user', content: [{ type: 'text', text: prompt }, ...images] }] }),
    });
    if (!res.ok) throw new Error(`vision API ${res.status}: ${await res.text()}`);
    const data = (await res.json()) as { content: { text?: string }[] };
    text = (data.content.find((c) => c.text)?.text || '').trim();
  } catch (e) {
    console.warn(`⚠️  Vision critique failed (${(e as Error).message}) — SKIP.`);
    // THIRD silent-pass hole (found while rewiring, not in the original
    // catalogue): a failed vision CALL also reported `passed: true`.
    writeFeedback({
      passed: false,
      mode: 'degraded',
      skipped: ['critic'],
      source: 'Vision (error)',
      critiqueSummary: `Vision call failed: ${(e as Error).message}`,
      actionableFixes: ['Re-run once the vision endpoint is reachable.'],
      criteria: uniformCriteria(VISUAL_REQUEST, 'skip', `the critic call failed (${(e as Error).message}) — this criterion was never judged`),
    });
    process.exit(0);
  }

  let raw: { passed?: boolean; critiqueSummary?: string; actionableFixes?: string[]; criteria?: unknown };
  try {
    raw = JSON.parse(text.replace(/^```json\s*|```$/g, ''));
  } catch {
    fail({
      passed: false,
      mode: 'full',
      source: 'Vision LLM aesthetic gate',
      critiqueSummary: `Critic returned unparseable output: ${text.slice(0, 200)}`,
      actionableFixes: ['Re-run the critic.'],
      criteria: unreached('the critic returned unparseable output, so no criterion received a verdict'),
    });
  }

  // Identity is OURS. The critic answered positionally; adoptCriticVerdicts
  // pairs each answer with the criterion the DRIVER froze and discards
  // anything the model said about fr/statement_sha. A critic that could
  // name identities could also invent them.
  let criteria: CriterionResult[] = [];
  if (VISUAL_REQUEST) {
    const adopted = adoptCriticVerdicts(VISUAL_REQUEST, raw.criteria);
    if (!adopted) {
      fail({
        passed: false,
        mode: 'full',
        source: 'Vision LLM aesthetic gate',
        critiqueSummary: `Critic did not answer all ${VISUAL_REQUEST.criteria.length} criteria with pass|fail verdicts.`,
        actionableFixes: ['Re-run the critic; every frozen criterion needs its own verdict and evidence.'],
        criteria: unreached('the critic\'s answer did not line up with the frozen criteria'),
      });
    }
    criteria = adopted;
  }

  const summary = typeof raw.critiqueSummary === 'string' ? raw.critiqueSummary : '';
  const fixes = Array.isArray(raw.actionableFixes) ? raw.actionableFixes.map(String) : [];
  // `passed` is derived from the criteria by composeFeedback whenever a
  // request is present, so the critic's own boolean cannot overrule its
  // per-criterion answers.
  const out = composeFeedback({
    passed: raw.passed === true,
    mode: 'full',
    source: 'Vision LLM aesthetic gate',
    critiqueSummary: summary,
    actionableFixes: fixes,
    criteria,
  });
  if (!out.passed) {
    writeComposed(out);
    console.error(`❌ ${out.source}: ${out.critiqueSummary}`);
    out.actionableFixes.forEach((f) => console.error(`   → ${f}`));
    process.exit(1);
  }
  writeComposed(out);
  console.log('🎉 Visual review passed all gates. UI meets the committed design bar.');
  process.exit(0);
}

main().catch((e) => {
  console.error('Harness crashed:', e);
  process.exit(1);
});
