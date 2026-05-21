"""
scrape_fx_history.py
使用 Playwright 爬取 investing.com 各幣種兌 USD 歷史匯率
輸出：fx_history_combined.csv

使用方式：
  python scrape_fx_history.py                              # 預設 2026-01-01 至今日
  python scrape_fx_history.py --start-date 20260101 --end-date 20260410
依賴：playwright, pandas, beautifulsoup4
安裝瀏覽器：python -m playwright install chromium
"""

import sys
import time
import random
import re
import os
import argparse
import pandas as pd
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')


def _normalise_date(s: str) -> str:
    """將 YYYYMMDD 轉為 YYYY-MM-DD；若已是 YYYY-MM-DD 則原樣返回。"""
    s = s.strip()
    if re.match(r'^\d{8}$', s):
        return f'{s[:4]}-{s[4:6]}-{s[6:8]}'
    return s


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='investing.com 匯率歷史資料爬取工具')
    parser.add_argument('--start-date', default='2026-01-01',
                        help='起始日，格式 YYYYMMDD 或 YYYY-MM-DD（預設 2026-01-01）')
    parser.add_argument('--end-date', default=datetime.today().strftime('%Y-%m-%d'),
                        help='結束日，格式 YYYYMMDD 或 YYYY-MM-DD（預設今日）')
    parser.add_argument('--output', default='',
                        help='輸出 CSV 路徑（預設與本程式同目錄之 fx_history_combined.csv）')
    parser.add_argument('--currencies', default='',
                        help='只爬指定幣種，逗號分隔，例如 inr 或 inr,krw（預設爬全部）')
    return parser.parse_args()


_args = _parse_args()

# ─── 設定 ───────────────────────────────────────────────────────────────────────
_ALL_CURRENCIES = ['krw', 'eur', 'jpy', 'gbp', 'aud', 'cad', 'hkd', 'cny', 'twd', 'inr']

# investing.com HK 對小面值貨幣顯示的是「每 N 單位換多少 USD」
# 須除以 N 才能還原為「1 單位換多少 USD」
CCY_UNIT_SCALE: dict[str, int] = {
    'jpy': 100,   # 每 100 日圓
    'krw': 1000,  # 每 1000 韓元
    'inr': 100,   # 每 100 盧比
}
CURRENCIES = (
    [c.strip().lower() for c in _args.currencies.split(',') if c.strip()]
    if _args.currencies
    else _ALL_CURRENCIES
)
START_DATE  = _normalise_date(_args.start_date)
END_DATE    = _normalise_date(_args.end_date)
OUTPUT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = _args.output if _args.output else os.path.join(OUTPUT_DIR, 'fx_history_combined.csv')
USER_AGENT  = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/146.0.0.0 Safari/537.36'
)

# ─── 工具 ───────────────────────────────────────────────────────────────────────
def human_delay(lo=0.8, hi=2.2):
    time.sleep(random.uniform(lo, hi))


def dismiss_popups(page):
    """關閉常見的彈窗（包含 cookie、廣告、登入提示）"""
    close_patterns = [
        '#onetrust-accept-btn-handler',
        'button[id*="accept"]',
        'button[aria-label*="close" i]',
        'button[aria-label*="Close" i]',
        'div[class*="popupCloseIcon"]',
        'i[class*="popupCloseIcon"]',
        'span[class*="closeButton"]',
        # 登入/認證彈窗（auth_popup）— 按 Escape 或點背景關閉
        'div[class*="auth_popup"]',
    ]
    for sel in close_patterns:
        try:
            elems = page.locator(sel)
            if elems.count() > 0 and elems.first.is_visible(timeout=1000):
                # 嘗試按 Escape 關閉彈窗，或直接點擊（若為背景遮罩）
                try:
                    page.keyboard.press('Escape')
                    time.sleep(0.3)
                except Exception:
                    pass
                elems.first.click(timeout=2000)
                human_delay(0.3, 0.5)
        except Exception:
            pass
    # 額外嘗試：按 Escape 關閉任何模態彈窗
    try:
        page.keyboard.press('Escape')
        time.sleep(0.2)
    except Exception:
        pass


