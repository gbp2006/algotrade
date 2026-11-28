"""Боевой раннер: заявки уходят по активному заданию робота на счёте LIVE.

Отдельных замков `--arm` и `FINAM_ALLOW_TRADING` больше нет (ADR 27.11):
управление — СТАРТ/СТОП робота и кнопка «Закрыть всё» в панели. Остаются
STOP_REAL, лок от двойного прогона (держит панель), лимиты, экспирация и
идемпотентность. Ошибка ключа/equity одного счёта пропускает только его.
`--dry-run` — явная репетиция без отправки, `--arm` принят для совместимости
со старыми командами заданий и ничего не меняет.

Запуск:
    ./run.sh live-run --day 2026-11-27   # реальные заявки
    ./run.sh live-dry --day 2026-11-27   # только planned
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from algo.broker.execution import (  # noqa: E402
    ExecutionError, Order, OrderGateway, positions_from_response,
)
from algo.broker.finam import FinamBroker  # noqa: E402
from algo.broker.secrets import resolve_secret  # noqa: E402
from algo.broker.live_guard import (  # noqa: E402
    STOP_REAL, account_equity, assert_stop_clear, battle_limits,
    decision_client_id, expiry_allows, parse_pricing, price_for, quote_age_sec,
    reconcile_guard,
)
from algo import trade_journal as tj  # noqa: E402
from algo.journal_positions import journal_positions as shared_journal_positions  # noqa: E402
from algo.portfolio import exposure_of, size_contracts  # noqa: E402
from algo.instance_configs import all_configs, live_settings_from_store  # noqa: E402
from algo.instruments import DEFAULT, INSTRUMENTS  # noqa: E402
from algo.live_config import SettingsError  # noqa: E402
from algo.live_signal import collect as collect_signals  # noqa: E402
from algo.robot_store import RobotStore  # noqa: E402

PAPER = ROOT / "results" / "paper.csv"
LIVE = ROOT / "results" / "live.csv"
STOP = ROOT / "results" / "STOP"
SUMMARY = ROOT / "results" / "live_run.json"
MSK = timezone(timedelta(hours=3))


def read_paper(day: date) -> list[dict]:
    if not PAPER.exists():
        return []
    with PAPER.open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f)
                if "config" in r and r.get("date") == str(day)]


def plan_targets(rows: list[dict], settings, day: date) -> dict:
    """Целевые позиции по счёту и символу. Одна строка на пару (счёт, символ)."""
    plans: dict[str, dict[str, dict]] = {}
    by_id = {c.id: c for c in all_configs()}
    for cfg_id, rs in settings.robots.items():
        # живой инстанс может повторять решение бумажного конфига с другим id
        src = rs.source_config or cfg_id
        cfg = by_id.get(src)
        exposure = exposure_of(cfg) if cfg is not None else rs.exposure
        if not exposure:
            print(f"ВНИМАНИЕ: {src} нет в реестре и экспозиция не задана — пропущен")
            continue
        mine = [r for r in rows if r["config"] == src]
        if not mine:
            continue
        last = mine[-1]
        sym = last["symbol"]
        plan = plans.setdefault((rs.account, rs.key_ref), {}).setdefault(sym, {
            "target": 0, "price": float(last["price"]), "robots": [],
            "pricings": set(), "expiry": True, "exposures": [],
            # детерминированное время решения из paper.csv, а не время запуска:
            # повторный --arm того же дня не должен создавать вторую заявку (F01)
            "when": last.get("time", ""),
        })
        plan["target"] += int(last["target"])
        # expositions из самих конфигов: 2.0 база, 0.6 RTS, 0.7 золото (ADR 24)
        plan["exposures"].append(exposure)
        plan["robots"].append(cfg_id)
        plan["pricings"].add(rs.pricing)
        plan["expiry"] = plan["expiry"] and rs.trade_on_expiry
    return plans


def expiry_ok(day: date, sym: str, delta: int, trade_on_expiry: bool,
              run_day: date | None = None) -> bool:
    """Экспирация проверяется по дню исполнения, не по дню бумажного решения."""
    return expiry_allows(run_day or day, sym, delta, trade_on_expiry)


def journal_positions(account: str) -> tuple[dict[str, int], int]:
    """Модель позиций счёта по журналу раннера (общая с перекладкой)."""
    return shared_journal_positions(account, LIVE)


def broker_positions(broker, account: str) -> dict[str, int]:
    response = broker.account(account)
    return positions_from_response(response.get("positions", response))


def sync_live_runtime(store, updates: list[dict]) -> list[str]:
    """Отразить в панели фактическую позицию счёта у живых роботов.

    Только наблюдение: заявки, STOP и настройки не меняются. `set_runtime`
    перезаписывает всю строку, поэтому недостающие поля берём из прежнего
    состояния. Ошибка одного инстанса не срывает боевой прогон.
    """
    notes: list[str] = []
    try:
        store.init_db()
    except Exception as exc:  # noqa: BLE001 — панель не должна ронять бой
        return [f"рантайм недоступен: {type(exc).__name__}"]
    for u in updates:
        iid = str(u["instance_id"])
        try:
            prev = store.get_runtime(iid) or {}
            store.set_runtime(iid, {
                "symbol": u.get("symbol") or prev.get("symbol") or "",
                "position": int(u.get("position") or 0),
                "equity": float(u.get("equity") or prev.get("equity") or 0),
                "last_price": float(u.get("last_price") or prev.get("last_price") or 0),
                "last_decision": u.get("last_decision") or prev.get("last_decision") or "",
                "note": u.get("note") or prev.get("note") or "",
            })
        except Exception as exc:  # noqa: BLE001 — процедура наблюдательная
            notes.append(f"{iid}: рантайм не обновлён ({type(exc).__name__})")
    return notes


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


def write_summary(day, args, counts, settings, plans, notes, fills) -> None:
    """Сводка прогона пишется и при досрочном STOP — панель не должна видеть старый JSON."""
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps({
        "date": str(day), "armed": not args.dry_run, "dry_run": args.dry_run,
        "counts": counts,
        "robots": sorted(settings.robots),
        "accounts": sorted({acc for acc, _ in plans}),
        "fills": fills,
        "notes": notes[:40],
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="боевой контур (заявки уходят по заданию LIVE-робота)")
    ap.add_argument("--arm", action="store_true",
                    help="устаревший флаг, принят для совместимости и ничего не меняет")
    ap.add_argument("--dry-run", action="store_true",
                    help="явная репетиция: проверить всё, но не отправлять")
    ap.add_argument("--day", default=date.today().isoformat(),
                    help="дата решений из paper.csv (по умолчанию сегодня)")
    args = ap.parse_args(argv)

    # Локов больше нет (ADR 27.11): повторный прогон ловит client_id в журнале.
    try:
        if STOP.exists() or STOP_REAL.exists():
            print("STOP установлен: заявки не отправляются")
            return 0
        try:
            settings = live_settings_from_store()
        except SettingsError as exc:
            print(f"настройки не прошли проверку: {exc}")
            return 2
        if settings.empty:
            print("нет активных live-роботов в store — заявок нет")
            return 0

        day = date.fromisoformat(args.day)
        # Экспирация проверяется на дату Actual исполнения, а не на дату
        # бумажного решения: догоняющий --day=вчера не должен уйти в экспирацию.
        run_day = datetime.now(MSK).date()
        counts: dict[str, int] = {}
        notes: list[str] = []
        fills: list[dict] = []
        paper_signals: dict[str, dict] = {}
        decisions: dict[tuple[str, str], str] = {}
        runtime_updates: list[dict] = []
        aborted = False  # STOP посреди прогона: сводка всё равно пишется

        #_signal: бой сам считает сигнал по свежим барам и пишет его в свой журнал;
        # paper.csv больше не участвует в отправке заявок (ADR 27.11).
        try:
            price_broker = FinamBroker.service()
        except Exception as exc:  # noqa: BLE001 — без данных заявок не будет
            print(f"нет сервисного ключа для баров — {exc}")
            return 2
        plans, signal_notes, recorded = collect_signals(
            RobotStore(), settings, day, price_broker)
        notes.extend(signal_notes)
        if recorded:
            notes.append(f"персональный журнал: решений {len(recorded)}")
        if not plans:
            print(f"{day}: решений для боевых роботов нет")
            return 0

        for (acc_id, key_ref), symbols in plans.items():
            acc = settings.accounts[acc_id]
            try:
                broker = FinamBroker(secret=resolve_secret(key_ref or acc.key_ref),
                                     account=acc_id)
            except Exception as exc:  # noqa: BLE001 — без ключа счёт не трогаем
                note = f"{acc_id}: ключ счёта недоступен — {exc}"
                notes.append(note)
                print(note)
                continue
            equity = account_equity(broker, acc_id)
            if equity is None or equity <= 0:
                note = f"{acc_id}: нет equity счёта — заявок нет"
                notes.append(note)
                print(note)
                continue
            notes.append(f"{acc_id}: equity {equity:.0f} ₽, экспозиции "
                         f"{sorted(set().union(*(p['exposures'] for p in symbols.values())))}")
            model, uncertain = journal_positions(acc_id)
            if uncertain:
                # F03: ответ мог потеряться, но заявка исполнена — опрашиваем
                # брокера ещё раз до STOP, чтобы не блокировать торговлю зря.
                try:
                    tj.refresh_executions(broker, acc_id, csv_path=LIVE)
                    model, uncertain = journal_positions(acc_id)
                except Exception as exc:  # noqa: BLE001 — при недоступности API STOP как раньше
                    print(f"{acc_id}: повторная сверка недоступна — {exc}")
            if uncertain:
                note = f"{acc_id}: {uncertain} неопределённых заявок — ручная сверка"
                STOP_REAL.write_text(note + "\n", encoding="utf-8")
                notes.append(note)
                print(note)
                aborted = True
                break
            try:
                issues = reconcile_guard(
                    broker, model, account=acc_id, stop=STOP_REAL, enforce=True)
            except Exception as exc:  # noqa: BLE001 — расхождение = STOP, не торгуем
                note = f"{acc_id}: сверка не прошла — {exc}"
                notes.append(note)
                print(note)
                aborted = True
                break
            if issues:
                notes.append(f"{acc_id}: сверка: {'; '.join(issues)}")

            actual = broker_positions(broker, acc_id)
            gateway = OrderGateway(
                broker,
                limits=battle_limits(
                    equity, max_exposure=acc.max_exposure,
                    max_qty=acc.max_qty,
                ).as_limits(),
                journal=LIVE,
            )

            for sym, plan in symbols.items():
                ids = "+".join(plan["robots"])
                direction = (plan["target"] > 0) - (plan["target"] < 0)
                exposure = min(plan["exposures"]) if plan["exposures"] else 1.0
                exposure = min(exposure, acc.max_exposure)  # потолок счёта (консервативно)
                # сайзинг Силаева: лот = equity × экспозиция / (цена × множитель)
                lots = size_contracts(equity, plan["price"], mult_for(sym), exposure)
                target = direction * lots  # бумага даёт направление, счёт — размер
                client_id = decision_client_id(
                    ids, day, "buy" if target >= actual.get(sym, 0) else "sell",
                    plan["when"], abs(target))
                status = reason = note = ""
                delta = 0
                order = None

                if len(plan["pricings"]) > 1:
                    status, reason = "rejected", "конфликт режимов цены на счёте/символе"
                else:
                    delta = target - actual.get(sym, 0)
                    if delta != 0:
                        side = "buy" if delta > 0 else "sell"
                        if not expiry_ok(day, sym, delta, plan["expiry"], run_day):
                            status, reason = "skipped", "день экспирации"
                        else:
                            # collect_signals кладёт строку (rs.pricing.value),
                            # price_for() ждёт PricingMode — приводим явно.
                            pricing = parse_pricing(
                                str(next(iter(plan["pricings"]))), sym)
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
                                    pricing=pricing.value, result_qty=target,
                                )

                if order is not None and not status:
                    try:
                        assert_stop_clear(STOP_REAL)
                    except ExecutionError as exc:
                        note = (f"{acc_id}/{sym}: STOP_REAL посреди прогона — "
                                f"заявка не отправлена: {exc}")
                        notes.append(note)
                        print(note)
                        aborted = True
                        break
                    result = gateway.submit(order, account=acc_id,
                                            stop=STOP_REAL,
                                            dry_run=args.dry_run)
                    status, reason = result.status, result.reason
                    if result.sent and result.client_order_id:
                        paper_signals[result.client_order_id] = {
                            "price": plan["price"], "side": side, "symbol": sym}
                elif status in ("skipped", "rejected"):
                    # чтобы пропуск был виден в журнале, а не только в сводке
                    stub = Order(client_id=client_id, config=ids, symbol=sym,
                                 side="buy" if delta > 0 else "sell",
                                 qty=abs(delta), price=plan["price"],
                                 multiplier=mult_for(sym), min_step=tick_for(sym),
                                 account=acc_id, result_qty=target)
                    gateway.log_decision(stub, status, reason)

                counts[status or "noop"] = counts.get(status or "noop", 0) + 1
                decisions[(acc_id, sym)] = status or "noop"
                if reason:
                    decisions[(acc_id, sym)] += f": {reason}"
                if reason or note:
                    notes.append(f"{acc_id}/{sym}: {reason or note}")
            if aborted:
                break

            # Заявка может исполниться за секунды: дописать filled/partial в журнал.
            # Делаем после reconcile — иначе модель position из sent-заявок
            # перестанет совпадать с брокером и сверка поставит STOP.
            try:
                refreshed = tj.refresh_executions(
                    broker, acc_id, csv_path=LIVE)
                if refreshed["updated"]:
                    notes.append(f"{acc_id}: исполнений в журнале: "
                                 f"{refreshed['updated']}/{refreshed['checked']}")
                for cid, detail in refreshed.get("details", {}).items():
                    sig = paper_signals.get(cid)
                    if sig is None:
                        continue
                    side = detail["side"]
                    adverse = ((detail["price"] - sig["price"]) if side == "buy"
                               else (sig["price"] - detail["price"]))
                    tick = tick_for(sig["symbol"])
                    fills.append({
                        "client_order_id": cid, "symbol": sig["symbol"],
                        "side": side, "qty": detail["qty"],
                        "signal_price": sig["price"], "fill_price": detail["price"],
                        "adverse_ticks": round(adverse / tick, 2) if tick else None,
                        "adverse_rub": round(adverse * detail["qty"]
                                             * mult_for(sig["symbol"]), 2),
                        "status": detail["status"], "ts": detail["ts"],
                    })
            except Exception as exc:  # noqa: BLE001 — отсутствие брокера не роняет прогон
                notes.append(f"{acc_id}: не удалось обновить исполнения: "
                             f"{type(exc).__name__}")

            # Позиция в панели — факт счёта после прогона, а не намерение.
            # При недоступности API остаёмся на позиции до отправки (dry-run
            # её не меняет); ошибка наблюдения не должна рушить сводку.
            try:
                actual_now = broker_positions(broker, acc_id)
            except Exception:  # noqa: BLE001 — панель наблюдательная
                actual_now = None
            for sym, plan in symbols.items():
                pos = actual_now.get(sym, 0) if actual_now is not None \
                    else actual.get(sym, 0)
                for iid in plan["robots"]:
                    runtime_updates.append({
                        "instance_id": iid, "symbol": sym, "position": pos,
                        "equity": equity, "last_price": plan["price"],
                        "last_decision": f"{day} {plan['when']} "
                                         f"{decisions.get((acc_id, sym), 'noop')}",
                        "note": "факт позиции счёта (общая для роботов счёта)",
                    })

        notes.extend(sync_live_runtime(RobotStore(), runtime_updates))
        write_summary(day, args, counts, settings, plans, notes, fills)
        print(f"live {day}: {sum(counts.values())} решений, статусы {counts}, "
              f"{'dry-run' if args.dry_run else 'реальные заявки'}"
              f"{'; STOP — сводка записана' if aborted else ''}")
        return 2 if aborted else 0
    finally:
        pass  # лок прогона держит панель; дубли заявок отсекает журнал по статусу


if __name__ == "__main__":
    raise SystemExit(main())
