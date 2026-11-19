"""Веб-дашборд бумажной торговли: тёмный интерфейс, 6 конфигураций.

Запуск: uvicorn web.app:app --host 0.0.0.0 --port 8080
Доступ: basic-auth из .env (DASH_USER / DASH_PASS).
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

ROOT = Path(__file__).resolve().parent.parent
PAPER = ROOT / "results" / "paper.csv"
LOG = ROOT / "results" / "daily.log"
STOP = ROOT / "results" / "STOP"
HEALTH = ROOT / "results" / "health.json"
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
from algo.portfolio import CAPITAL, account_card, ledger  # noqa: E402

app = FastAPI(title="Algo dashboard")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")
security = HTTPBasic(auto_error=False)

_cache: dict[str, tuple[float, object]] = {}


def auth(cred: HTTPBasicCredentials | None = Depends(security)) -> str:
    if os.environ.get("DASH_OPEN") == "1":   # локальная отладка без пароля
        return "guest"
    user = os.environ.get("DASH_USER", "zt")
    pwd = os.environ.get("DASH_PASS", "algo")
    if cred is None or cred.username != user or cred.password != pwd:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="auth required",
                            headers={"WWW-Authenticate": "Basic"})
    return cred.username


def _cached(key: str, ttl: int, fn):
    now = time.time()
    if key in _cache and now - _cache[key][0] < ttl:
        return _cache[key][1]
    val = fn()
    _cache[key] = (now, val)
    return val


def read_paper() -> list[dict]:
    if not PAPER.exists():
        return []
    with PAPER.open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if "config" in r]


def quote():
    def fetch():
        b = FinamBroker()
        q = b.quote("CNYRUBF@RTSX")
        return {"bid": q.bid, "ask": q.ask, "last": q.last,
                "spread_ticks": round((q.ask - q.bid) * 1000), "ts": q.timestamp}
    return _cached("quote", 10, fetch)


def price_series() -> list[list]:
    def fetch():
        b = FinamBroker()
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        df = b.bars("CNYRUBF@RTSX", "TIME_FRAME_M5", start, end)
        return [[d.strftime("%H:%M"), round(float(v), 3)] for d, v in
                zip(df.index, df["close"])]
    return _cached("price", 30, fetch)


TF_MAP = {
    "M1": "TIME_FRAME_M1", "M5": "TIME_FRAME_M5", "M15": "TIME_FRAME_M15",
    "M30": "TIME_FRAME_M30", "H1": "TIME_FRAME_H1", "D": "TIME_FRAME_D",
}


def candles(tf: str = "M5", days: int = 2) -> list[list]:
    """Свечи [метка, open, high, low, close] по таймфрейму."""
    def fetch():
        b = FinamBroker()
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        df = b.bars("CNYRUBF@RTSX", TF_MAP.get(tf, "TIME_FRAME_M5"), start, end)
        fmt = "%d.%m %H:%M" if tf != "D" else "%d.%m"
        return [[d.strftime(fmt), float(o), float(h), float(l), float(c)]
                for d, o, h, l, c in zip(df.index, df["open"], df["high"],
                                         df["low"], df["close"])]
    return _cached(f"candles:{tf}:{days}", 20, fetch)


def timer_state(name: str) -> str:
    try:
        r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=3)
        return r.stdout.strip() or "unknown"
    except Exception:
        return "n/a"


def config_stats(cfg, rows: list[dict], price: float | None = None) -> dict:
    state = ledger(rows, cfg.id)
    card = account_card(state, price) if price else {
        "capital": CAPITAL, "equity": round(state["equity"]), "realized": 0,
        "unrealized": 0, "contracts": state["position"], "notional": 0, "margin": 0,
        "free": round(state["equity"]), "exposure_pct": 0.0,
        "pnl_pct": 0.0, "trades": state["trades"]}
    mine = [r for r in rows if r["config"] == cfg.id]
    last = mine[-1] if mine else None
    equity_pts, acc = [], CAPITAL
    for r in mine:
        if r.get("action") == "решение":
            acc = CAPITAL + ledger([x for x in mine if (x["date"], x["time"]) <= (r["date"], r["time"])], cfg.id)["realized"]
            equity_pts.append([r["date"][5:] + " " + r["time"], round(acc)])
    return {
        "id": cfg.id,
        "name": cfg.display or cfg.id,
        "title": cfg.display or cfg.id,
        "desc": cfg.comment,
        "params": dict(cfg.params),
        "position": card["contracts"],
        "entry_price": round(state["entry"], 3),
        "entry_time": last["date"][5:] + " " + last["time"] if last else "",
        "pnl": card["realized"],
        "unrealized": card["unrealized"],
        "trades": card["trades"],
        "equity": equity_pts,
        "card": card,
        "last": last,
        "status": "live" if card["contracts"] != 0 else ("waiting" if mine else "offline"),
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request, _: str = Depends(auth)):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/api/state")
def state(_: str = Depends(auth)):
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
    strategies = [config_stats(cfg, rows, price) for cfg in CONFIGS]
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

    return JSONResponse({
        "generated": datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S"),
        "quote": q,
        "prices": prices,
        "strategies": strategies,
        "portfolio": portfolio,
        "health": {
            "timers": {"morning": timer_state("algotrading-morning.timer"),
                       "daily": timer_state("algotrading-daily.timer"),
                       "web": timer_state("algotrading-web.service")},
            "stop": STOP.exists(),
            "watchdog": json.loads(HEALTH.read_text(encoding="utf-8")) if HEALTH.exists() else None,
            "log": log,
        },
    })


def config_detail(cfg_id: str) -> dict:
    """Сделки, эквити и сравнение с бэктестом по одной конфигурации."""
    cfg = BY_ID.get(cfg_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="нет такой конфигурации")
    rows = [r for r in read_paper() if r["config"] == cfg_id]

    trades = []
    pos = 0
    entry = 0.0
    opened = None
    realized = 0.0
    equity = []
    peak = 0.0
    max_dd = 0.0

    for r in rows:
        target = int(r["target"])
        price = float(r["price"])
        if target == pos:
            continue
        if pos != 0 and opened is not None:
            pnl = (price - entry) * MULT * pos
            realized += pnl
            peak = max(peak, realized)
            max_dd = min(max_dd, realized - peak)
            trades.append({
                "open_date": opened[0], "open_time": opened[1],
                "close_date": r["date"], "close_time": r["time"],
                "dir": "LONG" if pos > 0 else "SHORT",
                "entry": round(entry, 3), "exit": round(price, 3),
                "pnl": round(pnl, 0),
            })
            equity.append([r["date"][5:] + " " + r["time"], round(realized, 0)])
        if target != 0:
            entry = price
            opened = (r["date"], r["time"])
        pos = target

    unrealized = 0.0
    if pos != 0 and opened is not None:
        try:
            q = quote()
            unrealized = (q["last"] - entry) * MULT * pos
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
        "position": pos,
    }

    expected = None
    if rows:
        try:
            expected = _expected(cfg, rows[0]["date"], rows[-1]["date"])
        except Exception as e:  # noqa: BLE001
            expected = {"error": str(e)[:120]}

    return {"id": cfg.id, "title": cfg.display or cfg.id, "desc": cfg.comment,
            "params": dict(cfg.params), "stats": stats, "trades": trades,
            "equity": equity, "expected": expected}


def _expected(cfg, start: str, end: str):
    """Что конфигурация дала бы на архиве за тот же период (кэш 1 час)."""
    def calc():
        from algo.data import load_cached
        from algo.live import decision
        m5 = load_cached("2026-11/CNYRUBF.txt", 5)
        days = sorted({d for d in m5.index.date
                       if str(d) >= start and str(d) <= end and d.weekday() < 5})
        from algo.portfolio import size_contracts
        pos, entry, pnl, trades = 0, 0.0, 0.0, 0
        for day in days:
            dec = decision(cfg, m5[m5.index.date <= day], day)
            if dec is None:
                continue
            contracts = size_contracts(CAPITAL + pnl, dec.price) if dec.target != 0 else 0
            target = dec.target * contracts
            if target == pos:
                continue
            if pos != 0:
                pnl += (dec.price - entry) * MULT * pos
                trades += 1
            if target != 0:
                entry = dec.price
            pos = target
        return {"net": round(pnl, 0), "trades": trades, "days": len(days)}
    return _cached(f"expected:{cfg.id}:{start}:{end}", 3600, calc)


@app.get("/api/config/{cfg_id}")
def api_config(cfg_id: str, _: str = Depends(auth)):
    try:
        return JSONResponse(config_detail(cfg_id))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)[:200]})


@app.get("/api/candles")
def api_candles(tf: str = "M5", days: int = 2, _: str = Depends(auth)):
    try:
        return JSONResponse({"tf": tf, "candles": candles(tf, days)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"tf": tf, "candles": [], "error": str(e)[:160]})


@app.get("/api/quote")
def api_quote(_: str = Depends(auth)):
    try:
        return JSONResponse(_cached("quote_fast", 2, lambda: {
            **quote(), "ts_now": datetime.now(MSK).strftime("%H:%M:%S")}))
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)[:160]})


@app.post("/api/stop")
def toggle_stop(_: str = Depends(auth)):
    if STOP.exists():
        STOP.unlink()
        return {"stop": False}
    STOP.write_text(datetime.now(MSK).isoformat(), encoding="utf-8")
    return {"stop": True}
