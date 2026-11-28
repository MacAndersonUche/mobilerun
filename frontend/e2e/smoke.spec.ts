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
  // Home has nav tiles (no sidebar/bottom nav). Dating + Devices among them.
  const home = page.locator('[data-testid="home-page"]');
  await expect(home.getByTestId('home-nav-tiles')).toBeVisible();
  await expect(home.getByRole('link', { name: /Dating/i })).toHaveCount(1);
  await expect(home.getByRole('link', { name: /Devices/i })).toHaveCount(1);
  await expect(home.getByRole('link', { name: /Social/i })).toHaveCount(1);
  await expect(home.getByRole('link', { name: /Tasks/i })).toHaveCount(1);
  await expect(page.getByTestId('desktop-sidebar')).toHaveCount(0);
  await expect(page.getByTestId('mobile-bottom-nav')).toHaveCount(0);
  await expect(home.getByRole('link', { name: /^Manage$/i })).toHaveCount(0);
  await shot(page, '03-home');

  const routes = [
    ['/chat', '04-chat'],
    ['/devices', '05-devices'],
    ['/dating', '06-dating'],
    ['/social', '07-social'],
    ['/dating', '08-dating'],
    ['/settings', '09-settings'],
    ['/tasks', '11-tasks'],
    ['/history', '12-history'],
  ] as const;

  for (const [route, name] of routes) {
    await page.goto(route);
    await page.waitForTimeout(500);
    await shot(page, name);
  }

  await page.goto('/account');
  await expect(page).toHaveURL(/\/settings$/);
  const settings = page.getByTestId('settings-page');
  await expect(settings.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible();
  await expect(page.getByTestId('settings-account-card')).toBeVisible();
  await expect(page.getByTestId('settings-logout')).toBeVisible();
  await shot(page, '14-settings-account');

  await page.goto('/devices');
  await expect(page.getByRole('heading', { name: 'Install APK' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Connect phone' })).toBeVisible();
  await expect(page.getByText('Download-only', { exact: false })).toBeVisible();
  await shot(page, '15-devices-apk-qr');
});
