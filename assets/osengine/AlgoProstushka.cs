/*
 * Исследовательский порт стратегий песочницы в OsEngine 2.0.2.0.
 * Четыре семейства правил из algo/configs.py + algo/robot_configs.py:
 *   AlgoProstushka, AlgoUniversal, AlgoChannelBreak, AlgoDonchian.
 * Сайзинг: 100% номинала (equity * exposure / (price * multiplier)), минимум 1 контракт.
 * Модель: сигнал по закрытию свечи, рыночная заявка исполняется движком тестера
 * на следующем баре (задаётся в optimizer_trade_settings).
 * НЕ боевой робот: только сверка бэктестов, ADR 18.11 не отменяется.
 */
using System;
using System.Collections.Generic;
using OsEngine.Entity;
using OsEngine.OsTrader.Panels;
using OsEngine.OsTrader.Panels.Attributes;
using OsEngine.OsTrader.Panels.Tab;

namespace OsEngine.Robots
{
    internal static class AlgoProstushkaCommon
    {
        public static int Minutes(DateTime t) { return t.Hour * 60 + t.Minute; }
        public static bool IsFirstOfDay(List<Candle> c, int i, int minutes)
        {
            if (i == 0) return Minutes(c[i].TimeStart) >= minutes;
            return c[i].TimeStart.Date != c[i - 1].TimeStart.Date &&
                   Minutes(c[i].TimeStart) >= minutes;
        }
        public static decimal Sma(List<Candle> c, int end, int period)
        {
            if (end < period - 1) return 0m;
            decimal s = 0m;
            for (int i = end - period + 1; i <= end; i++) s += c[i].Close;
            return s / period;
        }
        public static decimal Volume(BotTabSimple tab, decimal price, decimal mult, decimal exposure)
        {
            decimal equity = 200000m;
            if (tab.Portfolio != null && tab.Portfolio.ValueCurrent > 0)
                equity = tab.Portfolio.ValueCurrent;
            decimal notional = price * mult;
            if (notional <= 0) return 1m;
            decimal v = Math.Floor(equity * exposure / notional);
            if (v < 1m) v = 1m;
            if (v > 1000m) v = 1000m;
            return v;
        }
        public static int PositionDirection(List<Position> p)
        {
            if (p == null || p.Count == 0) return 0;
            return p[0].Direction == Side.Buy ? 1 : -1;
        }
    }

    [Bot("AlgoProstushka")]
    public class AlgoProstushka : BotPanel
    {
        private BotTabSimple _tab;
        private StrategyParameterInt _ma, _eh, _em, _filter, _multInt;
        private StrategyParameterBool _friday, _weekend;
        private StrategyParameterDecimal _mult, _exposure;
        private DateTime _lastDecision = DateTime.MinValue;

        public AlgoProstushka(string name, StartProgram p) : base(name, p)
        {
            TabCreate(BotTabType.Simple);
            _tab = TabsSimple[0];
            _ma = CreateParameter("MA period", 40, 2, 500, 1, "Base");
            _eh = CreateParameter("Entry hour", 13, 0, 23, 1, "Time");
            _em = CreateParameter("Entry minute", 50, 0, 55, 5, "Time");
            _filter = CreateParameter("Filter bars", 3, 1, 20, 1, "Base");
            _friday = CreateParameter("Allow short Friday", false, "Base");
            _weekend = CreateParameter("Skip weekends", true, "Base");
            _mult = CreateParameter("Multiplier", 1000m, 0.0001m, 100000m, 0.0001m, "Money");
            _exposure = CreateParameter("Exposure", 1m, 0.1m, 2m, 0.1m, "Money");
            _tab.CandleFinishedEvent += Candle;
            Description = "Port of algo/strategies/prostushka.py. Research only.";
        }
        public override string GetNameStrategyType() { return "AlgoProstushka"; }
        public override void ShowIndividualSettingsDialog() { }

        private void Candle(List<Candle> c)
        {
            if (c.Count < _ma.ValueInt + _filter.ValueInt + 2) return;
            int i = c.Count - 1;
            DateTime t = c[i].TimeStart;
            if (t.Date == _lastDecision.Date) return;
            if (AlgoProstushkaCommon.Minutes(t) < _eh.ValueInt * 60 + _em.ValueInt) return;
            if (_weekend.ValueBool && t.DayOfWeek == DayOfWeek.Saturday) return;
            if (_weekend.ValueBool && t.DayOfWeek == DayOfWeek.Sunday) return;
            _lastDecision = t.Date;

            decimal ma = AlgoProstushkaCommon.Sma(c, i, _ma.ValueInt);
            if (ma <= 0) return;
            bool longOk = true;
            for (int k = 0; k < _filter.ValueInt; k++)
            {
                decimal mak = AlgoProstushkaCommon.Sma(c, i - k, _ma.ValueInt);
                if (mak <= 0 || c[i - k].Close <= mak) { longOk = false; break; }
            }
            int want = 0;
            if (c[i].Close > ma && longOk) want = 1;
            else if (c[i].Close < ma)
            {
                bool fridayOk = t.DayOfWeek != DayOfWeek.Friday || _friday.ValueBool;
                if (fridayOk) want = -1;
            }
            int have = AlgoProstushkaCommon.PositionDirection(_tab.PositionsOpenAll);
            if (want == have) return;
            if (have != 0) _tab.CloseAllAtMarket();
            if (want > 0) _tab.BuyAtMarket(AlgoProstushkaCommon.Volume(_tab, c[i].Close, _mult.ValueDecimal, _exposure.ValueDecimal));
            else if (want < 0) _tab.SellAtMarket(AlgoProstushkaCommon.Volume(_tab, c[i].Close, _mult.ValueDecimal, _exposure.ValueDecimal));
        }
    }

}
