#!/usr/bin/env python3
"""eval.py — контрольный набор запросов к индексу истории.

Зачем: любая правка ранжирования (веса, синонимы, свежесть) должна проверяться
цифрами, а не ощущением «вроде ищет».

    ./infra/db/eval.py                # прогнать, сравнить с baseline
    ./infra/db/eval.py --save         # записать текущий результат как baseline
    ./infra/db/eval.py -v             # показать топ-3 по каждому запросу
    ./infra/db/eval.py --fail-on-regress   # код возврата 1 при ухудшении (для скриптов)

Метрики: hit@1, hit@3 (правильная папка в топ-1 / топ-3), MRR.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # не мусорить db/__pycache__

sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory  # noqa: E402

BASELINE = Path(__file__).resolve().parent / "eval-baseline.json"

# (запрос, ожидаемая папка проекта)
CASES: list[tuple[str, object]] = [  # ожидание: папка проекта или список допустимых
    # Текущий корпус: алготрейдинг, песочница → WSL → бой.
    ("робот по торговым системам Силаева четыре системы", "2026-11-18_17-10_silayev-robot-research"),
    ("реверс стратегии автора по истории счёта последователя", "2026-11-19_12-16_author-strategy-reverse"),
    ("Простушка на пуле ликвидных фьючерсов 12 инструментов", "2026-11-19_12-23_prostushka-multi-futures"),
    ("первый прогон бумажного контура девять конфигураций", "2026-11-19_14-00_paper-first-run"),
    ("бесплатные модели отбор избранные", "2026-11-20_15-33_free-models-favorites"),
    ("аудит сделок бумажного контура на WSL восстановление сверки", "2026-11-20_16-02_wsl-paper-audit"),
    ("общее хранилище баров песочница и WSL market.db", "2026-11-20_16-24_two-env-bar-store"),
    ("автоматическая запись новых баров в хранилище", "2026-11-20_16-35_live-ticks-to-db"),
    ("динамический путь ISS-архива отчёт архивный файл", "2026-11-20_16-40_iss-month-path"),
    ("статус соседней сессии прототип торговых роботов WSL", "2026-11-20_16-50_neighbor-session-status"),
    ("укрепление цикла песочница бумага бой whitelist", "2026-11-20_17-08_cycle-hardening"),
    ("G3 безопасное исполнение заявок шлюз лимиты", "2026-11-20_17-35_g3-execution"),
    ("риск-модуль и чистка документации ATR экспозиция", "2026-11-20_18-45_risk-and-docs"),
    ("авторская вариация Самурая TIME_MA", "2026-11-20_19-31_samurai-author-variant"),
    ("поиск входных параметров 2025 2026 плато MA50", "2026-11-20_22-35_param-search-2025-2026"),
    ("режим против подгонки новые роботы риск WSL", "2026-11-20_23-00_regime-and-robots"),
    ("большой поиск стратегий ликвидные инструменты РФ каталог", "2026-11-21_00-42_strategy-search"),
    ("добавление Donchian 20/10 в бумажный тест", "2026-11-23_17-22_donchian-paper"),
    ("поиск стратегий Коваль-Зайцева KZ-02", "2026-11-23_17-53_kz-strategy-search"),
    ("готовность к реальной торговле FINAM MOEX переключатель", "2026-11-23_18-02_live-readiness"),
    ("идеи с нормальной доходностью РФ рынок RU-01", "2026-11-23_18-43_ru-market-ideas"),
    ("доходность роботов и портфеля по депозитам", "2026-11-23_18-45_portfolio-returns-deposit"),
]


def evaluate(limit: int = 3) -> dict:
    hits1 = hits3 = 0
    rr = 0.0
    per_case = []
    for query, expected in CASES:
        rows = memory.search(query, limit=limit)
        projects = [r["project"] for r in rows]
        allowed = [expected] if isinstance(expected, str) else list(expected)
        rank = next((i + 1 for i, p in enumerate(projects) if p in allowed), 0)
        hits1 += rank == 1
        hits3 += 1 <= rank <= 3
        rr += (1.0 / rank) if rank else 0.0
        per_case.append({"query": query, "expected": expected, "rank": rank, "top": projects})
    n = len(CASES)
    return {
        "cases": n,
        "hit_at_1": round(hits1 / n, 3),
        "hit_at_3": round(hits3 / n, 3),
        "mrr": round(rr / n, 3),
        "details": per_case,
    }


def auto_cases() -> list[tuple[str, str]]:
    """Смоук-кейсы прямо из корпуса: цитата пользователя → её сессия.

    Это не измерение качества (цитата почти дословно есть в notes.md, поэтому
    потолок 100 %), а бесплатная проверка «индекс жив и отвечает» после правок.
    Набор обновляется сам вместе с корпусом.
    """
    import re as _re

    con = memory.db_connect(readonly=True)
    names = [r["name"] for r in con.execute(
        "SELECT name FROM project WHERE name LIKE '2%'")]
    df: dict[str, int] = {}
    for n in names:
        txt = con.execute(
            "SELECT GROUP_CONCAT(body,' ') b FROM chunk WHERE doc_id IN "
            "(SELECT id FROM doc WHERE project=?)", (n,)).fetchone()["b"] or ""
        for w in set(_re.findall(r"[а-яёa-z][а-яёa-z0-9]{4,}", txt.lower())):
            df[w] = df.get(w, 0) + 1
    con.close()
    cases = []
    for n in names:
        p = memory.SESSIONS / n / "notes.md"
        if not p.exists():
            continue
        quotes = _re.findall(r"«([^»]{40,200})»", p.read_text(encoding="utf-8", errors="replace"))
        if not quotes:
            continue
        words = [w for w in _re.findall(r"[а-яёa-z][а-яёa-z0-9]{4,}", quotes[0].lower())
                 if 2 <= df.get(w, 0) <= 12]
        if len(words) >= 3:
            cases.append((" ".join(words[:5]), n))
    return cases


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true", help="записать результат как baseline")
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--fail-on-regress", action="store_true")
    ap.add_argument("--auto", action="store_true", help="плюс смоук-кейсы из корпуса")
    args = ap.parse_args()

    memory.build(verbose=False)  # дешёвая проверка актуальности
    res = evaluate(args.limit)

    print(f"hit@1 {res['hit_at_1']:.1%}   hit@3 {res['hit_at_3']:.1%}   MRR {res['mrr']:.3f}   "
          f"({res['cases']} запросов)")

    misses = [d for d in res["details"] if d["rank"] == 0 or d["rank"] > args.limit]
    if misses:
        print(f"\nпромахи ({len(misses)}):")
        for d in misses:
            top = d["top"][0] if d["top"] else "—"
            exp = d["expected"] if isinstance(d["expected"], str) else " | ".join(x[:22] for x in d["expected"])
            print(f"  {d['query']:32s} ожидалось {exp:42s} сверху {top[:40]}")

    if args.auto:
        auto = auto_cases()
        ok = sum(1 for q, exp in auto
                 if exp in [r["project"] for r in memory.search(q, limit=3)])
        print(f"\nсмоук из корпуса: {ok}/{len(auto)} (не метрика качества, а проверка живости)")

    if args.verbose:
        print("\nвсе кейсы:")
        for d in res["details"]:
            print(f"  {d['rank'] or '-':>2}  {d['query']}")

    regress = False
    if args.save:
        BASELINE.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nbaseline сохранён: {BASELINE.name}")
    elif BASELINE.exists():
        old = json.loads(BASELINE.read_text(encoding="utf-8"))
        for key in ("hit_at_1", "hit_at_3", "mrr"):
            delta = res[key] - old.get(key, 0)
            flag = "↑" if delta > 0.0005 else ("↓" if delta < -0.0005 else "=")
            print(f"  {key}: {old.get(key, 0):.3f} → {res[key]:.3f} {flag}")
            if delta < -0.0005:
                regress = True
        if regress:
            print("регрессия относительно baseline")
    else:
        print("\nbaseline ещё нет — запусти с --save")

    return 1 if (regress and args.fail_on_regress) else 0


if __name__ == "__main__":
    sys.exit(main())
