"""Веб-дашборд бумажной торговли: тёмный интерфейс, 6 конфигураций.

Запуск: uvicorn web.app:app --host 0.0.0.0 --port 8080
Доступ: без авторизации — панель открыта только в домашней сети / через VPN.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

ROOT = Path(__file__).resolve().parent.parent
PAPER = ROOT / "results" / "paper.csv"
LOG = ROOT / "results" / "daily.log"
STOP = ROOT / "results" / "STOP"
HEALTH = ROOT / "results" / "health.json"
ALERTS = ROOT / "results" / "alerts_seen.json"
MSK = timezone(timedelta(hours=3))
MULT = 1000.0

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except Exception:
    pass

import sys  # noqa: E402

sys.path.insert(0, str(ROOT))
from algo.broker.finam import FinamBroker  # noqa: E402
from algo.configs import BY_ID, CONFIGS  # noqa: E402
from algo.robot_configs import ROBOT_BY_ID, ROBOT_CONFIGS  # noqa: E402
from algo.instruments import DEFAULT, INSTRUMENTS, margin, symbol as inst_symbol  # noqa: E402
from algo.portfolio import (CAPITAL, account_card, drawdown_stats,  # noqa: E402
                            exposure_of, ledger)
from algo import metrics_store  # noqa: E402


def instrument_of(cfg):
    return INSTRUMENTS.get(cfg.instrument, DEFAULT)


def capital_of(cfg) -> float:
    return float(cfg.capital or CAPITAL)

app = FastAPI(title="Algo dashboard")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")

_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, ttl: int, fn):
    now = time.time()
    if key in _cache and now - _cache[key][0] < ttl:
        return _cache[key][1]
    val = fn()
    _cache[key] = (now, val)
    return val

# Фоновое обновление health.json каждые 5 минут
import threading
import time

def _health_refresh_loop() -> None:
    """Каждые 5 мин пересчитывает results/health.json через scripts/40_watchdog.py."""
    script = str(ROOT / "scripts" / "40_watchdog.py")
    while True:
        try:
            subprocess.run([sys.executable, script], capture_output=True, text=True, timeout=120)
        except Exception:  # noqa: BLE001 — обновление не должно ронять панель
            pass
        time.sleep(300)

@app.on_event("startup")
def _startup_health() -> None:
    threading.Thread(target=_health_refresh_loop, daemon=True).start()

REMOTE = os.environ.get("ALGO_PANEL_REMOTE", "").rstrip("/")


def _remote_paper() -> str | None:
    """Журнал с боевой панели: локальная копия смотрит на сервер, иначе пусто."""
    def fetch():
        try:
            with urllib.request.urlopen(f"{REMOTE}/api/paper.csv", timeout=3) as r:
                return r.read().decode("utf-8")
        except Exception:  # noqa: BLE001 — сервер недоступен: читаем локальный файл
            return None
    return _cached("paper:remote", 5, fetch)


def read_paper() -> list[dict]:
    text = _remote_paper() if REMOTE else None
    if text is None:
        if not PAPER.exists():
            return []
        text = PAPER.read_text(encoding="utf-8")
    return [r for r in csv.DictReader(text.splitlines()) if "config" in r]


def alerts_digest(wd: dict | None) -> str:
    """Отпечаток набора алертов сторожа.

    Меняется только когда меняется сам текст проблем/замечаний, а не время
    проверки — иначе «прочитано» не дожило бы до следующего прогона.
    """
    if not wd:
        return ""
    items = list(wd.get("problems") or []) + list(wd.get("warnings") or [])
    if not items:
        return ""
    return hashlib.sha1("\n".join(items).encode("utf-8")).hexdigest()[:16]


def alerts_seen() -> str:
    """Отпечаток, который пользователь отметил прочитанным."""
    if not ALERTS.exists():
        return ""
    try:
        return str(json.loads(ALERTS.read_text(encoding="utf-8")).get("digest", ""))
    except Exception:  # noqa: BLE001 — битый файл не должен ронять панель
        return ""


def quote_for(inst, day=None) -> dict:
    """Котировка инструмента (символ резолвится на дату) — кэш 10 с."""
    sym = inst_symbol(inst, day)

    def fetch():
        b = FinamBroker()
        q = b.quote(sym)
        return {"symbol": sym, "bid": q.bid, "ask": q.ask, "last": q.last,
                "spread_ticks": round((q.ask - q.bid) / inst.tick), "ts": q.timestamp}
    return _cached(f"quote:{sym}", 10, fetch)


ALL_CONFIGS = CONFIGS + ROBOT_CONFIGS
ALL_BY_ID = {**BY_ID, **ROBOT_BY_ID}


def quote(config_id: str | None = None) -> dict:
    cfg = ALL_BY_ID.get(config_id) if config_id else ALL_CONFIGS[0]
    return quote_for(instrument_of(cfg or ALL_CONFIGS[0]))


def price_series(inst=None) -> list[list]:
    inst = inst or instrument_of(CONFIGS[0])

    def fetch():
        b = FinamBroker()
        sym = inst_symbol(inst)
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        df = b.bars(sym, "TIME_FRAME_M5", start, end)
        return [[d.strftime("%H:%M"), round(float(v), inst.digits)] for d, v in
                zip(df.index, df["close"])]
    return _cached(f"price:{inst.code}", 30, fetch)


TF_MAP = {
    "M1": "TIME_FRAME_M1", "M5": "TIME_FRAME_M5", "M15": "TIME_FRAME_M15",
    "M30": "TIME_FRAME_M30", "H1": "TIME_FRAME_H1", "D": "TIME_FRAME_D",
}


def candles(tf: str = "M5", days: int = 2, config_id: str | None = None) -> list[list]:
    """Свечи [метка, open, high, low, close] по таймфрейму."""
    cfg = ALL_BY_ID.get(config_id) if config_id else ALL_CONFIGS[0]
    inst = instrument_of(cfg or ALL_CONFIGS[0])

    def fetch():
        b = FinamBroker()
        sym = inst_symbol(inst)
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        df = b.bars(sym, TF_MAP.get(tf, "TIME_FRAME_M5"), start, end)
        fmt = "%d.%m %H:%M" if tf != "D" else "%d.%m"
        return [[d.strftime(fmt), float(o), float(h), float(l), float(c)]
                for d, o, h, l, c in zip(df.index, df["open"], df["high"],
                                         df["low"], df["close"])]
    return _cached(f"candles:{inst.code}:{tf}:{days}", 20, fetch)


def timer_state(name: str) -> str:
    try:
        r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=3)
        return r.stdout.strip() or "unknown"
    except Exception:
        return "n/a"


def config_stats(cfg, rows: list[dict], price: float | None = None) -> dict:
    inst = instrument_of(cfg)
    mult, capital, go = inst.mult, capital_of(cfg), margin(inst)
    state = ledger(rows, cfg.id, mult, capital)
    card = account_card(state, price, mult, go, capital) if price else {
        "capital": capital, "equity": round(state["equity"]), "realized": 0,
        "unrealized": 0, "contracts": state["position"], "notional": 0, "margin": 0,
        "free": round(state["equity"]), "exposure_pct": 0.0,
        "pnl_pct": 0.0, "trades": state["trades"]}
    mine = [r for r in rows if r["config"] == cfg.id]
    last = mine[-1] if mine else None
    equity_pts, dd_points = [], []
    acc, pos, entry = capital, 0, 0.0
    for r in mine:
        target = int(r["target"])
        px_ = float(r["price"])
        if target != pos:
            if pos != 0:
                acc += (px_ - entry) * mult * pos
                dd_points.append((r["date"], acc))
                equity_pts.append([r["date"][5:] + " " + r["time"], round(acc)])
            if target != 0:
                entry = px_
            pos = target
    dd = drawdown_stats(dd_points)
    return {
        "id": cfg.id,
        "name": cfg.display or cfg.id,
        "title": cfg.display or cfg.id,
        "desc": cfg.comment,
        "params": dict(cfg.params),
        "instrument": inst.code,
        "instrument_label": inst.label,
        "digits": inst.digits,
        "position": card["contracts"],
        "entry_price": round(state["entry"], inst.digits),
        "entry_time": last["date"][5:] + " " + last["time"] if last else "",
        "pnl": card["realized"],
        "unrealized": card["unrealized"],
        "trades": card["trades"],
        "equity": equity_pts,
        "card": {**card, **dd},
        "last": last,
        "status": "live" if card["contracts"] != 0 else ("waiting" if mine else "offline"),
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # шаблон меняется при деплое — браузер не должен держать старую копию
    return templates.TemplateResponse(request, "index.html", {},
                                      headers={"Cache-Control": "no-store"})


@app.get("/favicon.ico")
def favicon():
    return RedirectResponse("/static/img/favicon.ico")


@app.get("/api/paper.csv")
def paper_csv():
    """Сырой журнал: локальная панель тянет его с боевой (ALGO_PANEL_REMOTE)."""
    if not PAPER.exists():
        return PlainTextResponse("", media_type="text/plain")
    return PlainTextResponse(PAPER.read_text(encoding="utf-8"), media_type="text/plain")


@app.get("/api/state")
def state():
    rows = read_paper()
    q = None
    try:
        q = quote()
    except Exception as e:  # noqa: BLE001
        q = {"error": str(e)[:120]}
    try:
        prices = price_series()
    except Exception:
        prices = []
    log = []
    if LOG.exists():
        log = LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]

    price = q.get("last") if q and "last" in q else None
    snap = {r["config"]: r for r in metrics_store.latest()}
    strategies = []
    for cfg in ALL_CONFIGS:
        try:
            qc = quote_for(instrument_of(cfg))
            px_c = qc.get("last")
        except Exception:  # noqa: BLE001 — один инструмент не должен ронять панель
            qc, px_c = None, None
        item = config_stats(cfg, rows, px_c)
        item["quote"] = qc
        item["metrics"] = snap.get(cfg.id)
        strategies.append(item)
    del price
    portfolio = {
        "capital": sum(x["card"]["capital"] for x in strategies),
        "equity": sum(x["card"]["equity"] for x in strategies),
        "pnl": sum(x["card"]["realized"] + x["card"]["unrealized"] for x in strategies),
        "notional": sum(x["card"]["notional"] for x in strategies),
        "margin": sum(x["card"]["margin"] for x in strategies),
        "contracts": sum(abs(x["card"]["contracts"]) for x in strategies),
        "accounts": len(strategies),
    }
    portfolio["pnl_pct"] = (round(100 * portfolio["pnl"] / portfolio["capital"], 2)
                            if portfolio["capital"] else 0.0)
    portfolio["exposure_pct"] = (round(100 * portfolio["notional"] / portfolio["equity"], 1)
                                 if portfolio["equity"] else 0.0)

    wd = json.loads(HEALTH.read_text(encoding="utf-8")) if HEALTH.exists() else None
    ok = bool(wd and wd.get("ok"))
    digest = alerts_digest(wd)
    if not digest and ALERTS.exists():
        ALERTS.unlink()          # алертов нет — снимаем отметку, чтобы повтор показать
    seen = alerts_seen()

    return JSONResponse({
        "generated": datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S"),
        "quote": q,
        "prices": prices,
        "strategies": strategies,
        "portfolio": portfolio,
        "health": {
            "status": "OK" if ok else "PROBLEMS",
            "timers": {"morning": timer_state("algotrading-morning.timer"),
                       "daily": timer_state("algotrading-daily.timer"),
                       "web": timer_state("algotrading-web.service")},
            "stop": STOP.exists(),
            "watchdog": wd,
            "alerts": {"digest": digest, "seen": seen,
                       "dismissed": bool(digest) and digest == seen},
            "log": log,
        },
        "ok": ok,
    })


def config_detail(cfg_id: str) -> dict:
    """Сделки, эквити и сравнение с бэктестом по одной конфигурации."""
    cfg = ALL_BY_ID.get(cfg_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="нет такой конфигурации")
    rows = [r for r in read_paper() if r["config"] == cfg_id]
    inst = instrument_of(cfg)
    mult, capital = inst.mult, capital_of(cfg)

    trades = []
    pos = 0
    entry = 0.0
    opened = None
    realized = 0.0
    equity = []
    dd_points = []
    peak = 0.0
    max_dd = 0.0

    for r in rows:
        target = int(r["target"])
        price = float(r["price"])
        if target == pos:
            continue
        if pos != 0 and opened is not None:
            pnl = (price - entry) * mult * pos
            realized += pnl
            peak = max(peak, realized)
            max_dd = min(max_dd, realized - peak)
            trades.append({
                "open_date": opened[0], "open_time": opened[1],
                "close_date": r["date"], "close_time": r["time"],
                "dir": "LONG" if pos > 0 else "SHORT",
                "entry": round(entry, inst.digits), "exit": round(price, inst.digits),
                "pnl": round(pnl, 0),
            })
            equity.append([r["date"][5:] + " " + r["time"], round(realized, 0)])
            dd_points.append((r["date"], capital + realized))
        if target != 0:
            entry = price
            opened = (r["date"], r["time"])
        pos = target

    unrealized = 0.0
    if pos != 0 and opened is not None:
        try:
            q = quote_for(inst)
            unrealized = (q["last"] - entry) * mult * pos
        except Exception:
            pass

    wins = [t for t in trades if t["pnl"] > 0]
    stats = {
        "trades": len(trades),
        "net": round(realized, 0),
        "unrealized": round(unrealized, 0),
        "winrate": round(100 * len(wins) / len(trades), 1) if trades else 0.0,
        "avg": round(realized / len(trades), 0) if trades else 0.0,
        "dd": round(max_dd, 0),
        "dd_days": drawdown_stats(dd_points)["max_dd_days"],
        "position": pos,
    }

    expected = None
    if rows:
        try:
            expected = _expected(cfg, rows[0]["date"], rows[-1]["date"])
        except Exception as e:  # noqa: BLE001
            expected = {"error": str(e)[:120]}

    return {"id": cfg.id, "title": cfg.display or cfg.id, "desc": cfg.comment,
            "params": dict(cfg.params), "instrument": inst.code,
            "instrument_label": inst.label, "digits": inst.digits,
            "stats": stats, "trades": trades,
            "open_trade": ({"dir": "LONG" if pos > 0 else "SHORT",
                            "entry": round(entry, inst.digits),
                            "opened": opened[0] + " " + opened[1] if opened else "",
                            "tip": ""} if pos != 0 and opened else None),
            "equity": equity, "expected": expected}


def _expected(cfg, start: str, end: str):
    """Что конфигурация дала бы на архиве за тот же период (кэш 1 час)."""
    inst = instrument_of(cfg)
    mult, capital = inst.mult, capital_of(cfg)

    def calc():
        from algo.data import load_cached
        from algo.live import decision
        m5 = load_cached(inst.file, 5)
        days = sorted({d for d in m5.index.date
                       if str(d) >= start and str(d) <= end and d.weekday() < 5})
        from algo.portfolio import size_contracts
        pos, entry, pnl, trades = 0, 0.0, 0.0, 0
        for day in days:
            dec = decision(cfg, m5[m5.index.date <= day], day)
            if dec is None:
                continue
            contracts = size_contracts(capital + pnl, dec.price, mult,
                                              exposure_of(cfg)) if dec.target != 0 else 0
            target = dec.target * contracts
            if target == pos:
                continue
            if pos != 0:
                pnl += (dec.price - entry) * mult * pos
                trades += 1
            if target != 0:
                entry = dec.price
            pos = target
        return {"net": round(pnl, 0), "trades": trades, "days": len(days)}
    return _cached(f"expected:{cfg.id}:{start}:{end}", 3600, calc)


@app.get("/api/config/{cfg_id}")
def api_config(cfg_id: str):
    try:
        return JSONResponse(config_detail(cfg_id))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)[:200]})


@app.get("/api/robot-compare")
def api_robot_compare():
    """Ежедневная сверка четырёх новых роботов с базовыми конфигурациями."""
    spec = importlib.util.spec_from_file_location(
        "paper_report", ROOT / "scripts" / "32_paper_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows, start, end = mod.build_rows()
    return JSONResponse({"start": start, "end": end,
                         "comparison": mod.robot_compare(rows)})


@app.get("/api/metrics")
def api_metrics(config: str | None = None):
    """История состояния счёта и метрик из SQLite (для графиков и анализа)."""
    metrics_store.init_db()
    return JSONResponse({
        "latest": metrics_store.latest(config),
        "history": metrics_store.history(config) if config else [],
        "equity": metrics_store.equity_curve(config) if config else [],
    })


@app.get("/api/trades")
def api_trades(config: str | None = None):
    """Сделки для mark-ов на графике (вход/выход/открытая позиция)."""
    cfg = ALL_BY_ID.get(config) if config else ALL_CONFIGS[0]
    if cfg is None:
        return JSONResponse({"error": "нет конфигурации"})
    rows = [r for r in read_paper() if r["config"] == cfg.id]
    inst = instrument_of(cfg)
    mult = inst.mult
    trades = []
    pos, entry, opened = 0, 0.0, None
    for r in rows:
        target = int(r["target"])
        price = float(r["price"])
        if target == pos:
            continue
        if pos != 0 and opened:
            trades.append({
                "dir": "LONG" if pos > 0 else "SHORT",
                "in": opened[0][5:] + " " + opened[1], "in_px": round(entry, inst.digits),
                "out": r["date"][5:] + " " + r["time"], "out_px": round(price, inst.digits),
                "pnl": round((price - entry) * mult * pos, 0),
            })
        if target != 0:
            entry, opened = price, (r["date"], r["time"])
        pos = target
    open_trade = None
    if pos != 0 and opened:
        open_trade = {
            "dir": "LONG" if pos > 0 else "SHORT",
            "in": opened[0][5:] + " " + opened[1], "in_px": round(entry, inst.digits),
        }
    return JSONResponse({"config": cfg.id, "trades": trades, "open": open_trade})


@app.get("/api/health")
def api_health():
    """Статус бумажного теста: таймеры, стоп-флаг, свежесть данных, журнал.

    Для внешних мониторов: 200, если ok, иначе 503 (проблемы — в теле).
    """
    wd = None
    if HEALTH.exists():
        try:
            wd = json.loads(HEALTH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — битый health.json не должен ронять панель
            wd = None
    ok = bool(wd and wd.get("ok"))
    return JSONResponse({
        "status": "OK" if ok else "PROBLEMS",
        "checked": (wd or {}).get("checked"),
        "problems": (wd or {}).get("problems") or [],
        "warnings": (wd or {}).get("warnings") or [],
        "data_date": (wd or {}).get("data_date"),
        "rows": (wd or {}).get("rows") or 0,
        "stop": bool(STOP.exists()),
    }, status_code=200 if ok else 503)


@app.get("/api/candles")
def api_candles(tf: str = "M5", days: int = 2, config: str | None = None):
    try:
        return JSONResponse({"tf": tf, "config": config,
                             "candles": candles(tf, days, config)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"tf": tf, "candles": [], "error": str(e)[:160]})


@app.get("/api/quote")
def api_quote(config: str | None = None):
    try:
        key = f"quote_fast:{config or 'default'}"
        return JSONResponse(_cached(key, 2, lambda: {
            **quote(config), "ts_now": datetime.now(MSK).strftime("%H:%M:%S")}))
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)[:160]})


@app.post("/api/stop")
def toggle_stop():
    if STOP.exists():
        STOP.unlink()
        return {"stop": False}
    STOP.write_text(datetime.now(MSK).isoformat(), encoding="utf-8")
    return {"stop": True}


@app.post("/api/alerts/ack")
def ack_alerts():
    """Отметить текущий набор алертов прочитанным (общий для всех браузеров)."""
    wd = json.loads(HEALTH.read_text(encoding="utf-8")) if HEALTH.exists() else None
    digest = alerts_digest(wd)
    if not digest:
        ALERTS.unlink(missing_ok=True)
        return {"digest": "", "dismissed": False}
    ALERTS.write_text(json.dumps({"digest": digest,
                                  "at": datetime.now(MSK).isoformat()},
                                 ensure_ascii=False), encoding="utf-8")
    return {"digest": digest, "dismissed": True}
