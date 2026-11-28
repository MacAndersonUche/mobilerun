import { test, expect } from '@playwright/test';

/**
 * Apps for Start shows only when Working has no enabled runnable apps
 * (first run / empty Working). Expanding lists every dating app with
 * Templates/AI controls — even when /api/dating/config fails.
 */
async function mockDatingApis(
  page: import('@playwright/test').Page,
  opts: { failConfig?: boolean; enabledWorking?: boolean } = {}
) {
  await page.route('**/api/**', async (route) => {
    const url = route.request().url();
    if (opts.failConfig && url.includes('/api/dating/')) {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'config unavailable' }),
      });
      return;
    }
    if (url.includes('/api/dating/config')) {
      const enabled = !!opts.enabledWorking;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          apps: [
            {
              name: 'Bumble',
              package_name: 'com.bumble.app',
              enabled,
              daily_swipe_cap: 50,
              opener_mode: 'templates',
            },
            {
              name: 'Hinge',
              package_name: 'co.hinge.app',
              enabled,
              daily_swipe_cap: 50,
              opener_mode: 'ai',
            },
          ],
          persona_prompt: '',
          opener_mode: 'templates',
          speed_preset: 'balanced',
          min_total_messages_per_day: 100,
          max_total_messages_per_day: 500,
          date_flow: {},
        }),
      });
      return;
    }
    if (url.includes('/api/dating/status')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          running: false,
          paused: false,
          current_app: null,
        }),
      });
      return;
    }
    if (url.includes('/api/dating/stats')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ apps: [], today: { swipes: 0, messages: 0 } }),
      });
      return;
    }
    if (url.includes('/api/dating/openers')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          library: { templates: [] },
          bucket_now: 'morning',
          bucket_counts: {},
        }),
      });
      return;
    }
    if (url.includes('/api/devices')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ok' }),
    });
  });
}

async function auth(page: import('@playwright/test').Page) {
  await page.addInitScript(() => {
    localStorage.setItem('mobilerun_auth_token', 'visual-preview-token');
    localStorage.setItem('mobilerun_user_email', 'mac@macai.local');
    localStorage.setItem('mobilerun_backend_url', 'http://127.0.0.1:9');
  });
}

test.describe('Apps for Start collapsible', () => {
  test('hidden when Working already has enabled apps', async ({ page }) => {
    await auth(page);
    await mockDatingApis(page, { enabledWorking: true });
    await page.goto('/dating');
    await expect(page.getByTestId('dating-status-refresh')).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByTestId('dating-apps-for-start')).toHaveCount(0);
  });

  test('collapsed on load; expand shows app rows + Templates/AI', async ({
    page,
  }) => {
    await auth(page);
    await mockDatingApis(page, { enabledWorking: false });
    await page.goto('/dating');

    const section = page.getByTestId('dating-apps-for-start');
    const toggle = page.getByTestId('dating-apps-for-start-toggle');
    await expect(toggle).toBeVisible({ timeout: 15000 });
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await expect(page.locator('#dating-apps-for-start-panel')).toHaveCount(0);

    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const panel = page.locator('#dating-apps-for-start-panel');
    await expect(panel).toBeVisible();

    const list = page.getByTestId('dating-apps-for-start-list');
    await expect(list).toBeVisible();
    await expect(
      page.getByTestId('dating-app-for-start-com.bumble.app')
    ).toBeVisible();
    await expect(
      page.getByTestId('dating-app-for-start-co.hinge.app')
    ).toBeVisible();
    await expect(
      page.getByTestId('dating-app-for-start-com.hily.app')
    ).toBeVisible();
    await expect(
      page.getByTestId('dating-app-opener-mode-com.bumble.app')
    ).toBeVisible();
    await expect(
      page
        .getByTestId('dating-app-opener-mode-com.bumble.app')
        .getByRole('button', { name: 'Templates' })
    ).toBeVisible();
    await expect(
      page
        .getByTestId('dating-app-opener-mode-com.bumble.app')
        .getByRole('button', { name: 'AI' })
    ).toBeVisible();
    await expect(
      list.locator('[data-testid^="dating-app-for-start-"]')
    ).toHaveCount(15);

    await expect(section.getByRole('button', { name: 'Save config' })).toBeVisible();
  });

  test('expand still shows app rows when dating config API fails', async ({
    page,
  }) => {
    await auth(page);
    await mockDatingApis(page, { failConfig: true });
    await page.goto('/dating');

    const toggle = page.getByTestId('dating-apps-for-start-toggle');
    await expect(toggle).toBeVisible({ timeout: 15000 });
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(
      page.getByTestId('dating-apps-for-start-list')
    ).toBeVisible();
    await expect(
      page.getByTestId('dating-app-for-start-com.bumble.app')
    ).toBeVisible();
    await expect(
      page
        .getByTestId('dating-app-opener-mode-co.hinge.app')
        .getByRole('button', { name: 'AI' })
    ).toBeVisible();
    await expect(
      page
        .locator('[data-testid="dating-apps-for-start-list"]')
        .locator('[data-testid^="dating-app-for-start-"]')
    ).toHaveCount(15);
  });
});