# ─── 日期設定 ──────────────────────────────────────────────────────────────────
def set_date_range(page) -> bool:
    """
    1. 找到日期選擇器觸發按鈕（含日期字串的 shadow-select div）並點擊
    2. 等待 input[type=date] 出現（opacity-0，動態加入 DOM）
    3. 用 fill(force=True) 設定起訖日期
    4. 點擊「應用」按鈕（<div class="...bg-v2-blue...">，非 <button>）
    """
    try:
        # ── Step 1：找到日期選擇器並點擊 ──────────────────────────────────
        # 先嘗試關閉可能阻擋點擊的彈窗（auth/login popup）
        try:
            page.keyboard.press('Escape')
            time.sleep(0.3)
        except Exception:
            pass
        for auth_sel in ['div[class*="auth_popup_darkBackground"]',
                         'div[class*="darkBackground"]']:
            try:
                el = page.locator(auth_sel).first
                if el.is_visible(timeout=1000):
                    page.keyboard.press('Escape')
                    time.sleep(0.5)
                    break
            except Exception:
                pass

        date_trigger = page.locator('div[class*="shadow-select"]').filter(
            has_text=re.compile(r'\d{4}-\d{2}-\d{2}')
        ).first
        date_trigger.scroll_into_view_if_needed()
        human_delay(0.3, 0.5)

        # 先嘗試正常點擊，若被彈窗遮擋則用 force=True
        try:
            date_trigger.click(timeout=5000)
        except Exception:
            print(f'    [備用] 使用 force=True 點擊觸發器', flush=True)
            date_trigger.click(force=True)
        print(f'    日期選擇器已點擊', flush=True)

        # ── Step 2：等待 date inputs 出現 ─────────────────────────────────
        page.wait_for_selector('input[type="date"]', timeout=8000)
        human_delay(0.5, 0.8)

        date_inputs = page.locator('input[type="date"]').all()
        if len(date_inputs) < 2:
            print(f'    [警告] 只找到 {len(date_inputs)} 個 date input')
            return False

        # ── Step 3：用 fill(force=True) 設定日期值 ────────────────────────
        # inputs 是 opacity-0 的原生 date input，需要 force=True 繞過可見度檢查
        date_inputs[0].fill(START_DATE, force=True)
        human_delay(0.2, 0.4)
        date_inputs[1].fill(END_DATE, force=True)
        human_delay(0.3, 0.5)

        s_val = date_inputs[0].input_value()
        e_val = date_inputs[1].input_value()
        print(f'    日期值：{s_val} ～ {e_val}')

        # ── Step 4：點擊「應用」按鈕 ────────────────────────────────────
        # Apply 按鈕是 <div class="...bg-v2-blue...cursor-pointer...">，非 <button>
        apply_clicked = False

        # 策略 A：找 bg-v2-blue div 中包含「應用」文字的
        apply_divs = page.locator('div[class*="bg-v2-blue"]')
        if apply_divs.count() > 0:
            for i in range(apply_divs.count()):
                txt = apply_divs.nth(i).inner_text()
                if '應用' in txt or 'Apply' in txt:
                    apply_divs.nth(i).click(force=True)
                    print(f'    ✓ Apply 已點擊（bg-v2-blue div）')
                    apply_clicked = True
                    break
            if not apply_clicked:
                apply_divs.first.click(force=True)
                print(f'    ✓ Apply 已點擊（bg-v2-blue div, 第一個）')
                apply_clicked = True

        # 策略 B：用 cursor-pointer div 含「應用」文字
        if not apply_clicked:
            js_result = page.evaluate("""() => {
                var kw = '\u61c9\u7528';
                // 找含「應用」文字的 div，且有 cursor-pointer 類
                var divs = document.querySelectorAll('div[class*="cursor-pointer"]');
                for (var i=0; i<divs.length; i++) {
                    var t=(divs[i].textContent||'').trim();
                    var r=divs[i].getBoundingClientRect();
                    if(t.includes(kw) && t.length<=8 && r.width>0 && r.height>0) {
                        divs[i].click();
                        return 'CLICKED_DIV: '+t;
                    }
                }
                // fallback: 任何包含「應用」的可見元素
                var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                var node;
                while(node=walker.nextNode()){
                    if(node.textContent.trim()===kw){
                        var el=node.parentElement;
                        var r=el.getBoundingClientRect();
                        if(r.width>0 && r.height>0){
                            el.click();
                            return 'CLICKED_TEXT: '+el.tagName;
                        }
                    }
                }
                return null;
            }""")
            if js_result:
                print(f'    ✓ Apply JS fallback: {js_result}')
                apply_clicked = True
            else:
                print('    [警告] 找不到 Apply 按鈕')

        human_delay(3.0, 5.0)
        return apply_clicked

    except Exception as e:
        print(f'    [錯誤] 日期設定失敗：{e}')
        return False


