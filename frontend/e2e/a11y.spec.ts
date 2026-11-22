import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'fs';
import path from 'path';

const outDir = path.join('..', 'docs', 'ui-screenshots');
const reportDir = path.join('..', 'docs', 'a11y-reports');

test.beforeAll(() => {
  fs.mkdirSync(outDir, { recursive: true });
  fs.mkdirSync(reportDir, { recursive: true });
});

async function auth(page: import('@playwright/test').Page) {
  await page.addInitScript(() => {
    localStorage.setItem('mobilerun_auth_token', 'visual-preview-token');
    localStorage.setItem('mobilerun_user_email', 'mac@macai.local');
  });
}

const routes = [
  ['/', 'home'],
  ['/chat', 'chat'],
  ['/devices', 'devices'],
  ['/dating', 'dating'],
  ['/social', 'social'],
  ['/dating', 'dating'],
  ['/live', 'live'],
  ['/settings', 'settings'],
  ['/account', 'account'],
  ['/tasks', 'tasks'],
  ['/history', 'history'],
] as const;

test('login a11y', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /MacMobileRun|MobileRun/i })).toBeVisible();
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa'])
    .disableRules(['color-contrast']) // design tokens reviewed separately; muted UI chrome
    .analyze();
  fs.writeFileSync(
    path.join(reportDir, `${test.info().project.name}-login.json`),
    JSON.stringify(results, null, 2)
  );
  // Fail on serious/critical only (labels, names, structure)
  const serious = results.violations.filter((v) =>
    ['serious', 'critical'].includes(v.impact || '')
  );
  expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
});

test('authenticated pages a11y + shots', async ({ page }) => {
  await auth(page);
  const allSerious: unknown[] = [];
  for (const [route, name] of routes) {
    await page.goto(route);
    await page.waitForTimeout(400);
    await page.screenshot({
      path: path.join(outDir, `${test.info().project.name}-a11y-${name}.png`),
      fullPage: true,
    });
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .disableRules(['color-contrast'])
      .analyze();
    fs.writeFileSync(
      path.join(reportDir, `${test.info().project.name}-${name}.json`),
      JSON.stringify(
        {
          url: route,
          violations: results.violations.map((v) => ({
            id: v.id,
            impact: v.impact,
            description: v.description,
            nodes: v.nodes.length,
          })),
        },
        null,
        2
      )
    );
    for (const v of results.violations) {
      if (v.impact === 'serious' || v.impact === 'critical') {
        allSerious.push({ route, id: v.id, impact: v.impact, description: v.description });
      }
    }
  }
  expect(allSerious, JSON.stringify(allSerious, null, 2)).toEqual([]);
});
