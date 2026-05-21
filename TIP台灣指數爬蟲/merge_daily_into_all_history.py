"""
將單日合併 CSV（如 daily_YYYYMMDD.csv）併入 all_history.csv。
同一「指數代碼 + 日期」以日檔列覆寫主檔列；其餘主檔列保留。
日期會正規化為 YYYY/MM/DD 以利比對（支援 2026/4/2 與 2026/04/02）。
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


COLUMNS = (
    "指數代碼",
    "指數名稱",
    "日期",
    "價格指數值",
    "報酬指數值",
    "漲跌點數",
    "漲跌百分比",
)


def norm_date(s: str) -> str:
    s = (s or "").strip().replace("-", "/").replace(".", "/")
    parts = s.split("/")
    if len(parts) == 3:
        try:
            return f"{int(parts[0]):04d}/{int(parts[1]):02d}/{int(parts[2]):02d}"
        except ValueError:
            pass
    return s


def row_key(row: dict[str, str]) -> tuple[str, str]:
    return (row.get("指數代碼", "").strip(), norm_date(row.get("日期", "")))


def parse_csv(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    rows: list[dict[str, str]] = []
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames:
        for r in reader:
            if not r:
                continue
            rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(COLUMNS), extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})


def merge(daily_rows: list[dict[str, str]], base_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    by_key: dict[tuple[str, str], dict[str, str]] = {}
    for r in base_rows:
        k = row_key(r)
        if k[0]:
            by_key[k] = dict(r)
    for r in daily_rows:
        k = row_key(r)
        if k[0]:
            by_key[k] = {c: r.get(c, "") for c in COLUMNS}

    def sort_key(r: dict[str, str]) -> tuple[str, tuple[int, int, int]]:
        code = r.get("指數代碼", "")
        d = norm_date(r.get("日期", ""))
        parts = d.split("/")
        try:
            dt = (int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            dt = (0, 0, 0)
        return (code, (-dt[0], -dt[1], -dt[2]))

    return sorted(by_key.values(), key=sort_key)


def main() -> None:
    p = argparse.ArgumentParser(description="Merge daily TIP CSV into all_history.csv")
    p.add_argument("daily", type=Path, help="單日合併檔，例如 output/daily_20260402.csv")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("output") / "all_history.csv",
        help="主歷史檔路徑（預設 output/all_history.csv）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="只顯示將覆寫幾筆、合併後總列數，不寫檔",
    )
    args = p.parse_args()

    daily_path = args.daily
    out_path = args.output
    if not daily_path.is_file():
        raise SystemExit(f"找不到日檔：{daily_path.resolve()}")

    daily_rows = parse_csv(daily_path)
    base_rows = parse_csv(out_path) if out_path.is_file() else []

    daily_keys = {row_key(r) for r in daily_rows if row_key(r)[0]}
    overwritten = sum(1 for r in base_rows if row_key(r) in daily_keys)
    merged = merge(daily_rows, base_rows)

    print(f"日檔列數：{len(daily_rows)}")
    print(f"主檔原有列數：{len(base_rows)}")
    print(f"與日檔重疊（將以日檔覆寫）：{overwritten}")
    print(f"合併後總列數：{len(merged)}")

    if args.dry_run:
        print("(dry-run，未寫入)")
        return

    write_csv(out_path, merged)
    print(f"已寫入：{out_path.resolve()}")


if __name__ == "__main__":
    main()
