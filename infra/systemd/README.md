# systemd-юниты WSL

Источники всех юнитов, которые реально работают на `wsl-algo`. До 28.11 в git
было только 5 файлов, остальные жили только на сервере; теперь хранятся здесь.
Состояние на 28.11 скопировано с WSL дословно, включая флаги и расписания.

| Юнит | Расписание (МСК) | Что делает |
|---|---|---|
| `algotrading-web.service` | всегда | панель uvicorn `:80` |
| `algotrading-scheduler.service` | всегда | внутренний планировщик заданий `inst:*`; в репозитории `ALGO_SCHEDULER_MODE=robots` |
| `algotrading-scheduler.service.d/override.conf` | — | на WSL старые флаги `SHADOW=0`, `ONLY_ROBOTS=1` дают тот же режим `robots` |
| `algotrading-backup.timer` | 03:00 ежедневно | бэкап трёх БД (`95_backup_db.py`) |
| `algotrading-channel.timer` | пн–пт, каждые 10 мин 09:00–23:50 | `--channel` бумажного раннера (`31_paper_live.py`) |
| `algotrading-morning.timer` | пн–пт 10:25 | утренний выход (`31_paper_live.py`) |
| `algotrading-daily.timer` | пн–пт 13:55 | `paper-live`, `update`, `report` |
| `algotrading-shadow.timer` | пн–пт 13:57 | теневой прогон G3 (`33_shadow_live.py`) |
| `algotrading-update-live.timer` | каждые 10 мин | добор баров Финама (`10b_append_finam.py`) |
| `algotrading-friday.timer` | пт 18:45 | тот же `daily.service` — закрытие позиций перед выходными |

`ALGO_VOL_ROLLOVER=1` выставлен в `daily`/`morning`/`channel.service`:
квартальные ноги выбираются по VOL так же, как в бэктесте.

Установка/обновление на WSL (только по явному решению — таймеры влияют на
счёт дней бумаги и тени):

```bash
sudo cp infra/systemd/algotrading-*.service infra/systemd/algotrading-*.timer /etc/systemd/system/
sudo cp infra/systemd/algotrading-scheduler.service.d/override.conf /etc/systemd/system/algotrading-scheduler.service.d/
sudo systemctl daemon-reload
sudo systemctl enable --now algotrading-daily.timer algotrading-morning.timer \
  algotrading-channel.timer algotrading-shadow.timer algotrading-update-live.timer \
  algotrading-friday.timer algotrading-backup.timer
```

Скрипт выкладки копирует эти файлы только в `~/algotrading/infra/systemd/` —
установленные юниты в `/etc/systemd/system/` он не трогает.
