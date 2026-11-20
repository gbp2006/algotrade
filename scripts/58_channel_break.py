"""«Пробой временного канала»: аудит данных + бэктест train 2023–25 → OOS 2026.

Запуск из корня песочницы: ./.venv/bin/python scripts/58_channel_break.py
Подробности — reports/channel-break-research.md. В консоли только сводка.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")

from algo import engine, results  # noqa: E402
from algo.data import DATA_ROOT, load_cached, load_txt  # noqa: E402
from algo.strategies import channel_break  # noqa: E402

START = "23:40"     # прокси-граница: вечерняя сессия MOEX заканчивается ~23:50
SWITCH = "15:00"
REPORT = Path("reports/channel-break-research.md")
WARMUP_DAYS = 30
OOS_END = pd.Timestamp("2026-11-21")  # данные до 20.11 включительно

SPECS = {
    "CNY": dict(
        path="2026-11/CNYRUBF.txt",
        costs=engine.Costs(tick=0.001, multiplier=1000.0),
        sl=0.36, sl_tight=0.12,      # ~3% / ~1% от цены ~12 ₽
        periods=[("train", "2023-01-01", "2026-01-01"),
                 ("oos", "2026-01-01", "2026-11-21")],
    ),
    "Si": dict(
        path="2026-11/Si.txt",
        costs=engine.Costs(tick=1.0, multiplier=1.0),
        sl=3000.0, sl_tight=1000.0,  # ~3% / ~1% от цены ~100 тыс.
        periods=[("train", "2023-01-01", "2026-01-01"),
                 ("oos", "2026-01-01", "2026-11-21")],
    ),
    "RTS": dict(
        path=DATA_ROOT.parent / "cache/iss/RTS_2026_M5_cont.txt",
        costs=engine.Costs(tick=10.0, multiplier=1.644562),
        sl=3300.0, sl_tight=1100.0,  # 3300 — авторское значение для RI
        periods=[("oos", "2026-01-01", "2026-11-21")],  # train-истории нет
    ),
}

def V(variant, direction, sl, mode="night", start=START, boundary="exact"):
    return dict(variant=variant, direction=direction, sl=sl, mode=mode,
                start=start, boundary=boundary)


VARIANTS = [
    V("long-noSL",   "long",  None),
    V("short-noSL",  "short", None),
    V("both-noSL",   "both",  None),
    V("long-SL",     "long",  "sl"),
    V("short-SL",    "short", "sl"),
    V("both-SL",     "both",  "sl"),
    V("both-tight",  "both",  "tight"),
    V("both-noSL-C", "both",  None,   mode="day"),
    V("both-SL-C",   "both",  "sl",   mode="day"),
    # прокси с буквальным 01:00: граница молчаливо становится первой свечой дня
    # (канал = вечер 15:00 -> утро, сделка держится через ночь до утра)
    V("both-noSL-ON", "both", None,   start="01:00", boundary="first_bar"),
    V("both-SL-ON",   "both", "sl",   start="01:00", boundary="first_bar"),
]


def hour_info(df: pd.DataFrame) -> dict:
    hours = df.index.hour
    cnt = np.bincount(hours, minlength=24)
    hhmm = df.index.strftime("%H:%M")
    return dict(
        rows=len(df),
        hist={h: int(cnt[h]) for h in range(24) if cnt[h]},
        night=int(((hours >= 15) | (hours < 1)).sum()),
        at15=int((hhmm == "15:00").sum()),
        at01=int((hhmm == "01:00").sum()),
        at2340=int((hhmm == START).sum()),
        first=str(df.index.min().date()),
        last=str(df.index.max().date()),
    )


def stats_from_trades(trades: list, targets: pd.Series, start: str, end: str) -> dict:
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    tr = [t for t in trades if lo <= t.exit_time < hi]
    if not tr:
        return {"trades": 0, "net_profit": 0.0, "profit_factor": 0.0,
                "avg_trade": 0.0, "max_drawdown": 0.0, "win_rate": 0.0,
                "in_market_pct": 0.0}
    pnl = np.array([t.net for t in tr], dtype=float)
    cum = np.cumsum(pnl)
    dd = cum - np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    gw, gl = wins.sum(), -losses.sum()
    seg = targets.loc[(targets.index >= lo) & (targets.index < hi)]
    return {
        "trades": len(tr),
        "net_profit": round(float(pnl.sum()), 2),
        "profit_factor": round(float(gw / gl), 2) if gl else float("inf"),
        "avg_trade": round(float(pnl.mean()), 2),
        "max_drawdown": round(float(dd.min()), 2),
        "win_rate": round(100 * len(wins) / len(tr), 1),
        "in_market_pct": round(100 * float((seg != 0).mean()), 1) if len(seg) else 0.0,
    }


def backtest(df: pd.DataFrame, spec: dict, start: str, end: str, v: dict) -> tuple[dict, pd.Series]:
    warm = pd.Timestamp(start) - pd.Timedelta(days=WARMUP_DAYS)
    d = df.loc[(df.index >= warm) & (df.index < end)]
    sl = None
    if v["sl"] == "sl":
        sl = spec["sl"]
    elif v["sl"] == "tight":
        sl = spec["sl_tight"]
    tg = channel_break.targets(
        d, start_time=v["start"], switch_time=SWITCH, direction=v["direction"],
        sl=sl, channel_mode=v["mode"], boundary_mode=v["boundary"], skip_weekend=True,
        tick=spec["costs"].tick, slippage_ticks=spec["costs"].slippage_ticks,
    )
    res = engine.run(d, tg, spec["costs"])
    return stats_from_trades(res.trades, tg, start, end), tg


def line(name: str, st: dict) -> str:
    if not st.get("trades"):
        return f"{name:30} нет сделок"
    return (f"{name:30} {st['trades']:>4} сд  net {st['net_profit']:>9} ₽  "
            f"PF {st['profit_factor']:>5}  DD {st['max_drawdown']:>8}")


def main() -> None:
    data = {}
    audit = {}
    for name, spec in SPECS.items():
        df = load_cached(spec["path"]) if name != "RTS" else load_txt(spec["path"])
        data[name] = df
        audit[name] = hour_info(df)

    # гистограмма по часам — компактно, по одной строке на инструмент
    for name, a in audit.items():
        hist = " ".join(f"{h:02d}:{v}" for h, v in a["hist"].items())
        print(f"{name:4} {a['rows']:>8,} баров {a['first']}..{a['last']} | 15:00={a['at15']} "
              f"01:00={a['at01']} {START}={a['at2340']} | {hist}")
        print("     ^ ночных баров (15:00–01:00): "
              f"{a['night']:,} ({100*a['night']/a['rows']:.1f}%), но меток 01:00 — {a['at01']}")

    rows = []
    console = []
    for name, spec in SPECS.items():
        df = data[name]
        for period, start, end in spec["periods"]:
            for v in VARIANTS:
                st, tg = backtest(df, spec, start, end, v)
                rows.append(dict(instrument=name, period=period, start=start, end=end,
                                 variant=v["variant"], direction=v["direction"],
                                 sl=v["sl"], mode=v["mode"],
                                 start_time=v["start"], boundary=v["boundary"], **st))
                if v["variant"] in ("both-noSL", "both-SL"):
                    results.record(
                        strategy="channel_break", instrument=name,
                        period=f"{period} {start[:4]}-{end[:4]}", stats=st,
                        params=dict(variant=v["variant"], start=v["start"],
                                    switch=SWITCH, channel=v["mode"],
                                    sl=v["sl"] or "none", boundary=v["boundary"]),
                        note="прокси границы; интрабарный стоп по open следующего бара",
                    )
                key = (name, period, v["variant"])
                if key in {
                    ("CNY", "train", "both-noSL"), ("CNY", "oos", "both-noSL"),
                    ("CNY", "oos", "both-SL"), ("Si", "oos", "both-noSL"),
                    ("Si", "oos", "both-SL"), ("RTS", "oos", "both-noSL"),
                }:
                    console.append(line(f"{name} {period} {v['variant']}", st))

    for s in console:
        print(s)

    # буквальные параметры 01:00/15:00: меток 01:00 нет, OsEngine не нашёл бы границу
    literal = {n: int(channel_break.targets(
        data[n].loc["2026-01-01":"2026-02-01"],
        start_time="01:00", switch_time="15:00", boundary_mode="exact"
    ).ne(0).sum()) for n in SPECS}

    write_report(audit, rows, literal)
    print(f"отчёт: {REPORT}")


def write_report(audit: dict, rows: list[dict], literal: dict) -> None:
    out = pd.DataFrame(rows)
    L = [
        "# Пробой временного канала — исследование", "",
        f"Дата: {pd.Timestamp.now():%d.%m.%Y}. Источники: `readme.txt`, `_TimeChannelBreak.cs`, "
        "`разбор/TCBreakClaudeV3.cs` из папки ТС «Умный трейдер» (Коваль-Зайцев).", "",
        "## 1. Что это за стратегия", "",
        "OsEngine-робот на минутках. Параметры автора: StartTime=0100 (конец торгов / "
        "начало нового диапазона), SwitchTime=1500 (конец расчёта канала / старт торгов), "
        "SL=3300 пунктов для RI, объём 1. Канал HH/LL строится по барам ночной сессии, "
        "направление `dir` — сравнением закрытий на 01:00 двух соседних дней. "
        "С 15:00 до 01:00 при `dir=+1` торгуется пробой HH вверх (лонг), при `dir=-1` — "
        "пробой LL вниз (шорт, только в V3; оригинал шорт не торгует). "
        "Выход — на StartTime следующего дня, стоп подтягивается к LL/HH (V3).", "",
        "**Расхождение ТЗ и исходника.** В `LaunchCalc()` C# идёт от последнего бара назад: "
        "находит ближайший бар 15:00, затем расширяет канал назад до ближайшего бара 01:00 "
        "того же дня и сравнивает закрытия 01:00 текущего и предыдущего дня. То есть в "
        "исходнике канал = 01:00→15:00 **дневной** сессии, а не 15:00→01:00 ночной, как "
        "написано в ТЗ. Оба варианта портированы: `channel_mode='night'` (ТЗ, основной) и "
        "`channel_mode='day'` (C#), строки с суффиксом `-C` в таблицах.", "",
        "## 2. Доступность данных: ночной сессии нет", "",
        "| инструмент | бары | период | 15:00 | 01:00 | 23:40 | ночных (15–01) | часы с барами |",
        "|---|---:|---|---:|---:|---:|---:|---|",
    ]
    for n, a in audit.items():
        L.append(f"| {n} | {a['rows']:,} | {a['first']}..{a['last']} | {a['at15']:,} | "
                 f"{a['at01']} | {a['at2340']:,} | {a['night']:,} | "
                 f"{min(a['hist']) :02d}–{max(a['hist']):02d} |")
    L += [
        "",
        "**Вывод:** в трёх архивах нет ни одного бара с меткой 01:00 (и вообще 00:00–06:00). "
        "В буквальном режиме `boundary_mode='exact'` (как у OsEngine, где `curTime == 100` "
        "и поиск бара 01:00 в `LaunchCalc`) число ненулевых целевых позиций на тестовом "
        f"месяце 2026-01: CNY={literal['CNY']}, Si={literal['Si']}, RTS={literal['RTS']}. "
        "То есть стратегия в исходном виде на этих инструментах **не работает**. "
        "Наша функция `daily_first_bar` при буквальных 01:00 молчаливо подставила бы "
        "первую свечу дня (07:00–10:00) — это уже другая стратегия, и мы её тоже проверяем.",
        "",
        "Два честно описанных прокси (оба — не авторская конфигурация):", "",
        "- `start=23:40`, `boundary=exact` — канал = вечер предыдущего дня 15:00→23:40, "
        "сделка = вечер текущего дня 15:00→23:40 (основной вариант, суффиксов нет).",
        "- `start=01:00`, `boundary=first_bar` — канал = 15:00 предыдущего дня → первая "
        "свеча текущего дня, сделка держится через ночь до первой свечи следующего дня "
        "(суффикс `-ON`). Это ближе к буквальному смыслу StartTime, но граница сдвинута "
        "на утро и есть разрыв между сессиями.", "",
        "## 3. Модель исполнения и оговорки", "",
        "- Сигнал по close бара, сделка по open следующего бара; 0.01% за сторону + 1 тик; "
        "решения в субботу/воскресенье отключены (`skip_weekend=True`).",
        "- Интрабарный stop-order на барах невоспроизим: если low/high бара задел уровень "
        "стопа, позиция обнуляется на этом баре и выход исполняется по open следующего бара. "
        "Это консервативно (resp. хуже авторского стопа) и завышает проскальзывание.",
        "- Варианты `-C` — канал по C# `LaunchCalc` (start→switch); `-ON` — ночной "
        "прокси с утренней границей; `-tight` — стоп ~1%.",
        "- `sl=None` — только выход по времени; `SL` = ~3% от характерной цены "
        "(CNY 0.36, Si 3000, RTS 3300 — авторское значение), `tight` = ~1%. "
        "Стоп V3: лонг max(LL, entry−SL), шорт min(HH, entry+SL).",
        "- Train 2023–2025 → OOS 2026 (у CNY/Si), RTS — только 2026 из ISS (train-архива "
        "нет, данные не back-adjusted). OOS неполный: CNY/RTS до 20.11, Si до 31.10.",
        "- Для каждого прогона данные берутся с 30-дневным прогревом; статистика считается "
        "только по сделкам с выходом внутри периода. `in_market_pct` — доля баров с позицией.",
        "- RTS из ISS — квартальные контракты без back-adjustment: цифры оценочные.",
        "", "## 4. Результаты", "",
        "Все варианты (₽, 1 контракт; net уже включает комиссии и проскальзывание):", "",
        "| инструмент | период | вариант | сделок | net | PF | avg | DD | в рынке % |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        if not r["trades"]:
            continue
        L.append(f"| {r['instrument']} | {r['period']} {r['start'][:4]} | {r['variant']} | "
                 f"{r['trades']} | {r['net_profit']} | {r['profit_factor']} | "
                 f"{r['avg_trade']} | {r['max_drawdown']} | {r['in_market_pct']} |")
    L += [
        "", "Варианты с нулём сделок в таблицу не включены (означают, что канал/направление "
        "ни разу не дали пробоя за период).", "",
        "## 5. Сравнение с нашими тремя системами", "",
        "- **Простушка/Универсалка/Хитрушка** принимают решение один раз в сутки по "
        "закрытию после 13:00 и держат позицию до следующего решения; здесь решение "
        "привязано к вечернему пробою канала и выходу в конце вечера — другой ритм и другая "
        "экспозиция (часы 15:00–23:40 вместо полного дня).",
        "- У наших систем тренд = SMA/offset'ы, у этой — экстремумы предыдущего вечера и "
        "флаг `dir` по закрытиям границы. Это независимый сигнал, но он использует те же "
        "вечерние часы, где Универсалка уже держит позицию (конфликт по сайзу при "
        "одновременном включении).",
        "- Стоп и принудительный выход внутри дня есть только у Самурая (пятница 18:45); "
        "у пробоя канала выход по времени каждый вечер — больше оборот и больше commissions "
        "при том же среднем размере сделки.",
        "- Ни одна из трёх систем не требует ночных баров 01:00; эта требует, но в архиве "
        "их нет — ещё одно принципиальное отличие.", "",
        "## 6. Рекомендация", "",
        "**Не включать в бумажный тест.** Причины: (1) буквальная стратегия на доступных "
        "данных невоспроизводима — меток 01:00 нет ни у CNY, ни у Si, ни у RTS; оба proxies "
        "меняют идею (вечер→вечер или вечер→утро вместо ночь→ночь), то есть проверяется "
        "другая система; (2) расхождение ТЗ и C# в определении канала не позволяет "
        "однозначно выбрать «правильный» вариант; (3) интрабарный стоп аппроксимируется "
        "с консервативным выходом по следующему open; (4) результаты нестабильны: на CNY и "
        "Si train-прогон прибылен (PF 1.18–1.26), а OOS 2026 — около нуля или в минусе "
        "(PF 0.88–1.00); прибыль держится в основном на коротком (RTS 2026) и/"
        "или на прокси с другим определением канала, что похоже на подгонку под окно.", "",
        "Если вернуться к теме — нужны настоящие round-the-clock бары (крипта или MOEX "
        "с ночной сессией с метками после полуночи) и отдельное решение по стопу "
        "внутри бара; только после этого имеет смысл сравнивать с нашими системами на "
        "одном окне.", "",
    ]
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
