"""Перекладка квартальных позиций (подготовлено, НЕ включено).

Проверяет реальные позиции счетов из live_settings/store и, если ликвидность
ушла в следующий контракт (или до экспирации мало дней), выставляет две ноги с
общим roll_id через OrderGateway. По умолчанию dry-run — заявки не уходят.

Запуск: ./run.sh rollover-dry [--day YYYY-MM-DD] [--force-before 7]
        ./run.sh rollover [--arm]   # только после ворот и ручного решения
"""

from __future__ import annotations

import argparse
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
from algo.broker.live_guard import (  # noqa: E402
    PricingMode, STOP_REAL, account_equity, battle_limits, decision_client_id,
    price_for, quote_age_sec, reconcile_guard,
)
from algo.instance_configs import live_settings_from_store  # noqa: E402
from algo.instruments import INSTRUMENTS, active_contracts  # noqa: E402
from algo.live_config import SettingsError, load_settings  # noqa: E402
from algo.rollover import is_perpetual, plan_roll, roll_decision  # noqa: E402
from algo.rollover_integration import volumes_for  # noqa: E402

LIVE = ROOT / "results" / "live.csv"
STOP = ROOT / "results" / "STOP"
LOCK = ROOT / "results" / "rollover.lock"
# Отдельный лок заявок: ролл не должен делить live.lock с боевым раннером
ORDER_LOCK = ROOT / "results" / "rollover_orders.lock"
SUMMARY = ROOT / "results" / "rollover_run.json"


def instrument_for(symbol: str, contracts_by_inst: dict):
    for inst, contracts in contracts_by_inst.items():
        if symbol in contracts or symbol == inst.symbol:
            return inst
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="перекладка квартальных контрактов")
    ap.add_argument("--arm", action="store_true", help="разрешить отправку")
    ap.add_argument("--day", default=date.today().isoformat())
    ap.add_argument("--force-before", type=int, default=7,
                    help="переложиться за N календарных дней до экспирации")
    args = ap.parse_args(argv)

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print("перекладка уже выполняется (rollover.lock)")
        return 0
    os.write(fd, str(os.getpid()).encode())
    try:
        if STOP.exists() or STOP_REAL.exists():
            print("STOP установлен: перекладка пропущена")
            return 0
        try:
            settings = live_settings_from_store()
            if settings.empty:
                settings = load_settings()
        except SettingsError as exc:
            print(f"настройки: {exc}")
            return 2
        if settings.empty:
            print("нет активных роботов — перекладывать нечего")
            return 0

        day = date.fromisoformat(args.day)
        broker = FinamBroker()
        used = sorted({r.account for r in settings.robots.values()})
        now = datetime.now().strftime("%H%M%S")
        results: dict[str, int] = {}
        notes: list[str] = []

        contracts_by_inst = {
            inst: active_contracts(inst, day) for inst in INSTRUMENTS.values()
        }

        for acc_id in used:
            acc = settings.accounts[acc_id]
            response = broker.account(acc_id)
            actual = positions_from_response(response.get("positions", response))
            model = {s: q for s, q in actual.items() if q != 0}
            # Ролл — перекладка, а не новый бой: расхождение с брокером только
            # логируем, STOP не выставляем (режим репетиции контура).
            try:
                reconcile_guard(broker, model, account=acc_id,
                                stop=STOP_REAL, enforce=False)
            except Exception as exc:  # noqa: BLE001 — информационно
                notes.append(f"{acc_id}: сверка (информационно) "
                             f"{type(exc).__name__}: {exc}")

            equity = account_equity(broker, acc_id) or 0
            if equity <= 0:
                notes.append(f"{acc_id}: нет equity — перекладка пропущена")
                continue
            gateway = OrderGateway(
                broker,
                limits=battle_limits(equity, max_exposure=acc.max_exposure,
                                     max_qty=acc.max_qty).as_limits(),
                journal=LIVE, lock=ORDER_LOCK)

            for sym, qty in actual.items():
                if qty == 0 or is_perpetual(sym):
                    continue
                inst = instrument_for(sym, contracts_by_inst)
                if inst is None:
                    continue
                contracts = contracts_by_inst[inst]
                if sym not in contracts:
                    continue
                volumes = volumes_for(broker, list(contracts), day)
                dec = roll_decision(day, sym, qty, contracts, volumes,
                                    policy="volume",
                                    force_before_expiry=args.force_before)
                if dec is None:
                    continue
                quote_old = broker.quote(sym)
                quote_new = broker.quote(dec.next_symbol)
                legs = plan_roll(dec, quote_old.last, quote_new.last)
                notes.append(f"{acc_id}: {sym} → {dec.next_symbol} ({dec.reason})")
                for n, leg in enumerate(legs):
                    quote = quote_old if leg.role == "close" else quote_new
                    age = quote_age_sec(quote)
                    if age is None or age > settings.max_quote_age_sec:
                        results["rejected"] = results.get("rejected", 0) + 1
                        continue
                    price, order_type, _ = price_for(
                        PricingMode.MARKETABLE, leg.price, leg.side, quote,
                        inst.tick)
                    order = Order(
                        client_id=decision_client_id(
                            "roll:" + dec.roll_id, day, leg.side, now, n),
                        config="roll:" + dec.roll_id, symbol=leg.symbol,
                        side=leg.side, qty=leg.qty, price=price,
                        multiplier=inst.mult, min_step=inst.tick,
                        order_type=order_type, account=acc_id, pricing="roll")
                    res = gateway.submit(order, account=acc_id,
                                         stop=STOP_REAL, dry_run=not args.arm)
                    results[res.status] = results.get(res.status, 0) + 1

        SUMMARY.parent.mkdir(parents=True, exist_ok=True)
        SUMMARY.write_text(json.dumps({
            "date": str(day), "armed": bool(args.arm),
            "results": results, "notes": notes[:30],
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"rollover {day}: {sum(results.values())} ног, статусы {results}, "
              f"arm={args.arm}")
        return 0
    finally:
        os.close(fd)
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
