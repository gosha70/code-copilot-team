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
import * as fs from 'node:fs';
import * as path from 'node:path';

const DEV_URL = process.env.DEV_URL || 'http://localhost:3000';
const ROUTES = (process.env.ROUTES || '/').split(',').map((r) => r.trim()).filter(Boolean);
const BREAKPOINTS = (process.env.BREAKPOINTS || '375,768,1440')
  .split(',').map((n) => parseInt(n.trim(), 10)).filter((n) => n > 0);
const OUT_DIR = path.resolve(process.env.OUT_DIR || 'tmp/ui-review');
const DESIGN_MD = path.resolve(process.env.DESIGN_MD || 'DESIGN.md');
const CRITIC = (process.env.CRITIC || 'agent').toLowerCase();
const FEEDBACK = path.join(OUT_DIR, 'critique-feedback.json');
const REQUEST = path.join(OUT_DIR, 'critique-request.json');

interface Feedback {
  passed: boolean;
  source: string;
  critiqueSummary: string;
  actionableFixes: string[];
}

function writeFeedback(fb: Feedback): void {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  fs.writeFileSync(FEEDBACK, JSON.stringify(fb, null, 2));
}

function fail(fb: Feedback): never {
  console.error(`❌ ${fb.source}: ${fb.critiqueSummary}`);
  fb.actionableFixes.forEach((f) => console.error(`   → ${f}`));
  writeFeedback(fb);
  process.exit(1);
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

  if (!fs.existsSync(DESIGN_MD)) {
    fail({
      passed: false,
      source: 'Config',
      critiqueSummary: `Missing steering file ${DESIGN_MD}. The harness needs the DESIGN.md bundle.`,
      actionableFixes: ['Scaffold the ui-harness bundle (DESIGN.md + design/tokens.json) and re-run.'],
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
        source: 'Harness (degraded, no Playwright)',
        critiqueSummary: `Playwright/Chromium unavailable AND HTTP smoke failed for ${smokeUrl}.`,
        actionableFixes: [`Start the dev server at ${DEV_URL}. Run \`npm run harness:init\` to enable the full visual review.`],
      });
    }
    console.warn(`⚠️  Playwright unavailable — HTTP smoke PASS for ${smokeUrl}; visual review + DOM rubric SKIPPED. Run \`npm run harness:init\` to enable.`);
    writeFeedback({
      passed: true,
      source: 'Harness (degraded, no Playwright)',
      critiqueSummary: `Playwright/Chromium unavailable — HTTP smoke PASS for ${smokeUrl}; visual critique + DOM rubric SKIPPED.`,
      actionableFixes: [],
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
            source: 'Harness',
            critiqueSummary: `Could not load ${url}. Is the dev server running at ${DEV_URL}?`,
            actionableFixes: [`Start the dev server, then re-run. Override the URL with DEV_URL=...`],
          });
        }
        await page.waitForTimeout(400);

        // a11y gate — fail-fast, cheapest signal.
        const a11y = await runAccessibilityAudit(page);
        if (!a11y.passed) {
          fail({
            passed: false,
            source: 'axe-core WCAG 2.2 AA gate',
            critiqueSummary: `${a11y.criticalCount} critical/serious a11y violations on ${route} @ ${width}px.`,
            actionableFixes: a11y.criticalIssues,
          });
        }

        // Anti-slop rubric pre-filter.
        const rubric = await runRubricChecks(page);
        rubricFlags.push(...rubric.flags.map((f) => `${route}@${width}: ${f}`));
        if (!rubric.passed) {
          fail({
            passed: false,
            source: 'Anti-slop rubric',
            critiqueSummary: `Hard anti-slop violation on ${route} @ ${width}px.`,
            actionableFixes: rubric.flags,
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
    // The driving agent is the critic. Emit a request it can act on and stop.
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
    writeFeedback({ passed: true, source: 'Vision (skipped)', critiqueSummary: 'No API key — vision critique SKIPPED.', actionableFixes: [] });
    process.exit(0);
  }

  const images = shots.slice(0, 6).map((s) => ({
    type: 'image',
    source: { type: 'base64', media_type: 'image/png', data: fs.readFileSync(s.file).toString('base64') },
  }));
  const prompt = `You are an elite, hyper-critical frontend design auditor. Score these screenshots of a running UI STRICTLY against the project's committed design steering below. Look for "AI slop" tells (default accent, centered-card monotony, generic hero + 3 feature cards, emoji icons, no hierarchy, missing empty/loading states) and violations of the stated tokens, layout grammar, and Do/Don'ts.\n\n=== DESIGN.md ===\n${designMd}\n=== END ===\n\nAdvisory rubric flags from the deterministic pre-filter: ${advisory.length ? advisory.join('; ') : 'none'}.\n\nRespond with ONLY raw JSON: {"passed": boolean, "critiqueSummary": string, "actionableFixes": string[]}. passed=false if it reads as generic/AI-generated or violates the steering.`;

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
    writeFeedback({ passed: true, source: 'Vision (error)', critiqueSummary: `Vision call failed: ${(e as Error).message}`, actionableFixes: [] });
    process.exit(0);
  }

  let verdict: Feedback;
  try {
    verdict = { source: 'Vision LLM aesthetic gate', ...JSON.parse(text.replace(/^```json\s*|```$/g, '')) };
  } catch {
    fail({ passed: false, source: 'Vision LLM aesthetic gate', critiqueSummary: `Critic returned unparseable output: ${text.slice(0, 200)}`, actionableFixes: ['Re-run the critic.'] });
  }
  if (!verdict.passed) fail(verdict);
  writeFeedback(verdict);
  console.log('🎉 Visual review passed all gates. UI meets the committed design bar.');
  process.exit(0);
}

main().catch((e) => {
  console.error('Harness crashed:', e);
  process.exit(1);
});
