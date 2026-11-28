/* Проверяет 7 разделов: меню, вкладки, диалоги, безопасные контролы, правку счёта, deep-link, ошибки JS. */
import puppeteer from 'puppeteer-core';

const url = process.argv[2] || 'http://192.168.0.230/ui/';
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
  ['Мои роботы', 'Боевой контур', 'Инструменты', 'Мастер робота'],
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
  // Radix Tabs реагирует на клик мышью; DOM click() не переключает панель,
  // поэтому проверяем реальное содержимое каждой вкладки, а не одни подписи.
  for (let j = 0; j < tabCount; j += 1) {
    const tab = (await page.$$('button[role="tab"]'))[j];
    if (tab) await tab.click();
    await new Promise((r) => setTimeout(r, 500));
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

const base = url.replace(/\/ui\/?$/, '').replace(/\/$/, '');

// Диалоги проверяем только открытием/отменой: никаких сохранений и заявок.
// Настоящий клик мышью нужен и здесь (Radix слушает mousedown).
const clickButton = async (p, text, root = p) => {
  for (const handle of await root.$$('button')) {
    const label = (await handle.evaluate((item) => item.textContent ?? '')).trim();
    if (label === text) { await handle.click(); return true; }
  }
  return false;
};
const checkDialog = async (p, openText, marker, closeText) => {
  if (!await clickButton(p, openText)) {
    problems.push(`диалоги: нет кнопки «${openText}»`);
    return;
  }
  await new Promise((r) => setTimeout(r, 500));
  const dialog = await p.$('[role="dialog"]');
  if (!dialog) { problems.push(`диалог «${openText}» не открылся`); return; }
  const text = (await dialog.evaluate((item) => item.innerText || '')).toLowerCase();
  if (!text.includes(marker.toLowerCase())) problems.push(`диалог «${openText}»: нет «${marker}»`);
  if (!await clickButton(p, closeText, dialog)) problems.push(`диалог «${openText}»: нет кнопки «${closeText}»`);
  await new Promise((r) => setTimeout(r, 400));
  if (await p.$('[role="dialog"]')) problems.push(`диалог «${openText}» не закрылся`);
};

// Регрессия правки счёта: старый ID уходит в URL PATCH, новый — только в new_id.
// Запрос перехватывается и не меняет реальные данные.
await page.goto(`${base}/accounts`, { waitUntil: 'networkidle2', timeout: 30000 });
await new Promise((r) => setTimeout(r, 1200));
let patched = null;
const onRequest = (req) => {
  if (req.method() === 'PATCH' && req.url().includes('/api/accounts/')) {
    patched = { url: req.url(), body: req.postData() || '' };
    return req.respond({ status: 200, contentType: 'application/json', body: '{}' });
  }
  req.continue();
};
await page.setRequestInterception(true);
page.on('request', onRequest);
try {
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('button')]
      .find((item) => item.textContent?.trim() === 'Изменить');
    btn?.click();
  });
  await new Promise((r) => setTimeout(r, 500));
  await page.evaluate(() => {
    const input = document.querySelector('input[placeholder="например 2115210 или КлФ-2115210"]');
    if (!input) throw new Error('нет поля ID счёта');
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(input, 'КлФ-9999999');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await new Promise((r) => setTimeout(r, 250));
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('button')]
      .find((item) => item.textContent?.trim() === 'Сохранить');
    btn?.click();
  });
  await new Promise((r) => setTimeout(r, 900));
} finally {
  page.off('request', onRequest);
  await page.setRequestInterception(false);
}
if (!patched) problems.push('правка счёта: PATCH не отправлен');
else {
  const oldId = decodeURIComponent((patched.url.split('/api/accounts/')[1] || '').split('?')[0]);
  const body = JSON.parse(patched.body || '{}');
  if (oldId === 'КлФ-9999999') problems.push('правка счёта: новый ID попал в URL');
  if (body.new_id !== 'КлФ-9999999') problems.push('правка счёта: новый ID не передан в new_id');
}

// Регрессия сохранения ключа: секрет идёт в /api/keys, ссылка — в PATCH счёта.
// Оба запроса перехватываются — реальные данные не меняются.
let keyPost = null;
let keyPatch = null;
const onKeyRequest = (req) => {
  if (req.method() === 'POST' && req.url().includes('/api/keys')) {
    keyPost = req.postData() || '';
    return req.respond({ status: 200, contentType: 'application/json',
      body: '{"key_ref":"acc:2115213","saved":true}' });
  }
  if (req.method() === 'PATCH' && req.url().includes('/api/accounts/')) {
    keyPatch = { url: req.url(), body: req.postData() || '' };
    return req.respond({ status: 200, contentType: 'application/json', body: '{}' });
  }
  req.continue();
};
await page.setRequestInterception(true);
page.on('request', onKeyRequest);
try {
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('button')]
      .find((item) => item.textContent?.trim() === 'Ключ');
    btn?.click();
  });
  await new Promise((r) => setTimeout(r, 400));
  await page.evaluate(() => {
    const input = document.querySelector('[role="dialog"] input[type="password"]');
    if (!input) throw new Error('нет поля API-ключа');
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(input, 'tapi_sk_тестовый');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await new Promise((r) => setTimeout(r, 250));
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll('[role="dialog"] button')]
      .find((item) => item.textContent?.trim() === 'Сохранить');
    btn?.click();
  });
  await new Promise((r) => setTimeout(r, 900));
} finally {
  page.off('request', onKeyRequest);
  await page.setRequestInterception(false);
}
if (!keyPost || !JSON.parse(keyPost || '{}').secret) problems.push('ключ: секрет не отправлен в /api/keys');
if (!keyPatch) problems.push('ключ: PATCH счёта с key_ref не отправлен');
else {
  const accId = decodeURIComponent((keyPatch.url.split('/api/accounts/')[1] || '').split('?')[0]);
  const body = JSON.parse(keyPatch.body || '{}');
  if (body.key_ref !== `acc:${accId}`) problems.push('ключ: PATCH не привязал acc:<id> к счёту');
}

