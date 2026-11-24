"""OsEngine MCP batch: 17 портов × 2025/2026, сравнение с нашим движком."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path("/mnt/DiskD/opencode-algo")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "/tmp/opencode")

from osengine_mcp_client import Client  # noqa: E402
from algo import engine, results  # noqa: E402
from algo.data import load_cached  # noqa: E402
from algo.portfolio import size_contracts  # noqa: E402
from algo.strategies import channel_break, prostushka, universal  # noqa: E402
from algo.strategies import candidates as C  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "portfolio_returns", ROOT / "scripts" / "85_portfolio_returns.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

FOLDER5 = "Z:\\mnt\\DiskD\\opencode-algo\\cache\\osengine_compare\\algo_2023_2026"
FOLDER60 = "Z:\\mnt\\DiskD\\opencode-algo\\cache\\osengine_compare\\algo_h1_2023_2026"
WINDOWS = {
    "2025": ("2024-01-01T00:00:00", "2025-01-01T00:00:00", "2026-01-01T00:00:00"),
    "2026": ("2025-01-01T00:00:00", "2026-01-01T00:00:00", "2026-11-23T23:59:59"),
}
REPORT = ROOT / "reports" / "osengine-port-comparison.md"

# id, bot, security, timeframe, params, mult, deposit
CONFIGS = [
    ("p-base", "AlgoProstushka", "CNY.txt", "Min5",
     {"MA period": 40, "Entry hour": 13, "Entry minute": 50, "Filter bars": 3,
      "Allow short Friday": False, "Skip weekends": True, "Multiplier": 1000}, 1000.0, 200000),
    ("p-fast", "AlgoProstushka", "CNY.txt", "Min5",
     {"MA period": 50, "Entry hour": 13, "Entry minute": 40, "Filter bars": 6,
      "Allow short Friday": True, "Skip weekends": True, "Multiplier": 1000}, 1000.0, 200000),
    ("p-friday", "AlgoProstushka", "CNY.txt", "Min5",
     {"MA period": 40, "Entry hour": 13, "Entry minute": 50, "Filter bars": 3,
      "Allow short Friday": False, "Skip weekends": True, "Multiplier": 1000}, 1000.0, 200000),
    ("u-base", "AlgoUniversal", "CNY.txt", "Min5",
     {"Ref hour": 10, "Ref minute": 5, "Entry hour": 13, "Entry minute": 30,
      "Long offset": 0.004, "Short offset": 0.002, "Hold": "Daily",
      "Allow short Friday": False, "Skip weekends": True, "Multiplier": 1000}, 1000.0, 200000),
    ("u-wide", "AlgoUniversal", "CNY.txt", "Min5",
     {"Ref hour": 10, "Ref minute": 5, "Entry hour": 13, "Entry minute": 30,
      "Long offset": 0.001, "Short offset": 0.001, "Hold": "Daily",
      "Allow short Friday": False, "Skip weekends": True, "Multiplier": 1000}, 1000.0, 200000),
    ("u-morning", "AlgoUniversal", "CNY.txt", "Min5",
     {"Ref hour": 10, "Ref minute": 5, "Entry hour": 13, "Entry minute": 30,
      "Exit hour": 10, "Exit minute": 20, "Long offset": 0.004, "Short offset": 0.002,
      "Hold": "Morning", "Allow short Friday": False, "Skip weekends": True,
      "Multiplier": 1000}, 1000.0, 200000),
    ("p-rts", "AlgoProstushka", "RTS.txt", "Min5",
     {"MA period": 40, "Entry hour": 13, "Entry minute": 50, "Filter bars": 3,
      "Allow short Friday": False, "Skip weekends": True, "Multiplier": 1.644562}, 1.644562, 260000),
    ("p-gold", "AlgoProstushka", "GOLD.txt", "Min5",
     {"MA period": 40, "Entry hour": 13, "Entry minute": 50, "Filter bars": 3,
      "Allow short Friday": False, "Skip weekends": True, "Multiplier": 82.2281}, 82.2281, 450000),
    ("p-ma50", "AlgoProstushka", "CNY.txt", "Min5",
     {"MA period": 50, "Entry hour": 13, "Entry minute": 50, "Filter bars": 3,
      "Allow short Friday": False, "Skip weekends": True, "Multiplier": 1000}, 1000.0, 200000),
    ("p-fast2", "AlgoProstushka", "CNY.txt", "Min5",
     {"MA period": 50, "Entry hour": 13, "Entry minute": 40, "Filter bars": 3,
      "Allow short Friday": True, "Skip weekends": True, "Multiplier": 1000}, 1000.0, 200000),
    ("u-1340", "AlgoUniversal", "CNY.txt", "Min5",
     {"Ref hour": 10, "Ref minute": 5, "Entry hour": 13, "Entry minute": 40,
      "Long offset": 0.004, "Short offset": 0.002, "Hold": "Daily",
      "Allow short Friday": False, "Skip weekends": True, "Multiplier": 1000}, 1000.0, 200000),
    ("p-train", "AlgoProstushka", "CNY.txt", "Min5",
     {"MA period": 50, "Entry hour": 13, "Entry minute": 40, "Filter bars": 1,
      "Allow short Friday": False, "Skip weekends": True, "Multiplier": 1000}, 1000.0, 200000),
    ("cb-day", "AlgoChannelBreak", "CNY.txt", "Min5",
     {"Start hour": 1, "Start minute": 0, "Switch hour": 13, "Switch minute": 0,
      "Stop loss": 0.12, "Direction": "Long", "Multiplier": 1000}, 1000.0, 200000),
    ("cb-day-si", "AlgoChannelBreak", "SI.txt", "Min5",
     {"Start hour": 1, "Start minute": 0, "Switch hour": 13, "Switch minute": 0,
      "Stop loss": 1000, "Direction": "Long", "Multiplier": 1}, 1.0, 200000),
    ("d20-cn", "AlgoDonchian", "CNY.txt", "Min5",
     {"Entry": 20, "Exit": 10, "Entry hour": 13, "Entry minute": 55,
      "Allow short": True, "Multiplier": 1000}, 1000.0, 200000),
    ("d20-si", "AlgoDonchian", "SI.txt", "Min5",
     {"Entry": 20, "Exit": 10, "Entry hour": 13, "Entry minute": 55,
      "Allow short": True, "Multiplier": 1}, 1.0, 200000),
]

DATA_CACHE = {}


def data_for(inst):
    if inst not in DATA_CACHE:
        if inst in ("CNY", "Si"):
            name = "Si.txt" if inst == "Si" else "CNYRUBF.txt"
            DATA_CACHE[inst] = load_cached(ROOT / "data" / "2026-11" / name, 5)
        else:
            old = load_cached(ROOT / "data" / "2025.12" / f"{inst}.txt", 5)
            new = load_cached(ROOT / "cache" / "iss" / f"{inst}_2026_M5_cont.txt", 5)
            DATA_CACHE[inst] = pd.concat([old, new]).sort_index()
    return DATA_CACHE[inst]


def our_targets(cfg_id, df):
    if cfg_id.startswith("p-") and cfg_id not in ("p-gold", "p-rts"):
        p = next(x for x in CONFIGS if x[0] == cfg_id)[4]
        return prostushka.targets(
            df, ma_period=round(p["MA period"]), entry_time=f"{p['Entry hour']:02d}:{p['Entry minute']:02d}",
            filter_bars=p["Filter bars"], use_filter_long=True,
            allow_short_friday=p["Allow short Friday"], skip_weekend=True)
    if cfg_id in ("p-rts", "p-gold", "p-base", "p-friday"):
        p = next(x for x in CONFIGS if x[0] == cfg_id)[4]
        return prostushka.targets(df, ma_period=p["MA period"],
                                  entry_time=f"{p['Entry hour']:02d}:{p['Entry minute']:02d}",
                                  filter_bars=p["Filter bars"], use_filter_long=True,
                                  allow_short_friday=p["Allow short Friday"], skip_weekend=True)
    if cfg_id.startswith("u-"):
        p = next(x for x in CONFIGS if x[0] == cfg_id)[4]
        return universal.targets(df, ref_time=f"{p['Ref hour']:02d}:{p['Ref minute']:02d}",
                                 entry_time=f"{p['Entry hour']:02d}:{p['Entry minute']:02d}",
                                 long_offset=p["Long offset"], short_offset=p["Short offset"],
                                 hold=p["Hold"].lower(),
                                 exit_time=f"{p.get('Exit hour',10):02d}:{p.get('Exit minute',20):02d}",
                                 skip_weekend=True)
    if cfg_id.startswith("cb-"):
        p = next(x for x in CONFIGS if x[0] == cfg_id)[4]
        return channel_break.targets(df, start_time="01:00", switch_time="13:00",
                                     direction=p["Direction"].lower(), sl=p["Stop loss"],
                                     boundary_mode="first_bar", channel_mode="day",
                                     tick=0.001 if cfg_id == "cb-day" else 1.0,
                                     skip_weekend=True)
    if cfg_id.startswith("d20"):
        return C.donchian(df, entry=20, exit_=10, at="13:55", allow_short=True)
    raise ValueError(cfg_id)


def our_stats(cfg_id, inst, start, end, mult, deposit):
    df = data_for(inst)
    if cfg_id == "p-h1":
        df = df.resample("60min", label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min",
             "close": "last", "vol": "sum"}).dropna(subset=["close"])
    tg = our_targets(cfg_id, df)
    costs = m.SPECS[inst]["costs"]
    res = engine.run(df, tg, costs)
    tr = [t for t in res.trades if pd.Timestamp(start) <= t.exit_time < pd.Timestamp(end)
          and t.entry_price > 0]
    capital = deposit
    peak = capital
    dd = 0.0
    for t in tr:
        size = size_contracts(capital, abs(t.entry_price), mult, 1.0)
        capital += t.net * size
        peak = max(peak, capital)
        dd = min(dd, capital - peak)
    gains = sum(t.net for t in tr if t.net > 0)
    losses = sum(-t.net for t in tr if t.net < 0)
    return dict(trades=len(tr), profit=capital - deposit,
                pct=100 * (capital / deposit - 1), pf=gains / losses if losses else 0.0,
                dd_pct=100 * dd / peak)


def wait_data(c, folder):
    # переключение Set -> Folder: без тикла OsEngine не пересобирает хранилище
    c.tool("optimizer_data_set_config", {"source_type": "Set",
                                         "set_name": "project_SI_2023_2025"})
    time.sleep(2)
    c.tool("optimizer_data_set_config", {
        "source_type": "Folder", "folder_path": folder,
        "type_tester_data": "Candle",
        "date_from": "2023-01-01T00:00:00", "date_to": "2026-11-23T23:59:59"})
    for _ in range(40):
        cfg = c.tool("optimizer_data_get_config", {})
        s = c.tool("optimizer_data_get_status", {})
        if (cfg.get("folder_path") == folder and s.get("is_loaded")
                and s.get("securities_count", 0) > 0):
            time.sleep(3)
            return s
        time.sleep(1)
    raise RuntimeError(f"data not loaded: {folder}")


def run_one(c, cfg_id, bot, security, tf, params, mult, deposit, year):
    _, start, end = WINDOWS[year]
    wait_data(c, FOLDER60 if tf == "Hour1" else FOLDER5)
    c.tool("optimizer_bot_set", {"strategy_name": bot, "is_script": True})
    tabs = c.tool("optimizer_bot_tab_get_config", {})["tabs"]
    c.tool("optimizer_bot_tab_set_config", {
        "tab_name": tabs[0]["tab_name"], "security_name": security,
        "time_frame": tf})
    existing = c.tool("optimizer_params_get", {})["parameters"]
    items = []
    for p in existing:
        name = p["name"]
        if name not in params:
            continue
        v = params[name]
        item = {"name": name, "value": v, "on": False}
        if p["type"] in ("Int", "Decimal"):
            item.update(start=v, stop=v, step=1 if p["type"] == "Int" else 0.0001)
        items.append(item)
    # один включённый параметр с одним значением = один проход
    dummy = next(p for p in items if isinstance(p.get("value"), (int, float)) and not isinstance(p.get("value"), bool))
    dummy["on"] = True
    c.tool("optimizer_params_set", {"parameters": items})
    c.tool("optimizer_trade_settings_set", {
        "commission_type": "Percent", "commission_value": 0.01,
        "order_execution_type": "Intersection",
        "slippage_to_simple_order": 1, "slippage_to_stop_order": 1,
        "start_deposit": deposit})
    c.tool("optimizer_phases_set", {
        "time_start": start, "time_end": end,
        "iteration_count": 1, "percent_on_filtration": 100,
        "last_in_sample": True})
    n = c.tool("optimizer_get_pass_count", {})["pass_count"]
    if n != 1:
        raise RuntimeError(f"{cfg_id}/{year}: pass_count={n}")
    r = c.tool("optimizer_start", {})
    if not r.get("started"):
        raise RuntimeError(f"{cfg_id}/{year}: {r}")
    for _ in range(180):
        st = c.tool("optimizer_get_status", {})
        if not st.get("is_running"):
            break
        time.sleep(1)
    else:
        raise RuntimeError(f"{cfg_id}/{year}: timeout")
    rep = c.tool("optimizer_get_report", {"sort_type": "TotalProfit", "limit": 1})
    fazes = rep.get("fazes", [])
    if not fazes or not fazes[0].get("reports"):
        return dict(trades=0, profit=0.0, pct=0.0, pf=0.0, dd_pct=0.0, raw=0.0)
    x = fazes[0]["reports"][0]
    return dict(trades=x["positions_count"], profit=x["total_profit"] * mult,
                pct=x["total_profit"] * mult / deposit * 100,
                pf=x["profit_factor"], dd_pct=abs(x["max_draw_down"]) * 100,
                raw=x["total_profit"])


def load_done():
    """Уже посчитанные пары (id, год) и OE-метрики из отчёта."""
    done = {}
    if not REPORT.exists():
        return done
    for line in REPORT.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or " our " in line:
            continue
        cells = [x.strip() for x in line.strip("|").split("|")]
        if len(cells) != 5 or cells[0] in ("робот", "---") or cells[2] not in WINDOWS:
            continue
        try:
            oe = [float(x.replace("%", "")) for x in
                  [cells[4].split("/")[0].strip(),
                   cells[4].split("/")[1].strip(),
                   cells[4].split("/")[2].strip()]]
        except (ValueError, IndexError):
            continue
        done[(cells[0], cells[2])] = dict(trades=int(oe[0]), pct=oe[1], pf=oe[2],
                                          profit=oe[1] / 100 * dict(
                                              (x[0], x[6]) for x in CONFIGS)[cells[0]],
                                          dd_pct=0.0, raw=0.0)
    return done


def main():
    c = Client()
    rows = []
    done = load_done()
    for year in ("2025", "2026"):
        _, start, end = WINDOWS[year]
        for cfg_id, bot, sec, tf, params, mult, dep in CONFIGS:
            inst = "Si" if sec == "SI.txt" else sec[:-4].replace("CNY", "CNY")
            if inst not in ("CNY", "Si", "RTS", "GOLD"):
                inst = "CNY"
            if (cfg_id, year) in done:
                o = done[(cfg_id, year)]
            else:
                o = run_one(c, cfg_id, bot, sec, tf, params, mult, dep, year)
            a = our_stats(cfg_id, inst, start, end, mult, dep)
            print(f"{cfg_id:10} {year} our {a['trades']:4} {a['pct']:7.2f}% PF {a['pf']:5.2f} DD {a['dd_pct']:5.1f}%"
                  f" | OE {o['trades']:4} {o['pct']:7.2f}% PF {o['pf']:5.2f}")
            stats = dict(trades=o["trades"], net_profit=round(o["profit"], 2),
                         profit_factor=round(o["pf"], 2),
                         max_drawdown=round(-o["dd_pct"] * dep / 100, 2))
            if (cfg_id, year) not in done:
                results.record(strategy=f"osengine:{cfg_id}", instrument=inst,
                               period=year, stats=stats,
                               params=dict(bot=bot, security=sec, tf=tf, deposit=dep),
                               note=f"OsEngine MCP, normalized x{mult:g}; DD {o['dd_pct']:.1f}%")
            rows.append(dict(id=cfg_id, inst=inst, year=year, dep=dep, o=o, a=a))
            with REPORT.open("w", encoding="utf-8") as f:
                f.write(report_text(rows))


def report_text(rows):
    L = ["# Порт в OsEngine и сравнение: 2025 / 2026", "",
         f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Скрипты: `assets/osengine/*.cs`, ",
         "`scripts/osengine_*` (через MCP :6500, optimizer, один проход на точку).", "",
         "Одинаковые бары (наш M5 → OsEngine folder), издержки 0.01% + 1 тик, ",
         "сигнал по close → исполнение на следующем баре (Intersection), ",
         "100% номинала, тот же депозит. OsEngine PnL_norm = PnL_OE × multiplier ",
         "(в folder-режиме OsEngine не знает step cost инструмента).", "",
         "| робот | инстр. | год | наш сд / % / PF / DD% | OE сд / % / PF |",
         "|---|---|---|---:|---:|"]
    for r in rows:
        a, o = r["a"], r["o"]
        L.append(f"| {r['id']} | {r['inst']} | {r['year']} | "
                 f"{a['trades']} / {a['pct']:.2f}% / {a['pf']:.2f} / {a['dd_pct']:.1f}% | "
                 f"{o['trades']} / {o['pct']:.2f}% / {o['pf']:.2f} |")
    L += ["", "DD OsEngine не сопоставим: в folder-режиме движок не знает step cost, ",
          "поэтому его DD% рассчитан на неотмасштабированном PnL; приводим только наш DD.",
          "Execution type Intersection ≠ буквальный open следующего бара; ",
          "RTS/GOLD 2026 — ISS-серии без back-adjustment; p-h1 не запущен: ",
          "folder-режим не отдаёт Hour1-серию.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    main()
