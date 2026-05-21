-- 將 raw.wantgoo_monthly_revenue 的時間欄統一為 month（月頻，DATE 該月一號）
-- 支援：year_month → month，或舊版 "date" → month
-- 若已使用最新 load_wantgoo_monthly_revenue.py，首次連線會自動遷移；此檔供手動 psql 備用

BEGIN;

DROP INDEX IF EXISTS raw.idx_wantgoo_monthly_revenue_ym;
DROP INDEX IF EXISTS raw.idx_wantgoo_monthly_revenue_date;
DROP INDEX IF EXISTS raw.idx_wantgoo_monthly_revenue_month;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'raw' AND table_name = 'wantgoo_monthly_revenue'
          AND column_name = 'year_month'
    ) THEN
        EXECUTE 'ALTER TABLE raw.wantgoo_monthly_revenue RENAME COLUMN year_month TO "month"';
    ELSIF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'raw' AND table_name = 'wantgoo_monthly_revenue'
          AND column_name = 'date'
    ) THEN
        EXECUTE 'ALTER TABLE raw.wantgoo_monthly_revenue RENAME COLUMN "date" TO "month"';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_wantgoo_monthly_revenue_month
    ON raw.wantgoo_monthly_revenue ("month");

COMMIT;
