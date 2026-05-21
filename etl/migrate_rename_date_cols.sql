-- ============================================================
-- migrate_rename_date_cols.sql
-- 日期欄位統一命名遷移腳本
--
-- 規則：
--   日資料  trade_date  → date
--   月資料  year_month  → month
--   季資料  year_month  → season
--
-- 執行方式（在 DBeaver 或 psql 內執行）：
--   psql $DATABASE_URL -f etl/migrate_rename_date_cols.sql
--
-- 注意：
--   - 執行前請先備份資料庫，或確認資料已可重新 ETL 還原
--   - 若欄位已是目標名稱（例如首次建表就用新名稱），PostgreSQL
--     會回傳 "column does not exist" 的錯誤，忽略即可
-- ============================================================

-- ── 日資料：trade_date → date ──────────────────────────────

ALTER TABLE raw.tej_stock_price
    RENAME COLUMN trade_date TO date;

ALTER TABLE raw.tej_chip
    RENAME COLUMN trade_date TO date;

ALTER TABLE raw.tej_market_stats
    RENAME COLUMN trade_date TO date;

ALTER TABLE raw.tej_intl_index
    RENAME COLUMN trade_date TO date;

-- ── 月資料：year_month → month ────────────────────────────

ALTER TABLE raw.tej_director_monthly
    RENAME COLUMN year_month TO month;

-- ── 季資料：year_month → season ───────────────────────────

ALTER TABLE raw.tej_quarterly
    RENAME COLUMN year_month TO season;

-- ── 驗證（執行後可用這些查詢確認欄位名稱已更新）─────────────
-- SELECT column_name FROM information_schema.columns
--   WHERE table_schema = 'raw' AND table_name = 'tej_stock_price'
--   ORDER BY ordinal_position;
--
-- SELECT column_name FROM information_schema.columns
--   WHERE table_schema = 'raw' AND table_name = 'tej_quarterly'
--   ORDER BY ordinal_position;
