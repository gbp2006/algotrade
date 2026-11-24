/* Headless-проверка GUI: открывает /ui, ловит ошибки JS и проверяет рендер. */
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
await new Promise((resolve) => setTimeout(resolve, 2500));
const info = await page.evaluate(() => ({
  rootLength: document.getElementById('root')?.innerHTML.length ?? 0,
  text: (document.body.innerText || '').slice(0, 400),
  sections: [...document.querySelectorAll('aside button')].map((el) => el.textContent?.trim()),
}));
console.log(JSON.stringify({ url, ...info, problems }, null, 2));
await browser.close();
if (!info.rootLength || problems.length) process.exitCode = 1;
