// Capture the public demo screenshots from a running stack.
//
//   KB_BASE_URL=http://localhost:8069 npm run screenshots
//
// CHROME_PATH overrides the browser binary.
import { existsSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import puppeteer from 'puppeteer-core';

const BASE = process.env.KB_BASE_URL || 'http://localhost:8069';
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = resolve(ROOT, 'docs/screenshots');
const CHROME = [process.env.CHROME_PATH, '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'].find(
  (path) => path && existsSync(path)
);
if (!CHROME) {
  console.error('No Chrome/Chromium found. Set CHROME_PATH to the browser binary.');
  process.exit(2);
}

const PAGES = [
  ['launcher', '/apps'],
  ['contacts', '/apps/contacts'],
  ['sales', '/apps/sales'],
  ['purchase', '/apps/purchase'],
  ['inventory', '/apps/inventory'],
  ['accounting', '/apps/accounting'],
];

mkdirSync(OUT, { recursive: true });
const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
});
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });

try {
  await page.goto(`${BASE}/web/login`, { waitUntil: 'networkidle2' });
  await page.type('input[name="login"]', process.env.KB_ADMIN_LOGIN || 'admin');
  await page.type('input[name="password"]', process.env.KB_ADMIN_PASSWORD || 'admin');
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'networkidle2' }),
    page.click('button[type="submit"]'),
  ]);

  for (const [name, path] of PAGES) {
    const response = await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle2' });
    if (response.status() !== 200) throw new Error(`${path} returned ${response.status()}`);
    await new Promise((r) => setTimeout(r, 400));
    const file = resolve(OUT, `${name}.png`);
    await page.screenshot({ path: file });
    console.log(file);
  }
} finally {
  await browser.close();
}
