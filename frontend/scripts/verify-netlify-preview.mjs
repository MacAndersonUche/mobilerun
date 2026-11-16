/**
 * Playwright visual + smoke against deployed Netlify preview.
 * Usage: PLAYWRIGHT_BASE_URL=https://deploy-preview-1--macsmobilerun.netlify.app node scripts/verify-netlify-preview.mjs
 */
import { chromium, devices } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const baseURL =
  process.env.PLAYWRIGHT_BASE_URL ||
  'https://deploy-preview-1--macsmobilerun.netlify.app';
const outDir = path.join(__dirname, '../../docs/ui-screenshots/netlify-preview');
fs.mkdirSync(outDir, { recursive: true });

const routes = [
  '/',
  '/chat',
  '/devices',
  '/needs-you',
  '/social',
  '/dating',
  '/live',
  '/settings',
  '/account',
  '/tasks',
  '/history',
];

async function runViewport(label, viewport) {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport,
    ...devices['Desktop Chrome'],
  });
  const page = await context.newPage();
  const defects = [];

  // Login page
  await page.goto(baseURL + '/', { waitUntil: 'networkidle', timeout: 60000 });
  await page.screenshot({ path: path.join(outDir, `${label}-01-login.png`), fullPage: true });
  const loginHeading = await page.getByRole('heading', { name: /MobileRun/i }).count();
  if (!loginHeading) defects.push(`${label}: login missing MobileRun heading`);

  await page.addInitScript(() => {
    localStorage.setItem('mobilerun_auth_token', 'visual-preview-token');
    localStorage.setItem('mobilerun_user_email', 'mac@macai.local');
  });

  for (let i = 0; i < routes.length; i++) {
    const route = routes[i];
    const res = await page.goto(baseURL + route, {
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    });
    await page.waitForTimeout(600);
    const name = `${label}-${String(i + 2).padStart(2, '0')}-${route.replace(/\//g, '') || 'home'}.png`;
    await page.screenshot({ path: path.join(outDir, name), fullPage: true });
    if (!res || res.status() >= 400) {
      defects.push(`${label}: ${route} HTTP ${res?.status()}`);
    }
    // Overflow / horizontal scroll check
    const overflow = await page.evaluate(() => {
      const doc = document.documentElement;
      return {
        scrollWidth: doc.scrollWidth,
        clientWidth: doc.clientWidth,
        bodyBg: getComputedStyle(document.body).backgroundColor,
      };
    });
    if (overflow.scrollWidth > overflow.clientWidth + 2) {
      defects.push(`${label}: ${route} horizontal overflow ${overflow.scrollWidth}>${overflow.clientWidth}`);
    }
  }

  await browser.close();
  return defects;
}

const defects = [
  ...(await runViewport('mobile390', { width: 390, height: 844 })),
  ...(await runViewport('desktop1440', { width: 1440, height: 900 })),
];

const report = { baseURL, defects, outDir };
fs.writeFileSync(path.join(outDir, 'report.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
if (defects.length) {
  console.error('DEFECTS FOUND');
  process.exit(1);
}
console.log('Netlify preview verify OK');
