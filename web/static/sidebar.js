// Общий сайдбар вкладок. На «Тесте» — все стратегии (основной скрипт рисует
// свой список), на «Торговле» и «Роботах» — только боевые инстансы.
(async function () {
  const box = document.getElementById('list');
  if (!box) return;
  const esc = s => String(s ?? '').replace(/[&<>"]/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const liveContext = ['/trade', '/robots'].includes(location.pathname);
  try {
    let items = [];
    if (liveContext) {
      const r = await fetch('/api/instances?mode=live', { cache: 'no-store' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      items = (await r.json()).map(i => ({
        id: i.id, title: i.id, strategy: i.spec_id,
        status: i.status === 'active' ? 'live' : i.status,
      }));
      box.innerHTML = items.length
        ? items.map(s => `
            <a class="item" href="/robots?mode=live" title="${esc(s.title)}">
              <span class="ico">${s.strategy === 'prostushka' ? 'П' : 'У'}</span>
              <span class="nm">${esc(s.title)}</span>
              <span class="st ${esc(s.status)}"></span>
            </a>`).join('')
        : '<div class="hint">боевых роботов нет</div>';
      return;
    }
    const r = await fetch('/api/state', { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    items = data.strategies || [];
    box.innerHTML = items.length
      ? items.map(s => `
          <a class="item" href="/?config=${encodeURIComponent(s.id)}" title="${esc(s.title || s.id)}">
            <span class="ico">${s.strategy === 'prostushka' ? 'П' : 'У'}</span>
            <span class="nm">${esc(s.title || s.id)}</span>
            <span class="st ${esc(s.status || '')}"></span>
          </a>`).join('')
      : '<div class="hint">стратегий нет</div>';
  } catch (e) {
    box.innerHTML = '<div class="hint">список недоступен</div>';
  }
})();
