// Browser smoke test for the F1 demo script. Drives the running stack with a
// real Chrome: sign in, open all five apps, exercise search/kanban, create a
// partner, create and confirm a quotation, and check for JS/console errors.
//
//   KB_BASE_URL=http://localhost:8069 npm run smoke
//
// CHROME_PATH overrides the browser binary when it is not in the usual place.
import { existsSync } from 'node:fs';
import puppeteer from 'puppeteer-core';

const BASE = process.env.KB_BASE_URL || 'http://localhost:8069';
const CHROME = [process.env.CHROME_PATH, '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'].find(
  (path) => path && existsSync(path)
);
if (!CHROME) {
  console.error('No Chrome/Chromium found. Set CHROME_PATH to the browser binary.');
  process.exit(2);
}

const LOGIN = process.env.KB_ADMIN_LOGIN || 'admin';
const PASSWORD = process.env.KB_ADMIN_PASSWORD || 'admin';
const stamp = Date.now().toString(36);
const results = [];
const errors = [];

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
});
const page = await browser.newPage();
page.setDefaultTimeout(15000);
page.on('console', (m) => { if (m.type() === 'error') errors.push(`console: ${m.text()}`); });
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
page.on('requestfailed', (r) => errors.push(`requestfailed: ${r.url()} ${r.failure()?.errorText}`));

