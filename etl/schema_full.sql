-- 完整初始化 schema：包含 raw、meta、backup 及 wantgoo 月營收表
-- 可用於全新資料庫的第一次初始化。

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS meta;
CREATE SCHEMA IF NOT EXISTS backup;

CREATE TABLE IF NOT EXISTS raw.fx_crawler (
    currency VARCHAR(16) NOT NULL,
    date DATE NOT NULL,
    close DOUBLE PRECISION,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    change_pct DOUBLE PRECISION,
    PRIMARY KEY (currency, date)
);

CREATE TABLE IF NOT EXISTS raw.tej_stock_price (
    security_code VARCHAR(64) NOT NULL,
    date DATE NOT NULL,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    close DOUBLE PRECISION,
    volume_k_shares DOUBLE PRECISION,
    turnover_k_twd DOUBLE PRECISION,
    return_pct DOUBLE PRECISION,
    return_ln DOUBLE PRECISION,
    turnover_rate_pct DOUBLE PRECISION,
    shares_outstanding_k DOUBLE PRECISION,
    market_cap_m DOUBLE PRECISION,
    market_cap_weight_pct DOUBLE PRECISION,
    turnover_value_weight_pct DOUBLE PRECISION,
    trade_count DOUBLE PRECISION,
    pe_tse DOUBLE PRECISION,
    pb_tse DOUBLE PRECISION,
    ps_tej DOUBLE PRECISION,
    div_yield_tse DOUBLE PRECISION,
    cash_div_rate DOUBLE PRECISION,
    price_change DOUBLE PRECISION,
    hl_spread_pct DOUBLE PRECISION,
    alert_a VARCHAR(32),
    disposition_d VARCHAR(32),
    full_delivery_y VARCHAR(32),
    excess_return_daily DOUBLE PRECISION,
    capm_beta_1y DOUBLE PRECISION,
    price_limit VARCHAR(64),
    PRIMARY KEY (security_code, date)
);

CREATE TABLE IF NOT EXISTS raw.tej_chip (
    security_code VARCHAR(64) NOT NULL,
    date DATE NOT NULL,
    fi_net_buy_lot DOUBLE PRECISION,
    it_net_buy_lot DOUBLE PRECISION,
    dt_net_buy_lot DOUBLE PRECISION,
    total_net_buy_lot DOUBLE PRECISION,
    fi_net_days DOUBLE PRECISION,
    it_net_days DOUBLE PRECISION,
    dt_net_days DOUBLE PRECISION,
    inst_net_days DOUBLE PRECISION,
    fi_holding_pct DOUBLE PRECISION,
    it_holding_pct DOUBLE PRECISION,
    total_holding_pct DOUBLE PRECISION,
    margin_balance_lot DOUBLE PRECISION,
    margin_buy_lot DOUBLE PRECISION,
    margin_sell_lot DOUBLE PRECISION,
    margin_usage_pct DOUBLE PRECISION,
    margin_maint_ratio DOUBLE PRECISION,
    short_balance_lot DOUBLE PRECISION,
    short_sell_lot DOUBLE PRECISION,
    short_usage_pct DOUBLE PRECISION,
    short_margin_ratio DOUBLE PRECISION,
    sec_lending_balance_lot DOUBLE PRECISION,
    sec_lending_sell_lot DOUBLE PRECISION,
    short_buy_lot DOUBLE PRECISION,
    short_maint_ratio DOUBLE PRECISION,
    overall_maint_ratio DOUBLE PRECISION,
    margin_limit_lot DOUBLE PRECISION,
    short_limit_lot DOUBLE PRECISION,
    short_vol_ratio_pct DOUBLE PRECISION,
    margin_vol_ratio_pct DOUBLE PRECISION,
    extras JSONB,
    PRIMARY KEY (security_code, date)
);

CREATE TABLE IF NOT EXISTS raw.tej_market_stats (
    security_code VARCHAR(64) NOT NULL,
    date DATE NOT NULL,
    trade_amount DOUBLE PRECISION,
    trade_volume DOUBLE PRECISION,
    trade_count DOUBLE PRECISION,
    total_bid_volume DOUBLE PRECISION,
    total_bid_count DOUBLE PRECISION,
    total_ask_volume DOUBLE PRECISION,
    total_ask_count DOUBLE PRECISION,
    limit_up_bid_volume DOUBLE PRECISION,
    limit_up_bid_count DOUBLE PRECISION,
    limit_up_ask_volume DOUBLE PRECISION,
    limit_up_ask_count DOUBLE PRECISION,
    limit_down_bid_volume DOUBLE PRECISION,
    limit_down_bid_count DOUBLE PRECISION,
    limit_down_ask_volume DOUBLE PRECISION,
    limit_down_ask_count DOUBLE PRECISION,
    advance_count DOUBLE PRECISION,
    decline_count DOUBLE PRECISION,
    unchanged_count DOUBLE PRECISION,
    no_trade_count DOUBLE PRECISION,
    limit_up_count DOUBLE PRECISION,
    limit_down_count DOUBLE PRECISION,
    PRIMARY KEY (security_code, date)
);

CREATE TABLE IF NOT EXISTS raw.tej_intl_index (
    security_code VARCHAR(128) NOT NULL,
    date DATE NOT NULL,
    index_value DOUBLE PRECISION,
    PRIMARY KEY (security_code, date)
);

CREATE TABLE IF NOT EXISTS raw.tej_director_monthly (
    security_code VARCHAR(64) NOT NULL,
    month DATE NOT NULL,
    total_shares DOUBLE PRECISION,
    director_holding_pct DOUBLE PRECISION,
    major_shareholder_pct DOUBLE PRECISION,
    PRIMARY KEY (security_code, month)
);

CREATE TABLE IF NOT EXISTS raw.tej_quarterly (
    security_code VARCHAR(64) NOT NULL,
    season DATE NOT NULL,
    data JSONB,
    PRIMARY KEY (security_code, season)
);

CREATE TABLE IF NOT EXISTS raw.wantgoo_monthly_revenue (
    security_code VARCHAR(16) NOT NULL,
    security_name VARCHAR(256),
    "month" DATE NOT NULL,
    revenue_ntd_thousand BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (security_code, "month")
);

CREATE INDEX IF NOT EXISTS idx_wantgoo_monthly_revenue_month
    ON raw.wantgoo_monthly_revenue ("month");

CREATE TABLE IF NOT EXISTS meta.security_master (
    security_code VARCHAR(128) NOT NULL PRIMARY KEY,
    ticker VARCHAR(64),
    name VARCHAR(256),
    market VARCHAR(32)
);
