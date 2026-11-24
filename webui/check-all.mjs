/* Проверяет все 7 разделов: клики по меню, ошибки JS и факт рендера. */
import puppeteer from 'puppeteer-core';

const url = process.argv[2] || 'http://192.168.0.230:8080/ui/';
const browser = await puppeteer.launch({
  executablePath: '/usr/bin/google-chrome',
  headless: true,
  args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
});
const page = await browser.newPage();
const problems = [];
page.on('console', (msg) => {
  if (msg.type() === 'error') problems.push(`console: ${msg.text()}`);
});
page.on('pageerror', (err) => problems.push(`pageerror: ${err.message}`));
page.on('requestfailed', (req) =>
  problems.push(`requestfailed: ${req.url()} ${req.failure()?.errorText ?? ''}`));

await page.goto(url, { waitUntil: 'networkidle2', timeout: 30000 });
await new Promise((r) => setTimeout(r, 1500));

const results = [];
for (let i = 0; i < 7; i += 1) {
  await page.evaluate((index) => {
    (document.querySelectorAll('aside button')[index] ?? document.querySelector('aside button'))?.click();
  }, i);
  await new Promise((r) => setTimeout(r, 1800));
  const tabCount = await page.evaluate(() => document.querySelectorAll('button[role="tab"]').length);
  for (let j = 0; j < tabCount; j += 1) {
    await page.evaluate((index) => {
      (document.querySelectorAll('button[role="tab"]')[index])?.click();
    }, j);
    await new Promise((r) => setTimeout(r, 400));
  }
  const info = await page.evaluate((tabs) => ({
    name: document.querySelector('aside button.bg-accent')?.textContent?.trim() ?? '?',
    length: document.getElementById('root')?.innerHTML.length ?? 0,
    text: (document.body.innerText || '').slice(0, 90).replace(/\n/g, ' '),
    tabs,
  }), tabCount);
  results.push({ ...info, errors: problems.length });
}
console.log(JSON.stringify({ results, problems }, null, 2));
await browser.close();
if (problems.length || results.some((row) => row.length < 100)) process.exitCode = 1;
