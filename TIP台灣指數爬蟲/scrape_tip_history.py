"""
TIP 臺灣指數公司 — 指數歷史資料爬蟲（API 版）

直接呼叫 https://backend.taiwanindex.com.tw/api，不再需要 Playwright。
輸出格式與原版相同（指數代碼、指數名稱、日期、價格指數值、報酬指數值、漲跌點數、漲跌百分比）。
"""

from __future__ import annotations

import argparse
import csv
import random
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import requests

API_BASE  = "https://backend.taiwanindex.com.tw/api"
SITE_BASE = "https://taiwanindex.com.tw"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)

COLUMNS = (
    "指數代碼",
    "指數名稱",
    "日期",
    "價格指數值",
    "報酬指數值",
    "漲跌點數",
    "漲跌百分比",
)


class NoDataError(Exception):
    """指定日期區間無資料，或該指數頁面不支援歷史下載。"""


# ── Session ──────────────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent":      USER_AGENT,
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Referer":         f"{SITE_BASE}/",
        "Origin":          SITE_BASE,
    })
    return s


# ── Index list ────────────────────────────────────────────────────────────────

def list_all_indexes(sess: requests.Session) -> list[tuple[str, str]]:
    """從 API 取得完整指數列表，回傳 [(代碼, 名稱), ...]，依代碼排序。"""
    r = sess.get(f"{API_BASE}/indexes", params={"count": -1, "page": 1}, timeout=30)
    r.raise_for_status()
    items = r.json()
    seen: dict[str, str] = {}
    for item in items:
        code = (item.get("code") or "").strip()
        name = (item.get("name") or "").strip()
        if not code or code in seen:
            continue
        if not item.get("show_history", True):
            continue
        seen[code] = name
    return sorted(seen.items(), key=lambda x: x[0])


# ── Date helpers ──────────────────────────────────────────────────────────────

def _to_api_date(s: str) -> str:
    """統一轉為 API 要求的 YYYY-MM-DD 格式。"""
    s = (s or "").strip().replace("/", "-").replace(".", "-")
    parts = s.split("-")
    if len(parts) == 3:
        try:
            return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        except ValueError:
            pass
    return s


# ── Core fetch ────────────────────────────────────────────────────────────────

def fetch_records(
    sess: requests.Session,
    code: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, str]]:
    """呼叫 /indexes/{code}/records API，回傳資料列 list。"""
    params = {"start": _to_api_date(start_date), "end": _to_api_date(end_date)}
    r = sess.get(f"{API_BASE}/indexes/{code}/records", params=params, timeout=60)
    r.raise_for_status()
    payload = r.json()

    if payload.get("empty", True) or not payload.get("data"):
        raise NoDataError(f"{code} 查無指定日期區間的歷史資料")

    labels: list[str]  = payload["data"].get("labels", [])
    datasets: list[dict] = payload["data"].get("datasets", [])

    if not labels:
        raise NoDataError(f"{code} 回傳空資料")

    vmap: dict[str, list] = {
        ds["value_type"]: ds["data"]
        for ds in datasets
        if "value_type" in ds
    }

    def val(vtype: str, i: int) -> str:
        lst = vmap.get(vtype, [])
        return str(lst[i]) if i < len(lst) else ""

    return [
        {
            "日期":       labels[i],
            "價格指數值": val("price",                i),
            "報酬指數值": val("return",               i),
            "漲跌點數":   val("volatility_points",    i),
            "漲跌百分比": val("volatility_percentage", i),
        }
        for i in range(len(labels))
    ]


# ── Public helpers ────────────────────────────────────────────────────────────

def scrape_one(
    code: str,
    start_date: str,
    end_date: str,
    out_path: Path,
) -> Path:
    """單一指數：下載並存為 CSV。"""
    sess = make_session()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = fetch_records(sess, code, start_date, end_date)

    try:
        idx_map = dict(list_all_indexes(sess))
        name = idx_map.get(code, code)
    except Exception:
        name = code

    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(COLUMNS))
        w.writeheader()
        for row in rows:
            w.writerow({"指數代碼": code, "指數名稱": name, **row})

    return out_path


