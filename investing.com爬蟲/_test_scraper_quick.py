"""
_test_scraper_quick.py — 爬蟲快速煙霧測試
只爬取 1 個幣種（TWD）最近 7 天，驗證 Playwright + investing.com 連線正常。
執行：python _test_scraper_quick.py
"""
import sys
import os
import time
import random
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 強制覆寫 sys.argv，避免 scrape_fx_history 的 _parse_args() 誤讀測試參數
END_DATE   = datetime.today().strftime('%Y-%m-%d')
START_DATE = (datetime.today() - timedelta(days=7)).strftime('%Y-%m-%d')

sys.argv = [
    'scrape_fx_history.py',
    '--start-date', START_DATE,
    '--end-date',   END_DATE,
]

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scrape_fx_history import (
    USER_AGENT, dismiss_popups, set_date_range, parse_table
)
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

print('=' * 60)
print('爬蟲快速煙霧測試（1 幣種 × 7 天）')
print(f'測試幣種：TWD/USD')
print(f'日期範圍：{START_DATE} ～ {END_DATE}')
print('=' * 60)

CURRENCY = 'twd'
URL = f'https://hk.investing.com/currencies/{CURRENCY}-usd-historical-data'

with sync_playwright() as pw:
    browser = pw.chromium.launch(
        headless=False,
        args=['--lang=zh-HK,zh']
    )
    context = browser.new_context(
        user_agent=USER_AGENT,
        viewport={'width': 1440, 'height': 900},
        locale='zh-HK',
    )
    page = context.new_page()

    try:
        print(f'\n→ 載入 {URL}')
        page.goto(URL, timeout=90000, wait_until='domcontentloaded')
        time.sleep(7)
        dismiss_popups(page)

        try:
            page.wait_for_selector('table tbody tr', timeout=30000)
        except PWTimeout:
            print('[警告] 表格等待超時，繼續...')

        rows = page.locator('table tbody tr').count()
        print(f'→ 初始資料筆數：{rows}')

        if rows == 0:
            print('[錯誤] 頁面無法載入表格，請確認網路或 investing.com 存取狀況')
        else:
            print(f'→ 設定日期 {START_DATE} ～ {END_DATE}')
            ok = set_date_range(page)
            print(f'→ 日期設定結果：{"成功" if ok else "失敗（可能影響資料範圍）"}')

            time.sleep(3)
            df = parse_table(page)

            if df.empty:
                print('[警告] 解析失敗或無資料')
            else:
                d0 = df['date'].min().strftime('%Y-%m-%d')
                d1 = df['date'].max().strftime('%Y-%m-%d')
                print(f'\n✓ TWD/USD 測試成功！取得 {len(df)} 筆（{d0} ～ {d1}）')
                print('\n前 5 筆資料：')
                print(df.head().to_string(index=False))

    except Exception as e:
        import traceback
        print(f'[錯誤] {e}')
        traceback.print_exc()
    finally:
        context.close()
        browser.close()
        print('\n瀏覽器已關閉')

print('\n' + '=' * 60)
print('煙霧測試完成')
print('若上方顯示「✓ TWD/USD 測試成功」，表示爬蟲機制正常。')
print('可接著執行完整爬蟲：')
print('  python scrape_fx_history.py --start-date 20260101')
print('=' * 60)
