"""Боевой раннер (подготовлен, НЕ включён). Отправляет заявки только при --arm
И FINAM_ALLOW_TRADING=1. По умолчанию всё пишется в журнал как `planned`.

Правила и формат настроек — docs/live-design.md. Запуск:
    ./run.sh live-dry            # репетиция, ни одной заявки
    ./run.sh live --arm          # только после ворот и ручного решения

Робот попадает в контур, только если явно перечислен в live_settings.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from algo.broker.execution import Order, OrderGateway, positions_from_response  # noqa: E402
from algo.broker.finam import FinamBroker  # noqa: E402
from algo.broker.secrets import resolve_secret  # noqa: E402
from algo.broker.live_guard import (  # noqa: E402
    STOP_REAL, assert_stop_clear, battle_limits, decision_client_id,
    expiry_allows, price_for, quote_age_sec, reconcile_guard,
)
from algo.configs import CONFIGS  # noqa: E402
from algo.instance_configs import live_settings_from_store  # noqa: E402
from algo.instruments import DEFAULT, INSTRUMENTS  # noqa: E402
from algo.live_config import SettingsError, load_settings  # noqa: E402
from algo.robot_configs import ROBOT_CONFIGS  # noqa: E402

PAPER = ROOT / "results" / "paper.csv"
LIVE = ROOT / "results" / "live.csv"
STOP = ROOT / "results" / "STOP"
RUN_LOCK = ROOT / "results" / "live_run.lock"
SUMMARY = ROOT / "results" / "live_run.json"
BY_ID = {c.id: c for c in CONFIGS + ROBOT_CONFIGS}


def read_paper(day: date) -> list[dict]:
    if not PAPER.exists():
        return []
    with PAPER.open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f)
                if "config" in r and r.get("date") == str(day)]


def plan_targets(rows: list[dict], settings, day: date) -> dict:
    """Целевые позиции по счёту и символу. Одна строка на пару (счёт, символ)."""
    plans: dict[str, dict[str, dict]] = {}
    for cfg_id, rs in settings.robots.items():
        cfg = BY_ID.get(cfg_id)
        if cfg is None:
            print(f"ВНИМАНИЕ: {cfg_id} нет в реестре конфигураций — пропущен")
            continue
        mine = [r for r in rows if r["config"] == cfg_id]
        if not mine:
            continue
        last = mine[-1]
        sym = last["symbol"]
        plan = plans.setdefault((rs.account, rs.key_ref), {}).setdefault(sym, {
            "target": 0, "price": float(last["price"]), "robots": [],
            "pricings": set(), "expiry": True,
        })
        plan["target"] += int(last["target"])
        plan["robots"].append(cfg_id)
        plan["pricings"].add(rs.pricing)
        plan["expiry"] = plan["expiry"] and rs.trade_on_expiry
    return plans


def journal_positions(account: str) -> tuple[dict[str, int], int]:
    """Позиции по своим отправленным заявкам + число неопределённых.

    Это модель контура для сверки с брокером. `uncertain` — заявка могла уйти,
    торговать до ручной сверки нельзя.
    """
    model: dict[str, int] = {}
    uncertain = 0
    if not LIVE.exists():
        return model, uncertain
    with LIVE.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("account") != account:
                continue
            if r.get("status") == "uncertain":
                uncertain += 1
            if r.get("status") != "sent" or not r.get("symbol"):
                continue
            qty = int(float(r.get("qty") or 0))
            signed = qty if r.get("side") == "buy" else -qty
            sym = r["symbol"]
            model[sym] = model.get(sym, 0) + signed
    return model, uncertain


def broker_positions(broker, account: str) -> dict[str, int]:
    response = broker.account(account)
    return positions_from_response(response.get("positions", response))


def acquire_run_lock() -> int | None:
    RUN_LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(RUN_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    os.write(fd, str(os.getpid()).encode())
    return fd


def tick_for(symbol: str) -> float:
    for inst in INSTRUMENTS.values():
        if inst.symbol == symbol:
            return inst.tick
    return DEFAULT.tick


def mult_for(symbol: str) -> float:
    for inst in INSTRUMENTS.values():
        if inst.symbol == symbol:
            return inst.mult
    return DEFAULT.mult


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="боевой контур (dry-run по умолчанию)")
    ap.add_argument("--arm", action="store_true",
                    help="разрешить отправку (вместе с FINAM_ALLOW_TRADING=1)")
    ap.add_argument("--day", default=date.today().isoformat(),
                    help="дата решений из paper.csv (по умолчанию сегодня)")
    args = ap.parse_args(argv)

    fd = acquire_run_lock()
    if fd is None:
        print("боевой контур уже выполняется (live_run.lock)")
        return 0
    try:
        if STOP.exists() or STOP_REAL.exists():
            print("STOP установлен: заявки не отправляются")
            return 0
        try:
            settings = live_settings_from_store()
            if settings.empty:
                settings = load_settings()  # миграционный fallback на live_settings.json
        except SettingsError as exc:
            print(f"настройки не прошли проверку: {exc}")
            return 2
        if settings.empty:
            print("live_settings.json: нет роботов в белом списке — заявок нет")
            return 0

        day = date.fromisoformat(args.day)
        plans = plan_targets(read_paper(day), settings, day)
        if not plans:
            print(f"{day}: решений для боевых роботов нет")
            return 0

        counts: dict[str, int] = {}
        notes: list[str] = []
        now = datetime.now().strftime("%H%M%S")

        for (acc_id, key_ref), symbols in plans.items():
            acc = settings.accounts[acc_id]
            try:
                broker = FinamBroker(secret=resolve_secret(key_ref or acc.key_ref),
                                     account=acc_id)
            except Exception as exc:  # noqa: BLE001 — без ключа счёт не трогаем
                print(f"{acc_id}: ключ счёта недоступен — {exc}")
                return 2
            model, uncertain = journal_positions(acc_id)
            if uncertain:
                note = f"{acc_id}: {uncertain} неопределённых заявок — ручная сверка"
                STOP_REAL.write_text(note + "\n", encoding="utf-8")
                print(note)
                return 2
            try:
                issues = reconcile_guard(
                    broker, model, account=acc_id, stop=STOP_REAL, enforce=True)
            except Exception as exc:  # noqa: BLE001 — расхождение = STOP, не торгуем
                print(f"{acc_id}: сверка не прошла — {exc}")
                return 2
            if issues:
                notes.append(f"{acc_id}: сверка: {'; '.join(issues)}")

            actual = broker_positions(broker, acc_id)
            gateway = OrderGateway(
                broker,
                limits=battle_limits(
                    acc.capital, max_exposure=acc.max_exposure,
                    max_qty=acc.max_qty,
                ).as_limits(),
                journal=LIVE, lock=ROOT / "results" / "live.lock",
            )

            for sym, plan in symbols.items():
                ids = "+".join(plan["robots"])
                client_id = decision_client_id(
                    ids, day, "buy" if plan["target"] >= actual.get(sym, 0) else "sell",
                    now, abs(plan["target"]))
                status = reason = note = ""
                delta = 0
                order = None

                if len(plan["pricings"]) > 1:
                    status, reason = "rejected", "конфликт режимов цены на счёте/символе"
                else:
                    delta = plan["target"] - actual.get(sym, 0)
                    if delta != 0:
                        side = "buy" if delta > 0 else "sell"
                        if not expiry_allows(day, sym, delta, plan["expiry"]):
                            status, reason = "skipped", "день экспирации"
                        else:
                            pricing = next(iter(plan["pricings"]))
                            quote = None
                            if pricing.value != "signal":
                                quote = broker.quote(sym)
                                age = quote_age_sec(quote)
                                if age is None or age > settings.max_quote_age_sec:
                                    status, reason = "rejected", "котировка устарела"
                            if not status:
                                price, order_type, note = price_for(
                                    pricing, plan["price"], side, quote, tick_for(sym))
                                order = Order(
                                    client_id=client_id, config=ids, symbol=sym,
                                    side=side, qty=abs(delta), price=price,
                                    multiplier=mult_for(sym), min_step=tick_for(sym),
                                    order_type=order_type, account=acc_id,
                                    pricing=pricing.value,
                                )

                if order is not None and not status:
                    assert_stop_clear(STOP_REAL)
                    result = gateway.submit(order, account=acc_id,
                                            stop=STOP_REAL,
                                            dry_run=not args.arm)
                    status, reason = result.status, result.reason
                elif status in ("skipped", "rejected"):
                    # чтобы пропуск был виден в журнале, а не только в сводке
                    stub = Order(client_id=client_id, config=ids, symbol=sym,
                                 side="buy" if delta > 0 else "sell",
                                 qty=abs(delta), price=plan["price"],
                                 multiplier=mult_for(sym), min_step=tick_for(sym),
                                 account=acc_id)
                    gateway.log_decision(stub, status, reason)

                counts[status or "noop"] = counts.get(status or "noop", 0) + 1
                if reason or note:
                    notes.append(f"{acc_id}/{sym}: {reason or note}")

        SUMMARY.parent.mkdir(parents=True, exist_ok=True)
        SUMMARY.write_text(json.dumps({
            "date": str(day), "armed": bool(args.arm), "counts": counts,
            "robots": sorted(settings.robots),
            "accounts": sorted({acc for acc, _ in plans}),
            "notes": notes[:40],
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"live {day}: {sum(counts.values())} решений, статусы {counts}, "
              f"arm={args.arm}")
        return 0
    finally:
        os.close(fd)
        RUN_LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