async function step(name, fn) {
  try { results.push({ name, status: 'PASS', detail: await fn() }); }
  catch (e) { results.push({ name, status: 'FAIL', detail: e.message }); }
}
const text = (sel) => page.$eval(sel, (e) => e.textContent.trim());
const href = (sel) => page.$eval(sel, (e) => e.getAttribute('href'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function mainText() {
  return (await page.$eval('#main-content', (e) => e.innerText)).trim();
}
async function goto(path) {
  const response = await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle2' });
  if (response.status() !== 200) throw new Error(`${path} returned ${response.status()}`);
}

try {
  await step('login page renders', async () => {
    await goto('/web/login');
    return text('h1');
  });

  await step('sign in', async () => {
    await page.type('input[name="login"]', LOGIN);
    await page.type('input[name="password"]', PASSWORD);
    await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle2' }), page.click('button[type="submit"]')]);
    if (!page.url().endsWith('/apps')) throw new Error(`landed on ${page.url()}`);
    return page.url();
  });

  await step('build stamp matches running image', async () => {
    const ready = await fetch(`${BASE}/readyz`).then((r) => r.json());
    const stampText = await text('.build-stamp');
    if (stampText !== ready.build_id) {
      throw new Error(`UI shows ${stampText}, container is ${ready.build_id} — rebuild with make deploy`);
    }
    return stampText;
  });

  for (const key of ['contacts', 'sales', 'accounting', 'purchase', 'inventory']) {
    await step(`open ${key}`, async () => {
      await goto(`/apps/${key}`);
      await page.waitForSelector('.kpi-grid .kpi-card');
      const title = await text('h1');
      const kpis = await page.$$eval('.kpi-grid .kpi-card', (els) => els.length);
      if (!kpis) throw new Error('no dashboard KPIs');
      return `${title} (${kpis} KPIs)`;
    });

    await step(`open first ${key} screen`, async () => {
      await goto(`/apps/${key}`);
      const target = await page.evaluate(() => {
        const bar = document.querySelector('header.topbar .menubar');
        let link = bar.querySelector(':scope > a.menu-btn[href]');
        if (!link) {
          const menu = bar.querySelector('.menu');
          menu.querySelector('button.menu-btn')?.click();
          link = menu.querySelector('.menu-panel a[href]');
        }
        return link ? link.getAttribute('href') : null;
      });
      if (!target) throw new Error('no menubar link on app home');
      await page.evaluate((h) => {
        const link = [...document.querySelectorAll('header.topbar .menubar a[href]')].find(
          (e) => e.getAttribute('href') === h
        );
        link.click();
      }, target);
      await page.waitForFunction((h) => location.pathname + location.search === h, {}, target);
      await sleep(300);
      const body = await mainText();
      if (!body) throw new Error('blank screen');
      if (body.includes('Access denied')) throw new Error('access denied');
      return `${target}: ${body.split('\n')[0]}`;
    });
  }

  await step('contacts search', async () => {
    await goto('/apps/contacts/action/5');
    await page.waitForSelector('input[name="q"]');
    await page.type('input[name="q"]', 'Acme');
    await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle2' }), page.click('form.searchbar button[type="submit"]')]);
    if (!page.url().includes('q=Acme')) throw new Error(`unexpected url ${page.url()}`);
    const rows = await page.$$eval('.data-table tbody tr', (els) => els.length);
    if (rows < 1) throw new Error('no matching rows');
    return `${rows} row(s) for Acme`;
  });

  await step('contacts kanban toggle', async () => {
    const target = await href('a[href*="view=kanban"]');
    await page.click('a[href*="view=kanban"]');
    await page.waitForFunction((h) => location.pathname + location.search === h, {}, target);
    await sleep(300);
    if (!(await mainText())) throw new Error('blank kanban');
    return target;
  });

  await step('create contact via UI', async () => {
    await goto('/apps/contacts/action/5/new');
    await page.waitForSelector('form.record-form input[type="text"]');
    const name = `Browser Check ${stamp}`;
    await page.type('form.record-form input[type="text"]', name);
    await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle2' }), page.click('form.record-form button[type="submit"]')]);
    const title = await text('h1');
    if (!title.includes(name)) throw new Error(`h1 is ${JSON.stringify(title)}`);
    return title;
  });

  let quotationUrl = '';
  let quotationNumber = '';
  await step('create quotation via UI', async () => {
    await goto('/apps/sales/action/12/new');
    await page.waitForSelector('form.record-form');
    await page.select('select[name="partner_id"]', '4');
    const product = await page.$eval('select[name="order_line\\[new-0\\]\\[product_id\\]"] option:nth-child(2)', (e) => e.value);
    await page.select('select[name="order_line\\[new-0\\]\\[product_id\\]"]', product);
    await page.type('input[name="order_line\\[new-0\\]\\[name\\]"]', 'Browser smoke line');
    await page.type('input[name="order_line\\[new-0\\]\\[qty\\]"]', '2');
    await page.type('input[name="order_line\\[new-0\\]\\[price_unit\\]"]', '100');
    await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle2' }), page.click('form.record-form button[type="submit"]')]);
    quotationUrl = new URL(page.url()).pathname;
    quotationNumber = await text('h1');
    if (!/^\/apps\/sales\/action\/12\/\d+$/.test(quotationUrl)) throw new Error(`unexpected url ${quotationUrl}`);
    return `${quotationUrl} (${quotationNumber})`;
  });

  await step('confirm quotation with object button', async () => {
    await goto(quotationUrl);
    const clicked = await page.evaluate(() => {
      const button = [...document.querySelectorAll('button')].find((e) => e.textContent.trim() === 'Confirm');
      if (!button) return false;
      button.click();
      return true;
    });
    if (!clicked) throw new Error('Confirm button not rendered');
    await page.waitForFunction(
      () => ![...document.querySelectorAll('button')].some((e) => e.textContent.trim() === 'Confirm'),
      { timeout: 10000 }
    );
    return 'state changed to Sales Order';
  });

  await step('create invoice from confirmed order', async () => {
    await goto(quotationUrl);
    const clicked = await page.evaluate(() => {
      const button = [...document.querySelectorAll('button')].find((e) => e.textContent.trim() === 'Create Invoice');
      if (!button) return false;
      button.click();
      return true;
    });
    if (!clicked) throw new Error('Create Invoice button not rendered');
    // The RPC keeps us on the order; the next step verifies the invoice exists
    // by searching for it in Accounting.
    await sleep(600);
    return 'Create Invoice clicked';
  });

  await step('post the generated invoice', async () => {
    await goto('/apps/accounting/action/20');
    await page.waitForSelector('input[name="q"]');
    await page.type('input[name="q"]', quotationNumber);
    await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle2' }), page.click('form.searchbar button[type="submit"]')]);
    await page.waitForSelector('.data-table tbody tr a', { visible: true });
    await sleep(300);
    await page.evaluate(() => {
      const link = [...document.querySelectorAll('.data-table tbody tr a')].find(
        (e) => e.getClientRects().length > 0
      );
      if (!link) throw new Error('no visible invoice row');
      link.click();
    });
    await page.waitForFunction(() => location.pathname.startsWith('/apps/accounting/action/20/'), {});
    await page.waitForSelector('form.record-form');
    const clicked = await page.evaluate(() => {
      const button = [...document.querySelectorAll('button')].find((e) => e.textContent.trim() === 'Post');
      if (!button) return false;
      button.click();
      return true;
    });
    if (!clicked) throw new Error('Post button not rendered');
    await page.waitForFunction(
      () => ![...document.querySelectorAll('button')].some((e) => e.textContent.trim() === 'Post'),
      { timeout: 10000 }
    );
    return `${quotationNumber} posted`;
  });

  await step('app switcher', async () => {
    await page.click('#app-switcher-btn');
    await sleep(150);
    if ((await page.$eval('#app-switcher-btn', (e) => e.getAttribute('aria-expanded'))) !== 'true') {
      throw new Error('switcher did not open');
    }
    await page.click('#app-switcher-btn');
    return 'opens and closes';
  });
} finally {
  await browser.close();
}

console.log(JSON.stringify({ base: BASE, results, errors }, null, 2));
if (results.some((r) => r.status === 'FAIL') || errors.length) process.exitCode = 1;
