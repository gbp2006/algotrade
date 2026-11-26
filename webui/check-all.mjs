/* Проверяет 7 разделов: menu, вкладки, безопасные контролы, deep-link, ошибки JS. */
import puppeteer from 'puppeteer-core';

const url = process.argv[2] || 'http://192.168.0.230:8080/ui/';
const browser = await puppeteer.launch({
  executablePath: '/usr/bin/google-chrome',
  headless: true,
  args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
});
const page = await browser.newPage();
const problems = [];
const watch = (p) => {
  p.on('console', (msg) => {
    if (msg.type() === 'error') problems.push(`console: ${msg.text()}`);
  });
  p.on('pageerror', (err) => problems.push(`pageerror: ${err.message}`));
  p.on('requestfailed', (req) =>
    problems.push(`requestfailed: ${req.url()} ${req.failure()?.errorText ?? ''}`));
};
watch(page);

// Проверяем только подписи вкладок: они стабильны и не зависят от данных.
const REQUIRED = [
  ['Сводка и кривая капитала', 'Позиции', 'Аллокация', 'Метрики и статистика'],
  ['Свечи и индикаторы', 'Сделки роботов', 'Заявки брокера', 'Пополнения и снятия'],
  ['Мои роботы', 'Боевой контур', 'Инструменты', 'Расписание', 'Мастер робота'],
  ['Песочница и прогоны', 'Симулятор потоков капитала'],
  ['Счета', 'Брокеры и коннекторы', 'Операции и предпросмотр'],
  ['Сделки и заявки', 'Операции по счетам', 'История пересчёта лотности'],
  ['Все логи', 'Заявки и сделки', 'Роботы', 'Планировщик', 'Здоровье и API'],
];
// Только безопасные действия: не трогаем ARM, STOP, удаление и реальные заявки.
const SAFE_CLICKS = ['Опросить счета', 'Проверить', 'Рассчитать лот'];

await page.goto(url, { waitUntil: 'networkidle2', timeout: 30000 });
await new Promise((r) => setTimeout(r, 1500));

const results = [];
for (let i = 0; i < 7; i += 1) {
  await page.evaluate((index) => {
    (document.querySelectorAll('aside button')[index] ?? document.querySelector('aside button'))?.click();
  }, i);
  await new Promise((r) => setTimeout(r, 1800));
  const tabCount = await page.evaluate(() => document.querySelectorAll('button[role="tab"]').length);
  let seen = '';
  for (let j = 0; j < tabCount; j += 1) {
    await page.evaluate((index) => {
      (document.querySelectorAll('button[role="tab"]')[index])?.click();
    }, j);
    await new Promise((r) => setTimeout(r, 400));
    seen += await page.evaluate(() => document.body.innerText || '');
  }
  for (const label of SAFE_CLICKS) {
    await page.evaluate((text) => {
      const button = [...document.querySelectorAll('button')]
        .find((item) => item.textContent?.trim() === text);
      button?.click();
    }, label);
    await new Promise((r) => setTimeout(r, 250));
  }
  for (const marker of REQUIRED[i] ?? []) {
    if (!seen.includes(marker)) problems.push(`раздел ${i}: нет «${marker}»`);
  }
  const info = await page.evaluate((tabs) => ({
    name: document.querySelector('aside button.bg-accent')?.textContent?.trim() ?? '?',
    length: document.getElementById('root')?.innerHTML.length ?? 0,
    text: (document.body.innerText || '').slice(0, 90).replace(/\n/g, ' '),
    tabs,
  }), tabCount);
  results.push({ ...info, errors: problems.length });
}

// Прямая ссылка должна открывать раздел, а не последний сохранённый в localStorage.
const base = url.replace(/\/ui\/?$/, '').replace(/\/$/, '');
const deep = await browser.newPage();
watch(deep);
await deep.goto(`${base}/robots`, { waitUntil: 'networkidle2', timeout: 30000 });
await new Promise((r) => setTimeout(r, 1200));
const active = await deep.evaluate(() =>
  document.querySelector('aside button.bg-accent')?.textContent?.trim() ?? '');
if (!active.includes('Роботы')) problems.push(`deep-link /robots: активен «${active}»`);
await deep.close();

console.log(JSON.stringify({ results, problems }, null, 2));
await browser.close();
if (problems.length || results.some((row) => row.length < 100)) process.exitCode = 1;
