import { test, expect } from '@playwright/test';

async function authAndMock(page: import('@playwright/test').Page) {
  await page.route('**/api/**', async (route) => {
    const url = route.request().url();
    if (url.includes('/api/dating/stats')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          today: { swipes: 3, messages: 12 },
          apps: [
            {
              name: 'Hinge',
              package: 'co.hinge.app',
              today: { swipes: 0, likes: 0, openers: 5, replies: 0, total_messages: 5 },
              targets: { opener_target: 75, opener_progress: 5 },
              total: { swipes: 0, openers: 5, replies: 0, messages: 5, matches: 0 },
              inbox: { unread: 0, new_matches: 0 },
              last_active: null,
            },
            {
              name: 'Hily',
              package: 'com.hily.app',
              today: { swipes: 3, likes: 3, openers: 2, replies: 0, total_messages: 2 },
              targets: { opener_target: 75, opener_progress: 2 },
              total: { swipes: 3, openers: 2, replies: 0, messages: 2, matches: 0 },
              inbox: { unread: 0, new_matches: 0 },
              last_active: null,
            },
          ],
        }),
      });
      return;
    }
    if (url.includes('/api/dating/config')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          apps: [],
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
        body: JSON.stringify({ running: false, paused: false, current_app: null }),
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
    if (url.includes('/api/usage/tokens')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          timezone: 'Europe/London',
          days: 30,
          from: '2026-10-29',
          to: '2026-11-27',
          totals: {
            prompt_tokens: 100,
            completion_tokens: 40,
            total_tokens: 140,
            requests: 7,
          },
          by_provider: {
            gemini: {
              prompt_tokens: 100,
              completion_tokens: 40,
              total_tokens: 140,
              requests: 7,
            },
          },
          daily: [
            {
              date: '2026-11-27',
              prompt_tokens: 100,
              completion_tokens: 40,
              total_tokens: 140,
              requests: 7,
            },
          ],
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
  await page.addInitScript(() => {
    localStorage.setItem('mobilerun_auth_token', 'visual-preview-token');
    localStorage.setItem('mobilerun_user_email', 'mac@macai.local');
    localStorage.setItem('mobilerun_backend_url', 'http://127.0.0.1:9');
  });
}

test.describe('portal batch', () => {
  test('home has tiles, no chrome; Dating Working rows collapsed with today', async ({
    page,
  }) => {
    await authAndMock(page);
    await page.goto('/');
    await expect(page.getByTestId('home-nav-tiles')).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole('link', { name: /Dating/i })).toBeVisible();
    await expect(page.getByTestId('desktop-sidebar')).toHaveCount(0);
    await expect(page.getByTestId('mobile-bottom-nav')).toHaveCount(0);
    await expect(page.getByText('All Apps')).toHaveCount(0);

    await page.goto('/dating');
    await expect(page.getByRole('heading', { name: /^Dating$/i })).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByText('Today · All Apps')).toHaveCount(0);
    await expect(page.getByTestId('dating-apps-working')).toBeVisible();
    const hingeToggle = page.getByTestId('dating-working-toggle-co.hinge.app');
    await expect(hingeToggle).toBeVisible();
    await expect(hingeToggle).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByTestId('dating-today-co.hinge.app')).toContainText(
      '5 messages'
    );
    await hingeToggle.click();
    await expect(hingeToggle).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByTestId('dating-today-detail-co.hinge.app')).toBeVisible();
  });

  test('Usage shows token totals, not history', async ({ page }) => {
    await authAndMock(page);
    await page.goto('/usage');
    await expect(page.getByTestId('usage-page')).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole('heading', { name: /^Usage$/i })).toBeVisible();
    await expect(page.getByText(/AI API tokens/i)).toBeVisible();
    await expect(page.getByText('140', { exact: true }).first()).toBeVisible();
    await expect(page.getByTestId('usage-daily')).toBeVisible();
    await expect(page.getByText('Task History')).toHaveCount(0);
  });

  test('Settings is one merged page', async ({ page }) => {
    await authAndMock(page);
    await page.goto('/settings');
    await expect(page.getByTestId('settings-page')).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('settings-workspace')).toBeVisible();
    await expect(page.getByTestId('settings-ai-tools')).toBeVisible();
  });
});
