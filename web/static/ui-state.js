/* Запоминание состояния интерфейса: вкладка, подвкладка, выбранные сущности. */
(() => {
  const KEY = 'algo.ui.v1';
  const read = () => {
    try {
      const v = JSON.parse(localStorage.getItem(KEY) || '{}');
      // Защита от старого повреждённого состояния (строки/массивы вместо объекта):
      // Object.assign со строкой превращал ключи в позиции и ломал запоминание выбора.
      return v && typeof v === 'object' && !Array.isArray(v) ? v : {};
    } catch (_) { return {}; }
  };
  const write = (patch) => {
    const state = Object.assign(read(), patch);
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (_) {}
    return state;
  };
  window.UIState = {
    state: read,
    get: (k, fallback) => (k in read() ? read()[k] : fallback),
    // Поддерживаем оба вызова: set({k: v}) и set('k', v) — последний раньше
    // записывал в localStorage символы ключа вместо самих настроек.
    set: (patch, value) => write(typeof patch === 'string' ? { [patch]: value } : (patch || {})),
  };

  document.addEventListener('DOMContentLoaded', () => {
    const nav = document.querySelector('[data-ui-nav]');
    if (nav) nav.addEventListener('click', (e) => {
      const a = e.target.closest('a[data-section]');
      if (a) write({ section: a.dataset.section, lastSection: a.getAttribute('href') });
    });

    document.querySelectorAll('[data-ui-sub]').forEach((el) => {
      el.addEventListener('click', () => write({ lastSub: el.dataset.uiSub }));
    });

    document.querySelectorAll('[data-ui-restore]').forEach((el) => {
      const key = el.dataset.uiRestore;
      const saved = read()[key];
      if (saved !== undefined) el.value = saved;
      el.addEventListener('change', () => write({ [key]: el.value }));
    });

    // Повторное открытие корня возвращает на последний рабочий раздел.
    if (location.pathname === '/' && !location.search.includes('home=1')) {
      const saved = read();
      if (saved.lastSection && saved.lastSection !== '/') {
        let target;
        try { target = new URL(saved.lastSection, location.origin); } catch (_) {}
        if (target && target.origin === location.origin) {
          if (saved.lastSection === '/trade' && saved.lastSub
              && !target.searchParams.has('mode')) {
            target.searchParams.set('mode', saved.lastSub);
          }
          location.replace(target.pathname + target.search);
        }
      }
    }
  });
})();
