# web/ — локальная панель

FastAPI + Jinja, запускается `./run.sh dash` на `127.0.0.1:8809`.

- `app.py` — API и страницы: стратегии, бумажный контур, здоровье, алерты.
- `templates/` — HTML-шаблоны.
- `static/` — css/js/иконки (обложка `img/hero.jpg` — из `../assets/`).
- Лог процесса — `../results/web-local.log`.

Панель читает `results/` и `reports/`; данные рынка — через `algo.data`.
