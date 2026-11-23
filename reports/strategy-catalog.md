# Каталог потенциальных стратегий для ликвидных инструментов РФ

Дата: 21.11.2026. Черновик — все найденные идеи, включая те, что мы сейчас не
сможем реализовать. Статусы: 🟢 — беру в прототип на наших данных; 🟡 — реализуемо
позже / нужны дополнительные данные; 🔴 — требует того, чего нет (стакан,
опционы, история акций, интрабарные стопы).

Набор инструментов: фьючерсы MOEX **Si, RTS(RI), CNY, GLDRUBF (GOLD), BR**;
приоритет — M1/M5/дневные бары, движок `algo/engine.py` (сигнал по close, сделка
по open следующего бара, 0.01% + 1 тик, `skip_weekend`).

## Источники поиска

- Quantpedia: Time-Series Momentum Effect — https://quantpedia.com/strategies/time-series-momentum-effect
- Quantpedia: Time-Series Momentum Works Everywhere — https://quantpedia.com/time-series-momentum-works-everywhere
- Quantpedia: Boundaries of Time Series Momentum — https://quantpedia.com/boundaries-of-time-series-momentum
- Quantpedia: Time-Series vs Cross-Sectional Momentum/Value/Carry — https://quantpedia.com/time-series-vs-cross-sectional-implementation-of-momentum-value-and-carry-strat
- QuantConnect Strategy Library — https://www.quantconnect.com/docs/v2/writing-algorithms/strategy-library
- QuantConnect: Pairs Trading With Stocks — https://www.quantconnect.com/research/15300/pairs-trading-with-stocks
- QuantConnect: Opening Range Breakout — https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play
- Robot Wealth: A Short Take on Real-World Pairs Trading — https://robotwealth.com/a-short-take-on-real-world-pairs-trading
- BuildAlpha: Opening Range Breakout, 4 setups — https://www.buildalpha.com/opening-range-breakout
- QuantifiedStrategies: 100 Free Trading Strategies — https://quantifiedstrategies.substack.com/p/100-free-trading-strategies
- Tradeify: Trend Following Explained — https://tradeify.co/education/trading-strategies
- QuantInsti: Trend Following with TSMOM + Continuous Forecasts — https://blog.quantinsti.com/trend-following-strategy-futures-time-series-momentum-continuous-forecasts-project-jirong-huang
- PapersWithBacktest: Mean Reversion Trading Strategy — https://paperswithbacktest.com/strategies/mean-reversion-trading-strategy
- MOEX: Investing strategies — https://www.moex.com/a7206
- VWAP reversion (intraday) — https://www.ainvest.com/aime/share/backtest-proven-strategy-intraday-ad203b

## 1. Тренд и моментум

