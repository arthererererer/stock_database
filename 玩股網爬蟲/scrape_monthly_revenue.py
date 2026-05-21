# -*- coding: utf-8 -*-
"""
玩股網：依股票清單爬取「每月營收」頁之當月營收（API 回傳之 monthRevenue，單位：仟元）。
需使用 Playwright 瀏覽器環境以通過網站對自動化請求的檢查。
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)

TW = timezone(timedelta(hours=8))

DEFAULT_LIST = (
    Path(__file__).resolve().parent
    / "Variable_setting"
    / "上市櫃股票清單.csv"
)


def ms_to_yyyymm(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=TW).strftime("%Y/%m")


def parse_ym(value: str) -> str | None:
    """標準化 YYYY/MM（或 YYYY-MM）格式；格式錯誤回傳 None。"""
    value = value.strip().replace("-", "/")
    try:
        datetime.strptime(value, "%Y/%m")
        return value
    except ValueError:
        return None


def validate_ym(value: str) -> str:
    """argparse type function：格式錯誤時拋出 ArgumentTypeError。"""
    import argparse as _ap
    result = parse_ym(value)
    if result is None:
        raise _ap.ArgumentTypeError(f"日期格式錯誤（需為 YYYY/MM）：{value!r}")
    return result


def add_calendar_months(y: int, mo: int, delta: int) -> tuple[int, int]:
    """曆月加減 delta（可為負）。"""
    idx = y * 12 + (mo - 1) + delta
    ny, nm0 = divmod(idx, 12)
    return ny, nm0 + 1


def rolling_ym_bounds(months: int) -> tuple[str, str]:
    """
    以台灣時區「本月」為終點，含本月在內共 months 個曆月。
    回傳 (start_ym, end_ym) 字串，格式 YYYY/MM，可供字串比較。
    """
    now = datetime.now(TW)
    y, m = now.year, now.month
    sy, sm = add_calendar_months(y, m, -(months - 1))
    end_ym = f"{y}/{m:02d}"
    start_ym = f"{sy}/{sm:02d}"
    return start_ym, end_ym


def slice_stocks_after_code(
    stocks: list[tuple[str, str]], after_code: str
) -> tuple[list[tuple[str, str]], int]:
    """
    依清單順序，找到第一筆 代號 == after_code 後，回傳其**下一筆起**的子清單
    與該筆的 0-based 索引。找不到則拋出 ValueError。
    """
    target = after_code.strip()
    if not target:
        raise ValueError("代號不得為空白")
    for i, (code, _) in enumerate(stocks):
        if code.strip() == target:
            return stocks[i + 1 :], i
    raise ValueError(f"清單中找不到代號 {target!r}")


def prompt_interactive() -> dict:
    """
    互動模式：以 Python input() 引導使用者設定參數，
    回傳含 start_ym / end_ym / limit / after_code 的 dict，取消時回傳 None。
    """
    SEP = "=" * 42
    print(SEP)
    print("  玩股網月營收爬蟲 - 互動啟動工具")
    print(SEP)
    print()
    print("請輸入要爬取的月營收日期區間（格式：YYYY/MM）")
    print("直接按 Enter 略過，代表不限制該端日期。")
    print()

    # --- 起始年月 ---
    while True:
        raw = input("起始年月（例如 2024/01，留空=不限）：").strip()
        if not raw:
            start_ym = None
            break
        result = parse_ym(raw)
        if result:
            start_ym = result
            break
        print(f"  [錯誤] 格式不符，請輸入 YYYY/MM（例如 2024/01）")

    # --- 結束年月 ---
    while True:
        raw = input("結束年月（例如 2026/03，留空=不限）：").strip()
        if not raw:
            end_ym = None
            break
        result = parse_ym(raw)
        if result:
            end_ym = result
            break
        print(f"  [錯誤] 格式不符，請輸入 YYYY/MM（例如 2026/03）")

    if start_ym and end_ym and start_ym > end_ym:
        print(f"\n  [錯誤] 起始年月 {start_ym} 晚於結束年月 {end_ym}，請重新執行。")
        return None

    # --- 測試筆數 ---
    while True:
        raw = input("只爬前 N 支股票（0 或留空=全部）：").strip()
        if not raw:
            limit = 0
            break
        if raw.isdigit():
            limit = int(raw)
            break
        print("  [錯誤] 請輸入非負整數")

    # --- 續爬：從某代號「之後」接續 ---
    print("接續爬蟲：請輸入清單裡「最後一檔已完成」的股票代號，")
    print("程式會從該代號的下一檔起爬（留空＝從清單第一檔開始）。")
    raw = input("接續代號（例如 4147，留空=從頭）：").strip()
    after_code = raw if raw else None

    # --- 確認 ---
    print()
    print("-" * 42)
    print(f"  起始年月：{start_ym or '不限（全部歷史）'}")
    print(f"  結束年月：{end_ym   or '不限（最新月份）'}")
    if after_code:
        print(f"  接續：自代號 {after_code} 的下一檔起")
    else:
        print("  接續：自清單第一檔起")
    print(f"  股票範圍：{'全部' if limit == 0 else f'前 {limit} 支'}")
    print("-" * 42)
    confirm = input("確認執行？(Y/N)：").strip().upper()
    if confirm != "Y":
        print("已取消。")
        return None

    return {
        "start_ym": start_ym,
        "end_ym": end_ym,
        "limit": limit,
        "after_code": after_code,
    }


def load_stocks(csv_path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "代號" not in reader.fieldnames:
            raise ValueError("CSV 需包含「代號」欄位")
        has_name = "名稱" in reader.fieldnames
        for row in reader:
            code = (row.get("代號") or "").strip()
            if not code:
                continue
            name = (row.get("名稱") or "").strip() if has_name else ""
            rows.append((code, name))
    return rows


def fetch_monthly_revenue_json(page, stock_id: str) -> tuple[int, str]:
    """回傳 (HTTP status, response body text)。"""
    return page.evaluate(
        """async ({ sid }) => {
            const url = `/stock/${sid}/financial-statements/monthly-revenue-data`;
            const r = await fetch(url);
            const text = await r.text();
            return [r.status, text];
        }""",
        {"sid": stock_id},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="玩股網月營收（當月營收）爬蟲")
    parser.add_argument(
        "--list",
        type=Path,
        default=DEFAULT_LIST,
        help="股票清單 CSV 路徑（需含「代號」欄；「名稱」選填）",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="輸出 CSV 路徑（預設：專案目錄 output/月營收_YYYYMMDD_HHMMSS.csv）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="僅處理前 N 支股票（0 表示全部，方便測試）",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="略過清單最前面 N 支（進階／腳本用）；與 --after-code 擇一",
    )
    parser.add_argument(
        "--after-code",
        default=None,
        metavar="代號",
        help="續爬：從清單中此代號的「下一檔」起爬（依 CSV 列順序）；與 --offset 擇一",
    )
    parser.add_argument(
        "--page-wait-ms",
        type=int,
        default=3000,
        help="載入個股頁後等待毫秒數，讓 cookie / 前端就緒（預設 3000）",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否以無頭模式啟動 Chromium（預設：是）",
    )
    parser.add_argument(
        "--start-ym",
        type=validate_ym,
        default=None,
        metavar="YYYY/MM",
        help="篩選起始年月（含），格式 YYYY/MM；留空表示不限早期",
    )
    parser.add_argument(
        "--end-ym",
        type=validate_ym,
        default=None,
        metavar="YYYY/MM",
        help="篩選結束年月（含），格式 YYYY/MM；留空表示不限近期",
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="互動模式：以提示引導輸入日期區間（雙擊 .bat 時使用）",
    )
    parser.add_argument(
        "--rolling-months",
        type=int,
        default=None,
        metavar="N",
        help="排程用：自動設定為含本月在內共 N 個曆月（不可與 --start-ym/--end-ym 併用；-i 時忽略）",
    )
    args = parser.parse_args()

    if args.after_code is not None:
        ac = str(args.after_code).strip()
        args.after_code = ac if ac else None

    if args.interactive:
        params = prompt_interactive()
        if params is None:
            return 0
        args.start_ym = params["start_ym"]
        args.end_ym   = params["end_ym"]
        args.limit    = params["limit"]
        ac = (params.get("after_code") or "").strip()
        args.after_code = ac if ac else None
        if args.after_code:
            args.offset = 0
        print()

    if (not args.interactive) and args.rolling_months is not None:
        if args.rolling_months < 1:
            print("錯誤：--rolling-months 須為 >= 1 的整數", file=sys.stderr)
            return 1
        if args.start_ym is not None or args.end_ym is not None:
            print(
                "錯誤：--rolling-months 不可與 --start-ym / --end-ym 併用",
                file=sys.stderr,
            )
            return 1
        args.start_ym, args.end_ym = rolling_ym_bounds(args.rolling_months)
        print(
            f"日期區間（--rolling-months {args.rolling_months}）："
            f"{args.start_ym} ～ {args.end_ym}",
            flush=True,
        )

    if args.start_ym and args.end_ym and args.start_ym > args.end_ym:
        print(
            f"錯誤：起始年月 {args.start_ym} 晚於結束年月 {args.end_ym}",
            file=sys.stderr,
        )
        return 1

    if not args.list.is_file():
        print(f"找不到清單檔：{args.list}", file=sys.stderr)
        return 1

    if args.after_code and args.offset:
        print(
            "錯誤：--after-code 與 --offset 請擇一使用",
            file=sys.stderr,
        )
        return 1

    if args.offset < 0:
        print("錯誤：--offset 不可為負數", file=sys.stderr)
        return 1

    stocks = load_stocks(args.list)
    total_in_list = len(stocks)

    if args.after_code:
        try:
            stocks, idx_hit = slice_stocks_after_code(stocks, args.after_code)
        except ValueError as e:
            print(f"錯誤：{e}（清單：{args.list}）", file=sys.stderr)
            return 1
        if not stocks:
            print(
                f"錯誤：代號 {args.after_code!r} 已是清單最後一檔，沒有後續可爬",
                file=sys.stderr,
            )
            return 1
        nxt_code, nxt_name = stocks[0][0], stocks[0][1]
        print(
            f"續爬：代號 {args.after_code} 為清單第 {idx_hit + 1} 列，"
            f"本次自第 {idx_hit + 2} 列（{nxt_code} {nxt_name}）起，共 {len(stocks)} 支",
            flush=True,
        )
    elif args.offset:
        if args.offset >= total_in_list:
            print(
                f"錯誤：--offset {args.offset} 大於等於清單總檔數 {total_in_list}",
                file=sys.stderr,
            )
            return 1
        stocks = stocks[args.offset :]
        print(
            f"續爬：已略過清單前 {args.offset} 支，本次處理 {len(stocks)} 支（清單共 {total_in_list} 支）",
            flush=True,
        )
    if args.limit and args.limit > 0:
        stocks = stocks[: args.limit]

    out_path = args.output
    if out_path is None:
        out_dir = Path(__file__).resolve().parent / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        range_tag = ""
        if args.start_ym or args.end_ym:
            s = (args.start_ym or "earliest").replace("/", "")
            e = (args.end_ym or "latest").replace("/", "")
            range_tag = f"_{s}-{e}"
        out_path = out_dir / f"月營收{range_tag}_{stamp}.csv"

    fieldnames = ["代號", "名稱", "年度月份", "當月營收_仟元"]

    success_count, fail_count = 0, 0
    t0 = time.perf_counter()

    print(
        f"正在啟動 Playwright／Chromium（headless={args.headless}），"
        f"本次 {len(stocks)} 檔，輸出：{out_path}",
        flush=True,
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=args.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            locale="zh-TW",
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()

        with out_path.open("w", encoding="utf-8-sig", newline="") as out_f:
            writer = csv.DictWriter(out_f, fieldnames=fieldnames)
            writer.writeheader()

            for idx, (code, name) in enumerate(stocks):
                if idx > 0:
                    delay = random.uniform(1.0, 5.0)
                    time.sleep(delay)

                url = (
                    f"https://www.wantgoo.com/stock/{code}/"
                    f"financial-statements/monthly-revenue"
                )
                try:
                    page.goto(url, wait_until="load", timeout=120000)
                except PlaywrightTimeout:
                    print(f"[逾時] {code} {name} 頁面載入失敗", flush=True)
                    fail_count += 1
                    continue

                page.wait_for_timeout(args.page_wait_ms)
                status, body = fetch_monthly_revenue_json(page, code)

                if status != 200:
                    print(
                        f"[API {status}] {code} {name}：{body[:120]}",
                        flush=True,
                    )
                    fail_count += 1
                    continue

                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    print(f"[JSON] {code} {name} 解析失敗", flush=True)
                    fail_count += 1
                    continue

                if not isinstance(data, list) or len(data) == 0:
                    print(f"[無資料] {code} {name}", flush=True)
                    fail_count += 1
                    continue

                rows_written = 0
                for item in data:
                    ms = item.get("date")
                    rev = item.get("monthRevenue")
                    if ms is None or rev is None:
                        continue
                    yyyymm = ms_to_yyyymm(int(ms))
                    if args.start_ym and yyyymm < args.start_ym:
                        continue
                    if args.end_ym and yyyymm > args.end_ym:
                        continue
                    writer.writerow(
                        {
                            "代號": code,
                            "名稱": name,
                            "年度月份": yyyymm,
                            "當月營收_仟元": int(rev),
                        }
                    )
                    rows_written += 1

                success_count += 1
                n = len(stocks)
                print(
                    f"[{success_count + fail_count}/{n}] {code} {name} "
                    f"已寫入 {rows_written} 筆（API 共 {len(data)} 筆）",
                    flush=True,
                )
                out_f.flush()

        browser.close()

    elapsed = time.perf_counter() - t0
    print(
        f"完成。成功 {success_count} 支、失敗 {fail_count} 支，"
        f"輸出：{out_path}，耗時 {elapsed:.1f} 秒",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
