/**
 * Mobile viewport: same-phone Connect this phone CTA, visible QR, pasteable code.
 */
import { test, expect } from '@playwright/test';

const PROD_API =
  process.env.PROD_API_URL ||
  'https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com';

test.describe('Devices same-phone pairing (mobile)', () => {
  test.beforeEach(({ }, testInfo) => {
    test.skip(testInfo.project.name !== 'mobile', 'Pixel viewport project only');
  });

  test('shows Connect this phone, QR, and copyable code', async ({ page }) => {
    const fakeToken = 'AB3K7Q2M';
    await page.route('**/api/auth/pair/create', async (route) => {
      const pairing_url = `mobilerun://pair?c=${fakeToken}`;
      const https_link = `https://macsmobilerun.netlify.app/p/${fakeToken}`;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          token: fakeToken,
          code: fakeToken,
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
          body: '[]',
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

    await page.goto('/devices');
    await expect(page.getByRole('heading', { name: 'Devices' })).toBeVisible({
      timeout: 20000,
    });

    // Generate code first (no auto-create)
    await page.getByTestId('generate-pairing-code-primary').click();

    const connectBtn = page.getByTestId('connect-this-phone');
    await expect(connectBtn).toBeVisible();
    await expect(connectBtn).toBeEnabled();

    const qr = page.getByTestId('pair-qr');
    await expect(qr).toBeVisible();
    const box = await qr.boundingBox();
    expect(box).toBeTruthy();
    expect(box!.width).toBeGreaterThan(100);
    expect(box!.height).toBeGreaterThan(100);

    await expect(page.getByTestId('pairing-code')).toHaveText(fakeToken);
    await expect(page.getByTestId('download-app-first')).toBeVisible();
    await expect(page.getByTestId('https-pair-fallback')).toBeVisible();
    await expect(page.getByTestId('pairing-short-link')).toContainText('/p/');

    await connectBtn.click();
    await expect(page.getByTestId('connect-hint')).toBeVisible({ timeout: 5000 });
  });
});
