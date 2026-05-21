"""補抓 JPY，合併到 fx_history_combined.csv"""
import sys, time, re, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrape_fx_history import (
    USER_AGENT, START_DATE, END_DATE, OUTPUT_FILE,
    dismiss_popups, set_date_range, parse_table
)
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

print(f'補抓 JPY（{START_DATE} ～ {END_DATE}）')

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False, args=['--lang=zh-HK,zh'])
    ctx = browser.new_context(user_agent=USER_AGENT, viewport={'width':1440,'height':900}, locale='zh-HK')
    page = ctx.new_page()

    try:
        url = 'https://hk.investing.com/currencies/jpy-usd-historical-data'
        print(f'載入: {url}')
        page.goto(url, timeout=90000, wait_until='domcontentloaded')
        time.sleep(8)
        dismiss_popups(page)

        rows_before = page.locator('table tbody tr').count()
        print(f'初始 rows: {rows_before}')

        # 設定日期
        print(f'設定日期: {START_DATE} ～ {END_DATE}')
        ok = set_date_range(page)
        print(f'set_date_range 返回: {ok}')

        time.sleep(3)

        df_jpy = parse_table(page)
        if df_jpy.empty or len(df_jpy) < 50:
            print(f'❌ JPY 解析失敗或筆數不足（{len(df_jpy)} 筆），嘗試重新設定日期...')
            time.sleep(3)
            ok2 = set_date_range(page)
            time.sleep(4)
            df_jpy = parse_table(page)

        if df_jpy.empty:
            print('❌ JPY 解析失敗')
        else:
            d0 = df_jpy['date'].min().strftime('%Y-%m-%d')
            d1 = df_jpy['date'].max().strftime('%Y-%m-%d')
            print(f'✅ JPY：{len(df_jpy)} 筆（{d0} ～ {d1}）')

            # 讀取現有 CSV
            existing = pd.read_csv(OUTPUT_FILE, encoding='utf-8-sig')
            existing['date'] = pd.to_datetime(existing['date'])
            print(f'現有 CSV：{len(existing)} 筆')

            # 移除舊的 JPY 資料
            existing = existing[existing['currency'] != 'JPY']
            print(f'移除舊 JPY 後：{len(existing)} 筆')

            # 加入新的 JPY
            df_jpy.insert(0, 'currency', 'JPY')
            combined = pd.concat([existing, df_jpy], ignore_index=True)
            combined = combined.sort_values(['currency', 'date']).reset_index(drop=True)
            combined.to_csv(OUTPUT_FILE, index=False, encoding='utf-8-sig')
            print(f'✅ 已更新 CSV：{len(combined)} 筆')

            print('\n各幣種統計：')
            summary = combined.groupby('currency').agg(
                筆數=('date', 'count'),
                最早=('date', 'min'),
                最新=('date', 'max'),
            )
            summary['最早'] = summary['最早'].dt.strftime('%Y-%m-%d')
            summary['最新'] = summary['最新'].dt.strftime('%Y-%m-%d')
            print(summary.to_string())

    except Exception as e:
        import traceback
        print(f'Error: {e}')
        traceback.print_exc()
    finally:
        ctx.close()
        browser.close()
        print('\nDone.')
