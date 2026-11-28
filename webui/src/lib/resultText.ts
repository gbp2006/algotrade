// Человекочитаемые результаты ответов сервера: сырой JSON не показываем пользователю.
import { money, time } from './format';

type Result = Record<string, unknown> | null | undefined;

const str = (value: unknown): string =>
  value === null || value === undefined ? '' : String(value);

const int = (value: unknown): number | null => {
  const number = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(number) ? number : null;
};

const plural = (value: number | null, one: string, few: string, many: string): string => {
  if (value === null) return 'н/д';
  const mod100 = Math.abs(value) % 100;
  const mod10 = mod100 % 10;
  const form = mod100 >= 11 && mod100 <= 14 ? many
    : mod10 === 1 ? one : mod10 >= 2 && mod10 <= 4 ? few : many;
  return `${money(value)} ${form}`;
};

const reason = (data: Result): string => {
  const text = str(data?.reason);
  return text ? `; причина: ${text}` : '';
};

/** Сводка справочника инструментов вместо строкки JSON. */
export const instrumentStatsText = (data: Result): string => {
  const refreshed = time(str(data?.last_refresh) || undefined);
  const error = str(data?.last_error);
  return `Инструментов в каталоге: ${plural(int(data?.total), 'инструмент', 'инструмента', 'инструментов')}`
    + `, с торговыми параметрами: ${money(int(data?.enriched))}`
    + `; обновлён ${refreshed}${error ? `; последняя ошибка: ${error}` : ''}.`;
};

/** Результат действия со справочником инструментов. */
export const instrumentActionText = (
  action: 'fav' | 'params' | 'refresh' | 'liquid', data: Result,
): string => {
  if (data?.ok === false) return `Ошибка справочника${reason(data)}`;
  if (action === 'fav') {
    const symbol = str(data?.symbol);
    return `${symbol}: ${data?.favorite === true ? 'добавлено в избранное' : 'удалено из избранного'}`;
  }
  if (action === 'params') {
    const symbol = str(data?.symbol);
    const tradeable = data?.tradeable ? 'торговля разрешена' : 'торговля запрещена';
    return `Параметры ${symbol}: ${tradeable}, лот ${money(int(data?.lot_size))},`
      + ` начальная маржа ${money(int(data?.initial_margin))} ₽`;
  }
  if (action === 'liquid') {
    const byType = data?.by_type;
    const groups = byType && typeof byType === 'object'
      ? Object.entries(byType).map(([kind, count]) => `${kind}: ${money(int(count))}`).join(', ')
      : '';
    return `Топ ликвидных обновлён: ${plural(int(data?.selected), 'инструмент', 'инструмента', 'инструментов')}`
      + `${groups ? ` (${groups})` : ''}`;
  }
  return `Каталог обновлён: получено ${money(int(data?.total))},`
    + ` добавлено ${money(int(data?.added))}, обновлено ${money(int(data?.updated))}`;
};

/** Результат ребаланса/закрытия фонда денежного рынка. */
export const fundActionText = (action: 'rebalance' | 'close', data: Result): string => {
  const verb = action === 'close' ? 'Закрытие фонда' : 'Ребаланс фонда';
  if (data?.ok === false) return `${verb}: не выполнено${reason(data)}`;
  if (data?.skipped === true) return `${verb}: пропущено${reason(data)}`;
  const closed = int(data?.closed);
  if (closed !== null) return `${verb}: закрыто ${plural(closed, 'пай', 'пая', 'паёв')}${reason(data)}`;
  const qty = int(data?.qty);
  const symbol = str(data?.symbol);
  if (qty !== null) {
    const side = str(data?.side) === 'sell' ? 'продажа' : 'покупка';
    const price = int(data?.price);
    return `${verb} ${symbol}: ${side} ${plural(qty, 'пай', 'пая', 'паёв')}`
      + `${price !== null ? ` по цене ${money(price, 4)}` : ''}`
      + `, статус ${str(data?.status) || 'отправлено'}${reason(data)}`;
  }
  return `${verb}: выполнено${reason(data)}`;
};
