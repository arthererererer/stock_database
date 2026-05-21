"""
load_crawler_fx.py — Investing.com 爬蟲匯率 CSV → PostgreSQL ETL

用法：
    python load_crawler_fx.py
    python load_crawler_fx.py --file /path/to/fx_history_combined.csv

環境變數：
    DATABASE_URL  PostgreSQL 連線字串
                  範例：postgresql://user:pass@localhost:5432/findb

資料說明：
    - 計價方式：外幣/USD，即 1 單位外幣可換多少 USD
      例：AUD=0.6672 代表 1 AUD = 0.6672 USD
    - TWD 同樣以外幣/USD 計價，可作為換算 TWD/其他外幣的橋接：
      TWD/JPY = (TWD close) / (JPY close)
    - 匯入策略：INSERT ... ON CONFLICT DO UPDATE（重複日期資料以新值覆寫）

幣種範圍（9 個）：
    KRW、EUR、JPY、GBP、AUD、CAD、HKD、CNY、TWD
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras

# ──────────────────────────────────────────────
# 基礎設定
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DEFAULT_FX_PATH = (
    Path(__file__).resolve().parent.parent / "investing.com爬蟲" / "fx_history_combined.csv"
)

EXPECTED_CURRENCIES = {"KRW", "EUR", "JPY", "GBP", "AUD", "CAD", "HKD", "CNY", "TWD"}

# ──────────────────────────────────────────────
# 清洗工具
# ──────────────────────────────────────────────

def clean_change_pct(val) -> float | None:
    """
    清洗 change% 欄位：
      "+0.03%"  → 0.0300
      "-0.03%"  → -0.0300
      ""        → None
    """
    if pd.isna(val):
        return None
    s = str(val).strip().replace("%", "").replace("+", "")
    if s in ("", "NA", "N/A", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def clean_numeric(val) -> float | None:
    if pd.isna(val):
        return None
    s = str(val).strip().replace(",", "")
    if s in ("", "NA", "N/A", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ──────────────────────────────────────────────
# 備份與驗證工具
# ──────────────────────────────────────────────

def backup_fx_table(conn: psycopg2.extensions.connection) -> tuple[str, int]:
    """
    匯入前在 backup schema 備份 raw.fx_crawler。
    回傳 (備份表名稱, 備份前筆數)。
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"fx_crawler_{ts}"
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS backup")
        cur.execute(
            f"CREATE TABLE backup.{backup_name} AS SELECT * FROM raw.fx_crawler"
        )
        cur.execute(f"SELECT COUNT(*) FROM backup.{backup_name}")
        count: int = cur.fetchone()[0]
        conn.commit()
    log.info("備份完成：backup.%s（%d 筆）", backup_name, count)
    return backup_name, count


def report_fx_date_range(conn: psycopg2.extensions.connection) -> None:
    """匯入後查詢各幣種的日期範圍與筆數。"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT currency,
                   COUNT(*)   AS total,
                   MIN(date)  AS min_date,
                   MAX(date)  AS max_date
            FROM raw.fx_crawler
            GROUP BY currency
            ORDER BY currency
        """)
        rows = cur.fetchall()

    log.info("── 資料庫 fx_crawler 目前狀態 ──────────────────")
    for currency, total, min_date, max_date in rows:
        log.info("  %-5s  %6d 筆  %s → %s", currency, total, min_date, max_date)
    log.info("────────────────────────────────────────────────")


# ──────────────────────────────────────────────
# 主要匯入邏輯
# ──────────────────────────────────────────────