# ─── 表格解析 ──────────────────────────────────────────────────────────────────
_DATE_RE = re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日')


def _norm_date(text: str) -> str:
    m = _DATE_RE.search(text)
    if m:
        return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    return text.strip()


def _find_hist_table(soup):
    """
    優先選取含有 <time> 標籤的表格（歷史數據行），
    再找含「日期/Date/Close」欄位的表格，
    最後才 fallback 到第一個表格。
    """
    all_tables = soup.find_all('table')

    # 優先：含有 <time> 標籤的表格（歷史數據特徵）
    for t in all_tables:
        if t.find('time'):
            return t

    # 次選：column header 含「日期」或「Close」的表格
    for t in all_tables:
        thead = t.find('thead')
        if thead:
            header_text = thead.get_text()
            if any(k in header_text for k in ('日期', '收市', 'Close', 'Date')):
                return t

    # 次選：class 含特定關鍵字
    for t in all_tables:
        cls = ' '.join(t.get('class', []))
        if re.search(r'freeze|historical|datatable', cls, re.I):
            return t

    # fallback
    return all_tables[0] if all_tables else None


def parse_table(page) -> pd.DataFrame:
    soup = BeautifulSoup(page.content(), 'html.parser')
    table = _find_hist_table(soup)
    if not table:
        return pd.DataFrame()

    tbody = table.find('tbody')
    if not tbody:
        return pd.DataFrame()

    rows = []
    for tr in tbody.find_all('tr'):
        cells = tr.find_all('td')
        if len(cells) < 2:
            continue
        time_tag = cells[0].find('time')
        raw_date = time_tag.get_text(strip=True) if time_tag else cells[0].get_text(strip=True)

        # 過濾掉非日期資料行（如貨幣轉換連結）
        normed = _norm_date(raw_date)
        if not re.match(r'\d{4}-\d{2}-\d{2}', normed):
            continue

        def cv(i):
            return cells[i].get_text(strip=True).replace(',', '') if i < len(cells) else ''

        rows.append({
            'date':    normed,
            'close':   cv(1),
            'open':    cv(2),
            'high':    cv(3),
            'low':     cv(4),
            'change%': cv(6),
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    for col in ('close', 'open', 'high', 'low'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date', 'close']).sort_values('date').reset_index(drop=True)
    return df


def apply_unit_scale(df: pd.DataFrame, currency: str) -> pd.DataFrame:
    """將 investing.com 以 N 單位計價的幣種還原為 1 單位 = X USD。"""
    scale = CCY_UNIT_SCALE.get(currency.lower())
    if scale is None or df.empty:
        return df
    for col in ('close', 'open', 'high', 'low'):
        if col in df.columns:
            df[col] = df[col] / scale
    return df


# ─── 單幣爬取 ──────────────────────────────────────────────────────────────────
def scrape_one(page, currency: str) -> pd.DataFrame:
    url = f'https://hk.investing.com/currencies/{currency}-usd-historical-data'
    print(f'  → 載入 {url}', flush=True)

    # 頁面載入（允許最多重試一次）
    for attempt in range(2):
        try:
            page.goto(url, timeout=90000, wait_until='domcontentloaded')
            break
        except PWTimeout:
            if attempt == 0:
                print(f'  [警告] {currency} 頁面載入超時，重試中...', flush=True)
                time.sleep(10)
            else:
                print(f'  [錯誤] {currency} 頁面無法載入，跳過', flush=True)
                return pd.DataFrame()
        except Exception as e:
            print(f'  [錯誤] {currency} 頁面錯誤：{e}', flush=True)
            return pd.DataFrame()

    # 等待頁面 JS 執行完成（第一次載入瀏覽器需較長時間）
    time.sleep(7)
    dismiss_popups(page)

    # 等待歷史資料表格（允許較長時間，超時後仍繼續）
    try:
        page.wait_for_selector('table tbody tr', timeout=30000)
    except PWTimeout:
        print(f'  [警告] {currency} 表格等待超時，繼續嘗試...', flush=True)

    rows_before = page.locator('table tbody tr').count()
    print(f'  → 初始資料筆數：{rows_before}', flush=True)

    if rows_before == 0:
        # 頁面可能沒有正確載入，再等一下
        time.sleep(5)
        rows_before = page.locator('table tbody tr').count()
        print(f'  → 再次確認筆數：{rows_before}', flush=True)
        if rows_before == 0:
            print(f'  [警告] {currency.upper()} 頁面無資料', flush=True)
            return pd.DataFrame()

    # 設定日期範圍
    print(f'  → 設定日期 {START_DATE} ～ {END_DATE}', flush=True)
    ok = set_date_range(page)

    # 等待表格重新渲染
    time.sleep(3)
    try:
        page.wait_for_selector('table tbody tr', timeout=15000)
    except Exception:
        pass

    df = parse_table(page)
    if df.empty:
        print(f'  [警告] {currency.upper()} 解析失敗或無資料', flush=True)
    else:
        df = apply_unit_scale(df, currency)
        d0 = df['date'].min().strftime('%Y-%m-%d')
        d1 = df['date'].max().strftime('%Y-%m-%d')
        scale = CCY_UNIT_SCALE.get(currency.lower())
        scale_note = f'（÷{scale}）' if scale else ''
        print(f'  ✓  {currency.upper()}/USD{scale_note}：{len(df)} 筆（{d0} ～ {d1}），close={df["close"].iloc[-1]:.6f}', flush=True)
    return df


# ─── 主程式 ────────────────────────────────────────────────────────────────────
def main():
    print('=' * 60, flush=True)
    print('investing.com 匯率歷史資料爬取工具（Playwright 版本）', flush=True)
    print(f'日期範圍：{START_DATE} ～ {END_DATE}', flush=True)
    print(f'幣種：{" ".join(c.upper() for c in CURRENCIES)}', flush=True)
    print('=' * 60, flush=True)

    frames = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,  # 非 headless 避免 Cloudflare 封鎖
            args=['--lang=zh-HK,zh']
        )
        try:
            for idx, currency in enumerate(CURRENCIES, 1):
                print(f'\n[{idx}/{len(CURRENCIES)}] 爬取 {currency.upper()}/USD ...', flush=True)
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={'width': 1440, 'height': 900},
                    locale='zh-HK',
                )
                page = context.new_page()
                df = pd.DataFrame()
                try:
                    df = scrape_one(page, currency)
                except Exception as e:
                    print(f'  [錯誤] {currency.upper()} 爬取異常：{e}', flush=True)
                finally:
                    context.close()
                if not df.empty:
                    df.insert(0, 'currency', currency.upper())
                    frames.append(df)
                wait_s = random.uniform(8.0, 12.0)
                print(f'  等待 {wait_s:.1f}s ...', flush=True)
                time.sleep(wait_s)
        finally:
            browser.close()
            print('\n瀏覽器已關閉')

    if not frames:
        print('\n[錯誤] 未取得任何資料。')
        return

    combined = (
        pd.concat(frames, ignore_index=True)
        .sort_values(['currency', 'date'])
        .reset_index(drop=True)
    )
    combined.to_csv(OUTPUT_FILE, index=False, encoding='utf-8-sig')

    print(f'\n{"=" * 60}')
    print(f'完成！共 {len(combined)} 筆，已儲存至：')
    print(f'  {OUTPUT_FILE}')
    print('\n各幣種筆數統計：')
    summary = combined.groupby('currency').agg(
        筆數=('date', 'count'),
        最早日期=('date', 'min'),
        最新日期=('date', 'max'),
    )
    summary['最早日期'] = summary['最早日期'].dt.strftime('%Y-%m-%d')
    summary['最新日期'] = summary['最新日期'].dt.strftime('%Y-%m-%d')
    print(summary.to_string())
    print('=' * 60)


if __name__ == '__main__':
    main()
