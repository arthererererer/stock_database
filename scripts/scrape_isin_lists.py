"""
TWSE ISIN 證券清單爬蟲
======================
來源：https://isin.twse.com.tw/isin/C_public.jsp?strMode=<N>

產出檔案（存放於 Variable_setting/）：
  上市櫃股票清單.csv  — strMode=2 股票 + strMode=4 股票（格式：代號,名稱）
  興櫃清單.csv        — strMode=5（格式：代號,名稱）
  ETF清單.csv         — strMode=2 ETF + strMode=4 ETF（格式：代號,名稱,ISIN,上市日期,市場別）
  基金清單.csv        — strMode=7（格式：代號,名稱,ISIN,發行日期）
  指數清單.csv        — strMode=11（格式：代號,名稱,ISIN,發行日期）

用法：
  python scripts/scrape_isin_lists.py
  python scripts/scrape_isin_lists.py --output-dir Variable_setting
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://isin.twse.com.tw/isin/C_public.jsp"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
ENCODING = "ms950"
REQUEST_DELAY = 2.0  # seconds between requests


# ── 解析工具 ──────────────────────────────────────────────────────────────────

def _fetch(mode: int) -> list[dict]:
    """抓取單一 strMode 頁面，回傳 list of dict，每筆含 category 欄位。"""
    url = f"{BASE_URL}?strMode={mode}"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    text = resp.content.decode(ENCODING, errors="replace")
    soup = BeautifulSoup(text, "html.parser")

    table = soup.find("table", class_="h4")
    if not table:
        raise RuntimeError(f"strMode={mode} 找不到資料表格")

    rows = table.find_all("tr")
    current_category = ""
    records: list[dict] = []

    for row in rows[1:]:
        cells = row.find_all("td")
        if not cells:
            continue

        if len(cells) == 1:
            # 分類標題列
            current_category = cells[0].text.strip()
            continue

        # 資料列：第一欄為「代號　名稱」（以全形空白 U+3000 分隔）
        raw_code_name = cells[0].text.strip()
        if "　" not in raw_code_name:
            continue
        code, name = raw_code_name.split("　", 1)
        code = code.strip()
        name = name.strip()

        col2 = cells[1].text.strip() if len(cells) > 1 else ""
        col3 = cells[2].text.strip() if len(cells) > 2 else ""
        col4 = cells[3].text.strip() if len(cells) > 3 else ""
        col5 = cells[4].text.strip() if len(cells) > 4 else ""

        records.append({
            "category": current_category,
            "代號": code,
            "名稱": name,
            "ISIN": col2,
            "日期": col3,  # 上市日期 or 發行日期
            "市場別": col4,
            "產業別": col5,
        })

    return records


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict],
               bom: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w"
    encoding = "utf-8-sig" if bom else "utf-8"
    with open(path, mode, newline="", encoding=encoding) as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  → 寫入 {path}（{len(rows)} 筆）")


# ── 主流程 ────────────────────────────────────────────────────────────────────

def run(output_dir: Path) -> None:
    print("=== ISIN 證券清單爬蟲 ===")

    # ── mode=2 上市 ──────────────────────────────────────────────────────────
    print("[1/5] 抓取 strMode=2（上市證券）...")
    mode2 = _fetch(2)
    time.sleep(REQUEST_DELAY)

    # ── mode=4 上櫃 ──────────────────────────────────────────────────────────
    print("[2/5] 抓取 strMode=4（上櫃證券）...")
    mode4 = _fetch(4)
    time.sleep(REQUEST_DELAY)

    # ── mode=5 興櫃 ──────────────────────────────────────────────────────────
    print("[3/5] 抓取 strMode=5（興櫃證券）...")
    mode5 = _fetch(5)
    time.sleep(REQUEST_DELAY)

    # ── mode=7 基金 ──────────────────────────────────────────────────────────
    print("[4/5] 抓取 strMode=7（開放式基金）...")
    mode7 = _fetch(7)
    time.sleep(REQUEST_DELAY)

    # ── mode=11 指數 ─────────────────────────────────────────────────────────
    print("[5/5] 抓取 strMode=11（指數）...")
    mode11 = _fetch(11)
    time.sleep(REQUEST_DELAY)

    print()

    # ── 上市櫃股票清單.csv ───────────────────────────────────────────────────
    stocks_listed   = [r for r in mode2 if r["category"] == "股票"]
    stocks_otc      = [r for r in mode4 if r["category"] == "股票"]
    stocks_all = stocks_listed + stocks_otc
    # 依代號排序，去除重複
    seen: set[str] = set()
    stocks_dedup: list[dict] = []
    for r in stocks_all:
        if r["代號"] not in seen:
            seen.add(r["代號"])
            stocks_dedup.append(r)
    stocks_dedup.sort(key=lambda x: x["代號"])

    print("寫出 上市櫃股票清單.csv（上市股票 + 上櫃股票）")
    _write_csv(
        output_dir / "上市櫃股票清單.csv",
        fieldnames=["代號", "名稱"],
        rows=stocks_dedup,
        bom=True,  # 保持與原格式一致（有 BOM）
    )

    # ── 興櫃清單.csv ─────────────────────────────────────────────────────────
    emerge_sorted = sorted(mode5, key=lambda x: x["代號"])
    print("寫出 興櫃清單.csv")
    _write_csv(
        output_dir / "興櫃清單.csv",
        fieldnames=["代號", "名稱"],
        rows=emerge_sorted,
        bom=True,
    )

    # ── ETF清單.csv ──────────────────────────────────────────────────────────
    etf_listed = [r for r in mode2 if r["category"] == "ETF"]
    etf_otc    = [r for r in mode4 if r["category"] == "ETF"]
    etf_all_raw = etf_listed + etf_otc
    seen_etf: set[str] = set()
    etf_all: list[dict] = []
    for r in etf_all_raw:
        if r["代號"] not in seen_etf:
            seen_etf.add(r["代號"])
            etf_all.append(r)
    etf_all.sort(key=lambda x: x["代號"])

    print("寫出 ETF清單.csv（上市 ETF + 上櫃 ETF）")
    _write_csv(
        output_dir / "ETF清單.csv",
        fieldnames=["代號", "名稱", "ISIN", "上市日期", "市場別"],
        rows=[
            {
                "代號": r["代號"],
                "名稱": r["名稱"],
                "ISIN": r["ISIN"],
                "上市日期": r["日期"],
                "市場別": r["市場別"],
            }
            for r in etf_all
        ],
        bom=True,
    )

    # ── 基金清單.csv ─────────────────────────────────────────────────────────
    funds_sorted = sorted(mode7, key=lambda x: x["代號"])
    print("寫出 基金清單.csv")
    _write_csv(
        output_dir / "基金清單.csv",
        fieldnames=["代號", "名稱", "ISIN", "發行日期"],
        rows=[
            {
                "代號": r["代號"],
                "名稱": r["名稱"],
                "ISIN": r["ISIN"],
                "發行日期": r["日期"],
            }
            for r in funds_sorted
        ],
        bom=True,
    )

    # ── 指數清單.csv ─────────────────────────────────────────────────────────
    indices_sorted = sorted(mode11, key=lambda x: x["代號"])
    print("寫出 指數清單.csv")
    _write_csv(
        output_dir / "指數清單.csv",
        fieldnames=["代號", "名稱", "ISIN", "發行日期"],
        rows=[
            {
                "代號": r["代號"],
                "名稱": r["名稱"],
                "ISIN": r["ISIN"],
                "發行日期": r["日期"],
            }
            for r in indices_sorted
        ],
        bom=True,
    )

    print()
    print("完成。")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    default_out  = project_root / "Variable_setting"

    parser = argparse.ArgumentParser(description="TWSE ISIN 證券清單爬蟲")
    parser.add_argument(
        "--output-dir", "-o",
        default=str(default_out),
        help=f"輸出目錄（預設：{default_out}）",
    )
    args = parser.parse_args()

    run(Path(args.output_dir))
