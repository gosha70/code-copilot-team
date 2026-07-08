// Deterministic anti-slop pre-filter. Catches the machine-detectable subset of
// the design-system anti-slop catalog by inspecting the rendered DOM, before the
// (expensive) vision critic. Advisory flags + hard fails.
import type { Page } from 'playwright';

export interface RubricResult {
  passed: boolean;
  flags: string[];
}

// Emoji used as standalone iconography (a reliable AI tell). Matches pictographic
// ranges; deliberately narrow to avoid flagging legitimate content emoji in prose.
const EMOJI_ICON = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u;

export async function runRubricChecks(page: Page): Promise<RubricResult> {
  const flags: string[] = await page.evaluate(
    ({ emojiSource }) => {
      const out: string[] = [];
      const emoji = new RegExp(emojiSource, 'u');
      const html = document.documentElement.outerHTML;
      const classAttrs = Array.from(document.querySelectorAll('[class]'))
        .map((el) => el.getAttribute('class') || '')
        .join(' ');

      // Untouched framework default tokens (the "shadcn default" look).
      if (/\b(bg|text|border|ring)-(indigo|violet|purple)-(500|600|700)\b/.test(classAttrs)) {
        out.push('DEFAULT-ACCENT: default indigo/violet/purple accent present — override the primary token.');
      }
      // Card default: heavy shadow + very round corners on many elements.
      const heavy = document.querySelectorAll('[class*="shadow-xl"],[class*="shadow-2xl"]').length;
      const round = document.querySelectorAll('[class*="rounded-3xl"]').length;
      if (heavy > 0 && round > 0) {
        out.push(`CARD-DEFAULT: shadow-xl + rounded-3xl present (${heavy}/${round}) — pick one card vocabulary, not both.`);
      }
      // Colored left-border strip — the single most reliable AI tell.
      if (/\bborder-l-(4|8)\b/.test(classAttrs)) {
        out.push('LEFT-STRIP: thick colored left-border strip present — banned.');
      }
      // Emoji-as-icon inside interactive controls or headings.
      const iconHosts = Array.from(document.querySelectorAll('button, a, h1, h2, h3, [role="button"]'));
      if (iconHosts.some((el) => emoji.test(el.textContent || ''))) {
        out.push('EMOJI-ICON: emoji used as iconography in a control/heading — use a real icon set.');
      }
      // No landmarks — <div onClick> soup.
      if (!document.querySelector('main') || document.querySelectorAll('nav, main, header, aside').length === 0) {
        out.push('NO-LANDMARKS: missing semantic landmarks (main/nav/header/aside).');
      }
      // Focus styling entirely absent.
      if (!/focus-visible:|:focus|focus:/.test(html)) {
        out.push('NO-FOCUS: no visible focus styling detected anywhere.');
      }
      return out;
    },
    { emojiSource: EMOJI_ICON.source },
  );

  // NO-LANDMARKS and EMOJI-ICON are hard fails; the rest are advisory to the critic.
  const hardFail = flags.some((f) => f.startsWith('NO-LANDMARKS') || f.startsWith('EMOJI-ICON'));
  return { passed: !hardFail, flags };
}
