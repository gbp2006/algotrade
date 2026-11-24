/* Тема (dark/light) и плотность таблиц. Настройки — в localStorage вместе с
   состоянием вкладок; применяется до загрузки DOM, чтобы не было мигания. */
(() => {
  const KEY = 'algo.ui.v1';
  const read = () => {
    try {
      const v = JSON.parse(localStorage.getItem(KEY) || '{}');
      return v && typeof v === 'object' && !Array.isArray(v) ? v : {};
    } catch (_) { return {}; }
  };
  const write = (patch) => {
    const state = Object.assign(read(), patch);
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (_) {}
  };
  const theme = () => read().theme === 'light' ? 'light' : 'dark';
  const density = () => read().density === 'compact' ? 'compact' : 'comfortable';

  const apply = () => {
    document.documentElement.setAttribute('data-theme', theme());
    document.documentElement.setAttribute('data-density', density());
    document.querySelectorAll('[data-theme-toggle]').forEach((b) => {
      b.textContent = theme() === 'dark' ? '☀ Светлая' : '◐ Тёмная';
    });
    document.querySelectorAll('[data-density-toggle]').forEach((b) => {
      b.textContent = density() === 'compact' ? 'Компактная' : 'Комфортная';
    });
  };

  const bind = () => {
    document.querySelectorAll('[data-theme-toggle]').forEach((b) => {
      b.addEventListener('click', () => {
        write({ theme: theme() === 'dark' ? 'light' : 'dark' });
        apply();
      });
    });
    document.querySelectorAll('[data-density-toggle]').forEach((b) => {
      b.addEventListener('click', () => {
        write({ density: density() === 'compact' ? 'comfortable' : 'compact' });
        apply();
      });
    });
  };

  apply();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind);
  } else {
    bind();
  }
})();
