-- 玩股網爬蟲資料表（可由 load_wantgoo_monthly_revenue.py 自動建立，此檔供手動參考／版本控管）
-- 月頻時間欄位名稱為 month（查詢時建議加雙引號 "month"），型別 DATE，存該月第一日（yyyy-mm-dd）

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.wantgoo_monthly_revenue (
    security_code          VARCHAR(16)  NOT NULL,
    security_name          VARCHAR(256),
    "month"                DATE         NOT NULL,
    revenue_ntd_thousand   BIGINT       NOT NULL,
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (security_code, "month")
);

CREATE INDEX IF NOT EXISTS idx_wantgoo_monthly_revenue_month
    ON raw.wantgoo_monthly_revenue ("month");
