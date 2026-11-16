import { chromium } from '@playwright/test';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const out = path.resolve(__dirname, '../../docs/ui-reference');
fs.mkdirSync(out, { recursive: true });

const targets = [
  { name: '01-mobilerun-ai-home', url: 'https://mobilerun.ai/', wait: 4000 },
  { name: '02-cloud-mobilerun', url: 'https://cloud.mobilerun.ai/', wait: 5000 },
  { name: '03-cloud-mobilerun-login', url: 'https://cloud.mobilerun.ai/login', wait: 5000 },
  { name: '04-docs-home', url: 'https://docs.mobilerun.ai/', wait: 3000 },
  { name: '05-docs-cloud-overview', url: 'https://docs.mobilerun.ai/cloud/overview', wait: 3000 },
  { name: '06-docs-cloud-quickstart', url: 'https://docs.mobilerun.ai/cloud/quickstart', wait: 3000 },
  { name: '07-docs-framework-overview', url: 'https://docs.mobilerun.ai/framework/overview', wait: 3000 },
  { name: '08-github-mobilerun', url: 'https://github.com/droidrun/mobilerun', wait: 3500 },
  { name: '09-github-droidrun-org', url: 'https://github.com/droidrun', wait: 3000 },
];

const browser = await chromium.launch({ headless: true });

async function capture(ctxName, opts) {
  const ctx = await browser.newContext({
    ...opts,
    userAgent:
      opts.userAgent ||
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
  });
  for (const t of targets) {
    const page = await ctx.newPage();
    const file = path.join(out, `${ctxName}-${t.name}.png`);
    try {
      const res = await page.goto(t.url, {
        waitUntil: 'domcontentloaded',
        timeout: 90000,
      });
      await page.waitForTimeout(t.wait);
      for (const sel of [
        'button:has-text("Accept")',
        'button:has-text("Accept all")',
        'button:has-text("Agree")',
        'button:has-text("Got it")',
        '[aria-label="Close"]',
      ]) {
        try {
          await page.locator(sel).first().click({ timeout: 800 });
        } catch {
          /* ignore */
        }
      }
      await page.waitForTimeout(400);
      await page.screenshot({ path: file, fullPage: true });
      console.log('OK', file, res?.status());
    } catch (e) {
      console.error('FAIL', t.name, e.message);
      try {
        await page.screenshot({
          path: path.join(out, `${ctxName}-${t.name}-error.png`),
          fullPage: true,
        });
      } catch {
        /* ignore */
      }
    } finally {
      await page.close();
    }
  }
  await ctx.close();
}

await capture('desktop', { viewport: { width: 1440, height: 900 } });
await capture('mobile', {
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
  userAgent:
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
});

await browser.close();
console.log('saved to', out);
