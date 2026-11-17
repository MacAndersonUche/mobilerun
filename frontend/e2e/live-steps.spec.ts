import { test, expect } from '@playwright/test';
import path from 'path';
import fs from 'fs';

/**
 * Plain-language live step log evidence.
 * E2E_LIVE=1 + API_URL: drive a real prod task on a paired emulator and
 * screenshot Tasks + Chat as steps appear.
 */
const outDir = path.join('..', 'docs', 'ui-screenshots');
const live = process.env.E2E_LIVE === '1';
const api = (process.env.API_URL || process.env.VITE_API_URL || '').replace(
  /\/$/,
  ''
);
const user = process.env.E2E_USER || 'ci-e2e';
const password = process.env.E2E_PASSWORD || 'admin';

test.beforeAll(() => {
  fs.mkdirSync(outDir, { recursive: true });
});

async function shot(page: import('@playwright/test').Page, name: string) {
  const project = test.info().project.name;
  await page.screenshot({
    path: path.join(outDir, `${project}-${name}.png`),
    fullPage: true,
  });
}

async function loginApi(): Promise<string> {
  const res = await fetch(`${api}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: user, password }),
  });
  if (!res.ok) throw new Error(`login ${res.status}`);
  return ((await res.json()) as { access_token: string }).access_token;
}

test('tasks page shows plain-language live steps', async ({ page }) => {
  if (live && api) {
    const token = await loginApi();
    await page.addInitScript(
      ({ t, apiUrl }) => {
        localStorage.setItem('mobilerun_auth_token', t);
        localStorage.setItem('mobilerun_user_email', 'ci-e2e@local');
        localStorage.setItem('mobilerun_backend_url', apiUrl);
      },
      { t: token, apiUrl: api }
    );

    await page.goto('/tasks');
    await expect(page.getByRole('heading', { name: /Run Automation Task/i })).toBeVisible({
      timeout: 20000,
    });
    // Prefer connected device if picker present
    const device = page.locator('#task-device');
    if (await device.count()) {
      await device.selectOption({ index: 1 }).catch(async () => {
        const opts = await device.locator('option').allTextContents();
        const online = opts.findIndex((o) => /online|●/i.test(o) || o.trim());
        if (online >= 0) await device.selectOption({ index: online });
      });
    }
    await page.locator('textarea, input[name="instruction"]').first().fill('open settings');
    await page.getByRole('button', { name: /run|submit|start/i }).first().click();
    await expect(page.getByTestId('task-progress')).toBeVisible({ timeout: 15000 });
    await expect
      .poll(async () => page.getByTestId('step-line').count(), { timeout: 180000 })
      .toBeGreaterThan(0);
    const first = page.getByTestId('step-line').first();
    await expect(first).toContainText(/Step\s+\d+:/i);
    await expect(first).toContainText(/Opened|Tapped|Typed|Swiped|Finished|open/i);
    await shot(page, 'tasks-live-steps');

    await page.goto('/history');
    await expect(page.getByTestId('history-task').first()).toBeVisible({
      timeout: 20000,
    });
    await page.getByTestId('history-task').first().click();
    await expect(page.getByTestId('step-line').first()).toBeVisible({
      timeout: 15000,
    });
    await shot(page, 'history-live-steps');
    return;
  }

  // Offline seeded layout
  await page.route('**/api/tasks**', async (route) => {
    const url = route.request().url();
    const method = route.request().method();
    if (method === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          task_id: 'task_demo',
          status: 'running',
          current_step: 1,
          max_steps: 8,
          instruction: 'open settings',
          steps: [],
        }),
      });
      return;
    }
    if (url.match(/\/api\/tasks\/task_demo/)) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          task_id: 'task_demo',
          status: 'running',
          current_step: 2,
          max_steps: 8,
          instruction: 'open settings',
          result: 'Step 2: Opened Settings',
          steps: [
            {
              n: 1,
              action: 'Opened Settings',
              reason: 'to begin the task',
              ok: true,
              package: 'com.android.settings',
              ts: Math.floor(Date.now() / 1000) - 5,
            },
            {
              n: 2,
              action: 'Tapped "Display"',
              reason: 'to find the conversation',
              ok: true,
              package: 'com.android.settings',
              ts: Math.floor(Date.now() / 1000),
            },
          ],
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          task_id: 'task_demo',
          status: 'running',
          current_step: 2,
          max_steps: 8,
          instruction: 'open settings',
          device_id: 'emu',
          started_at: new Date().toISOString(),
          mode: 'normal',
          steps: [
            {
              n: 1,
              action: 'Opened Settings',
              reason: 'to begin the task',
              ok: true,
              ts: Math.floor(Date.now() / 1000),
            },
          ],
        },
      ]),
    });
  });
  await page.route('**/api/devices', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { device_id: 'emu', name: 'emulator', connected: true },
      ]),
    });
  });
  await page.route('**/api/mode**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ mode: 'normal', speed_preset: 'balanced' }),
    });
  });
  await page.addInitScript(() => {
    localStorage.setItem('mobilerun_auth_token', 'visual-preview-token');
  });

  await page.goto('/tasks');
  await expect(page.locator('#task-device')).toBeVisible({ timeout: 15000 });
  await page.locator('#task-device').selectOption('emu');
  await page.locator('#task-instruction').fill('open settings');
  await page.getByRole('button', { name: /Run Task/i }).click();
  await expect(page.getByTestId('step-line').first()).toContainText(
    /Step\s+1:\s+Opened Settings/i,
    { timeout: 15000 }
  );
  await shot(page, 'tasks-live-steps');
});
