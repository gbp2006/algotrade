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
CASES: list[tuple[str, object]] = [  # ожидание: папка или список допустимых
    ("sstp не подключается", "2026-10-20_14-07_sstp-sysinv-connect-fail"),
    ("sstp отваливается периодически", "2026-10-31_20-23_sstp-periodic-failures"),
    ("happ sstp ssh конфликт", ["2026-10-09_22-12_happ-sstp-ssh-conflict", "2026-10-13_09-56_sstp-ca-cert-missing"]),
    ("каскад reality vless", ["2026-11-16_15-50_cascade-vpn-443-multiplex", "2026-11-13_12-03_two-hop-vpn-setup"]),
    ("mtproto fake tls telegram", "2026-11-16_15-50_cascade-vpn-443-multiplex"),
    ("обновление 3x-ui", "2026-11-04_22-05_3xui-pro-update"),
    ("zapret youtube напрямую", "2026-11-17_00-41_zapret2-ladon-eval"),
    ("яндекс imap smtp", "2026-10-12_12-02_yandex-mail-imap-smtp"),
    ("bluetooth залипания наушников", "2026-10-06_19-23_bluetooth-stutter-kde-connect"),
    ("grub не реагирует клавиатура", "2026-10-11_12-18_grub-keyboard-xhci-fix"),
    ("keepass ошибка слияния", "2026-11-04_15-00_keepass-sync-fix"),
    ("tachyon vless ключ не работает", "2026-11-17_01-50_tachyon-vless-fix"),
    ("playwright расширение chrome", "2026-10-21_21-41_playwright-extension-v2-config"),
    ("telegram vless роутинг kovcheg", "2026-11-17_09-59_telegram-vless-route"),
    ("ethernet пропадает после suspend", "2026-11-05_10-18_ethernet-after-suspend-fix"),
    ("задержки dns на роутере", "2026-10-02_17-31_kovcheg-router-storage"),
    ("графики grafana метрики 3x-ui", "2026-11-06_21-25_grafana-3xui-metrics"),
    ("торрент через vpn блокировка", "2026-11-06_19-53_torrent-vpn-restrictions"),
    ("фавикон панели", "2026-11-06_12-54_panel-favicon"),
    ("обновление npm права", "2026-10-21_16-34_opencode-npm-update-perms"),
    ("голосовой ввод выбор", "2026-10-22_17-20_voice-dictation-pick"),
    ("реальность не поднимается xray", "2026-11-07_18-45_reality-fix"),
    ("sstp ca cert gui редактор", "2026-10-13_09-56_sstp-ca-cert-missing"),
    ("dolphin не удаляет файл", "2026-10-13_00-11_dolphin-delete-error"),
    ("exa 403 ip block mcp", ["2026-10-21_14-26_mcp-exa-403-ip-block", "2026-10-13_11-40_opencode-search-tools"]),
    ("автозаголовок сессии сломался", "2026-10-24_15-00_opencode-auto-title-fix"),
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