// Регрессия поиска по строкам таблицы: react-table уходил в бесконечный
// setState-цикл на нестабильной ссылке отфильтрованных строк, вкладка
// умирала («страница подвешена»). Здесь проверяем, что ввод в поле поиска
// не вешает страницу и таблица фильтруется.
const searchQuery = await page.evaluate(() => {
  const cell = document.querySelector('tbody tr td');
  return (cell?.textContent ?? '').trim().slice(0, 3);
});
if (!searchQuery) problems.push('поиск по строкам: в таблице счетов нет строк');
else {
  try {
    await page.evaluate((text) => {
      const input = document.querySelector('input[placeholder="Поиск по строкам таблицы"]');
      if (!input) throw new Error('нет поля поиска по строкам');
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(input, text);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }, searchQuery);
    const filtered = await Promise.race([
      page.evaluate(() => document.querySelectorAll('tbody tr').length),
      new Promise((_, reject) => setTimeout(() => reject(new Error('страница не отвечает 5 c')), 5000)),
    ]);
    if (!filtered) problems.push('поиск по строкам: все строки отфильтровались');
  } catch (error) {
    problems.push(`поиск по строкам: ${error.message}`);
  }
}

// Сводка справочника инструментов должна быть фразой, а не сырым JSON.
const catalog = await browser.newPage();
watch(catalog);
await catalog.goto(`${base}/robots`, { waitUntil: 'networkidle2', timeout: 30000 });
await new Promise((r) => setTimeout(r, 1200));
// Radix переключается только на настоящем клике мыши, не на DOM click().
for (const handle of await catalog.$$('button[role="tab"]')) {
  const label = await handle.evaluate((item) => item.textContent ?? '');
  if (label.includes('Инструменты')) { await handle.click(); break; }
}
await new Promise((r) => setTimeout(r, 900));
const stats = await catalog.evaluate(() => {
  const node = [...document.querySelectorAll('div')]
    .find((item) => item.textContent?.startsWith('Инструментов в каталоге:'));
  return node?.textContent?.trim() ?? '';
});
if (!stats) problems.push('инструменты: нет человекочитаемой сводки справочника');
if (stats.startsWith('{')) problems.push('инструменты: сводка показывает сырой JSON');
await catalog.close();

// Подтверждение удаления счёта и инспектор JSON логов: открыть и отменить.
const dialogs = await browser.newPage();
watch(dialogs);
await dialogs.goto(`${base}/accounts`, { waitUntil: 'domcontentloaded', timeout: 30000 });
await new Promise((r) => setTimeout(r, 1800));
await checkDialog(dialogs, 'Удалить', 'Удалить счёт', 'Отмена');
await dialogs.goto(`${base}/logs`, { waitUntil: 'domcontentloaded', timeout: 30000 });
await new Promise((r) => setTimeout(r, 2200));
await checkDialog(dialogs, 'JSON', 'Контекст:', 'Закрыть');

// Мастер и расписание робота — карточки внутри вкладки «Мастер робота».
await dialogs.goto(`${base}/robots`, { waitUntil: 'domcontentloaded', timeout: 30000 });
await new Promise((r) => setTimeout(r, 1800));
if (!await clickButton(dialogs, 'Настроить')) problems.push('робот: нет кнопки «Настроить»');
await new Promise((r) => setTimeout(r, 1500));
let robotText = (await dialogs.evaluate(() => document.body.innerText || '')).toLowerCase();
if (!robotText.includes('редактирование робота') || !robotText.includes('расписание робота')) {
  problems.push('робот: карточки редактирования и расписания не открылись');
}
if (!await clickButton(dialogs, 'Отмена')) problems.push('робот: нет кнопки «Отмена» в мастере');
await new Promise((r) => setTimeout(r, 500));
for (const handle of await dialogs.$$('button[role="tab"]')) {
  const label = await handle.evaluate((item) => item.textContent ?? '');
  if (label.includes('Мастер робота')) { await handle.click(); break; }
}
await new Promise((r) => setTimeout(r, 900));
robotText = (await dialogs.evaluate(() => document.body.innerText || '')).toLowerCase();
if (!robotText.includes('мастер создания робота')) problems.push('робот: мастер создания не открылся');
await dialogs.close();

// Прямые ссылки всех разделов: панель сама меняет URL через pushState,
// поэтому обновление страницы обязано открывать тот же раздел, а не 404.
const deep = await browser.newPage();
watch(deep);
for (const [path, label] of [
  ['/portfolio', 'Портфель и обзор'], ['/charts', 'Торговля и графики'],
  ['/robots', 'Роботы и алгоритмы'], ['/simulation', 'Тестирование'],
  ['/accounts', 'Счета и брокеры'], ['/history', 'Операции и сделки'],
  ['/logs', 'Логи и диагностика'], ['/ui/logs', 'Логи и диагностика'],
]) {
  await deep.goto(`${base}${path}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await new Promise((r) => setTimeout(r, 900));
  const active = await deep.evaluate(() =>
    document.querySelector('aside button.bg-accent')?.textContent?.trim() ?? '');
  if (!active.includes(label)) problems.push(`deep-link ${path}: активен «${active}», ждали «${label}»`);
}
await deep.close();

console.log(JSON.stringify({ results, problems }, null, 2));
await browser.close();
if (problems.length || results.some((row) => row.length < 100)) process.exitCode = 1;
