# OsEngine как источник идей (23.11.2026)

Источник: локальный клон
`materials/04_Софт_и_инструменты/OsEngine Софт/OsEngine-master/project/OsEngine`
(GitHub `AlexWan/OsEngine`). Сверка с OsEngine как эталоном по-прежнему исключена
(ADR 18.11) — здесь он используется только как каталог логик.

Папка `Lenta` в этой версии отсутствует; роботы лежат в `Robots/{Trend,Patterns,
OnScriptIndicators,VolatilityStageRotationSamples,PositionsMicromanagement}`.
`ТС OsEngine 4 стратегии` содержит только скриншоты бэктестов, логики нет.
`_TimeChannelBreak.cs` нами уже портирован (`reports/channel-break-research.md`).

## Кандидаты, реализуемые на наших данных

| Идея | Файл в OsEngine | Логика | Почему может быть ценна |
|---|---|---|---|
| `ParabolicSarTrade` | `Robots/Trend/ParabolicSarTrade.cs` | вход по пересечению цены с SAR, выход по обратному сигналу | нелинейный встроенный трейлинг вместо ATR-каналов |
| `RviTrade` | `Robots/OnScriptIndicators/RviTrade.cs` | RVI из OHLC: нижняя <0 и верхняя > нижней, выход по возврату | новый осциллятор на тех же данных |
| `CciTrade` | `Robots/OnScriptIndicators/CciTrade.cs` | контртренд при CCI<−150 / >+150, выход по обратному сигналу | порог на typical price, до 3 позиций |
| `StrategyBillWilliams` | `Robots/Trend/StrategyBillWilliams.cs` | цена выше/ниже трёх линий Alligator + фрактал + AO, выход о среднюю линию | композитная структура, не наш SMA-cross |
| `PivotPointsRobot` | `Robots/Patterns/PivotPointsRobot.cs` | пробой R1/S1 от вчерашних H/L/C, цели R3/S3, %-стоп | дневные уровни — ценовая структура, которой нет в каталоге |
| `PinBarTrade` | `Robots/Patterns/PinBarTrade.cs` | закрытие/открытие в верхней или нижней трети бара + SMA-фильтр | микроструктура одного бара |
| `ThreeSoldierVolatilityAdaptive` | `Robots/Patterns/ThreeSoldierVolatilityAdaptive.cs` | три однонаправленных бара с телом выше порога, выход SL/TP | порог нормирован на цену — фильтр волатильности |
| `CandlesTurnaroundPattern` | `Robots/PositionsMicromanagement/CandlesTurnaroundPattern.cs` | разворот после крупной противоположной свечи, лестница TP + SL | частичное фиксирование вместо одного выхода |
| `BreakLinearRegressionChannel` | `Robots/Trend/BreakLinearRegressionChannel.cs` | закрытие за линией регрессионного канала, выход на противоположной | наклонный канал вместо горизонтального |
| `EnvelopsCountertrend` | `Robots/PositionsMicromanagement/EnvelopsCountertrend.cs` | вход за %-огибающей SMA, усреднение, TP/стоп | огибающие в % отличаются от Bollinger по σ |
| `VolatilityAdaptiveCandlesTrader` | `Robots/Patterns/VolatilityAdaptiveCandlesTrader.cs` | вход по направлению бара при \|close−open\|/close выше порога, трейлинг | адаптация к волатильности без индикатора |

## Топ-3 для прототипирования

1. **PivotPointsRobot** — новый класс дневных уровней, легко считается на дневных барах.
2. **ThreeSoldierVolatilityAdaptive** — режимный фильтр, которого не хватало в 30 проваленных прогонах.
3. **ParabolicSarTrade** — новый механизм выхода при сохранении нашего тайм-фильтра.

## Явные дубли того, что уже проверено

Bollinger (`StrategyBollinger`, `BollingerRevers`, `BollingerTrailing`,
`BollingerTrendVolatilityStagesFilter`); PriceChannel/Donchian (`PriceChannelTrade`,
`PriceChannelBreak`, `PriceChannelVolatility`, `PriceChannelTrendAtrFilter`,
`AlgoStart3PriceChannel`); RSI (`RsiTrade`, `RsiContrtrend`); MACD (`MacdRevers`,
`MacdTrail`, `MomentumMacd`). `Fisher`, `ClusterCountertrend`, `MarketMaker`,
`Options`, `Funding` требуют стакан/тики/опционы/funding — наших данных нет.

Решение: кандидатов в бумажный контур не выкладывать до прохождения строгих
гейтов (ADR 23.11 про 30 систем). Отчёт — источник идей для будущих прототипов.
