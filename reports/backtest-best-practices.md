# Лучшие практики тестирования алго-роботов vs наш процесс

Дата: 23.11.2026. Поиск: 4 веб-запроса + обзорные статьи/публикации.
Цель — не «ещё одна методичка», а список конкретных дыр в нашем тестировании.

## 1. Что рекомендуют (с источниками)

| Практика | Суть | Источник |
|---|---|---|
| Без look-ahead | индикаторы и сигналы используют только данные до t; явный `shift(1)`, проверка выравнивания по времени | [Lookahead-safe backtesting](https://github.com/quantskills/skill-backtesting-bias-avoidance/blob/main/SKILL.md), [TheQuantHackers](https://thequanthackers.com/blog/lookahead-bias-free-backtesting-python) |
| Реалистичные издержки | комиссия + спред + проскальзывание + рыночное воздействие; чувствительность к ним обязательна | [Slippage & commission](https://backtrex.com/en/blog/slippage-commission-backtesting-realistic-results), [Backtest vs Paper](https://referentiallabs.com/blog/backtesting-vs-paper-trading) |
| Поправка на множественные тесты | чем больше перебрано вариантов, тем выше ожидаемый максимум Sharpe просто от шума; Deflated Sharpe Ratio, PSR, MinTRL, PBO/CSCV | [Bailey & López de Prado, DSR](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf), [AQR, Multiple Testing](https://www.aqr.com/-/media/AQR/Documents/Journal-Articles/JFDS_Winter2019_A-Data-Science-Solution-to-Multiple-Testing-Crisis---Lopez_de_Prado.pdf?sc_lang=en), [Portfolio Optimization Book 8.3](https://portfoliooptimizationbook.com/book/8.3-dangers-backtesting.html) |
| Walk-forward (gold standard) | оптимизация на train → замороженные параметры на OOS → сдвиг окна; несколько независимых OOS-периодов; стабильность параметров важнее лучшего PF | [Pardo/Wikipedia](https://en.wikipedia.org/wiki/Walk_forward_optimization), [QuantInsti](https://blog.quantinsti.com/walk-forward-optimization-introduction), [BuildAlpha](https://www.buildalpha.com/walk-forward-optimization) |
| Плато параметров, а не пик | соседние параметры не должны разрушать результат; скачки optimum = подгонка | [BuildAlpha WFO](https://www.buildalpha.com/walk-forward-optimization), [Backtrex WFA](https://backtrex.com/en/blog/walk-forward-analysis-guide-backtesting) |
| Monte Carlo / шум / случайное сравнение | перестановки, бутстреп, «vs random» — проверка, что край не artifact одной траектории | [BuildAlpha robustness guide](https://www.buildalpha.com/walk-forward-optimization), [quantskills skill](https://github.com/quantskills/skill-backtesting-bias-avoidance/blob/main/SKILL.md) |
| Статистическая значимость | HAC t-stat, 95% CI, эффективный объём выборки, число сделок; минимальная длина истории (MinTRL) | [quantskills skill](https://github.com/quantskills/skill-backtesting-bias-avoidance/blob/main/SKILL.md), [Berkeley paper](https://escholarship.org/content/qt4w1110bb/qt4w1110bb.pdf) |
| Выживаемость и состав вселенной | включать исчезнувшие инструменты; фиксировать вселенную на каждом моменте t | [Survivorship bias](https://fastercapital.com/content/Backtesting--The-Perils-of-Survivorship-Bias-Risk-in-Strategy-Testing.html), [quantskills skill](https://github.com/quantskills/skill-backtesting-bias-avoidance/blob/main/SKILL.md) |
| Стресс-тесты и сценарии | проверка на широком наборе сценариев, а не на одной истории | [Portfolio Optimization Book 8.3](https://portfoliooptimizationbook.com/book/8.3-dangers-backtesting.html) |
| Поэтапная валидация | backtest → OOS → walk-forward → forward/paper → live; paper — проверка исполнения, а не доказательство доходности | [Confidence ladder](https://algorier.com/blog/trading-strategy-validation), [TradersPost workflow](https://blog.traderspost.io/article/backtest-forward-test-paper-trade-live-workflow), [Audacity](https://audacity.capital/trading-guides/backtesting-vs-forward-testing) |
| Paper vs backtest: tracking error | сравнивать факт с ожиданием; расхождение диагностирует данные/исполнение; paper короткий — только один режим | [Referential Labs](https://referentiallabs.com/blog/backtesting-vs-paper-trading), [markrbest paper-vs-live](https://markrbest.github.io/paper-vs-live) |

## 2. Что у нас уже хорошо

- **Причинность исполнения**: сигнал по close, сделка по open следующего бара; 0.01% + 1 тик; skip_weekend — зафиксировано в ADR 18.11.
- **Самонайденный look-ahead**: в новой партии прототипов дневной close включал вечернюю сессию, сигнал публиковался в 13:55 того же дня; нашли, добавили `shift(1)`, пересчитали все отчёты и удалили ошибочные строки из журнала.
- **Издержки и чувствительность**: 5 тиков = −28% прибыли; сравнение на 0.01% + 1 тик по всем системам.
- **Много инструментов**: 12 ликвидных фьючерсов, 2009–2025 (`reports/prostushka_multi_full.csv`), плюс 10-летняя капитальная симуляция по 1M на инструмент.
- **Плато вместо пика**: MA48 предпочтительнее MA40, сетки MA48–55; отдельный контроль подгонки `p-train` (лучший train проиграл базе на OOS).
- **Walk-forward сделан**: 9 проверок, лучший по train обыграл базу 4/9, вывод «доминирует подгонка» (`reports/regime-vs-overfit.md`).
- **Один журнал и окно** для сравнения роботов; fact vs expected и tracking error ежедневно; ворота G1–G4, 57 тестов, сторож, STOP.
- **Конфиги фиксируются**, новые идеи — только новым id; решения пишутся в ADR до включения.

## 3. Где не хватает (по важности)

1. **Поправка на множественные тесты — нет совсем.** Мы перебрали ~90 идей и десятки точек сеток, а выбираем по PF на OOS без DSR/PBO/учёта числа попыток. Это главная дыра: при таком числе trials высокий PF легко получить случайно. Наши же данные это подтверждают: победы на OOS 2026 не обобщились на 10 лет и 10 инструментов.
2. **Малые выборки OOS.** У медленных кандидатов 5–10 сделок за OOS — нет t-статистики, CI, минимальной длины истории. PF 2.04 на 5 сделках — не доказательство.
3. **Настоящий rolling walk-forward для новых кандидатов — нет.** Один срез 2023–25 → 2026; OOS к тому же многократно пересматривался в研究中 и перестал быть «чистым».
4. **Monte Carlo / шум / случайный бенчмарк — нет.** Есть только детерминированные сетки и два контроля (`p-train`, «просто лонг» у cb-day). Не проверяли, не даёт ли тот же результат перестановка доходностей.
5. **Стресс-сценарии — нет.** Есть режимная диагностика (волатильность, эффективность тренда по годам), но нет проверки на шоковых сценариях и разрывах ликвидности.
6. **Выживаемость/выбор вселенной.** Фьючерсы Continuous снижают проблему, но ISS-серии 2026 квартальных контрактов без back-adjustment мы использовали только как оценочные; набор из 12 «ликвидных» инструментов выбран вручную — selection bias не quantified.
7. **Модель исполнения упрощена.** Фиксированные 1 тик и 0.01%, без спреда/воздействия/частичных исполнений; G3-репетиция ещё не подключена к роботу.

## 4. Что делать (приоритет)

1. Ввести **журнал попыток** (ID, число перебранных вариантов, дата) и считать **Deflated Sharpe /expected maximum Sharpe** перед объявлением кандидата «рабочим». Минимум — явно указывать число trials и требовать OOS-результат выше порога, скорректированного на N.
2. Требовать **≥30 сделок OOS** или несколько независимых OOS-окон; для PF считать HAC t-stat и 95% CI. Медленные стратегии с 5 сделками не продвигать.
3. Сделать **rolling walk-forward** для каждого нового id: 3–5 окон, заморозка параметров, проверка стабильности optimum; в отчёте — только OOS-сегменты.
4. Добавить **Monte Carlo/перестановки** и сравнение со случайным сигналом на том же числе сделок.
5. Держать **чистый holdout** (последние 6–12 мес, не используемый в research) + уже идущий paper-тест как финальный forward-этап; не пересматривать OOS при каждой итерации.
6. Задокументировать **selection bias** набора инструментов и ограничения ISS-данных; добавить стресс-сценарии (шок 2022, флэт 2026, гэпы).
7. После G3 — сравнить реальные fills со смоделированными 1 тиком и пересчитать чувствительность.

## Выжимка для чата

Сильные стороны: честная модель исполнения, найденный и исправленный look-ahead, 12 инструментов, плато параметров, отдельный контроль подгонки, walk-forward, daily fact/expected и ворота G1–G4.
Главное отставание: **мы не делаем поправку на множественные тесты и не считаем статистическую значимость** при 5–10 сделках OOS — поэтому «победы» на коротком OOS и не выдержали проверку на 10 годах. Второе — нет Monte Carlo и настоящего rolling walk-forward по всем кандидатам.
