-- Целевая схема PostgreSQL + TimescaleDB для нового контура панели.
-- НЕ применяется к текущей SQLite-панели: миграция — отдельное решение.
-- Денежные и лотовые поля — строго NUMERIC; финансовый журнал append-only.
-- Секреты здесь не хранятся: только имена ссылок на ключи из auth.json.

-- TimescaleDB опционален: без расширения таблицы остаются обычными (PostgreSQL).
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb') THEN
    CREATE EXTENSION IF NOT EXISTS timescaledb;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS brokers (
    id            TEXT PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,          -- finam | tinvest | virtual | other
    display_name  TEXT NOT NULL,
    capabilities  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS accounts (
    id             TEXT PRIMARY KEY,
    broker_code    TEXT NOT NULL REFERENCES brokers(code),
    name           TEXT NOT NULL,
    mode           TEXT NOT NULL CHECK (mode IN ('TEST', 'LIVE')),
    currency       TEXT NOT NULL DEFAULT 'RUB',
    balance        NUMERIC(20, 4) NOT NULL DEFAULT 0,
    equity         NUMERIC(20, 4) NOT NULL DEFAULT 0,
    free_cash      NUMERIC(20, 4) NOT NULL DEFAULT 0,
    credentials_ref TEXT DEFAULT '',             -- имя ключа, не сам секрет
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_accounts_broker_mode ON accounts(broker_code, mode);

CREATE TABLE IF NOT EXISTS instrument_mappings (
    id            BIGSERIAL PRIMARY KEY,
    ticker        TEXT NOT NULL,
    broker_code   TEXT NOT NULL REFERENCES brokers(code),
    external_id   TEXT NOT NULL,                 -- FIGI / UID / board-код
    board         TEXT DEFAULT '',
    UNIQUE (ticker, broker_code)
);

CREATE TABLE IF NOT EXISTS algorithms (
    id                 TEXT PRIMARY KEY,
    code               TEXT NOT NULL UNIQUE,
    name               TEXT NOT NULL,
    description        TEXT NOT NULL DEFAULT '',
    default_params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    param_schema_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
    version            INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS robots (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL UNIQUE,
    algorithm_id         TEXT NOT NULL REFERENCES algorithms(id),
    account_id           TEXT NOT NULL REFERENCES accounts(id),
    symbol               TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN
                             ('RUNNING', 'PAUSED', 'STOPPED', 'ERROR', 'REDUCE_ONLY')),
    params_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
    lot_config_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
    risk_limits_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    current_position_lots NUMERIC(20, 8) NOT NULL DEFAULT 0,
    avg_entry_price      NUMERIC(20, 8) NOT NULL DEFAULT 0,
    calculated_next_lots NUMERIC(20, 8) NOT NULL DEFAULT 0,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_robots_account ON robots(account_id);

CREATE TABLE IF NOT EXISTS robot_account_switches (
    id              BIGSERIAL PRIMARY KEY,
    robot_id        TEXT NOT NULL REFERENCES robots(id),
    from_account_id TEXT REFERENCES accounts(id),
    to_account_id   TEXT NOT NULL REFERENCES accounts(id),
    position_action TEXT NOT NULL DEFAULT '',
    switched_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders (
    id              BIGSERIAL PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES accounts(id),
    robot_id        TEXT REFERENCES robots(id),
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    qty             NUMERIC(20, 8) NOT NULL,
    price           NUMERIC(20, 8) NOT NULL DEFAULT 0,
    status          TEXT NOT NULL,
    client_key      TEXT NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trades (
    id              BIGSERIAL PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES accounts(id),
    robot_id        TEXT REFERENCES robots(id),
    order_id        BIGINT REFERENCES orders(id),
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    lots            NUMERIC(20, 8) NOT NULL,
    price           NUMERIC(20, 8) NOT NULL,
    commission      NUMERIC(20, 4) NOT NULL DEFAULT 0,
    realized_pnl    NUMERIC(20, 4) NOT NULL DEFAULT 0,
    executed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_trades_account_time ON trades(account_id, executed_at DESC);

CREATE TABLE IF NOT EXISTS cash_flows (
    id              BIGSERIAL PRIMARY KEY,
    account_id      TEXT NOT NULL REFERENCES accounts(id),
    type            TEXT NOT NULL CHECK (type IN
                        ('DEPOSIT', 'WITHDRAWAL', 'DIVIDEND', 'VIRTUAL_RESET')),
    amount          NUMERIC(20, 4) NOT NULL,
    balance_before  NUMERIC(20, 4) NOT NULL,
    balance_after   NUMERIC(20, 4) NOT NULL,
    broker_tx_id    TEXT UNIQUE,
    client_key      TEXT UNIQUE,
    source          TEXT NOT NULL DEFAULT 'BROKER',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    note            TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_cash_flows_account_time ON cash_flows(account_id, created_at DESC);

CREATE TABLE IF NOT EXISTS cash_flow_lot_impacts (
    id            BIGSERIAL PRIMARY KEY,
    cash_flow_id  BIGINT NOT NULL REFERENCES cash_flows(id),
    robot_id      TEXT NOT NULL REFERENCES robots(id),
    lots_before   NUMERIC(20, 8) NOT NULL,
    lots_after    NUMERIC(20, 8) NOT NULL,
    status        TEXT NOT NULL,
    note          TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_lot_impacts_flow ON cash_flow_lot_impacts(cash_flow_id);

CREATE TABLE IF NOT EXISTS audit_and_system_logs (
    id            BIGSERIAL PRIMARY KEY,
    level         TEXT NOT NULL CHECK (level IN ('INFO', 'WARN', 'ERROR')),
    category      TEXT NOT NULL,
    account_id    TEXT REFERENCES accounts(id),
    robot_id      TEXT REFERENCES robots(id),
    message       TEXT NOT NULL,
    details_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_and_system_logs(created_at DESC);

-- Гипертаблицы TimescaleDB: свечи и снимки equity.
CREATE TABLE IF NOT EXISTS market_candles (
    symbol        TEXT NOT NULL,
    timeframe     TEXT NOT NULL,
    time          TIMESTAMPTZ NOT NULL,
    open          NUMERIC(20, 8) NOT NULL,
    high          NUMERIC(20, 8) NOT NULL,
    low           NUMERIC(20, 8) NOT NULL,
    close         NUMERIC(20, 8) NOT NULL,
    volume        NUMERIC(20, 4) NOT NULL DEFAULT 0,
    UNIQUE (symbol, timeframe, time)
);
CREATE TABLE IF NOT EXISTS equity_snapshots (
    account_id      TEXT NOT NULL REFERENCES accounts(id),
    robot_id        TEXT REFERENCES robots(id),
    time            TIMESTAMPTZ NOT NULL,
    balance         NUMERIC(20, 4) NOT NULL DEFAULT 0,
    equity          NUMERIC(20, 4) NOT NULL DEFAULT 0,
    net_trading_pnl NUMERIC(20, 4) NOT NULL DEFAULT 0,
    drawdown_pct    NUMERIC(10, 4) NOT NULL DEFAULT 0,
    UNIQUE (account_id, time)
);
CREATE INDEX IF NOT EXISTS idx_equity_account_time ON equity_snapshots(account_id, time DESC);

-- Гипертаблицы создаются только при установленном расширении.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
    PERFORM create_hypertable('market_candles', 'time', if_not_exists => TRUE);
    PERFORM create_hypertable('equity_snapshots', 'time', if_not_exists => TRUE);
  END IF;
END $$;