| ID | Название | Правила (как реализовывать) | Параметры | Инструменты | Источник | Статус |
|---|---|---|---|---|---|---|
| T01 | Time-series momentum (TSMOM) | Если доходность за последние 12 мес > 0 — лонг, < 0 — шорт; ребаланс раз в мес; сайз ∝ 1/реализ. волатильности | 12 мес, vol 20/60 дн | Si, CNY, RTS, GOLD, BR | [Moskowitz et al. 2012](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf) | 🟢 |
| T02 | TSMOM 6-1 / 3-1 | То же, но с пропуском последнего месяца (12-1) и короткими окнами 6/3 мес — ниже лага, больше сделок | 6-1, 3-1 мес | те же | [Quantpedia TSMOM](https://quantpedia.com/strategies/time-series-momentum-effect) | 🟢 |
| T03 | TSMOM + фильтр оценки (CAPE/percentile) | При цене в верхнем 10–20-летнем перцентиле — снизить риск/готовиться к развороту | перцентиль 90–95% | RTS, акции | [Boundaries of TSMOM](https://quantpedia.com/boundaries-of-time-series-momentum) | 🟡 |
| T04 | Donchian breakout «черепаха» | Вход при пробое 20-дневного max/min, выход при пробое 10-дневного; 1 юнит = 1% капитала / (2×ATR) | 20/10, ATR 20 | Si, CNY, RTS, BR | [Original Turtle Rules](https://www.tradingblox.com/originalturtles/originalturtlerules.htm) | 🟢 |
| T05 | ATR-канал с трейлинг-стопом (Chandelier) | Лонг при close > HH(N) + k×ATR, выход при close < highest_high − 3×ATR | N=20, k=0.5–1, trail 3 ATR | все фьючерсы | [Chandelier Exit](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/chandelier-exit) | 🟢 |
| T06 | EWMAC (две EMA + волатильность) | forecast = (EMA_fast − EMA_slow) / (0.01×цена×vol) ; нормализация делителем, сайз ∝ forecast, кап ±20 | 8/32, 16/64, vol 25 дн | Si, CNY, RTS | [pysystemtrade](https://github.com/pst-group/pysystemtrade/blob/develop/docs/introduction.md) | 🟢 |
| T07 | Breakout forecast (pysystemtrade) | forecast = (close − медианы close за N) / std(close за N), комбинируется с EWMAC | N=20–40 | те же | [QuantInsti TSMOM+CF](https://blog.quantinsti.com/trend-following-strategy-futures-time-series-momentum-continuous-forecasts-project-jirong-huang) | 🟢 |
| T08 | Двойное SMA (Golden/Dead cross) | Лонг при SMA50 > SMA200, шорт при обратном | 50/200 | Si, RTS, CNY | [QuantifiedStrategies](https://quantifiedstrategies.substack.com/p/100-free-trading-strategies) | 🟢 |
| T09 | Momentum с таргетом волатильности | Сигнал TSMOM, позиция = target_vol / realized_vol; потолок плеча | 10%/15% vol | все | [AQR Risk Parity](https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/Understanding-Risk-Parity.pdf) | 🟢 |
| T10 | Кросс-секционный моментум по акциям | Раз в мес: лонг топ-квинтиль по 12-1, шорт нижняя квинтиль | 12-1, мес | SBER/GAZP/LKOH/YDEX... | [Quantpedia TS vs XS](https://quantpedia.com/time-series-vs-cross-sectional-implementation-of-momentum-value-and-carry-strat) | 🟡 (нет истории акций) |
| T11 | Momentum с весом силы тренда (Baltas-Kosowski) | Вес ∝ t-статистика наклона регрессии цены + волатильность; ежемесячная пересборка | 12 мес | фьючерсы | [QuantConnect Library](https://www.quantconnect.com/docs/v2/writing-algorithms/strategy-library) | 🟡 |
| T12 | Time-series momentum + carry + value | Сумма трёх сигналов; carry = бэквардация/контанго, value = 5-летняя percentile цены | мес | фьючерсы | [Quantpedia TS vs XS](https://quantpedia.com/time-series-vs-cross-sectional-implementation-of-momentum-value-and-carry-strat) | 🔴 (нет кривой фьючерсов) |
| T13 | Тренд только в низковолатильном режиме | Включать TSMOM, если реализ. vol < медианы; иначе в кэш | vol 20 дн | все | [HMM regime](https://quantpedia.com/does-more-history-help-a-market-regime-hmm-and-the-trouble-with-out-of-sample-evaluation) | 🟢 |
| T14 | Trail по ATR после входа в тренд | Вход по TSMOM, выход по трейлингу 2–3 ATR от максимума сделки | 2–3 ATR | все | [Wilder volatility stop](https://oxfordstrat.com/trading-strategies/welles-wilder-1/) | 🟢 |

## 2. Mean reversion / статистический арбитраж

| ID | Название | Правила | Параметры | Инструменты | Источник | Статус |
|---|---|---|---|---|---|---|
| M01 | Pairs trading z-score | Найти коинтегрированную пару, spread = logA − β·logB, z = (spread−mean)/std; вход |z|>2, выход |z|<0.5, стоп |z|>4 | 60 дн, z 2/0.5/4 | Si/RTS, GOLD/BR, CNY/Si | [QuantConnect Pairs](https://www.quantconnect.com/research/15300/pairs-trading-with-stocks) | 🟢 (проверить коинтеграцию) |
| M02 | Equal-risk pairs | Без β: нормировать обе ноги на волатильность, торговать разность | vol 20 дн | те же | [Robot Wealth](https://robotwealth.com/a-short-take-on-real-world-pairs-trading) | 🟢 |
| M03 | OU / Kalman pairs | Динамический хедж-коэффициент, полураспад отклонения; вход при отклонении > 2σ | Kalman / OU | те же | [OU pairs GitHub](https://github.com/LucaCereghetti/Pairs-Trading-Mean-Reversion-Strategy) | 🟡 |
| M04 | Bollinger reversion | Лонг при close < mean−2σ, шорт при close > mean+2σ; выход на mean или RSI(2) | 20 дн, 2σ | Si, CNY, RTS | [PapersWithBacktest](https://paperswithbacktest.com/strategies/mean-reversion-trading-strategy) | 🟢 |
| M05 | RSI(2) экстремумы | Лонг RSI(2)<5, шорт RSI(2)>95; выход при RSI>50 / через 5 баров | 2/5, 5 баров | все | [QuantifiedStrategies](https://quantifiedstrategies.substack.com/p/100-free-trading-strategies) | 🟢 |
| M06 | Стохастик / Williams %R | Перепроданность < −80 / перекупленность > −20 + выход от средней | 14 | все | [Williams %R / Fidelity](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/williams-r) | 🟢 |
| M07 | Fade overnight gap | Если open − prev_close > 1%, шорт на open, закрытие на close; симметрично | 1% | [MyPivots gap fade](https://www.mypivots.com/article/details/43/fading-the-gap) | 🟡 |
| M08 | VWAP reversion | Лонг при цене на 2σ ниже VWAP в ликвидном инструменте, цель VWAP, выход к закрытию | 2σ, M5 | Si, RTS | [AInvest VWAP](https://www.ainvest.com/aime/share/backtest-proven-strategy-intraday-ad203b) | 🟡 (нужен VWAP из M5) |
| M09 | Краткосрочный реверс (1 мес, XS) | Покупать отставших, продавать лидеров прошлого месяца | 1 мес | акции | [Quantpedia reversal](https://quantpedia.com/strategies/short-term-reversal-with-futures) | 🟡 |
| M10 | Внутридневный реверс после открытия | Первые 30 мин decline → лонг на 10:30, выход к 15:30 | M5/M15 | Si, RTS | [Fung/Mok/Lam](https://scispace.com/pdf/intraday-price-reversals-for-index-futures-in-the-us-and-137ieyy6y7.pdf) | 🟡 |
| M11 | Реверс на стыке сессий | Пробой evening range и возврат → fade | M5 | Si, CNY | [локальный отчёт](reports/channel-break-research.md) | 🟡 |

## 3. Интрадей и время суток

| ID | Название | Правила | Параметры | Инструменты | Источник | Статус |
|---|---|---|---|---|---|---|
| I01 | Opening Range Breakout (ORB) | Диапазон high/low первых N мин; пробой вверх → лонг, вниз → шорт; стоп = противоположная граница, выход к закрытию | N=5/15/30/60, M5 | Si, RTS, CNY | [BuildAlpha / QuantConnect](https://www.buildalpha.com/opening-range-breakout) | 🟢 |
| I02 | Initial Balance (IB) | Первые 60 мин = IB; после пробоя IB торговать направление, при возврате — fade | 60 мин | Si, RTS | [Initial Balance](https://www.luxalgo.com/library/concept/initial-balance) | 🟢 |
| I03 | Пробой временного канала | Уже портирован (Коваль-Зайцев),研究 в `reports/channel-break-research.md` | 23:40/15:00 | CNY, Si, RTS | [OsEngine / отчёт](reports/channel-break-research.md) | ✅ есть (не в контур) |
| I04 | Volatility breakout (Newman) | Вход при пробое диапазонапредыдущего дня + k×ATR, выход по 50% диапазона или закрытию | k=0.5–1 | все | [Crabel / LuxAlgo](https://www.luxalgo.com/library/concept/volatility-breakout) | 🟢 |
| I05 | Первый час тренд,затем реверс | Если первый час направленный — продолжение; если хаотичный — fade к VWAP | M15 | Si, CNY | [Fung/Mok/Lam](https://scispace.com/pdf/intraday-price-reversals-for-index-futures-in-the-us-and-137ieyy6y7.pdf) | 🟡 |
| I06 | Last-hour momentum | Сигнал по доходности 15:00–18:00, держать до закрытия вечера | M15 | Si, RTS | [Bondarenko & Muravyev](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-finance/article/abs/market-return-around-the-clock-a-puzzle/089E33AC0B4D3B9A02CBA31EDF6505B3) | 🟡 |
| I07 | Day-of-weekэффект | Отдельно лонг/шорт по дням недели; пятничное правило уже есть в проекте | — | все | [календарные аномалии](https://www.slideshare.net/slideshow/analysis-of-stock-market-anomalies-worldwide/46671739) | 🟢 (уже частично) |
| I08 | Решения только в «активный» час | Вход не в 13:55, а в 13:40 / на открытии вечера — уже проверено (`entry-time-validation`) | 13:40 | [локальный отчёт](reports/entry-time-validation.md) | ✅ есть |

## 4. Carry, спреды, сезонность

| ID | Название | Правила | Параметры | Инструменты | Источник | Статус |
|---|---|---|---|---|---|---|
| C01 | Futures carry / roll yield | Лонг бэквардированных, шорт контанго; нужна кривую квартальных контрактов | мес | Si, RTS | [Quantpedia](https://quantpedia.com/time-series-vs-cross-sectional-implementation-of-momentum-value-and-carry-strat) | 🔴 (вечный CNY, нет кривой) |
| C02 | Calendar spread | Спред ближний−дальний контракт, z-score, вход 2σ | з 60 дн | Si, RTS | [Continuous futures](https://quantpedia.com/continuous-futures-contracts-methodology-for-backtesting) | 🔴 (нет кривой) |
| C03 | Синтетический фьючерс RTS vs корзина акций | Расхождение между RI и корзиной SBER/GAZP/LKOH → арбитраж | — | RI + акции | [MOEX](https://www.moex.com/a7206) | 🔴 (нет акций) |
| C04 | FX carry (RUB vs CNY/USD) | Процентный дифференциал как фильтр тренда | — | Si, CNY | [Koijen et al. Carry](https://www.nber.org/system/files/working_papers/w19325/w19325.pdf) | 🔴 (нет ставок) |
| C05 | Turn-of-month | Лонг в последний день месяца, выход на 3-й день нового месяца | −1…+3 дн | RTS, Si, CNY | [Gębka et al.](https://doi.org/10.1016/j.frl.2015.06.001) | 🟢 |
| C06 | Первый торговый день года / января | Сезонный лонг с 1 по 10 января | — | RTS | [QuantifiedStrategies](https://www.quantifiedstrategies.com/january-effect-in-stocks) | 🟡 |
| C07 | Предпраздничный эффект | Лонг за 2 дня до праздника, выход после | — | RTS, акции | [календарные аномалии](https://www.slideshare.net/slideshow/analysis-of-stock-market-anomalies-worldwide/46671739) | 🟡 |
| C08 | Дивидендный гэп SBER | Удержание/выход вокруг отсечки (май–июнь) | — | SBER | [календарные аномалии](https://www.slideshare.net/slideshow/analysis-of-stock-market-anomalies-worldwide/46671739) | 🔴 (нет акций) |
| C09 | Экспирационная неделя | Избегать/играть разворот на неделе экспирации квартальных | — | Si, RTS | [локальный ADR](docs/decisions.md) | 🟡 (у нас вечный CNY) |

## 5. Риск-оверлеи и комбинации

| ID | Название | Правила | Параметры | Инструменты | Источник | Статус |
|---|---|---|---|---|---|---|
| R01 | Volatility targeting | Позиция = target_vol / EWMA vol, кап 200% | 10–15% | все | [AQR Risk Parity](https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/Understanding-Risk-Parity.pdf) | 🟢 (почти есть ATR-резка) |
| R02 | Drawdown control | После просадки X% — половинный сайз, возврат после нового хая | 5/10% | портфель | [AQR tail risk](https://www.aqr.com/-/media/AQR/Documents/Insights/White-Papers/AQR-Chasing-Your-Own-Tail-Risk-Revisited.pdf?sc_lang=en) | 🟡 |
| R03 | Режимный HMM-фильтр | Скрытое состояние «тренд/флэт» по доходностям; в тренде — TSMOM, во флэте — реверс | 2–3 состояния | Si, CNY | [HMM regime](https://quantpedia.com/does-more-history-help-a-market-regime-hmm-and-the-trouble-with-out-of-sample-evaluation) | 🟡 |
| R04 | Ансамбль сигналов | Голосование TSMOM + Breakout + RSI(2) + Turn-of-month | 4 сигнала | все | [локальный отчёт](reports/strategy-research-summary.md) | 🟢 |
| R05 | Диверсификация по классам активов | Портфель из 4 классов с плечом ~2 — уже реализовано автором | 2× | портфель | [PROGRESS](PROGRESS.md) | ✅ есть |

## 6. ML / нестандартные (идеи на будущее)

| ID | Название | Суть | Источник | Почему пока нет |
|---|---|---|---|---|
| L01 | Random Forest / XGBoost на тех. индикаторах | Классификация знака завтрашней доходности по 20–50 признакам | [arxiv LSTM+RF](https://arxiv.org/abs/2512.02036) | Нужны метки + строгий OOS, легко переобучиться |
| L02 | LSTM / Transformer на OHLCV | Последовательная модель | [arxiv LSTM/DRL](https://arxiv.org/abs/2212.02721) | Мало данных, нестабильность |
| L03 | Genetic programming / alpha mining | Автоматический поиск формул | [Genetic programming](https://en.wikipedia.org/wiki/Genetic_programming) | Риск data-snooping |
| L04 | RL для сайзинга | Агент учится размеру позиции | [arxiv DRL ensemble](https://arxiv.org/abs/2511.12120v1) | Несовместимо с нашей детерминированной моделью исполнения |
| L05 | Сентимент / новости (TG-дампы автора) | Использовать `materials/` как фичи | [локальные материалы](materials/) | Субъективно, трудно свести в воспроизводимый сигнал |

## Итог отбора в прототип (первая партия)

Берём 8 штук, реализуемых на OHLC без стакана: **T01, T04, T06, T08, M04, M05, I01, C05**.
Критерий: есть явные правила, нет интрабарных стопов, есть смысл проверять train 2023–25 → OOS 2026.
Результаты прототипов — в `reports/strategy-prototypes.md`, код — `algo/strategies/candidates.py`
и `scripts/70_candidates.py`.

## 7. Добавлено глубокими поисковыми агентами (вторая волна, 21.11)

### 7.1 Тренд/моментум (агент 1)

| ID | Название | Правила | Параметры | Источник | Статус |
|---|---|---|---|---|---|
| T15 | TSMOM-1M | Месячная доходность > 0 → лонг на след. мес, < 0 → шорт | k=1 мес, сайз=40%/EWMA vol(60) | [Moskowitz et al. 2012](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf) | 🟢 |
| T16 | TSMOM-3M | То же, lookback 3 мес | k=3 мес | [Moskowitz et al. 2012](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf) | 🟢 |
| T17 | TSMOM-12M | То же, lookback 12 мес (= T01) | k=12 мес | [Moskowitz et al. 2012](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf) | ✅ дубль T01 |
| T18 | Five-Month EMA Trend | Месячный close выше 5-мес EMA → лонг, ниже → шорт; сайз ∝ sign×|ΔP|/σ5 | EMA 5 мес, σ=5-мес EMA | [Lempérière / QuantConnect](https://www.quantconnect.com/research/15257/commodities-futures-trend-following/) | 🟡 |
| T19 | SMA 10×30 | Кросс SMA10/SMA30, реверс на обратном | 10/30 дн | [Graham Capital / CME](https://www.cmegroup.com/content/dam/cmegroup/education/files/speed-of-trend-graham-research-march-2018.pdf) | 🟢 |
| T20 | SMA 20×60 | То же, 20/60 | 20/60 дн | [Graham Capital / CME](https://www.cmegroup.com/content/dam/cmegroup/education/files/speed-of-trend-graham-research-march-2018.pdf) | 🟢 |
| T21 | SMA 30×90 | То же, 30/90 | 30/90 дн | [Graham Capital / CME](https://www.cmegroup.com/content/dam/cmegroup/education/files/speed-of-trend-graham-research-march-2018.pdf) | 🟢 |
| T22 | SMA 40×120 | То же, 40/120 | 40/120 дн | [Graham Capital / CME](https://www.cmegroup.com/content/dam/cmegroup/education/files/speed-of-trend-graham-research-march-2018.pdf) | 🟢 |
| T23 | Turtle System 1 | Пробой HH20/LL20, выход LL10/HH10; 1 юнит = 1% капитала / ATR20, макс 4 юнита, стоп 2N | 20/10 | [Original Turtle Rules](https://www.tradingblox.com/originalturtles/originalturtlerules.htm) | 🟢 (= T04) |
| T24 | Turtle System 2 | Пробой HH55/LL55, выход LL20/HH20 | 55/20 | [Original Turtle Rules](https://www.tradingblox.com/originalturtles/originalturtlerules.htm) | 🟢 |
| T25 | Dynamic Breakout II | Адаптивный N∈[20,60] по vol; вход при close выше upper BB и пробое HH(N), выход по SMA(N) | BB 2σ, N 20–60 | [QuantConnect](https://www.quantconnect.com/research/15373/the-dynamic-breakout-ii-strategy/) | 🟡 |
| T26 | 12M Quintile Momentum | Кросс-секц.: лонг топ-25% по 12M ROC, шорт низ-25%, мес | 12 мес | [QuantConnect](https://www.quantconnect.com/research/15360/momentum-effect-in-commodities-futures/) | 🟡 (нужна кривая) |
| T27 | ROC(5) | Лонг при P(t)/P(t−5)−1 > 0, шорт при < 0 | n=5 дн | [Li/Zhang/Zhou](https://onlinelibrary.wiley.com/doi/full/10.1002/fut.21856) | 🟢 |
| T28 | VMA(5,10) | Лонг при переходе SMA5−SMA10 через 0 вверх, шорт вниз | 5/10 дн | [Li/Zhang/Zhou](https://onlinelibrary.wiley.com/doi/full/10.1002/fut.21856) | 🟢 |
| T29 | MACD(5,10) | То же для EMA5−EMA10 | 5/10 дн | [Li/Zhang/Zhou](https://onlinelibrary.wiley.com/doi/full/10.1002/fut.21856) | 🟢 |

### 7.2 Mean-reversion / арбитраж (агент 2)

| ID | Название | Правила | Параметры | Источник | Статус |
|---|---|---|---|---|---|
| M12 | Gatev distance pairs | Мес: нормализовать цены пары к 1, выбрать пару по мин. RSS за 252 дн; вход при |Δ|>2σ, выход на 0, край 126 дн | 252/126 дн, ±2σ | [Gatev et al.](https://doi.org/10.3386/w7032) | 🟡 (нет акций) |
| M13 | Cointegration z-score pairs | Engle–Granger, spread=P1−α−βP2, z за 30 дн; вход ±2, выход 0.5 | 252/30 дн | [Krape](https://maddoxk.github.io/quant-statarb-research/paper.pdf) | 🟡 |
| M14 | Cointegration + stop/time | Вход z<−2 / >+2, выход >−0.5 / <+0.75, стоп 7%, макс 50 дн | 50 дн, 7% | [Perlin et al.](https://periodicos.fgv.br/rbfin/article/download/4785/7889/19805) | 🟡 |
| M15 | Half-life Johansen | Johansen p≤0.10 + полураспад OU <30 дн; вход ±2σ, выход mean/3h/63 дн | 252/63 дн | [Deutsche Bank](https://pairtradefinder.com/downloads/DBPairTradeStudy.pdf) | 🟡 |
| M16 | PCA residual stat arb | Регресс доходности на 3 ПК, OU по остатку, вход ±2, выход 0.5, бета-нейтраль | 60 дн, K=3 | [Avellaneda & Lee](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1153505) | 🟡 |
| M17 | Kalman dynamic-hedge pairs | logP1=αt+βt·logP2, β обновляется Kalman; z ±2/0.5, макс 50 дн | 60 дн | [de Moura et al.](https://doi.org/10.1080/14697688.2016.1164886) | 🟡 |
| M18 | Bollinger volatility-breakout | Сквиз: BandWidth < 20-й перцентиль 126 дн; пробой upper/lower → вход, выход у противоп. полосы | 20, 2σ, 126/20% | [Bollinger](https://www.bollingerbands.com/bollinger-band-book) | 🟢 |
| M19 | Bollinger–MFI | %b>0.8 + MFI10>80 → лонг; %b<0.2 + MFI10<20 → шорт; выход %b 0.5 | 20/10 | [Bollinger Method II](https://www.bollingerbands.com/bollinger-band-book) | 🟡 (MFI нужен vol) |
| M20 | MA(1,200,0) | Close > SMA200 → лонг, иначе шорт/кэш | 1/200 дн | [Brock et al.](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1992.tb04681.x) | 🟢 |
| M21 | Turn-of-month MOEX | (= C05) лонг последний день мес + 3 дня | 4 дня | [Gębka et al.](https://doi.org/10.1016/j.frl.2015.06.001) | ✅ дубль C05 |
| M22 | Halloween seasonality | Лонг 31.10→30.04, кэш май–октябрь | 1 вход/год | [Bouman & Jacobsen](https://doi.org/10.1016/S0304-4076(01)00128-3) | 🟢 |
| M23 | 12–3 cross-sectional momentum | Ранг за 12 мес, skip 5 дн, лонг топ / шорт низ, держим 3 мес | 12-3, 3 мес | [Jegadeesh & Titman](https://www.bauer.uh.edu/rsusmel/phd/jegadeesh-titman93.pdf) | 🟡 |
| M24 | 1-month reversal | Покупать прошломесячных аутсайдеров, шорт лидеров | 1 мес | [Jegadeesh](https://www.anderson.ucla.edu/documents/areas/fac/finance/26-90.pdf) | 🟡 |
| M25 | Weekly contrarian | Ранг за 1 неделю, лонг низ / шорт топ, держим 3 нед | 1/3 нед | [Lehmann](https://finance.martinsewell.com/stylized-facts/dependence/Lehmann1990.pdf) | 🟡 |
| M26 | 12M TSMOM | (= T01) | 12 мес | [Moskowitz et al. 2012](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf) | ✅ дубль T01 |

**Итого каталог: ~65 уникальных идей** (с учётом дублей ~60), из них 🟢 24, 🟡 35, 🔴 6.

### 7.3 Русскоязычные источники (агент 3)

| ID | Название | Правила | Параметры | Источник | Статус |
|---|---|---|---|---|---|
| R01 | SMA(4/8) long-only | Кросс SMA4/SMA8 вверх → лонг, вниз → выход; без шорта и стопа | 4/8 баров | [Riskplayer](https://smart-lab.ru/blog/1127039.php) | 🟢 |
| R02 | Резвяков: восходящий range long | В 10:00, если HH и LL каждого из последних 2 дн выше предыдущих → лонг; выход 20:40 или −2% от макс. close | M5, 10:00/20:40, trail 2% | [А. Резвяков](https://smart-lab.ru/blog/1111228.php) | 🟢 |
| R03 | Резвяков: нисходящий range short | Зеркально: HH/LL последних 2 дн ниже предыдущих → шорт; выход 20:40 или +2% от мин. close | там же | [А. Резвяков](https://smart-lab.ru/blog/1111228.php) | 🟢 |
| R04 | Countertrend EMA–ATR long | Volume>1000, свечаDown, Close<EMA50, ATR14>1.1×сред. ATR21 → лонг; трейлинг по мин. 5 баров | EMA50, ATR14/21×1.1 | [OsEngine CountertrendEmaATR](https://github.com/AlexWan/OsEngine/blob/master/project/OsEngine/bin/Debug/Custom/Robots/CountertrendEmaATR.cs) | 🟡 (интрабарный трейлинг) |
| R05 | Countertrend EMA–ATR short | Зеркально: свечаUp, Close>EMA50 → шорт; трейлинг по макс. 5 баров | там же | [OsEngine CountertrendEmaATR](https://github.com/AlexWan/OsEngine/blob/master/project/OsEngine/bin/Debug/Custom/Robots/CountertrendEmaATR.cs) | 🟡 |
| R06 | EMA–ADX trend long | Close > EMA100 + условие ADX10 → лонг, роллинг-стоп | EMA100, ADX10 | [OsEngine StrategyEmaADX](https://github.com/AlexWan/OsEngine/blob/master/project/OsEngine/bin/Debug/Custom/Robots/StrategyEmaADX.cs) | 🟡 |
| R07 | EMA–ADX trend short | Зеркально | там же | [OsEngine StrategyEmaADX](https://github.com/AlexWan/OsEngine/blob/master/project/OsEngine/bin/Debug/Custom/Robots/StrategyEmaADX.cs) | 🟡 |
| R08 | Линейная регрессия long (S&C 2007) | Close > линия регрессии HLCC4(20), adj R² растёт и >0.2 → лонг; стоп −3.9% | 20 баров, R²>0.2, стоп 3.9% | [Smart-Lab](https://smart-lab.ru/blog/1153389.php) | 🟢 |
| R09 | Линейная регрессия short | Зеркально, стоп +3.9% | там же | [Smart-Lab](https://smart-lab.ru/blog/1153389.php) | 🟢 |
| R10 | RSI trend/counter reversal | RSI14 >70 → лонг (тренд) / шорт (контр), <30 → наоборот; всегда в рынке | RSI14, 70/30 | [Smart-Lab](https://smart-lab.ru/blog/336742.php) | 🟢 |

### 7.4 Интрадей и академия (агент 4)

| ID | Название | Правила | Параметры | Источник | Статус |
|---|---|---|---|---|---|
| I09 | Holmberg ORB | Порог rho=mean(log(C/O))+z·σ; пробой вверх/вниз от open → первая сделка, выход на закрытии | калибровка ρ | [Holmberg et al.](http://www.econ.umu.se/ueslpnr/ues845.pdf) | 🟡 |
| I10 | Crabel stretch ORB | buy-stop = HH(open range)+stretch, sell-stop = LL−stretch; первое исполнение, выход к закрытию | stretch | [Crabel](https://store.traders.com/-v07-c02-orb-pdf.html) | 🟢 (=I01) |
| I11 | Gap fade (сырой) | Gap>0 → шорт на open, gap<0 → лонг; выход на prev close или close | без стопа | [MyPivots](https://www.mypivots.com/article/details/43/fading-the-gap) | 🟢 |
| I12 | Gap fade + 25% стоп | То же, стоп = 25% от вел. гэпа | 25% | [MyPivots](https://www.mypivots.com/article/details/43/fading-the-gap) | 🟢 |
| I13 | FML first-hour reversal 20bp | OR=log(O/Cprev) ≥ +0.20% → шорт через 1 мин, ≤ −0.20% → лонг; выход через 1 час | 20bp, 1 мин/1 ч | [Fung/Mok/Lam](https://scispace.com/pdf/intraday-price-reversals-for-index-futures-in-the-us-and-137ieyy6y7.pdf) | 🟡 |
| I14 | FML 30bp | То же, порог 0.30% | 30bp | [Fung/Mok/Lam](https://scispace.com/pdf/intraday-price-reversals-for-index-futures-in-the-us-and-137ieyy6y7.pdf) | 🟡 |
| I15 | VWAP 2σ reversion | M5 VWAP (typical price), вход при close < VWAP−2σ / > +2σ, цель VWAP, стоп 1σ, выход 15:55 | 2σ/1σ, M5 | [QuantReplay](https://quantreplay.ai/research/vwap-reversion) | 🟡 |
| I16 | European-open long | Лонг на 4-часовое окно вокруг открытия Европы, остальное время кэш | 4 ч/день | [Bondarenko & Muravyev](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-finance/article/abs/market-return-around-the-clock-a-puzzle/089E33AC0B4D3B9A02CBA31EDF6505B3) | 🟡 |
| C10 | Commodity carry XS | Ранг по carry из кривой, лонг высокий / шорт низкий | мес | [Koijen et al.](https://www.nber.org/system/files/working_papers/w19325/w19325.pdf) | 🔴 (нет кривой) |
| C11 | Time-series carry | Знак carry (contango/backwardation) → направление | мес | [Koijen et al.](https://www.nber.org/system/files/working_papers/w19325/w19325.pdf) | 🔴 |
| T30 | Wilder ATR breakout reversal | ATR20, SIC = лучший close с входа, реверс при close < SIC−ARC / > SIC+ARC, стоп 6ATR | ATR20, 6ATR | [Wilder / Oxford Strategy](https://oxfordstrat.com/trading-strategies/welles-wilder-1/) | 🟢 (реверс по close) |

**Финальный счёт каталога: ~90 находок, ~78 уникальных; 🟢 ~30, 🟡 ~40, 🔴 ~8.**
Первая партия прототипов (9 штук) выбрана из 🟢 и уже считается в `scripts/70_candidates.py`.
