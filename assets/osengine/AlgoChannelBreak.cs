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
    internal static class AlgoChannelBreakCommon
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

    [Bot("AlgoChannelBreak")]
    public class AlgoChannelBreak : BotPanel
    {
        private BotTabSimple _tab;
        private StrategyParameterInt _sh, _sm, _wh, _wm;
        private StrategyParameterDecimal _sl, _mult, _exposure;
        private StrategyParameterString _direction;
        private DateTime _day = DateTime.MinValue, _boundaryDate = DateTime.MinValue;
        private decimal _boundaryClose = 0m, _prevBoundaryClose = 0m;
        private decimal _hh = 0m, _ll = 0m;
        private bool _armed, _boundaryToday, _switchToday;
        private int _dir;

        public AlgoChannelBreak(string name, StartProgram p) : base(name, p)
        {
            TabCreate(BotTabType.Simple);
            _tab = TabsSimple[0];
            _sh = CreateParameter("Start hour", 23, 0, 23, 1, "Time");
            _sm = CreateParameter("Start minute", 40, 0, 55, 5, "Time");
            _wh = CreateParameter("Switch hour", 13, 0, 23, 1, "Time");
            _wm = CreateParameter("Switch minute", 0, 0, 55, 5, "Time");
            _sl = CreateParameter("Stop loss", 0.12m, 0m, 100000m, 0.001m, "Base");
            _direction = CreateParameter("Direction", "Long", new[] { "Long", "Short", "Both" }, "Base");
            _mult = CreateParameter("Multiplier", 1000m, 0.0001m, 100000m, 0.0001m, "Money");
            _exposure = CreateParameter("Exposure", 1m, 0.1m, 2m, 0.1m, "Money");
            _tab.CandleFinishedEvent += Candle;
            Description = "Port of algo/strategies/channel_break.py day/long mode. Research only.";
        }
        public override string GetNameStrategyType() { return "AlgoChannelBreak"; }
        public override void ShowIndividualSettingsDialog() { }

        private void Candle(List<Candle> c)
        {
            if (c.Count < 2) return;
            int i = c.Count - 1;
            Candle bar = c[i];
            DateTime date = bar.TimeStart.Date;
            int m = AlgoChannelBreakCommon.Minutes(bar.TimeStart);
            int startM = _sh.ValueInt * 60 + _sm.ValueInt;
            int switchM = _wh.ValueInt * 60 + _wm.ValueInt;
            bool allowLong = _direction.ValueString == "Long" || _direction.ValueString == "Both";

            if (date != _day)
            {
                _day = date;
                _boundaryToday = false;
                _switchToday = false;
            }

            if (!_boundaryToday && m >= startM)
            {
                // граница цикла: выход и запоминание закрытия
                if (_armed && AlgoChannelBreakCommon.PositionDirection(_tab.PositionsOpenAll) != 0)
                    _tab.CloseAllAtMarket();
                _armed = false;
                _prevBoundaryClose = _boundaryClose;
                _boundaryClose = bar.Close;
                _boundaryDate = date;
                _hh = 0m;
                _ll = 0m;
                _boundaryToday = true;
                return;
            }

            if (_boundaryClose > 0)
            {
                if (_hh == 0m || bar.High > _hh) _hh = bar.High;
                if (_ll == 0m || bar.Low < _ll) _ll = bar.Low;
            }

            if (!_switchToday && m >= switchM && _boundaryClose > 0 && _prevBoundaryClose > 0)
            {
                _switchToday = true;
                _dir = _boundaryClose >= _prevBoundaryClose ? 1 : -1;
                if (!allowLong && _dir == 1) return;
                if (_hh > _ll && _ll > 0) _armed = true;
                return;
            }

            int have = AlgoChannelBreakCommon.PositionDirection(_tab.PositionsOpenAll);
            if (have == 1 && bar.Low <= _stop) { _tab.CloseAllAtMarket(); return; }
            if (have == -1 && bar.High >= _stop) { _tab.CloseAllAtMarket(); return; }

            if (_armed && have == 0 && _dir == 1 && allowLong && _hh > 0 && bar.Close > _hh)
            {
                decimal vol = AlgoChannelBreakCommon.Volume(_tab, bar.Close, _mult.ValueDecimal, _exposure.ValueDecimal);
                _tab.BuyAtMarket(vol);
                _stop = Math.Max(_ll, bar.Close - _sl.ValueDecimal);
            }
        }
        private decimal _stop;
    }

}
