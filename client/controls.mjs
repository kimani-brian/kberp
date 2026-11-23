import { existsSync } from 'node:fs';
import puppeteer from 'puppeteer-core';
const BASE = process.env.KB_BASE_URL || 'http://localhost:8069';
const PAGES = {
  contacts: 5, sales: 12, accounting: 20, purchase: 44, inventory: 25,
};
const CHROME = [process.env.CHROME_PATH, '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'].find((path) => path && existsSync(path));
if (!CHROME) {
  console.error('No Chrome/Chromium found. Set CHROME_PATH to the browser binary.');
  process.exit(2);
}
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const page = await browser.newPage();
page.setDefaultTimeout(15000);
const failures = [];
let tested = 0;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function goto(path) {
  const r = await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle2' });
  if (r.status() !== 200) throw new Error(`HTTP ${r.status()} for ${path}`);
}
async function check(name, fn) {
  try { const count = await fn(); tested += typeof count === 'number' ? count : 1; }
  catch (e) { failures.push({ name, detail: e.message }); }
}
async function assertScreen(label) {
  const state = await page.evaluate(() => ({
    main: document.querySelector('#main-content')?.innerText.trim() || '',
    h1: document.querySelector('#main-content h1')?.textContent.trim() || '',
  }));
  if (!state.main) throw new Error(`${label}: blank`);
  if (/Access denied|Internal Server Error|Traceback|404 Not Found/i.test(state.main)) throw new Error(`${label}: ${state.main.slice(0, 120)}`);
  if (!state.h1) throw new Error(`${label}: no h1`);
  return state.h1;
}

await goto('/web/login');
await page.type('input[name="login"]', process.env.KB_ADMIN_LOGIN || 'admin');
await page.type('input[name="password"]', process.env.KB_ADMIN_PASSWORD || 'admin');
await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle2' }), page.click('button[type="submit"]')]);

for (const [app, action] of Object.entries(PAGES)) {
  const list = `/apps/${app}/action/${action}`;
  await check(`${app}: page controls`, async () => {
    await goto(list);
    await page.waitForSelector('#main-content h1');
    const controls = await page.$$eval(
      '#main-content .page-head a, #main-content .page-head button, #main-content .searchbar button, #main-content .searchbar a.chip, #main-content .groupby-chips a.chip',
      (els) => [...new Set(els.map((e) => ({
        text: e.textContent.trim().replace(/\s+/g, ' ').slice(0, 30),
        href: e.getAttribute('href'),
      })))]
    );
    for (const control of controls) {
      await goto(list);
      await sleep(200);
      if (control.href) {
        await page.evaluate((href) => {
          const a = [...document.querySelectorAll('#main-content a[href]')].find((e) => e.getAttribute('href') === href);
          if (!a) throw new Error(`control ${href} missing`);
          a.click();
        }, control.href);
      } else {
        await page.evaluate((text) => {
          const b = [...document.querySelectorAll('#main-content button')].find((e) => e.textContent.trim().replace(/\s+/g, ' ') === text);
          if (!b) throw new Error(`button ${text} missing`);
          b.click();
        }, control.text);
      }
      await sleep(450);
      await assertScreen(`${app} ${control.text}`);
    }
    return controls.length;
  });
}

await browser.close();
console.log(JSON.stringify({ tested, failures }, null, 2));
if (failures.length) process.exitCode = 1;
