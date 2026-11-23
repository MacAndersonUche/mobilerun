import { test, expect } from '@playwright/test';
import path from 'path';
import fs from 'fs';

const outDir = path.join('..', 'docs', 'ui-screenshots');

test.beforeAll(() => {
  fs.mkdirSync(outDir, { recursive: true });
});

async function shot(page: import('@playwright/test').Page, name: string) {
  const project = test.info().project.name;
  const file = path.join(outDir, `${project}-${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
}

test('login screen', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /MacMobileRun/i })).toBeVisible();
  await shot(page, '01-login');
});

test('authenticated routes', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('mobilerun_auth_token', 'visual-preview-token');
    localStorage.setItem('mobilerun_user_email', 'mac@macai.local');
  });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /MacMobileRun/i })).toBeVisible({
    timeout: 15000,
  });
  await shot(page, '03-home');

  const routes = [
    ['/chat', '04-chat'],
    ['/devices', '05-devices'],
    ['/dating', '06-dating'],
    ['/social', '07-social'],
    ['/dating', '08-dating'],
    ['/live', '09-live'],
    ['/settings', '10-settings'],
    ['/account', '11-account'],
    ['/tasks', '12-tasks'],
    ['/history', '13-history'],
  ] as const;

  for (const [route, name] of routes) {
    await page.goto(route);
    await page.waitForTimeout(500);
    await shot(page, name);
  }

  await page.goto('/account');
  await expect(page.getByRole('heading', { name: 'Link a phone' })).toBeVisible();
  await shot(page, '14-account-link');

  await page.goto('/devices');
  await expect(page.getByRole('heading', { name: 'Install APK' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Connect phone' })).toBeVisible();
  await expect(page.getByText('Download-only', { exact: false })).toBeVisible();
  await shot(page, '15-devices-apk-qr');
});
