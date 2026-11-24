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
    internal static class AlgoUniversalCommon
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

    [Bot("AlgoUniversal")]
    public class AlgoUniversal : BotPanel
    {
        private BotTabSimple _tab;
        private StrategyParameterInt _rh, _rm, _eh, _em, _xh, _xm;
        private StrategyParameterDecimal _longOff, _shortOff, _mult, _exposure;
        private StrategyParameterString _hold;
        private StrategyParameterBool _friday, _weekend;
        private DateTime _day = DateTime.MinValue;
        private decimal _ref = 0m;
        private bool _refSet, _decided, _pendingExit;

        public AlgoUniversal(string name, StartProgram p) : base(name, p)
        {
            TabCreate(BotTabType.Simple);
            _tab = TabsSimple[0];
            _rh = CreateParameter("Ref hour", 10, 0, 23, 1, "Time");
            _rm = CreateParameter("Ref minute", 5, 0, 55, 5, "Time");
            _eh = CreateParameter("Entry hour", 13, 0, 23, 1, "Time");
            _em = CreateParameter("Entry minute", 30, 0, 55, 5, "Time");
            _xh = CreateParameter("Exit hour", 10, 0, 23, 1, "Time");
            _xm = CreateParameter("Exit minute", 20, 0, 55, 5, "Time");
            _longOff = CreateParameter("Long offset", 0.004m, 0m, 0.1m, 0.0001m, "Base");
            _shortOff = CreateParameter("Short offset", 0.002m, 0m, 0.1m, 0.0001m, "Base");
            _hold = CreateParameter("Hold", "Daily", new[] { "Daily", "Morning" }, "Base");
            _friday = CreateParameter("Allow short Friday", false, "Base");
            _weekend = CreateParameter("Skip weekends", true, "Base");
            _mult = CreateParameter("Multiplier", 1000m, 0.0001m, 100000m, 0.0001m, "Money");
            _exposure = CreateParameter("Exposure", 1m, 0.1m, 2m, 0.1m, "Money");
            _tab.CandleFinishedEvent += Candle;
            Description = "Port of algo/strategies/universal.py. Research only.";
        }
        public override string GetNameStrategyType() { return "AlgoUniversal"; }
        public override void ShowIndividualSettingsDialog() { }

        private void Candle(List<Candle> c)
        {
            if (c.Count < 2) return;
            int i = c.Count - 1;
            Candle bar = c[i];
            DateTime date = bar.TimeStart.Date;
            int m = AlgoUniversalCommon.Minutes(bar.TimeStart);
            int refM = _rh.ValueInt * 60 + _rm.ValueInt;
            int entM = _eh.ValueInt * 60 + _em.ValueInt;
            int exitM = _xh.ValueInt * 60 + _xm.ValueInt;

            if (date != _day)
            {
                _day = date;
                _refSet = false;
                _decided = false;
            }

            if (_pendingExit && m >= exitM)
            {
                _tab.CloseAllAtMarket();
                _pendingExit = false;
            }

            if (!_refSet && m >= refM)
            {
                _ref = bar.Close;
                _refSet = true;
            }

            if (_decided || !_refSet || m < entM || _ref <= 0) return;
            if (_weekend.ValueBool &&
                (bar.TimeStart.DayOfWeek == DayOfWeek.Saturday ||
                 bar.TimeStart.DayOfWeek == DayOfWeek.Sunday)) return;
            _decided = true;

            int want = 0;
            if (bar.Close >= _ref * (1m + _longOff.ValueDecimal)) want = 1;
            else if (bar.Close <= _ref * (1m - _shortOff.ValueDecimal))
            {
                if (bar.TimeStart.DayOfWeek != DayOfWeek.Friday || _friday.ValueBool) want = -1;
            }

            int have = AlgoUniversalCommon.PositionDirection(_tab.PositionsOpenAll);
            if (want == have) return;
            if (have != 0) _tab.CloseAllAtMarket();
            if (want > 0) _tab.BuyAtMarket(AlgoUniversalCommon.Volume(_tab, bar.Close, _mult.ValueDecimal, _exposure.ValueDecimal));
            else if (want < 0) _tab.SellAtMarket(AlgoUniversalCommon.Volume(_tab, bar.Close, _mult.ValueDecimal, _exposure.ValueDecimal));
            if (want != 0 && _hold.ValueString == "Morning") _pendingExit = true;
        }
    }

}
