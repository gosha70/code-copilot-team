// Deterministic WCAG 2.2 AA accessibility gate. Runs inside the Playwright
// page context via @axe-core/playwright. Cheap — runs before the vision critic.
import type { Page } from 'playwright';

export interface AuditResult {
  passed: boolean;
  criticalCount: number;
  totalCount: number;
  criticalIssues: string[];
}

// Zero *critical* violations required to pass. axe covers ~29.5% of WCAG
// success criteria — passing is a floor, not proof of accessibility.
export async function runAccessibilityAudit(page: Page): Promise<AuditResult> {
  // Imported dynamically so the harness still loads when the dep is absent.
  const { default: AxeBuilder } = await import('@axe-core/playwright');

  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag22aa'])
    .analyze();

  const critical = results.violations.filter(
    (v) => v.impact === 'critical' || v.impact === 'serious',
  );

  const criticalIssues = critical.map((v, i) => {
    const where = v.nodes.map((n) => n.target.join(' ')).slice(0, 3).join(' | ');
    return `[a11y #${i + 1}] ${v.id} (${v.impact}): ${v.help} — ${where} — ${v.helpUrl}`;
  });

  return {
    passed: critical.length === 0,
    criticalCount: critical.length,
    totalCount: results.violations.length,
    criticalIssues,
  };
}
