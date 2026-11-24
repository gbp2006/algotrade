// Единый словарь человекочитаемых подписей для всех экранов панели.
// Технические значения (id, ORDER_STATUS_*, коды типов) остаются в APIs и в
// атрибутах title/data — здесь только то, что видит человек. Файл подключается
// в <head> без defer, поэтому хелперы доступны всем встроенным скриптам.
(function () {
  'use strict';

  const ORDER = {
    planned: 'Запланирована', sent: 'Отправлена', partial: 'Частично',
    filled: 'Исполнена', cancelled: 'Отменена', rejected: 'Отклонена',
    uncertain: 'Не определена', skipped: 'Пропущена', blocked: 'Заблокирована',
    duplicate: 'Дубль', error: 'Ошибка', dry_run: 'Репетиция',
  };
  const ROBOT = {
    draft: 'Черновик', active: 'Работает', paused: 'На паузе',
    stopped: 'Остановлен', archived: 'В архиве',
  };
  const MODE = {
    paper: 'Бумажный', live: 'Боевой', test: 'Тестовый', archive: 'Архив',
  };
  const HEALTH = { OK: 'Всё в порядке', PROBLEMS: 'Есть проблемы' };
  const SIDE = {
    buy: 'Покупка', sell: 'Продажа', long: 'Лонг', short: 'Шорт',
    LONG: 'Лонг', SHORT: 'Шорт', hold: 'Держать', HOLD: 'Держать',
  };
  const SOURCE = {
    orders: 'Заявки', instances: 'Роботы', scheduler: 'Таймеры',
    health: 'Здоровье', journal: 'Журнал', bot: 'Робот', web: 'Панель',
  };
  const RUN = {
    ok: 'Успешно', success: 'Успешно', error: 'Ошибка', failed: 'Ошибка',
    missed: 'Пропущен', skipped: 'Пропущен', running: 'Выполняется',
  };
  const TYPE = {
    CURRENCIES: 'Валютные фьючерсы', FUTURES: 'Фьючерсы', EQUITIES: 'Акции',
    BONDS: 'Облигации', MONEY_MARKET: 'Фонды денежного рынка',
    ETF: 'Фонды и паи', FUNDS: 'Фонды и паи',
  };

  function pick(dict, value, fallback) {
    const raw = String(value == null ? '' : value);
    const key = raw.replace(/^ORDER_STATUS_/i, '').toLowerCase();
    if (Object.prototype.hasOwnProperty.call(dict, raw)) return dict[raw];
    if (Object.prototype.hasOwnProperty.call(dict, key)) return dict[key];
    return fallback == null ? (raw || '—') : fallback;
  }

  const orderStatus = v => pick(ORDER, v);
  const robotStatus = v => pick(ROBOT, v);
  const mode = v => pick(MODE, v);
  const health = v => pick(HEALTH, v);
  const side = v => pick(SIDE, v);
  const source = v => pick(SOURCE, v);
  const runStatus = v => pick(RUN, v);

  // Короткое имя стратегии берём из первого предложения описания:
  // «Простушка (Примечание №6 автора): …» → «Простушка».
  function strategyName(spec) {
    if (!spec) return '—';
    if (spec.title || spec.display) return spec.title || spec.display;
    const head = String(spec.about || spec.description || '')
      .split('(')[0].split(':')[0].trim();
    return head || spec.id || '—';
  }

  // Приоритет: human-readable имя конфигурации; technical id — второстепенный слой.
  function humanName(item) {
    if (!item) return '—';
    if (typeof item === 'string') return item;
    const direct = item.label || item.title || item.display || item.name;
    if (direct) return String(direct);
    const note = String(item.note || item.description || '');
    // Длинные примечания — это описание, а не имя: берём имя стратегии + id.
    if (note && note.length <= 60) return note;
    if (item.about) return `${strategyName(item)} · ${item.id || ''}`.trim();
    return note ? note.slice(0, 57) + '…' : String(item.id || '—');
  }

  const num = (v, digits) => (v == null || v === '')
    ? '—'
    : Number(v).toLocaleString('ru-RU', { maximumFractionDigits: digits == null ? 0 : digits });
  const money = v => (v == null || v === '') ? '—' : `${num(v)} ₽`;
  const qty = v => (v == null || v === '') ? '—' : num(v);

  // Группы инструментов: валюта → индексы → акции → сырьё → фонды → прочее.
  const GROUPS = [
    { title: 'Валютные фьючерсы', re: /CURRENC|\bCNY\b|\bUSD\b|\bEUR\b/i },
    { title: 'Индексы', re: /\bRTS\b|INDEX|ИНДЕКС/i },
    { title: 'Сырьё и золото', re: /GOLD|METAL|OIL|GAS|COMMOD|ЗОЛОТ|НЕФТ/i },
    { title: 'Акции', re: /EQUIT|STOCK|SHARE|\bMOEX\b/i },
    { title: 'Фонды и паи', re: /FUND|MONEY_MARKET|\bETF\b|\bПАИ?\b/i },
  ];
  function instrumentGroup(type, symbol, name) {
    const raw = [type, symbol, name].filter(Boolean).join(' ');
    if (type && Object.prototype.hasOwnProperty.call(TYPE, String(type).toUpperCase()))
      return TYPE[String(type).toUpperCase()];
    for (const g of GROUPS) if (g.re.test(raw)) return g.title;
    return 'Прочее';
  }
  function byTypePhrase(byType) {
    if (!byType || typeof byType !== 'object') return '—';
    const parts = Object.entries(byType)
      .map(([k, v]) => `${instrumentGroup(k)}: ${num(v)}`);
    return parts.length ? parts.join(', ') : '—';
  }

  // В тексте лога переводим только статусы — ids и числа оставляем нетронутыми.
  function logText(text) {
    return String(text == null ? '' : text)
      .replace(/\b(planned|sent|partial|filled|cancelled|rejected|uncertain)\b/g,
               m => ORDER[m] || m);
  }

  // Служебное решение превращаем в фразу; неизвестный текст оставляем как есть.
  function decision(text) {
    if (text == null || text === '') return '—';
    const s = String(text);
    if (/^HOLD\b/i.test(s)) return 'Решение: держать' + (/flat/i.test(s) ? ', позиции нет' : '');
    if (/^BUY\b/i.test(s)) return 'Решение: купить';
    if (/^SELL\b/i.test(s)) return 'Решение: продать';
    return 'Решение: ' + s;
  }

  window.UILabels = {
    orderStatus, robotStatus, mode, health, side, source, runStatus, humanName, strategyName,
    num, money, qty, instrumentGroup, byTypePhrase, decision, logText,
    ORDER, ROBOT, MODE, HEALTH, SIDE, SOURCE, TYPE,
  };
})();
