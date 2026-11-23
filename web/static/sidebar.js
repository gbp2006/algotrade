// Общий список стратегий в боковой панели вкладок «Торговля» и «Роботы».
// На вкладке «Тест» список рисует основной скрипт: там выбор стратегии локальный.
(async function () {
  const box = document.getElementById('list');
  if (!box) return;
  const esc = s => String(s ?? '').replace(/[&<>"]/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  try {
    const r = await fetch('/api/state', { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    const items = data.strategies || [];
    box.innerHTML = items.length
      ? items.map(s => `
          <a class="item" href="/?config=${encodeURIComponent(s.id)}" title="${esc(s.title || s.id)}">
            <span class="ico">${s.strategy === 'prostushka' ? 'П' : 'У'}</span>
            <span class="nm">${esc(s.title || s.id)}</span>
            <span class="st ${esc(s.status || '')}"></span>
          </a>`).join('')
      : '<div class="hint">стратегий нет</div>';
  } catch (e) {
    box.innerHTML = '<div class="hint">список стратегий недоступен</div>';
  }
})();
