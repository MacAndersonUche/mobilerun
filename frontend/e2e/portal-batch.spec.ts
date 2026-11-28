import { test, expect } from '@playwright/test';

async function authAndMock(page: import('@playwright/test').Page) {
  await page.route('**/api/**', async (route) => {
    const url = route.request().url();
    if (url.includes('/api/dating/stats')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          today: { swipes: 20, messages: 12 },
          apps: [
            {
              name: 'Bumble',
              package: 'com.bumble.app',
              today: { swipes: 9, likes: 9, openers: 4, replies: 0, total_messages: 4 },
              targets: { opener_target: 75, opener_progress: 4 },
              total: { swipes: 9, openers: 4, replies: 0, messages: 4, matches: 0 },
              inbox: { unread: 0, new_matches: 0 },
              last_active: null,
            },
            {
              name: 'Hinge',
              package: 'co.hinge.app',
              today: { swipes: 2, likes: 0, openers: 5, replies: 0, total_messages: 5 },
              targets: { opener_target: 75, opener_progress: 5 },
              total: { swipes: 2, openers: 5, replies: 0, messages: 5, matches: 0 },
              inbox: { unread: 0, new_matches: 0 },
              last_active: null,
            },
            {
              name: 'Yubo',
              package: 'co.yellw.yellowapp',
              today: { swipes: 1, likes: 0, openers: 8, replies: 0, total_messages: 8 },
              targets: { opener_target: 75, opener_progress: 8 },
              total: { swipes: 1, openers: 8, replies: 0, messages: 8, matches: 0 },
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
            {
              name: 'Facebook Dating',
              package: 'com.facebook.katana',
              today: { swipes: 6, likes: 0, openers: 11, replies: 0, total_messages: 11 },
              targets: { opener_target: 50, opener_progress: 11 },
              total: { swipes: 6, openers: 11, replies: 0, messages: 11, matches: 0 },
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
          apps: [
            {
              name: 'Bumble',
              package_name: 'com.bumble.app',
              enabled: true,
              daily_swipe_cap: 50,
            },
            {
              name: 'Hinge',
              package_name: 'co.hinge.app',
              enabled: true,
              daily_swipe_cap: 50,
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
  test('home tiles; Dating Working section + per-app today counters', async ({
    page,
  }) => {
    await authAndMock(page);
    await page.goto('/');
    const tiles = page.getByTestId('home-nav-tiles');
    await expect(tiles).toBeVisible({ timeout: 15000 });
    await expect(tiles.getByRole('link', { name: /Dating/i })).toBeVisible();
    await expect(tiles.getByRole('link', { name: /Social/i })).toBeVisible();
    await expect(tiles.getByRole('link', { name: /Tasks/i })).toBeVisible();
    await expect(tiles.getByRole('link', { name: /Devices/i })).toBeVisible();
    await expect(tiles.getByRole('link', { name: /^Settings$/i })).toHaveCount(0);
    await expect(page.getByRole('link', { name: /^Open settings$/i })).toBeVisible();
    await expect(page.getByTestId('desktop-sidebar')).toHaveCount(0);
    await expect(page.getByTestId('mobile-bottom-nav')).toHaveCount(0);
    await expect(page.getByText('All Apps')).toHaveCount(0);
    await expect(page.getByRole('link', { name: /^Usage$/i })).toHaveCount(0);

    await page.goto('/dating');
    await expect(page.getByRole('heading', { name: /^Dating$/i })).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByText('Today · All Apps')).toHaveCount(0);
    await expect(page.getByText(/Messages vs daily target/i)).toHaveCount(0);
    await expect(page.getByText(/Daily message limits/i)).toHaveCount(0);

    const workingToggle = page.getByTestId('dating-apps-working-toggle');
    await expect(workingToggle).toBeVisible();
    await expect(workingToggle).toHaveAttribute('aria-expanded', 'false');
    await expect(page.getByTestId('dating-today-co.hinge.app')).toHaveCount(0);
    // Header totals visible while collapsed (per-app rules: Bumble 9 + Hily 3
    // swipes; Hinge 5 + Yubo 8 + Hily 2 + FB 11 messages).
    await expect(page.getByTestId('dating-working-today-totals')).toHaveText(
      '12 swipes · 26 messages'
    );

    await workingToggle.click();
    await expect(workingToggle).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByTestId('dating-working-today-totals')).toBeVisible();

    // Bumble/Badoo: swipes only. Hinge/Yubo/Facebook: messages only. Others: both.
    await expect(page.getByTestId('dating-today-com.bumble.app')).toHaveText(
      'Today: 9 swipes'
    );
    await expect(page.getByTestId('dating-today-co.hinge.app')).toHaveText(
      'Today: 5 messages'
    );
    await expect(page.getByTestId('dating-today-co.yellw.yellowapp')).toHaveText(
      'Today: 8 messages'
    );
    await expect(page.getByTestId('dating-today-com.hily.app')).toHaveText(
      'Today: 3 swipes · 2 messages'
    );
    await expect(page.getByTestId('dating-today-com.facebook.katana')).toHaveText(
      'Today: 11 messages'
    );
    await expect(
      page.getByTestId('dating-today-note-com.facebook.katana')
    ).toHaveText('Max 50 a day');
  });

  test('/usage redirects home; no Usage tile', async ({ page }) => {
    await authAndMock(page);
    await page.goto('/usage');
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByTestId('home-nav-tiles')).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('usage-page')).toHaveCount(0);
  });

  test('Settings is one merged page with account + logout', async ({ page }) => {
    await authAndMock(page);
    await page.goto('/settings');
    await expect(page.getByTestId('settings-page')).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('settings-account-card')).toBeVisible();
    await expect(page.getByTestId('settings-account-meta')).toBeVisible();
    await expect(page.getByTestId('settings-account-meta')).not.toContainText('Backend:');
    await expect(page.getByTestId('settings-workspace')).toBeVisible();
    await expect(page.getByTestId('settings-workspace').locator('#settings-backend-url')).toBeVisible();
    await expect(page.getByTestId('settings-ai-tools')).toBeVisible();
    const advanced = page.getByTestId('settings-ai-advanced');
    await expect(advanced).toBeVisible();
    // Closed <details> keeps inputs in the DOM but hidden
    await expect(page.locator('#settings-temperature')).not.toBeVisible();
    await expect(page.locator('#settings-auth-token')).not.toBeVisible();
    await advanced.locator('summary').click();
    await expect(page.locator('#settings-temperature')).toBeVisible();
    await expect(page.locator('#settings-max-tokens')).toBeVisible();
    await expect(page.locator('#settings-auth-token')).toBeVisible();
    await expect(page.getByTestId('settings-logout')).toBeVisible();
    await expect(page.getByText('Owner')).toBeVisible();
    await expect(page.getByText(/Help & support/)).toBeVisible();
    await expect(page.getByRole('button', { name: /Copy user ID/i })).toBeVisible();
  });

  test('hamburger omits Settings, Devices, and Account (bottom nav has Settings/Devices)', async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name === 'desktop', 'hamburger is mobile-only');
    await authAndMock(page);
    await page.goto('/dating');
    await expect(page.getByTestId('mobile-menu-button')).toBeVisible({
      timeout: 15000,
    });
    await page.getByTestId('mobile-menu-button').click();
    const menu = page.getByRole('dialog', { name: /^Menu$/i });
    await expect(menu).toBeVisible();
    await expect(menu.getByRole('link', { name: /^Dating$/i })).toBeVisible();
    await expect(menu.getByRole('link', { name: /^Settings$/i })).toHaveCount(0);
    await expect(menu.getByRole('link', { name: /^Devices$/i })).toHaveCount(0);
    await expect(menu.getByRole('link', { name: /^Account$/i })).toHaveCount(0);
    await expect(page.getByTestId('mobile-bottom-nav').getByRole('link', { name: /^Settings$/i })).toBeVisible();
    await expect(page.getByTestId('mobile-bottom-nav').getByRole('link', { name: /^Devices$/i })).toBeVisible();
  });

  test('Dating has no dry-run checkbox or Pause; Start stays live', async ({
    page,
  }) => {
    await authAndMock(page);
    await page.goto('/dating');
    await expect(page.getByTestId('dating-start')).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('dating-stop')).toBeVisible();
    await expect(page.getByTestId('dating-status-refresh')).toBeVisible();
    await expect(page.getByTestId('dating-apps-for-start')).toHaveCount(0);
    await expect(page.getByTestId('dating-dry-run')).toHaveCount(0);
    await expect(page.getByText('Dry-run (no real likes/messages)')).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^(Pause|Resume)$/i })).toHaveCount(0);
    const startWait = page.waitForRequest(
      (r) =>
        r.url().includes('/api/dating/start') && r.method() === 'POST',
      { timeout: 15000 }
    );
    await page.getByTestId('dating-start').click();
    const req = await startWait;
    const body = req.postDataJSON() as { dry_run?: boolean };
    expect(body.dry_run).toBe(false);
  });

  test('Dating live activity collapsed when idle; expands when running; no screenshots toggle', async ({
    page,
  }) => {
    await authAndMock(page);
    await page.goto('/dating');
    await expect(page.getByTestId('live-activity')).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('live-activity-toggle')).toHaveAttribute(
      'aria-expanded',
      'false'
    );
    await expect(page.getByTestId('live-activity-panel')).toHaveCount(0);
    await expect(page.getByText(/Show screenshots/i)).toHaveCount(0);
    await expect(page.getByText(/Hide screenshots/i)).toHaveCount(0);

    await page.getByTestId('live-activity-toggle').click();
    await expect(page.getByTestId('live-activity-toggle')).toHaveAttribute(
      'aria-expanded',
      'true'
    );
    await expect(page.getByTestId('live-activity-panel')).toBeVisible();
    await expect(page.getByText(/Show screenshots/i)).toHaveCount(0);

    // Simulate an active job via status mock (last route wins), then reload.
    await page.route('**/api/dating/status', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          running: true,
          paused: false,
          current_app: 'com.hily.app',
          activity: {
            status: 'running',
            job_id: 'task_live_1',
            mode: 'dating',
            steps: [],
          },
        }),
      });
    });
    await page.goto('/dating');
    await expect(page.getByTestId('live-activity-toggle')).toHaveAttribute(
      'aria-expanded',
      'true',
      { timeout: 15000 }
    );
    await expect(page.getByTestId('live-activity-panel')).toBeVisible();
  });

  test('Social has no Signature or Notifications sections', async ({ page }) => {
    await authAndMock(page);
    await page.goto('/social');
    await expect(page.getByRole('heading', { name: 'Social', exact: true })).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByRole('heading', { name: 'Signature', exact: true })).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'Notifications', exact: true })).toHaveCount(0);
    await expect(page.getByText('Append signature')).toHaveCount(0);
    await expect(page.getByText('Email notify')).toHaveCount(0);
    await expect(page.getByTestId('social-save-config')).toBeVisible();
  });

  test('/account redirects to Settings with account controls', async ({
    page,
  }, testInfo) => {
    await authAndMock(page);
    await page.goto('/account');
    await expect(page).toHaveURL(/\/settings$/, { timeout: 15000 });
    const settings = page.getByTestId('settings-page');
    await expect(settings).toBeVisible();
    await expect(page.getByTestId('settings-account-card')).toBeVisible();
    await expect(page.getByTestId('settings-logout')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Account', exact: true })).toHaveCount(0);
    if (testInfo.project.name !== 'desktop') {
      await expect(
        page.getByTestId('mobile-bottom-nav').getByRole('link', { name: /^Devices$/i })
      ).toBeVisible();
      await expect(
        page.getByTestId('mobile-bottom-nav').getByRole('link', { name: /^Settings$/i })
      ).toBeVisible();
    }
  });
});
