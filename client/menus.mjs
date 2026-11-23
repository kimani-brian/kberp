import { existsSync } from 'node:fs';
import puppeteer from 'puppeteer-core';
const BASE = process.env.KB_BASE_URL || 'http://localhost:8069';
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
  if (r.status() !== 200) throw new Error(`${path} -> HTTP ${r.status()}`);
}
async function check(name, fn) {
  try { const count = await fn(); tested += typeof count === 'number' ? count : 1; }
  catch (e) { failures.push({ name, detail: e.message }); }
}
page.on('pageerror', (e) => failures.push({ name: 'pageerror', detail: e.message }));
page.on('console', (m) => { if (m.type() === 'error') failures.push({ name: 'console', detail: m.text() }); });

await goto('/web/login');
await page.type('input[name="login"]', process.env.KB_ADMIN_LOGIN || 'admin');
await page.type('input[name="password"]', process.env.KB_ADMIN_PASSWORD || 'admin');
await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle2' }), page.click('button[type="submit"]')]);

for (const app of ['contacts', 'sales', 'accounting', 'purchase', 'inventory']) {
  await check(`${app}: menubar buttons open`, async () => {
    await goto(`/apps/${app}`);
    const labels = await page.$$eval('header.topbar .menubar .menu > button.menu-btn', (els) => els.map((e) => e.textContent.trim()));
    for (let i = 0; i < labels.length; i++) {
      await goto(`/apps/${app}`);
      const buttons = await page.$$('header.topbar .menubar .menu > button.menu-btn');
      await buttons[i].click();
      await sleep(150);
      const expanded = await buttons[i].evaluate((e) => e.getAttribute('aria-expanded'));
      if (expanded !== 'true') throw new Error(`${labels[i]} did not expand (aria-expanded=${expanded})`);
      const visible = await page.evaluate((idx) => {
        const panel = document.querySelectorAll('header.topbar .menubar .menu .menu-panel')[idx];
        if (!panel || panel.getClientRects().length === 0) return false;
        const rect = panel.getBoundingClientRect();
        // A clipped panel still has a rect; elementFromPoint proves it is
        // actually painted where the user would click.
        const hit = document.elementFromPoint(rect.x + 20, rect.y + 20);
        return Boolean(hit && panel.contains(hit));
      }, i);
      if (!visible) throw new Error(`${labels[i]} panel is clipped or not painted`);
    }
    return labels.length;
  });

  await check(`${app}: all menubar links navigate`, async () => {
    await goto(`/apps/${app}`);
    const links = await page.$$eval('header.topbar .menubar a[href]', (els) =>
      [...new Set(els.map((e) => ({ href: e.getAttribute('href'), text: e.textContent.trim() })))]
    );
    for (const link of links) {
      await goto(`/apps/${app}`);
      const found = await page.evaluate((href) => {
        const a = [...document.querySelectorAll('header.topbar .menubar a[href]')].find((e) => e.getAttribute('href') === href);
        if (!a) return false;
        const menu = a.closest('.menu');
        if (menu) menu.querySelector('button.menu-btn')?.click();
        return true;
      }, link.href);
      if (!found) continue;
      await sleep(150);
      await page.evaluate((href) => {
        const a = [...document.querySelectorAll('header.topbar .menubar a[href]')].find((e) => e.getAttribute('href') === href);
        a.click();
      }, link.href);
      await page.waitForFunction((h) => location.pathname + location.search === h, {}, link.href);
      await sleep(350);
      const state = await page.evaluate(() => ({
        main: document.querySelector('#main-content')?.innerText.trim() || '',
        h1: document.querySelector('#main-content h1')?.textContent.trim() || '',
      }));
      if (!state.main) throw new Error(`${link.text} (${link.href}) rendered blank`);
      if (/Access denied|Internal Server Error|Traceback|404 Not Found/i.test(state.main)) throw new Error(`${link.text} (${link.href}): ${state.main.slice(0, 120)}`);
      if (!state.h1) throw new Error(`${link.text} (${link.href}) has no h1`);
    }
    return links.length;
  });
}

await check('topbar: brand + switcher + user + settings', async () => {
  await goto('/apps/contacts');
  await page.click('header.topbar a.brand');
  await page.waitForFunction(() => location.pathname === '/apps');
  await page.click('#app-switcher-btn');
  if ((await page.$eval('#app-switcher-btn', (e) => e.getAttribute('aria-expanded'))) !== 'true') throw new Error('switcher did not open');
  await page.click('#app-switcher-btn');
  await page.click('.user-btn');
  if ((await page.$eval('.user-btn', (e) => e.getAttribute('aria-expanded'))) !== 'true') throw new Error('user menu did not open');
  await page.click('.user-btn');
  const settings = await page.$('header.topbar a.topbar-link');
  if (settings) {
    await settings.click();
    await page.waitForFunction(() => location.pathname === '/settings');
    if (!(await page.$eval('#main-content', (e) => e.innerText.trim()))) throw new Error('settings blank');
  }
  return 'ok';
});

await browser.close();
console.log(JSON.stringify({ tested, failures }, null, 2));
if (failures.length) process.exitCode = 1;
