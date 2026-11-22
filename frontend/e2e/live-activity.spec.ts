import { test, expect } from '@playwright/test';
import path from 'path';
import fs from 'fs';

/**
 * Captures Dating + Social live-activity UI evidence.
 * When E2E_LIVE=1 and API credentials exist, drives real dry-run against prod
 * and waits for steps. Otherwise seeds localStorage mock activity for layout proof.
 */
const outDir = path.join('..', 'docs', 'ui-screenshots');
const live = process.env.E2E_LIVE === '1';
const api = (process.env.VITE_API_URL || process.env.API_URL || '').replace(/\/$/, '');
const user = process.env.E2E_USER || 'ci-e2e';
const password = process.env.E2E_PASSWORD || 'admin';

test.beforeAll(() => {
  fs.mkdirSync(outDir, { recursive: true });
});

async function shot(page: import('@playwright/test').Page, name: string) {
  const project = test.info().project.name;
  const file = path.join(outDir, `${project}-${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
}

async function loginApi(): Promise<string> {
  const res = await fetch(`${api}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: user, password }),
  });
  if (!res.ok) throw new Error(`login ${res.status}`);
  const data = (await res.json()) as { access_token: string };
  return data.access_token;
}

test('dating and social live activity views', async ({ page }) => {
  if (live && api) {
    const token = await loginApi();
    await page.addInitScript((t) => {
      localStorage.setItem('mobilerun_auth_token', t);
      localStorage.setItem('mobilerun_user_email', 'ci-e2e@mobilerun.local');
    }, token);

    // Dating dry-run
    await page.goto('/dating');
    await expect(page.getByTestId('live-activity')).toBeVisible({ timeout: 20000 });
    const dry = page.getByTestId('dating-dry-run');
    if (await dry.count()) {
      if (!(await dry.isChecked())) await dry.check();
    }
    await page.getByTestId('dating-start').click();
    await expect(page.getByTestId('live-activity-status')).not.toHaveText('idle', {
      timeout: 30000,
    });
    // Poll until steps appear (backend ticks / EventBridge)
    await expect
      .poll(
        async () =>
          page.locator('[data-testid="live-activity-step"]').count(),
        { timeout: 120000 }
      )
      .toBeGreaterThan(0);
    await shot(page, 'dating-live-activity');

    await page.getByTestId('dating-stop').click().catch(() => undefined);

    // Social dry-run
    await page.goto('/social');
    await expect(page.getByTestId('live-activity')).toBeVisible({ timeout: 20000 });
    const sdry = page.getByTestId('social-dry-run');
    if (await sdry.count()) {
      if (!(await sdry.isChecked())) await sdry.check();
    }
    await page.getByTestId('social-start').click();
    await expect
      .poll(
        async () =>
          page.locator('[data-testid="live-activity-step"]').count(),
        { timeout: 120000 }
      )
      .toBeGreaterThan(0);
    await shot(page, 'social-live-activity');
    await page.getByTestId('social-stop').click().catch(() => undefined);
    return;
  }

  // Offline layout evidence with seeded activity payload via route mock
  await page.route('**/api/dating/status', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        running: true,
        paused: false,
        current_app: 'ai.mobilerun.mockdating',
        review_queue: [],
        job_id: 'dating_demo',
        activity: {
          job_id: 'dating_demo',
          status: 'running',
          dry_run: true,
          current_step: 2,
          package: 'ai.mobilerun.mockdating',
          last_action: 'opener',
          steps: [
            {
              n: 1,
              action: 'opener',
              reason: 'dry_run — no real send/like',
              package: 'ai.mobilerun.mockdating',
              screen: 'ai.mobilerun.mockdating',
              ok: true,
              dry_run: true,
              ts: Math.floor(Date.now() / 1000) - 30,
            },
            {
              n: 2,
              action: 'opener',
              reason: 'dry_run — composing template',
              package: 'ai.mobilerun.mockdating',
              screen: 'ai.mobilerun.mockdating',
              ok: true,
              dry_run: true,
              ts: Math.floor(Date.now() / 1000),
            },
          ],
        },
      }),
    });
  });
  await page.route('**/api/dating/**', async (route) => {
    if (route.request().url().includes('/status')) {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ok', apps: [], config: {} }),
    });
  });
  await page.route('**/api/social/**', async (route) => {
    const url = route.request().url();
    if (url.includes('/status')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          running: true,
          paused: false,
          job_id: 'social_demo',
          needs_you_badge: 0,
          activity: {
            job_id: 'social_demo',
            status: 'running',
            dry_run: true,
            current_step: 1,
            package: 'com.google.android.apps.messaging',
            last_action: 'open_app',
            steps: [
              {
                n: 1,
                action: 'open_app',
                reason: 'dry_run — open stand-in messaging app',
                package: 'com.google.android.apps.messaging',
                screen: 'com.google.android.apps.messaging',
                ok: true,
                dry_run: true,
                ts: Math.floor(Date.now() / 1000),
              },
            ],
          },
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'ok',
        apps: [
          {
            name: 'Messages',
            package_name: 'com.google.android.apps.messaging',
            enabled: true,
            signature_enabled: true,
          },
        ],
        signature: { enabled_global: true, text: '— from MacAI' },
        escalation: { always_ask_new_contacts: true },
        speed_preset: 'balanced',
      }),
    });
  });
  await page.route('**/api/devices', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });
  await page.route('**/api/mode**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ mode: 'dating', speed_preset: 'balanced' }),
    });
  });

  await page.addInitScript(() => {
    localStorage.setItem('mobilerun_auth_token', 'visual-preview-token');
    localStorage.setItem('mobilerun_user_email', 'mac@macai.local');
  });

  await page.goto('/dating');
  await expect(page.getByTestId('live-activity')).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId('live-activity-step')).toHaveCount(2, {
    timeout: 15000,
  });
  await shot(page, 'dating-live-activity');

  await page.goto('/social');
  await expect(page.getByTestId('live-activity')).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId('live-activity-step')).toHaveCount(1, {
    timeout: 15000,
  });
  await shot(page, 'social-live-activity');
});