def load_fx(file_path: Path, conn: psycopg2.extensions.connection) -> None:
    if not file_path.exists():
        log.error("找不到匯率 CSV 檔案：%s", file_path)
        sys.exit(1)

    # ── 匯入前備份 ────────────────────────────
    backup_fx_table(conn)

    log.info("讀取匯率 CSV：%s", file_path)

    df = pd.read_csv(file_path, encoding="utf-8-sig", dtype=str)
    df.columns = [c.strip() for c in df.columns]

    # ── 欄位驗證 ──────────────────────────────
    required = {"currency", "date", "close", "open", "high", "low", "change%"}
    missing = required - set(df.columns)
    if missing:
        log.error("CSV 缺少必要欄位：%s", missing)
        sys.exit(1)

    # ── 清洗 ──────────────────────────────────
    df["currency"] = df["currency"].astype(str).str.strip().str.upper()
    df["date"]     = pd.to_datetime(df["date"].str.strip(), format="%Y-%m-%d", errors="coerce").dt.date
    df["close"]    = df["close"].apply(clean_numeric)
    df["open"]     = df["open"].apply(clean_numeric)
    df["high"]     = df["high"].apply(clean_numeric)
    df["low"]      = df["low"].apply(clean_numeric)
    df["change_pct"] = df["change%"].apply(clean_change_pct)
    df = df.drop(columns=["change%"])

    # 移除日期無效列
    invalid_date = df["date"].isna()
    if invalid_date.any():
        log.warning("移除 %d 筆日期無效資料", invalid_date.sum())
        df = df[~invalid_date]

    # ── 幣種檢查 ──────────────────────────────
    found_currencies = set(df["currency"].unique())
    unexpected = found_currencies - EXPECTED_CURRENCIES
    if unexpected:
        log.warning("CSV 含預期外幣種（仍會匯入）：%s", unexpected)
    missing_currencies = EXPECTED_CURRENCIES - found_currencies
    if missing_currencies:
        log.warning("CSV 缺少預期幣種（請確認爬蟲資料完整性）：%s", missing_currencies)

    total_rows = len(df)
    log.info("清洗後共 %d 筆資料，幣種：%s", total_rows, sorted(found_currencies))

    # ── 寫入資料庫 ────────────────────────────
    rows = list(
        df[["currency", "date", "close", "open", "high", "low", "change_pct"]]
        .itertuples(index=False, name=None)
    )

    sql = """
        INSERT INTO raw.fx_crawler (currency, date, close, open, high, low, change_pct)
        VALUES %s
        ON CONFLICT (currency, date) DO UPDATE
        SET close = EXCLUDED.close,
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            change_pct = EXCLUDED.change_pct
    """

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, rows, page_size=500)
        conn.commit()

    log.info("✓ 成功匯入 %d 筆（重複日期略過）", total_rows)

    # ── 匯入後統計報表 ────────────────────────
    print_summary(df)

    # ── 匯入後資料庫日期範圍驗證 ──────────────
    report_fx_date_range(conn)


def print_summary(df: pd.DataFrame) -> None:
    """印出各幣種筆數統計與日期範圍"""
    print("\n" + "=" * 55)
    print("  匯率匯入統計報表")
    print("=" * 55)
    print(f"  總筆數：{len(df):,}")
    print(f"  日期範圍：{df['date'].min()}  →  {df['date'].max()}")
    print()
    print(f"  {'幣種':<8}{'筆數':>8}{'最早日期':>14}{'最新日期':>14}{'close 缺值':>10}")
    print("  " + "-" * 53)

    for currency in sorted(df["currency"].unique()):
        sub = df[df["currency"] == currency]
        null_close = sub["close"].isna().sum()
        note = f"{null_close} 筆" if null_close > 0 else "—"
        print(
            f"  {currency:<8}{len(sub):>8,}{str(sub['date'].min()):>14}{str(sub['date'].max()):>14}{note:>10}"
        )

    # 特別提示 JPY 缺值狀況
    jpy = df[df["currency"] == "JPY"]
    if not jpy.empty:
        jpy_null = jpy["close"].isna().sum()
        if jpy_null > 0:
            print(f"\n  ⚠ JPY 有 {jpy_null} 筆 close 缺值，請以 IS NULL 查詢確認。")
        else:
            print("\n  ✓ JPY 無缺值。")

    print("=" * 55 + "\n")


# ──────────────────────────────────────────────
# 主程式
# ──────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Investing.com 爬蟲匯率 CSV → PostgreSQL ETL")
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_FX_PATH,
        help=f"匯率 CSV 路徑（預設：{DEFAULT_FX_PATH}）",
    )
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        log.error("環境變數 DATABASE_URL 未設定，請先 export DATABASE_URL=postgresql://...")
        sys.exit(1)

    log.info("連線至 PostgreSQL：%s", db_url.split("@")[-1])
    try:
        conn = psycopg2.connect(db_url)
    except psycopg2.OperationalError as exc:
        log.error("資料庫連線失敗：%s", exc)
        sys.exit(1)

    load_fx(args.file, conn)
    conn.close()
    log.info("匯率 ETL 完成。")


if __name__ == "__main__":
    main()
