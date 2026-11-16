/**
 * Desktop + mobile: Generate pairing code CTA, countdown, copyable short code, Remove device affordance.
 */
import { test, expect } from '@playwright/test';

const PROD_API =
  process.env.PROD_API_URL ||
  'https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com';

async function stubDevicesApis(page: import('@playwright/test').Page, code: string) {
  const pairing_url = `mobilerun://pair?c=${code}`;
  const https_link = `https://macsmobilerun.netlify.app/p/${code}`;
  await page.route('**/api/auth/pair/create', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        token: code,
        code,
        pairing_url,
        https_link,
        short_link: https_link,
        qr_code:
          'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
        expires_in: 600,
        cloud_http: PROD_API,
        cloud_ws: 'wss://sv7144gijj.execute-api.eu-west-2.amazonaws.com/prod',
      }),
    });
  });
  await page.route('**/api/devices', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            device_id: 'device_real_keep',
            name: 'Mac Phone',
            connected: true,
            platform: 'android',
          },
        ]),
      });
      return;
    }
    if (route.request().method() === 'DELETE') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true, revoked: true }),
      });
      return;
    }
    await route.continue();
  });
  await page.route('**/api/releases/latest', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        apk_url:
          'https://github.com/MacAndersonUche/mobilerun/releases/download/apk-137/mobilerun.apk',
        qr_code:
          'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
      }),
    });
  });
  await page.addInitScript(() => {
    localStorage.setItem('mobilerun_auth_token', 'visual-preview-token');
    localStorage.setItem('mobilerun_user_email', 'mac@macai.local');
  });
}

for (const project of ['desktop', 'mobile'] as const) {
  test.describe(`Devices generate code (${project})`, () => {
    test.beforeEach(({ }, testInfo) => {
      test.skip(testInfo.project.name !== project, `${project} project only`);
    });

    test('Generate pairing code shows short code + Remove device', async ({ page }) => {
      const code = 'AB3K7Q2M';
      await stubDevicesApis(page, code);
      await page.goto('/devices');
      await expect(page.getByRole('heading', { name: 'Devices' })).toBeVisible({
        timeout: 20000,
      });

      await page.getByTestId('generate-pairing-code-primary').click();
      await expect(page.getByTestId('pairing-code')).toHaveText(code);
      await expect(page.getByTestId('pairing-countdown')).toBeVisible();
      await expect(page.getByTestId('pair-qr')).toBeVisible();
      await expect(page.getByTestId('generate-pairing-code')).toContainText(/Regenerate/i);

      await expect(page.getByTestId('remove-device')).toBeVisible();
      await page.getByTestId('remove-device').click();
    });
  });
}
