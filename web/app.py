"""Веб-дашборд бумажной торговли: тёмный интерфейс, 6 конфигураций.

Запуск: uvicorn web.app:app --host 0.0.0.0 --port 8080
Доступ: basic-auth из .env (DASH_USER / DASH_PASS).
"""

from __future__ import annotations

import csv
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

ROOT = Path(__file__).resolve().parent.parent
PAPER = ROOT / "results" / "paper.csv"
LOG = ROOT / "results" / "daily.log"
STOP = ROOT / "results" / "STOP"
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
from algo.configs import CONFIGS  # noqa: E402

app = FastAPI(title="Algo dashboard")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
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
    return _cached("price", 120, fetch)


def timer_state(name: str) -> str:
    try:
        r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=3)
        return r.stdout.strip() or "unknown"
    except Exception:
        return "n/a"


def config_stats(cfg, rows: list[dict]) -> dict:
    mine = [r for r in rows if r["config"] == cfg.id]
    pos, entry, entry_time = 0, 0.0, ""
    realized = 0.0
    trades = 0
    equity: list[list] = []
    for r in mine:
        target = int(r["target"])
        price = float(r["price"])
        if target != pos:
            if pos != 0:
                realized += (price - entry) * MULT * pos
                trades += 1
                equity.append([r["date"][5:] + " " + r["time"], round(realized)])
            if target != 0:
                entry, entry_time = price, r["date"][5:] + " " + r["time"]
            pos = target
    last = mine[-1] if mine else None
    return {
        "id": cfg.id,
        "name": cfg.display or cfg.id,
        "title": cfg.display or cfg.id,
        "desc": cfg.comment,
        "position": pos,
        "entry_price": round(entry, 3),
        "entry_time": entry_time,
        "pnl": round(realized, 0),
        "trades": trades,
        "equity": equity,
        "last": last,
        "status": "live" if pos != 0 else ("waiting" if mine else "offline"),
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

    strategies = []
    for cfg in CONFIGS:
        s = config_stats(cfg, rows)
        if q and "last" in q and s["position"] != 0 and s["entry_price"]:
            s["unrealized"] = round((q["last"] - s["entry_price"]) * MULT * s["position"], 0)
        else:
            s["unrealized"] = 0
        strategies.append(s)

    return JSONResponse({
        "generated": datetime.now(MSK).strftime("%Y-%m-%d %H:%M:%S"),
        "quote": q,
        "prices": prices,
        "strategies": strategies,
        "health": {
            "timers": {"morning": timer_state("algotrading-morning.timer"),
                       "daily": timer_state("algotrading-daily.timer"),
                       "web": timer_state("algotrading-web.service")},
            "stop": STOP.exists(),
            "log": log,
        },
    })


@app.post("/api/stop")
def toggle_stop(_: str = Depends(auth)):
    if STOP.exists():
        STOP.unlink()
        return {"stop": False}
    STOP.write_text(datetime.now(MSK).isoformat(), encoding="utf-8")
    return {"stop": True}
