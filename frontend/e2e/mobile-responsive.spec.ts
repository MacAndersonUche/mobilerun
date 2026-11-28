/**
 * Mac's request: portal must look good at 360–430px (S21+ 384×854, iPhone 390×844).
 * Asserts no horizontal scroll, bottom/hamburger nav, usable job controls.
 */
import { test, expect } from '@playwright/test';
import path from 'path';
import fs from 'fs';

const outDir = path.join('..', 'docs', 'ui-screenshots');

test.beforeAll(() => {
  fs.mkdirSync(outDir, { recursive: true });
});

async function auth(page: import('@playwright/test').Page) {
  await page.addInitScript(() => {
    localStorage.setItem('mobilerun_auth_token', 'visual-preview-token');
    localStorage.setItem('mobilerun_user_email', 'mac@macai.local');
  });
}

async function assertNoHorizontalScroll(page: import('@playwright/test').Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(
    scrollWidth,
    `horizontal overflow: scrollWidth=${scrollWidth} clientWidth=${clientWidth}`
  ).toBeLessThanOrEqual(clientWidth + 1);
}

async function shot(page: import('@playwright/test').Page, name: string) {
  const project = test.info().project.name;
  const file = path.join(outDir, `${project}-responsive-${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
}

test.describe('mobile responsive portal', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    // Desktop project still runs layout sanity; mobile/s21 are the focus.
    testInfo.annotations.push({
      type: 'viewport',
      description: JSON.stringify(page.viewportSize()),
    });
  });

  test('login has no horizontal scroll', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /MacMobileRun/i })).toBeVisible();
    await assertNoHorizontalScroll(page);
    await shot(page, '01-login');
  });

  test('authenticated shell: nav + pages fit phone width', async ({ page }) => {
    await auth(page);
    await page.goto('/dating');
    await expect(page.getByRole('heading', { name: /Dating/i })).toBeVisible({
      timeout: 15000,
    });
    await assertNoHorizontalScroll(page);

    const vp = page.viewportSize();
    const isNarrow = (vp?.width || 1440) <= 430;
    if (isNarrow) {
      await expect(page.getByTestId('mobile-bottom-nav')).toBeVisible();
      await expect(page.getByTestId('mobile-menu-button')).toBeVisible();
      // Job controls usable
      await expect(page.getByTestId('dating-start')).toBeVisible();
      const startBox = await page.getByTestId('dating-start').boundingBox();
      expect(startBox?.height || 0).toBeGreaterThanOrEqual(40);
      // Open hamburger
      await page.getByTestId('mobile-menu-button').click();
      const menu = page.getByRole('dialog', { name: /Menu/i });
      await expect(menu).toBeVisible();
      await shot(page, '02-dating-menu-open');
      await menu.getByRole('link', { name: 'Social', exact: true }).click();
      await expect(page).toHaveURL(/\/social/);
      await assertNoHorizontalScroll(page);
      await shot(page, '03-social');
    }

    const routes = [
      ['/dating', '04-dating'],
      ['/devices', '05-devices'],
      ['/history', '06-history'],
      ['/settings', '07-settings'],
      ['/', '08-home'],
    ] as const;
    for (const [route, name] of routes) {
      await page.goto(route);
      await page.waitForTimeout(350);
      await assertNoHorizontalScroll(page);
      await shot(page, name);
    }
  });
});
