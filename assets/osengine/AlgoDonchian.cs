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
    internal static class AlgoDonchianCommon
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

    [Bot("AlgoDonchian")]
    public class AlgoDonchian : BotPanel
    {
        private BotTabSimple _tab;
        private StrategyParameterInt _entry, _exit, _eh, _em;
        private StrategyParameterBool _short;
        private StrategyParameterDecimal _mult, _exposure;
        private DateTime _day = DateTime.MinValue, _decisionDate = DateTime.MinValue;
        private readonly List<decimal> _hi = new List<decimal>();
        private readonly List<decimal> _lo = new List<decimal>();
        private decimal _curHi, _curLo, _curClose;
        private int _pos;

        public AlgoDonchian(string name, StartProgram p) : base(name, p)
        {
            TabCreate(BotTabType.Simple);
            _tab = TabsSimple[0];
            _entry = CreateParameter("Entry", 20, 2, 100, 1, "Base");
            _exit = CreateParameter("Exit", 10, 2, 100, 1, "Base");
            _eh = CreateParameter("Entry hour", 13, 0, 23, 1, "Time");
            _em = CreateParameter("Entry minute", 55, 0, 55, 5, "Time");
            _short = CreateParameter("Allow short", true, "Base");
            _mult = CreateParameter("Multiplier", 1000m, 0.0001m, 100000m, 0.0001m, "Money");
            _exposure = CreateParameter("Exposure", 1m, 0.1m, 2m, 0.1m, "Money");
            _tab.CandleFinishedEvent += Candle;
            Description = "Port of algo/strategies/candidates.py donchian. Research only.";
        }
        public override string GetNameStrategyType() { return "AlgoDonchian"; }
        public override void ShowIndividualSettingsDialog() { }

        private void Candle(List<Candle> c)
        {
            if (c.Count < 2) return;
            int i = c.Count - 1;
            Candle bar = c[i];
            DateTime date = bar.TimeStart.Date;
            if (date != _day && _day != DateTime.MinValue)
            {
                _hi.Add(_curHi);
                _lo.Add(_curLo);
                if (_hi.Count > 90) { _hi.RemoveAt(0); _lo.RemoveAt(0); }
                _curHi = bar.High;
                _curLo = bar.Low;
                _day = date;
            }
            else if (_day == DateTime.MinValue)
            {
                _curHi = bar.High;
                _curLo = bar.Low;
                _day = date;
            }
            else
            {
                if (bar.High > _curHi) _curHi = bar.High;
                if (bar.Low < _curLo) _curLo = bar.Low;
            }
            _curClose = bar.Close;

            int m = AlgoDonchianCommon.Minutes(bar.TimeStart);
            if (_decisionDate.Date == date || m < _eh.ValueInt * 60 + _em.ValueInt) return;
            if (_hi.Count < _entry.ValueInt) return;
            _decisionDate = date;

            decimal hh = 0m, ll = decimal.MaxValue, xh = 0m, xl = decimal.MaxValue;
            for (int k = 1; k <= _entry.ValueInt; k++)
            {
                int j = _hi.Count - k;
                if (_hi[j] > hh) hh = _hi[j];
                if (_lo[j] < ll) ll = _lo[j];
            }
            for (int k = 1; k <= _exit.ValueInt; k++)
            {
                int j = _hi.Count - k;
                if (_hi[j] > xh) xh = _hi[j];
                if (_lo[j] < xl) xl = _lo[j];
            }
            int want = _pos;
            if (want == 0)
            {
                if (_curClose > hh) want = 1;
                else if (_short.ValueBool && _curClose < ll) want = -1;
            }
            else if (want == 1 && _curClose < xl) want = 0;
            else if (want == -1 && _curClose > xh) want = 0;

            _pos = want;
            int have = AlgoDonchianCommon.PositionDirection(_tab.PositionsOpenAll);
            if (want == have) return;
            if (have != 0) _tab.CloseAllAtMarket();
            if (want > 0) _tab.BuyAtMarket(AlgoDonchianCommon.Volume(_tab, _curClose, _mult.ValueDecimal, _exposure.ValueDecimal));
            else if (want < 0) _tab.SellAtMarket(AlgoDonchianCommon.Volume(_tab, _curClose, _mult.ValueDecimal, _exposure.ValueDecimal));
        }
    }
}