def scrape_all_merged_csv(
    start_date: str,
    end_date: str,
    out_path: Path,
    *,
    limit: int | None = None,
    indexes: Iterable[tuple[str, str]] | None = None,
) -> Path:
    """
    逐一抓取所有指數歷史並合併為單一 CSV。
    每兩支指數之間隨機等待 0.3~0.8 秒（無需長延遲，API 不像瀏覽器那麼慢）。
    失敗自動重試最多 3 次（間隔 8s / 16s）。
    查無資料的指數直接跳過，不計入錯誤。
    """
    sess  = make_session()
    pairs = list(indexes) if indexes is not None else list_all_indexes(sess)
    if limit is not None:
        pairs = pairs[:limit]

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    n_ok = n_rows = 0
    total = len(pairs)

    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(COLUMNS))
        writer.writeheader()

        for i, (code, name) in enumerate(pairs):
            print(f"[{i + 1}/{total}] {code} {name}", flush=True)
            last_exc: Exception | None = None

            for attempt in range(3):
                if attempt > 0:
                    wait_s = 8 * attempt
                    print(f"  -> 重試 {attempt}/2，等待 {wait_s}s ...", flush=True)
                    time.sleep(wait_s)
                try:
                    rows = fetch_records(sess, code, start_date, end_date)
                    for row in rows:
                        writer.writerow({"指數代碼": code, "指數名稱": name, **row})
                    f.flush()
                    n_ok  += 1
                    n_rows += len(rows)
                    print(f"  -> 成功，+{len(rows)} 列", flush=True)
                    last_exc = None
                    break
                except NoDataError:
                    print("  -> 查無資料，跳過", flush=True)
                    last_exc = None
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    print(f"  -> 失敗（attempt {attempt + 1}）：{exc}", flush=True)

            if last_exc is not None:
                errors.append(f"{code} ({name}): {last_exc}")
                print("  -> 全部重試失敗，記錄錯誤", flush=True)

            if i + 1 < total:
                time.sleep(random.uniform(0.3, 0.8))

    if errors:
        err_path = out_path.with_suffix(".errors.txt")
        err_path.write_text("\n".join(errors), encoding="utf-8")
        print(f"有 {len(errors)} 筆指數失敗，詳情：{err_path.resolve()}")

    print(f"完成：成功 {n_ok}/{total}，合計 {n_rows} 列 -> {out_path.resolve()}", flush=True)
    return out_path


# ── Error retry helpers ───────────────────────────────────────────────────────

def _parse_error_codes(errors_path: Path) -> list[str]:
    """從 .errors.txt 解析失敗的指數代碼（格式：CODE (NAME): ...）。"""
    codes: list[str] = []
    for line in errors_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^([A-Za-z0-9]+)\s*\(", line.strip())
        if m:
            codes.append(m.group(1))
    return codes


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="TIP 指數歷史 CSV 下載（API 版，無需瀏覽器）")
    parser.add_argument("--all",  action="store_true", help="抓取全部指數")
    parser.add_argument("--code", default="",          help="單筆模式：指數代碼，例如 BC30")
    parser.add_argument("--start", default="2026/01/01", help="開始日期 YYYY/MM/DD")
    parser.add_argument("--end",   default="2026/05/15", help="結束日期 YYYY/MM/DD")

    date_grp = parser.add_mutually_exclusive_group()
    date_grp.add_argument("--today",     action="store_true", help="起訖日皆設為今天")
    date_grp.add_argument("--yesterday", action="store_true", help="起訖日皆設為昨天")

    parser.add_argument("-o", "--output", default="", help="輸出 CSV 路徑")
    parser.add_argument("--limit", type=int, default=0, help="僅處理前 N 支（測試用）")
    parser.add_argument(
        "--retry-errors",
        default="",
        metavar="ERRORS_TXT",
        help="讀取 .errors.txt 只重爬失敗的指數，需搭配 --start/--end",
    )
    args = parser.parse_args()

    if args.today:
        s = date.today().strftime("%Y/%m/%d")
        args.start = args.end = s
    elif args.yesterday:
        s = (date.today() - timedelta(days=1)).strftime("%Y/%m/%d")
        args.start = args.end = s

    lim = args.limit if args.limit > 0 else None

    # ── retry-errors mode ──
    if args.retry_errors:
        err_path = Path(args.retry_errors)
        if not err_path.is_file():
            raise SystemExit(f"找不到 errors 檔：{err_path}")
        codes = _parse_error_codes(err_path)
        if not codes:
            raise SystemExit("errors 檔中沒有可解析的指數代碼")
        sess    = make_session()
        all_map = dict(list_all_indexes(sess))
        indexes = [(c, all_map.get(c, c)) for c in codes]
        out = (
            Path(args.output)
            if args.output
            else Path("output") / f"retry_{err_path.stem}.csv"
        )
        print(f"重試 {len(indexes)} 支失敗指數 -> {out}")
        path = scrape_all_merged_csv(args.start, args.end, out, indexes=indexes)
        print(f"已儲存：{path.resolve()}")
        return

    # ── all mode ──
    if args.all:
        out = (
            Path(args.output)
            if args.output
            else Path("output") / "all_indexes_history.csv"
        )
        path = scrape_all_merged_csv(args.start, args.end, out, limit=lim)
        print(f"已合併儲存：{path.resolve()}")
        return

    # ── single mode ──
    code = args.code.strip()
    if not code:
        raise SystemExit("請指定 --code 或使用 --all")
    out = (
        Path(args.output)
        if args.output
        else Path("output") / f"{code}_history.csv"
    )
    path = scrape_one(code, args.start, args.end, out)
    print(f"已儲存：{path.resolve()}")


if __name__ == "__main__":
    main()
