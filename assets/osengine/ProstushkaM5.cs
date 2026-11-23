/*
 * Порт стратегии «Простушка» (MA48, M5) для OsEngine 2.0.2.0.
 * Логика: один сигнал в день на свече входа (по умолчанию 13:50):
 *   close > SMA(period)  -> long
 *   close < SMA(period)  -> short (если разрешён)
 *   противоположный сигнал закрывает позицию и открывает новую.
 * Источник: algo/strategies/prostushka.py, docs/strategies/prostushka.md.
 *
 * Это исследовательский порт для сравнения через OsEngine, а не боевой робот.
 */

using System;
using System.Collections.Generic;
using OsEngine.Charts.CandleChart.Indicators;
using OsEngine.Entity;
using OsEngine.Indicators;
using OsEngine.OsTrader.Panels;
using OsEngine.OsTrader.Panels.Attributes;
using OsEngine.OsTrader.Panels.Tab;

namespace OsEngine.Robots
{
    [Bot("ProstushkaM5")]
    public class ProstushkaM5 : BotPanel
    {
        private BotTabSimple _tab;
        private Aindicator _sma;

        private StrategyParameterString _regime;
        private StrategyParameterInt _maPeriod;
        private StrategyParameterInt _entryHour;
        private StrategyParameterInt _entryMinute;
        private StrategyParameterDecimal _volume;
        private StrategyParameterBool _allowShort;

        public ProstushkaM5(string name, StartProgram startProgram) : base(name, startProgram)
        {
            TabCreate(BotTabType.Simple);
            _tab = TabsSimple[0];

            _regime = CreateParameter("Regime", "On",
                new[] { "Off", "On", "OnlyLong", "OnlyClosePosition" }, "Base");
            _maPeriod = CreateParameter("MA period", 48, 5, 400, 1, "Base");
            _volume = CreateParameter("Volume, contracts", 1m, 1m, 100m, 1m, "Base");
            _allowShort = CreateParameter("Allow short", true, "Base");
            _entryHour = CreateParameter("Entry hour", 13, 0, 23, 1, "Time");
            _entryMinute = CreateParameter("Entry minute", 50, 0, 59, 5, "Time");

            _sma = IndicatorsFactory.CreateIndicatorByName("Sma", name + "Sma", false);
            _sma = (Aindicator)_tab.CreateCandleIndicator(_sma, "Prime");
            ((IndicatorParameterInt)_sma.Parameters[0]).ValueInt = _maPeriod.ValueInt;
            _sma.Save();

            ParametrsChangeByUser += ProstushkaM5_ParametrsChangeByUser;
            _tab.CandleFinishedEvent += Tab_CandleFinishedEvent;

            Description = "Простушка: entry 13:50 M5, close vs SMA, one signal per day. Research port.";
        }

        public override string GetNameStrategyType()
        {
            return "ProstushkaM5";
        }

        public override void ShowIndividualSettingsDialog()
        {
        }

        private void ProstushkaM5_ParametrsChangeByUser()
        {
            ((IndicatorParameterInt)_sma.Parameters[0]).ValueInt = _maPeriod.ValueInt;
            _sma.Save();
            _sma.Reload();
        }

        private void Tab_CandleFinishedEvent(List<Candle> candles)
        {
            if (_regime.ValueString == "Off") return;
            if (candles.Count < _maPeriod.ValueInt + 2) return;

            Candle candle = candles[candles.Count - 1];
            if (candle.TimeStart.Hour != _entryHour.ValueInt ||
                candle.TimeStart.Minute != _entryMinute.ValueInt) return;

            decimal ma = _sma.DataSeries[0].Last;
            if (ma <= 0) return;

            List<Position> positions = _tab.PositionsOpenAll;
            bool flat = positions == null || positions.Count == 0;
            bool isLong = !flat && positions[0].Direction == Side.Buy;
            bool wantLong = candle.Close > ma;
            bool wantShort = candle.Close < ma && _allowShort.ValueBool;

            if (flat)
            {
                if (_regime.ValueString == "OnlyClosePosition") return;
                if (wantLong) _tab.BuyAtMarket(GetVolume());
                else if (wantShort) _tab.SellAtMarket(GetVolume());
                return;
            }

            if (wantLong && !isLong)
            {
                _tab.CloseAllAtMarket();
                if (_regime.ValueString != "OnlyClosePosition") _tab.BuyAtMarket(GetVolume());
            }
            else if (wantShort && isLong)
            {
                _tab.CloseAllAtMarket();
                if (_regime.ValueString != "OnlyClosePosition") _tab.SellAtMarket(GetVolume());
            }
            else if (!_allowShort.ValueBool && !wantLong && isLong)
            {
                _tab.CloseAllAtMarket();
            }
        }

        private decimal GetVolume()
        {
            return _volume.ValueDecimal;
        }
    }
}
