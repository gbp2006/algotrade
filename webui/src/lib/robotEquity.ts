import type { Analytics, Robot, RuntimeState } from './types';

/** Equity для строки робота: своя строка рантайма, иначе equity реального счёта. */
export function robotEquity(
  robot: Pick<Robot, 'id' | 'mode' | 'account'>,
  runtime: RuntimeState | undefined,
  analytics: Analytics | undefined,
): number | null {
  const own = runtime?.equity ?? null;
  if (own !== null) return own;
  if (robot.mode !== 'live' || !robot.account) return null;
  return analytics?.real.find((account) => account.id === robot.account)?.equity ?? null;
}
