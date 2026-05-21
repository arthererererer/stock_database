"""
scripts/generate_report_a.py
議題 a：振幅分析研究報告產生器

執行：python scripts/generate_report_a.py
輸出：private/report_a.html

分析架構：
  1. 個股振幅大事件 — 後續報酬、超額報酬、持續性、成交量、股票特徵
  2. 個股振幅小事件 — 同上
  3. 注意股票期間 vs 非注意期間比較
  4. 市場整體振幅事件 — 指數表現
"""

import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

try:
    from scipy import stats as scipy_stats
    HAS_SCIPY = True
except (ImportError, OSError, AttributeError):
    scipy_stats = None
    HAS_SCIPY = False

try:
    import statsmodels.api as sm
    HAS_STATSMODELS = True
except (ImportError, OSError, AttributeError):
    sm = None
    HAS_STATSMODELS = False

# ── 路徑 ─────────────────────────────────────────────────────────────────────
BASE_DIR         = Path(__file__).resolve().parent.parent
STOCK_PRICE_DIR  = BASE_DIR / "All_Data" / "日資料" / "TEJ 股價資料庫"
CONSOLIDATED_CSV = BASE_DIR / "All_Data" / "事件資料" / "報告a_來源資料統合.csv"
OUTPUT_PATH      = BASE_DIR / "private" / "report_a.html"

# ── 參數 ─────────────────────────────────────────────────────────────────────
ROLLING_WINDOW   = 20
AMP_BIG_PCT      = 0.90
AMP_SML_PCT      = 0.10
PERSIST_HI_PCT   = 0.80
MARKET_HI_PCT    = 0.90
MARKET_LO_PCT    = 0.10
MIN_TRADING_DAYS = 252

INDEX_CODES = {"SC300", "TM100", "TWN50", "Y9999"}

LOAD_COLS = [
    "證券代碼", "年月日",
    "高低價差%", "報酬率％", "超額報酬(日)-大盤", "成交量(千股)",
    "市值(百萬元)", "本益比-TSE", "股價淨值比-TSE", "現金股利率", "CAPM_Beta 一年",
    "注意股票(A)", "處置股票(D)", "全額交割(Y)",
]
NUMERIC_COLS = [
    "高低價差%", "報酬率％", "超額報酬(日)-大盤", "成交量(千股)",
    "市值(百萬元)", "本益比-TSE", "股價淨值比-TSE", "現金股利率", "CAPM_Beta 一年",
]

# ── Plotly 暗色主題基礎 layout ────────────────────────────────────────────────
_BG      = "#0d1117"
_BG_CARD = "#161b22"
_BORDER  = "#30363d"
_TEXT    = "#e6edf3"
_MUTED   = "#8b949e"

def _base_layout(**kw):
    base = dict(
        paper_bgcolor=_BG, plot_bgcolor=_BG,
        font=dict(color=_TEXT, family="Noto Sans TC, system-ui"),
        xaxis=dict(gridcolor=_BORDER, linecolor=_BORDER, tickfont=dict(color=_MUTED)),
        yaxis=dict(gridcolor=_BORDER, linecolor=_BORDER, tickfont=dict(color=_MUTED)),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=_TEXT),
                    orientation="h", y=-0.22),
        margin=dict(t=40, r=20, b=70, l=60),
        hovermode="x unified",
        hoverlabel=dict(bgcolor=_BG_CARD, bordercolor=_BORDER, font=dict(color=_TEXT)),
    )
    for k, v in kw.items():
        if k in ("xaxis", "yaxis") and isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


# ════════════════════════════════════════════════════════════════════════
# 1. 資料載入
# ════════════════════════════════════════════════════════════════════════

def _load_from_consolidated() -> pd.DataFrame | None:
    """若統合 CSV 存在，則讀取（單檔、已預處理，較快）。"""
    if not CONSOLIDATED_CSV.exists():
        return None
    raw = pd.read_csv(CONSOLIDATED_CSV, encoding="utf-8-sig")
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw = raw.dropna(subset=["date"])
    raw = raw.sort_values(["stock_code", "date"]).reset_index(drop=True)
    return raw


def _load_from_source() -> pd.DataFrame:
    """從 TEJ 多個 CSV 讀取並合併（原始流程）。"""
    csvs = sorted(STOCK_PRICE_DIR.glob("*.csv"))
    if not csvs:
        raise FileNotFoundError(f"找不到 CSV：{STOCK_PRICE_DIR}")

    dfs = []
    for f in csvs:
        try:
            df = pd.read_csv(
                f, encoding="utf-16", sep="\t", dtype=str,
                usecols=lambda c: c in LOAD_COLS,
            )
            df["_src"] = f.name
            dfs.append(df)
        except Exception as e:
            print(f"  跳過 {f.name}: {e}", file=sys.stderr)

    raw = pd.concat(dfs, ignore_index=True)
    raw["證券代碼"] = raw["證券代碼"].astype(str).str.strip()
    raw["年月日"] = raw["年月日"].astype(str).str.strip()
    raw.sort_values("_src", inplace=True)
    raw.drop_duplicates(subset=["證券代碼", "年月日"], keep="last", inplace=True)
    raw.drop(columns=["_src"], inplace=True)

    for col in NUMERIC_COLS:
        if col in raw.columns:
            raw[col] = pd.to_numeric(
                raw[col].astype(str).str.replace(",", "", regex=False).str.strip(),
                errors="coerce",
            )

    raw["date"] = pd.to_datetime(raw["年月日"], format="%Y%m%d", errors="coerce")
    raw["stock_code"] = raw["證券代碼"].str.split().str[0]
    raw = raw.dropna(subset=["date"])
    raw.sort_values(["stock_code", "date"], inplace=True)
    raw.reset_index(drop=True, inplace=True)

    return raw


def load_data(force_source: bool = False) -> pd.DataFrame:
    """載入股價資料。優先使用統合 CSV（若存在且未強制從來源讀取）。"""
    print("[1/6] 載入股價資料...")
    if not force_source:
        raw = _load_from_consolidated()
        if raw is not None:
            n_codes = raw["stock_code"].nunique()
            print(f"  共 {len(raw):,} 筆，{n_codes:,} 個代碼（含指數，來自統合 CSV）")
            return raw

    raw = _load_from_source()
    n_codes = raw["stock_code"].nunique()
    print(f"  共 {len(raw):,} 筆，{n_codes:,} 個代碼（含指數）")
    return raw


# ════════════════════════════════════════════════════════════════════════
# 2. 共用篩選
# ════════════════════════════════════════════════════════════════════════

def apply_filters(df: pd.DataFrame):
    print("[2/6] 套用共用篩選...")

    is_idx    = df["stock_code"].isin(INDEX_CODES)
    idx_df    = df[is_idx].copy()
    stock_df  = df[~is_idx].copy()

    # 規則1：排除曾被全額交割的股票
    fy_stocks = set(
        stock_df[stock_df["全額交割(Y)"].astype(str).str.strip() == "Y"]["stock_code"]
    )
    stock_df = stock_df[~stock_df["stock_code"].isin(fy_stocks)]

    # 規則2：排除處置期間紀錄
    disp = stock_df["處置股票(D)"].astype(str).str.strip() == "D"
    stock_df = stock_df[~disp].copy()

    # 規則3：注意股票標記（保留但標記，用於分組）
    stock_df["is_attention"] = (
        stock_df["注意股票(A)"].astype(str).str.strip() == "A"
    ).astype(int)

    # 規則4：排除上市未滿 252 交易日的個股
    trade_cnt  = stock_df.groupby("stock_code").size()
    qualified  = set(trade_cnt[trade_cnt >= MIN_TRADING_DAYS].index)
    stock_df   = stock_df[stock_df["stock_code"].isin(qualified)]

    # 規則5：排除成交量為零
    stock_df = stock_df[stock_df["成交量(千股)"].fillna(0) > 0].copy()

    print(f"  個股：{stock_df['stock_code'].nunique():,} 檔，"
          f"{len(stock_df):,} 筆；指數：{idx_df['stock_code'].nunique()} 個")
    return stock_df.reset_index(drop=True), idx_df.reset_index(drop=True)


# ════════════════════════════════════════════════════════════════════════
# 3. 計算事件與後續指標（每檔股票向量化）
# ════════════════════════════════════════════════════════════════════════

def calc_events_and_windows(df: pd.DataFrame, idx_df: pd.DataFrame) -> pd.DataFrame:
    print("[3/6] 計算振幅事件與後續視窗...")

    # 取得大盤（Y9999 加權指數）日報酬，用於正確計算累積超額報酬
    mkt = idx_df[idx_df["stock_code"] == "Y9999"][["date", "報酬率％"]].copy()
    mkt = mkt.rename(columns={"報酬率％": "mkt_ret"})
    mkt["mkt_ret"] = pd.to_numeric(mkt["mkt_ret"], errors="coerce").fillna(0) / 100
    mkt = mkt.drop_duplicates("date")
    mkt_map = mkt.set_index("date")["mkt_ret"].to_dict()
    df = df.copy()
    df["mkt_ret"] = df["date"].map(mkt_map).fillna(0)

    results = []
    stocks = df["stock_code"].unique()

    for i, code in enumerate(stocks):
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(stocks)}...")

        g = df[df["stock_code"] == code].sort_values("date").reset_index(drop=True)
        n = len(g)

        amp = g["高低價差%"].values
        ret = g["報酬率％"].fillna(0).values / 100
        mkt_ret = g["mkt_ret"].values
        vol = g["成交量(千股)"].fillna(0).values

        # ── 振幅事件（方案B：前20日不含當日）────────────────────────────
        amp_s = pd.Series(amp)
        shifted = amp_s.shift(1)
        roll_90  = shifted.rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW).quantile(AMP_BIG_PCT).values
        roll_10  = shifted.rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW).quantile(AMP_SML_PCT).values
        roll_mean_amp = shifted.rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW).mean().values

        g["amp_big"]      = ((amp > roll_90) & ~np.isnan(roll_90)).astype(int)
        g["amp_sml"]      = ((amp < roll_10) & ~np.isnan(roll_10)).astype(int)
        g["roll90_amp"]   = roll_90
        g["roll10_amp"]   = roll_10
        g["abnormal_amp"] = np.where(roll_mean_amp > 0, amp / roll_mean_amp - 1, np.nan)

        # 異常成交量
        vol_s = pd.Series(vol)
        vol_shifted   = vol_s.shift(1)
        roll_mean_vol = vol_shifted.rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW).mean().values
        g["abnormal_vol"] = np.where(roll_mean_vol > 0, vol / roll_mean_vol - 1, np.nan)

        # ── 後續累積報酬（T日收盤買進、T+h日收盤賣出）────────────────────
        # 報酬 = 從 T+1 至 T+h 日之累積報酬（共 h 日）
        log_ret   = np.log1p(ret)
        log_mkt   = np.log1p(mkt_ret)
        cumlog    = np.cumsum(log_ret)
        cumlog_mkt = np.cumsum(log_mkt)

        for h in (1, 5, 20):
            fwd = np.full(n, np.nan)
            fex = np.full(n, np.nan)
            if n > h + 1:
                # 買進：T日收盤；賣出：T+h日收盤。報酬 = cumlog[T+h+1]-cumlog[T+1]
                fwd[:n-h-1] = np.expm1(cumlog[h+1:n] - cumlog[1:n-h])
                R_s = np.expm1(cumlog[h+1:n] - cumlog[1:n-h])
                R_m = np.expm1(cumlog_mkt[h+1:n] - cumlog_mkt[1:n-h])
                fex[:n-h-1] = np.where(R_m != -1, (1 + R_s) / (1 + R_m) - 1, np.nan)
            g[f"fwd_ret_{h}"]  = fwd
            g[f"fwd_exc_{h}"]  = fex

        # ── 持續性積分分數（後20日異常振幅/成交量之和）──────────────────
        ab_amp_f = np.nan_to_num(g["abnormal_amp"].values)
        ab_vol_f = np.nan_to_num(g["abnormal_vol"].values)
        cum_aa   = np.cumsum(ab_amp_f)
        cum_av   = np.cumsum(ab_vol_f)

        ps_amp = np.full(n, np.nan)
        ps_vol = np.full(n, np.nan)
        if n > ROLLING_WINDOW:
            ps_amp[:n-ROLLING_WINDOW] = cum_aa[ROLLING_WINDOW:] - cum_aa[:n-ROLLING_WINDOW]
            ps_vol[:n-ROLLING_WINDOW] = cum_av[ROLLING_WINDOW:] - cum_av[:n-ROLLING_WINDOW]
        g["persist_amp"] = ps_amp
        g["persist_vol"] = ps_vol

        # ── T~T+20 累積積分序列（供 1.3 積分演化圖使用）────────────────────
        # cum_amp_k = Σ 異常振幅(T+j), j=1..k；cum_amp_0=0
        for k in range(21):
            col = f"cum_amp_{k}"
            vals = np.full(n, np.nan)
            if k == 0:
                vals[:] = 0.0
            elif n > k:
                vals[:n - k] = cum_aa[k:n] - cum_aa[:n - k]
            g[col] = vals

        # ── T~T+20 累積報酬序列（供 1.3 累積報酬演化圖使用）────────────────
        # cum_ret_k = 持有 T+1 至 T+k 的累積報酬；cum_ret_0=0
        for k in range(21):
            col = f"cum_ret_{k}"
            vals = np.full(n, np.nan)
            if k == 0:
                vals[:] = 0.0
            elif n > k:
                vals[:n - k] = np.expm1(cumlog[k:n] - cumlog[:n - k])
            g[col] = vals

        # ── T~T+20 累積超額報酬序列（供 1.3 累積超額報酬演化圖使用）────────────────
        # cum_exc_k = (1+R_s)/(1+R_m)−1，R_s/R_m 為個股/大盤 T+1 至 T+k 累積報酬
        for k in range(21):
            col = f"cum_exc_{k}"
            vals = np.full(n, np.nan)
            if k == 0:
                vals[:] = 0.0
            elif n > k:
                R_s = np.expm1(cumlog[k:n] - cumlog[:n - k])
                R_m = np.expm1(cumlog_mkt[k:n] - cumlog_mkt[:n - k])
                vals[:n - k] = np.where(R_m != -1, (1 + R_s) / (1 + R_m) - 1, np.nan)
            g[col] = vals

        # ── 最大回撤（T 日收盤進場，持有至 T+20：觀察 T+1~T+20 路徑）────
        mdd = np.full(n, np.nan)
        limit = n - (ROLLING_WINDOW + 1)  # 需有 T+21 日資料
        if limit > 0:
            idx_arr = np.arange(limit)
            # 路徑：close T(=0), close T+1..close T+20，共 21 點
            offsets    = np.arange(1, ROLLING_WINDOW + 2)
            idx_matrix = idx_arr[:, None] + offsets          # (limit, 21)
            cl_matrix  = cumlog[idx_matrix]                  # (limit, 21)
            ref        = cumlog[idx_arr + 1][:, None]       # 起點 = close T
            paths      = np.expm1(cl_matrix - ref)           # 累積報酬路徑
            peaks      = np.maximum.accumulate(paths, axis=1)
            drawdowns  = paths - peaks                       # negative
            mdd[:limit] = drawdowns.min(axis=1)
        g["mdd_20"] = mdd

        # ── 完整弧形事件（Hump）：T+1 >= T 且 T+20 < T+1 ──────────────
        hump = np.zeros(n, dtype=int)
        limit2 = n - ROLLING_WINDOW
        if limit2 > 0 and not np.all(np.isnan(amp)):
            a1  = np.roll(amp, -1)   # amp at T+1
            a20 = np.roll(amp, -20)  # amp at T+20
            valid = np.arange(n) < limit2
            hump = ((a1 >= amp) & (a20 < a1) & valid &
                    ~np.isnan(amp) & ~np.isnan(a1) & ~np.isnan(a20)).astype(int)
        g["hump_event"] = hump

        results.append(g)

    out = pd.concat(results, ignore_index=True)
    out = out.drop(columns=["mkt_ret"], errors="ignore")
    print(f"  振幅大事件：{out['amp_big'].sum():,} 筆")
    print(f"  振幅小事件：{out['amp_sml'].sum():,} 筆")
    return out


def calc_stock_persist_prob(stock_df: pd.DataFrame) -> pd.DataFrame:
    """
    計算每檔股票 P(高持續性 | 振幅大事件)，使用該股過去振幅大事件中高持續性比例。
    避免前視偏誤：對 T 日事件，僅用 T 日之前之歷史。
    輸出：
      stock_code, stock_persist_prob（該股最新估計值）
      stock_persist_hi_n：用於估計之最後一次「歷史振幅大事件」中，高持續性事件筆數
      stock_persist_amp_n：同上段歷史之振幅大事件總次數（分母，≥5 才有機率）
    """
    cols = ["stock_code", "stock_persist_prob", "stock_persist_hi_n", "stock_persist_amp_n"]
    evt = stock_df[stock_df["amp_big"] == 1].copy()
    if len(evt) < 10:
        return pd.DataFrame(columns=cols)

    p80 = evt["persist_amp"].quantile(PERSIST_HI_PCT)
    evt["high_persist"] = (evt["persist_amp"] >= p80).astype(int)

    rows = []
    for code in evt["stock_code"].unique():
        sub = evt[evt["stock_code"] == code].sort_values("date").reset_index(drop=True)
        probs = []
        for i in range(len(sub)):
            prior = sub.iloc[:i]
            if len(prior) < 5:
                probs.append(np.nan)
            else:
                probs.append(prior["high_persist"].mean())
        sub["stock_persist_prob"] = probs
        last = sub.iloc[-1]
        if not np.isnan(last["stock_persist_prob"]):
            prior = sub.iloc[:-1]
            rows.append({
                "stock_code": code,
                "stock_persist_prob": round(last["stock_persist_prob"], 4),
                "stock_persist_hi_n": int(prior["high_persist"].sum()),
                "stock_persist_amp_n": int(len(prior)),
            })

    return pd.DataFrame(rows)


# ════════════════════════════════════════════════════════════════════════
# 4. 計算市場整體每日振幅大比例
# ════════════════════════════════════════════════════════════════════════

def calc_market_amplitude(df: pd.DataFrame) -> pd.DataFrame:
    """每日：振幅大／小個股比例（針對完成事件計算後的 stock_df）。"""
    agg = df.groupby("date").agg(
        amp_big_cnt=("amp_big", "sum"),
        amp_sml_cnt=("amp_sml", "sum"),
        total_cnt=("amp_big", "count"),
    ).reset_index()
    agg["amp_big_pct"] = agg["amp_big_cnt"] / agg["total_cnt"]
    agg["amp_sml_pct"] = agg["amp_sml_cnt"] / agg["total_cnt"]

    # 市場振幅偏多/偏少（對振幅大比例序列計算 rolling 百分位）
    pct_s = agg["amp_big_pct"]
    roll_s = pct_s.rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW)
    agg["mkt_hi90"] = roll_s.quantile(MARKET_HI_PCT)
    agg["mkt_lo10"] = roll_s.quantile(MARKET_LO_PCT)
    agg["mkt_amp_hi"] = (pct_s > agg["mkt_hi90"]).astype(int)
    agg["mkt_amp_lo"] = (pct_s < agg["mkt_lo10"]).astype(int)

    # 振幅小比例之 rolling 百分位（供圖表對稱呈現）
    pct_sml = agg["amp_sml_pct"]
    roll_sml = pct_sml.rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW)
    agg["mkt_sml_hi90"] = roll_sml.quantile(MARKET_HI_PCT)
    agg["mkt_sml_lo10"] = roll_sml.quantile(MARKET_LO_PCT)
    return agg


# ════════════════════════════════════════════════════════════════════════
# 5. 統計計算工具
# ════════════════════════════════════════════════════════════════════════

def _desc_stats(series: pd.Series, pct_scale=True) -> dict:
    """計算描述統計（報酬率自動 × 100 顯示為 %）。"""
    s = series.dropna()
    if len(s) == 0:
        return {}
    factor = 100 if pct_scale else 1
    return {
        "N":     len(s),
        "Mean":  round(s.mean() * factor, 3),
        "Median": round(s.median() * factor, 3),
        "Std":   round(s.std() * factor, 3),
        "Skew":  round(s.skew(), 3),
        "Kurt":  round(s.kurt(), 3),
        "P10":   round(s.quantile(0.10) * factor, 3),
        "P25":   round(s.quantile(0.25) * factor, 3),
        "P75":   round(s.quantile(0.75) * factor, 3),
        "P90":   round(s.quantile(0.90) * factor, 3),
        "WinRate": f"{(s > 0).mean()*100:.1f}%",
    }


def _stats_table_html(stats_dict: dict, label_map=None) -> str:
    """將 {horizon: stats} 轉成 HTML 表格。"""
    if not stats_dict:
        return "<p class='no-data'>無足夠資料</p>"
    rows = ""
    for col, d in stats_dict.items():
        label = label_map.get(col, col) if label_map else col
        cells = "".join(f"<td>{d.get(k, '—')}</td>" for k in
                        ["N", "Mean", "Median", "Std", "Skew", "Kurt",
                         "P10", "P25", "P75", "P90", "WinRate"])
        rows += f"<tr><td><b>{label}</b></td>{cells}</tr>"
    headers = "".join(f"<th>{h}</th>" for h in
                      ["", "N", "Mean%", "Median%", "Std%", "偏態", "峰態",
                       "P10%", "P25%", "P75%", "P90%", "勝率"])
    return f"""<div class='tbl-wrap'><table class='stat-tbl'>
        <thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table></div>"""


def _three_group_compare_chart_and_table(events_df: pd.DataFrame, char_col: str, ret_col: str, label: str) -> str:
    """依特徵百分位數分高三組：>P75、P25~P75、<P25，箱型圖（不含內嵌統計） + 圖下統計表。"""
    sub = events_df[[char_col, ret_col]].dropna()
    if len(sub) < 30:
        return f"<p class='no-data'>{label}：樣本不足</p>"
    p25 = sub[char_col].quantile(0.25)
    p75 = sub[char_col].quantile(0.75)
    hi_ret   = sub[sub[char_col] >  p75][ret_col]   # 高
    mid_ret  = sub[(sub[char_col] >= p25) & (sub[char_col] <= p75)][ret_col]  # 中
    lo_ret   = sub[sub[char_col] <  p25][ret_col]   # 低

    fig = go.Figure()
    fig.add_trace(go.Box(y=hi_ret.values * 100, name=f"高{label}（>P75）", marker_color="#58a6ff",
                         boxpoints=False, boxmean=False))
    fig.add_trace(go.Box(y=mid_ret.values * 100, name=f"中{label}（P25~P75）", marker_color="#8b949e",
                         boxpoints=False, boxmean=False))
    fig.add_trace(go.Box(y=lo_ret.values * 100, name=f"低{label}（<P25）", marker_color="#f85149",
                         boxpoints=False, boxmean=False))
    fig.update_layout(**_base_layout(
        title=dict(text=f"依 {label} 分組的後續報酬（T+20）", font=dict(size=13, color=_TEXT)),
        height=320, yaxis=dict(title="累積報酬%", ticksuffix="%"),
    ))
    chart_html = fig.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True})

    stats = {
        f"高{label}（>P75）": _desc_stats(hi_ret),
        f"中{label}（P25~P75）": _desc_stats(mid_ret),
        f"低{label}（&lt;P25）": _desc_stats(lo_ret),
    }
    tbl = _stats_table_html(stats)
    return f"<h4 style='margin:12px 0 8px; font-size:.9rem;'>依 {label} 分組（&gt;P75=高、P25~P75=中、&lt;P25=低）</h4><div class='chart-wrap' style='min-height:320px;'>{chart_html}</div>{tbl}"


# ════════════════════════════════════════════════════════════════════════
# 6. 圖表產生
# ════════════════════════════════════════════════════════════════════════

def _hist_3panel(events: pd.DataFrame, cols: list, title: str, xlabel: str) -> str:
    """3 個 horizon 的報酬率直方圖（subplot）。"""
    labels = {"fwd_ret_1": "T+1", "fwd_ret_5": "T+5", "fwd_ret_20": "T+20",
              "fwd_exc_1": "T+1", "fwd_exc_5": "T+5", "fwd_exc_20": "T+20"}
    colors = ["#58a6ff", "#3fb950", "#d29922"]

    fig = make_subplots(rows=1, cols=3,
                        subplot_titles=[labels.get(c, c) for c in cols],
                        horizontal_spacing=0.06)
    for i, col in enumerate(cols, 1):
        s = events[col].dropna() * 100
        if len(s) == 0:
            continue
        fig.add_trace(go.Histogram(
            x=s, name=labels.get(col, col),
            marker_color=colors[i-1], opacity=0.75,
            nbinsx=60,
            hovertemplate="%{x:.2f}%<br>count: %{y}<extra></extra>",
        ), row=1, col=i)
        # 加入 0 基準線
        fig.add_vline(x=0, line_width=1, line_dash="dash",
                      line_color="#6e7681", row=1, col=i)
        # 標注均值
        mean_v = s.mean()
        fig.add_vline(x=mean_v, line_width=1.5, line_color="#e3b341", row=1, col=i)

    fig.update_layout(**_base_layout(
        title=dict(text=title, font=dict(size=14, color=_TEXT)),
        height=380, showlegend=False,
    ))
    fig.update_xaxes(ticksuffix="%")
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True})


def _evolution_subplot_body(
    events_sub: pd.DataFrame, value_cols: list, pct_scale: bool,
) -> tuple[list, list, list] | None:
    """回傳 (med, p25, p75) 已乘上 pct 因子；資料無效則 None。"""
    missing = [c for c in value_cols if c not in events_sub.columns]
    if missing:
        return None
    sub = events_sub[value_cols].dropna(how="all")
    if len(sub) < 5:
        return None
    med = [sub[c].median() for c in value_cols]
    p25 = [sub[c].quantile(0.25) for c in value_cols]
    p75 = [sub[c].quantile(0.75) for c in value_cols]
    factor = 100 if pct_scale else 1
    med = [v * factor for v in med]
    p25 = [v * factor for v in p25]
    p75 = [v * factor for v in p75]
    return med, p25, p75


def _evolution_chart_pair(
    events_left: pd.DataFrame,
    events_right: pd.DataFrame,
    value_cols: list,
    title_left: str,
    title_right: str,
    color_left: str,
    color_right: str,
    ylabel: str,
    pct_scale: bool = False,
) -> go.Figure:
    """兩組事件並排之 T~T+20 演化圖（各子圖：中位數 + P25~P75 灰階面積），共用同一列版面。"""
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=[title_left, title_right],
        horizontal_spacing=0.06,
    )
    bodies = [
        _evolution_subplot_body(events_left, value_cols, pct_scale),
        _evolution_subplot_body(events_right, value_cols, pct_scale),
    ]
    x = list(range(21))
    tickvals = list(range(0, 21, 2))
    ticktext = [f"T+{k}" if k > 0 else "T" for k in range(0, 21, 2)]

    for col_idx, (body, color, med_name) in enumerate(
        zip(bodies, [color_left, color_right], ["高持續性·中位數", "一般·中位數"], strict=True),
        start=1,
    ):
        if body is None:
            fig.add_annotation(
                text="樣本不足或缺少欄位",
                x=10, y=0, showarrow=False,
                row=1, col=col_idx,
                font=dict(color=_MUTED, size=12),
            )
            continue
        med, p25, p75 = body
        show_band = col_idx == 1
        fig.add_trace(
            go.Scatter(
                x=x, y=p25, mode="lines", name="P25",
                line=dict(color="rgba(128,128,128,0.5)", width=1, dash="dot"), fill=None,
                legendgroup="p25", showlegend=show_band,
            ),
            row=1, col=col_idx,
        )
        fig.add_trace(
            go.Scatter(
                x=x, y=p75, mode="lines", name="P75",
                line=dict(color="rgba(128,128,128,0.5)", width=1, dash="dot"),
                fill="tonexty", fillcolor="rgba(128,128,128,0.25)",
                legendgroup="p75", showlegend=show_band,
            ),
            row=1, col=col_idx,
        )
        fig.add_trace(
            go.Scatter(
                x=x, y=med, mode="lines+markers", name=med_name,
                line=dict(color=color, width=2.5), marker=dict(size=5, color=color),
                legendgroup=f"med{col_idx}", showlegend=True,
            ),
            row=1, col=col_idx,
        )

    fig.update_layout(
        **_base_layout(
            height=340,
            showlegend=True,
            legend=dict(orientation="h", yanchor="top", y=-0.14, x=0.5, xanchor="center"),
            margin=dict(t=56, r=16, b=72, l=52),
        )
    )
    # make_subplots 會產生 xaxis / xaxis2、yaxis / yaxis2；僅對 layout.xaxis 設樣式不會套用到第二子圖，
    # 第二圖易残留預設白格線。以下不含 row/col，一次更新「全部」X／Y 軸。
    _x_style = dict(
        title_text="交易日",
        tickvals=tickvals,
        ticktext=ticktext,
        showgrid=True,
        gridwidth=1,
        gridcolor=_BORDER,
        showline=True,
        linewidth=1,
        linecolor=_BORDER,
        mirror=False,
        tickfont=dict(color=_MUTED),
        zeroline=True,
        zerolinewidth=1,
        zerolinecolor=_BORDER,
    )
    _y_style = dict(
        title_text=ylabel,
        ticksuffix="%" if pct_scale else "",
        showgrid=True,
        gridwidth=1,
        gridcolor=_BORDER,
        showline=True,
        linewidth=1,
        linecolor=_BORDER,
        mirror=False,
        tickfont=dict(color=_MUTED),
        zeroline=True,
        zerolinewidth=1,
        zerolinecolor=_BORDER,
    )
    fig.update_xaxes(**_x_style)
    fig.update_yaxes(**_y_style)
    # 百分比類：維持與單圖時相同之 y=0 虛線參考（zeroline 為實線，改以 hline 標示）
    if pct_scale:
        fig.update_yaxes(zeroline=False)
        fig.add_hline(y=0, line_width=1, line_dash="dash", line_color="#6e7681", row=1, col=1)
        fig.add_hline(y=0, line_width=1, line_dash="dash", line_color="#6e7681", row=1, col=2)
    return fig


def _persist_descriptive_stats(hi_evt: pd.DataFrame, lo_evt: pd.DataFrame, flag_col: str) -> str:
    """高 vs 一般持續性：特徵敘述統計比較（市值、Beta、注意股、事件強度）。Mann-Whitney U 檢定。"""
    FEATURES = [
        ("市值(百萬元)", "市值(百萬)", "num", lambda df: df["市值(百萬元)"]),
        ("CAPM_Beta 一年", "CAPM Beta", "num", lambda df: df["CAPM_Beta 一年"].replace(0, np.nan)),
        ("is_attention", "注意股占比", "pct", lambda df: df["is_attention"].fillna(0)),
        ("event_strength", "事件強度", "num", lambda df: df["event_strength"]),
    ]
    rows = []
    for col, label, fmt, getter in FEATURES:
        h = getter(hi_evt).dropna()
        l = getter(lo_evt).dropna()
        if len(h) < 5 or len(l) < 5:
            rows.append(f"<tr><td>{label}</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>")
            continue
        if fmt == "pct":
            mean_hi, med_hi = h.mean() * 100, h.median() * 100
            mean_lo, med_lo = l.mean() * 100, l.median() * 100
        else:
            mean_hi, med_hi = h.mean(), h.median()
            mean_lo, med_lo = l.mean(), l.median()
        try:
            if HAS_SCIPY and scipy_stats is not None:
                _, p_val = scipy_stats.mannwhitneyu(h, l, alternative="two-sided")
                sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else ""
            else:
                p_val, sig = np.nan, ""
        except Exception:
            p_val, sig = np.nan, ""
        f = ".2f" if fmt == "num" and (abs(mean_hi) < 1e6) else ".2e"
        p_str = "—" if (p_val is None or (isinstance(p_val, float) and np.isnan(p_val))) else f"{p_val:.4f}{sig}"
        rows.append(
            f"<tr><td>{label}</td>"
            f"<td>{mean_hi:{f}}</td><td>{med_hi:{f}}</td>"
            f"<td>{mean_lo:{f}}</td><td>{med_lo:{f}}</td>"
            f"<td>{p_str}</td></tr>"
        )
    p_note = "Mann-Whitney U 雙尾檢定：* p&lt;0.05, ** p&lt;0.01, *** p&lt;0.001。" if HAS_SCIPY else "（scipy 無法載入，p 值省略；請確認 NumPy/scipy 環境相容性。）"
    return f"""
<p class='rpt-note' style='margin:12px 0 8px;'>比較高持續性與一般事件之 T 日特徵。事件強度：振幅大=(高低價差%−P90)/P90；振幅小=(P10−高低價差%)/P10。{p_note}</p>
<div class='tbl-wrap'><table class='stat-tbl'>
<thead><tr><th>特徵</th><th colspan='2'>高持續性</th><th colspan='2'>一般</th><th>p值</th></tr>
<tr><th></th><th>Mean</th><th>Median</th><th>Mean</th><th>Median</th><th></th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>"""


def _persist_logit_model(events: pd.DataFrame, score_col: str, threshold: float, flag_col: str) -> str:
    """以 T 日特徵預測高持續性：Logit 迴歸。y=high_persist, X=log(1+市值)、Beta、注意股、事件強度。"""
    if not HAS_STATSMODELS:
        return "<p class='no-data'>需安裝 statsmodels 才能顯示 Logit 迴歸結果：<code>pip install statsmodels</code></p>"
    events = events.copy()
    events["event_strength"] = np.where(
        flag_col == "amp_big",
        np.where(events["roll90_amp"] > 0, (events["高低價差%"] - events["roll90_amp"]) / events["roll90_amp"], np.nan),
        np.where(events["roll10_amp"] > 0, (events["roll10_amp"] - events["高低價差%"]) / events["roll10_amp"], np.nan),
    )
    events["high_persist"] = (events[score_col] >= threshold).astype(int)
    events["log_mcap"] = np.log1p(events["市值(百萬元)"].fillna(0).clip(lower=0))
    X_cols = ["log_mcap", "CAPM_Beta 一年", "is_attention", "event_strength"]
    X = events[X_cols].copy()
    X["is_attention"] = X["is_attention"].fillna(0)
    X["CAPM_Beta 一年"] = X["CAPM_Beta 一年"].replace(0, np.nan)
    y = events["high_persist"]
    valid = X.notna().all(axis=1) & y.notna()
    X = sm.add_constant(X.loc[valid].reset_index(drop=True))
    y = y.loc[valid].reset_index(drop=True)
    if len(y) < 50 or y.nunique() < 2:
        return "<p class='no-data'>樣本不足或無變異，無法估計 Logit 模型。</p>"
    try:
        model = sm.Logit(y, X).fit(disp=0)
    except Exception as e:
        return f"<p class='no-data'>Logit 估計失敗：{str(e)[:80]}</p>"
    rows = []
    for name in model.params.index:
        coef = model.params[name]
        se = model.bse[name]
        z = model.tvalues[name]
        p = model.pvalues[name]
        ci_lo, ci_hi = model.conf_int().loc[name, 0], model.conf_int().loc[name, 1]
        sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
        rows.append(f"<tr><td>{name}</td><td>{coef:.4f}</td><td>{se:.4f}</td><td>{z:.3f}</td><td>{p:.4f}{sig}</td><td>[{ci_lo:.4f}, {ci_hi:.4f}]</td></tr>")
    pseudo_r2 = model.prsquared if hasattr(model, "prsquared") else getattr(model, "prsquared", "—")
    pseudo_r2_str = f"{pseudo_r2:.4f}" if isinstance(pseudo_r2, (int, float)) else str(pseudo_r2)
    return f"""
<p class='rpt-note' style='margin:12px 0 8px;'><b>因變數</b>：高持續性=1（積分≥P80），非報酬。本模型預測「事件是否具高持續性」，非預測報酬。自變數：log(1+市值)、CAPM Beta、注意股(0/1)、事件強度。N={len(y):,}。</p>
<div class='tbl-wrap'><table class='stat-tbl'>
<thead><tr><th>變數</th><th>係數</th><th>Std Err</th><th>z</th><th>P&gt;|z|</th><th>95% CI</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<p style='font-size:.85rem; color:var(--muted);'>Pseudo R² (McFadden): {pseudo_r2_str}</p>"""


def _persist_score_section(events: pd.DataFrame, score_col: str, hi_pct: float, n_total_events: int,
                          event_type_label: str = "振幅大事件", flag_col: str = "amp_big") -> str:
    """1.3 / 2.3 振幅持續性積分分析：高 vs 一般之 T~T+20 演化以左右並列子圖呈現（積分／報酬／超額報酬各一圖）+ T+20 箱型圖。"""
    s = events[score_col].dropna()
    if len(s) < 10:
        return "<p class='no-data'>樣本不足</p>"

    # 計算 T 日事件強度（供敘述統計與 Logit 使用）
    events = events.copy()
    if flag_col == "amp_big":
        events["event_strength"] = np.where(
            events["roll90_amp"].fillna(0) > 0,
            (events["高低價差%"] - events["roll90_amp"]) / events["roll90_amp"],
            np.nan,
        )
    else:
        events["event_strength"] = np.where(
            events["roll10_amp"].fillna(0) > 0,
            (events["roll10_amp"] - events["高低價差%"]) / events["roll10_amp"],
            np.nan,
        )

    threshold = s.quantile(hi_pct)
    hi_evt = events[events[score_col] >= threshold]
    lo_evt = events[events[score_col] < threshold]
    # 1.3/2.3 改為比較 T+20 超額累積報酬（vs 大盤），較具相對績效意義
    hi_ret = hi_evt["fwd_exc_20"].dropna()
    lo_ret = lo_evt["fwd_exc_20"].dropna()
    n_hi = len(hi_ret)
    n_lo = len(lo_ret)

    cols_amp = [f"cum_amp_{k}" for k in range(21)]
    cols_ret = [f"cum_ret_{k}" for k in range(21)]
    cols_exc = [f"cum_exc_{k}" for k in range(21)]
    sub_hi = f"高持續性事件（≥P{int(hi_pct*100)}，共 {n_hi:,} 件）"
    sub_lo = f"一般事件（<P{int(hi_pct*100)}，共 {n_lo:,} 件）"
    fig_amp_pair = _evolution_chart_pair(
        hi_evt, lo_evt, cols_amp, sub_hi, sub_lo, "#d29922", "#8b949e", "累積積分", False,
    )
    fig_cum_pair = _evolution_chart_pair(
        hi_evt, lo_evt, cols_ret, sub_hi, sub_lo, "#d29922", "#8b949e", "累積報酬%", True,
    )
    fig_exc_pair = _evolution_chart_pair(
        hi_evt, lo_evt, cols_exc, sub_hi, sub_lo, "#d29922", "#8b949e", "累積超額報酬%", True,
    )
    # 高持續性 vs 一般事件 T+20 超額累積報酬箱型圖
    fig_box = go.Figure()
    fig_box.add_trace(go.Box(y=hi_ret.values * 100, name="高持續性", marker_color="#d29922",
                             boxpoints=False, boxmean=False))
    fig_box.add_trace(go.Box(y=lo_ret.values * 100, name="一般", marker_color="#8b949e",
                             boxpoints=False, boxmean=False))
    fig_box.update_layout(
        **_base_layout(
            title=dict(text="高持續性 vs 一般事件後續超額報酬（T+20）", font=dict(size=13, color=_TEXT)),
            height=320,
            yaxis=dict(title="累積超額報酬%", ticksuffix="%"),
        )
    )

    stats = {"高持續性": _desc_stats(hi_ret), "一般事件": _desc_stats(lo_ret)}
    tbl_html = "<p style='margin-top:12px; font-size:.85rem; color:var(--muted);'>T+20 累積超額報酬（vs 大盤），公式 (1+R_s)/(1+R_m)−1</p>" + _stats_table_html(stats)
    _chart = lambda f: f.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True})
    _wrap = "min-height:400px; margin-bottom:16px;"
    persist_note = (
        f"分析對象：<b>所有{event_type_label}</b>（共 {n_total_events:,} 件）。高持續性 ≥ P{int(hi_pct*100)}：{n_hi:,} 件；一般 &lt; P{int(hi_pct*100)}：{n_lo:,} 件。"
        f"累積積分 = Σ 異常振幅(T+j)，j=1..k；累積報酬 = 持有 T+1 至 T+k 之累積報酬；累積超額報酬 = (1+R_s)/(1+R_m)−1 vs 大盤。橫軸 T~T+20。"
    )
    if event_type_label == "振幅小事件":
        persist_note += " 對振幅小事件而言，高持續性表示 T+1~T+20 異常振幅（相對於前20日均值）之積分較高，亦即振幅自 T 日異常縮小後逐漸回升甚至放大。"
    desc_html = _persist_descriptive_stats(hi_evt, lo_evt, flag_col)
    logit_html = _persist_logit_model(events, score_col, threshold, flag_col)
    return (
        f"<p class='rpt-note' style='margin-bottom:12px;'>{persist_note}</p>"
        f"<h4 style='margin:16px 0 8px; font-size:.95rem;'>積分演化（T~T+20，併列）</h4>"
        f"<div class='chart-wrap' style='{_wrap}'>{_chart(fig_amp_pair)}</div>"
        f"<h4 style='margin:16px 0 8px; font-size:.95rem;'>累積報酬演化（T~T+20，併列）</h4>"
        f"<div class='chart-wrap' style='{_wrap}'>{_chart(fig_cum_pair)}</div>"
        f"<h4 style='margin:16px 0 8px; font-size:.95rem;'>累積超額報酬演化（T~T+20，併列）</h4>"
        f"<div class='chart-wrap' style='{_wrap}'>{_chart(fig_exc_pair)}</div>"
        f"<h4 style='margin:16px 0 8px; font-size:.95rem;'>高持續性 vs 一般 T+20 超額報酬</h4>"
        f"<div class='chart-wrap' style='min-height:360px; margin-bottom:12px;'>{_chart(fig_box)}</div>{tbl_html}"
        f"<h4 style='margin:20px 0 8px; font-size:.95rem;'>高 vs 一般持續性：T 日特徵敘述統計比較</h4>{desc_html}"
        f"<h4 style='margin:20px 0 8px; font-size:.95rem;'>高持續性預測：Logistic 迴歸</h4>{logit_html}"
    )


def _char_analysis_section(events: pd.DataFrame) -> str:
    """1.5 股票特徵分析：各特徵三組箱型圖 + 圖下統計表。分組：>P75、P25~P75、<P25。"""
    chars = [
        ("市值(百萬元)",     "市值"),
        ("本益比-TSE",       "本益比"),
        ("股價淨值比-TSE",   "股淨比"),
        ("現金股利率",       "現金殖利率"),
        ("CAPM_Beta 一年",   "CAPM Beta"),
    ]
    html = "<p style='margin-bottom:12px; font-size:.85rem; color:var(--muted);'>T+20 累積報酬，公式 exp(Σ ln(1+r))−1。三分組：&gt;P75=高、P25~P75=中、&lt;P25=低。箱型圖僅顯示箱型、圖下為統計表。</p>"
    for col, label in chars:
        html += _three_group_compare_chart_and_table(events, col, "fwd_ret_20", label)
    return html


def _market_amp_chart(mkt_df: pd.DataFrame) -> str:
    """市場整體每日振幅大個股比例，與市場振幅偏多/偏少事件標記。擇一呈現：振幅大比例低=偏少、高=偏多；振幅小比例與其互補，統計意義相同。"""
    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=[
            "每日振幅大個股比例（%）",
            "市場振幅偏多/偏少事件發生日期",
        ],
        vertical_spacing=0.12,
    )

    pct_big = mkt_df["amp_big_pct"] * 100
    dates = mkt_df["date"]

    # Row 1: 振幅大比例 + 百分位帶
    fig.add_trace(go.Scatter(
        x=dates, y=pct_big, name="振幅大比例%",
        mode="lines", line=dict(color="#58a6ff", width=1.2),
        hovertemplate="%{y:.2f}%<extra></extra>",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=dates, y=mkt_df["mkt_hi90"] * 100, name="90th（偏多門檻）",
        mode="lines", line=dict(color="#d29922", width=1, dash="dash"),
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=dates, y=mkt_df["mkt_lo10"] * 100, name="10th（偏少門檻）",
        mode="lines", line=dict(color="#8b949e", width=1, dash="dash"),
    ), row=1, col=1)

    # Row 2: 市場事件標記
    hi_dates = mkt_df[mkt_df["mkt_amp_hi"] == 1]["date"]
    lo_dates = mkt_df[mkt_df["mkt_amp_lo"] == 1]["date"]
    hi_y = pct_big[mkt_df["mkt_amp_hi"] == 1]
    lo_y = pct_big[mkt_df["mkt_amp_lo"] == 1]

    fig.add_trace(go.Scatter(
        x=hi_dates, y=hi_y, name="市場振幅偏多",
        mode="markers", marker=dict(symbol="triangle-up", size=8, color="#f85149"),
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=lo_dates, y=lo_y, name="市場振幅偏少",
        mode="markers", marker=dict(symbol="triangle-down", size=8, color="#3fb950"),
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=dates, y=pct_big, name="振幅大比例（底圖）",
        mode="lines", line=dict(color="#30363d", width=0.8), showlegend=False,
    ), row=2, col=1)

    fig.update_layout(
        **_base_layout(
            title=dict(text="市場整體每日振幅大個股比例（擇一呈現：振幅小比例與其互補，統計意義相同）", font=dict(size=14, color=_TEXT)),
            height=520,
        )
    )
    fig.update_yaxes(ticksuffix="%", row=1, col=1)
    fig.update_yaxes(ticksuffix="%", row=2, col=1)
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True})


def _market_event_index_perf(mkt_df: pd.DataFrame, idx_df: pd.DataFrame,
                              event_col: str, event_label: str) -> str:
    """市場事件後，各指數 T+1, T+5, T+20 累積報酬的盒鬚圖。箱型圖不內嵌統計，圖下為統計表。"""
    event_dates = set(mkt_df[mkt_df[event_col] == 1]["date"])
    if not event_dates:
        return f"<p class='no-data'>{event_label}：無事件發生</p>"

    fig = go.Figure()
    colors_idx = {"SC300": "#58a6ff", "TM100": "#3fb950", "TWN50": "#d29922", "Y9999": "#f85149"}
    stats_rows = {}

    for code in ["SC300", "TM100", "TWN50", "Y9999"]:
        g = idx_df[idx_df["stock_code"] == code].sort_values("date").reset_index(drop=True)
        if g.empty:
            continue

        ret     = g["報酬率％"].fillna(0).values / 100
        log_ret = np.log1p(ret)
        cumlog  = np.cumsum(log_ret)
        n       = len(g)
        for h_val, h_label in [(1, "T+1"), (5, "T+5"), (20, "T+20")]:
            fwd = np.full(n, np.nan)
            if n > h_val:
                fwd[:n-h_val] = np.expm1(cumlog[h_val:] - cumlog[:n-h_val])
            g[f"fwd_{h_val}"] = fwd

        evts = g[g["date"].isin(event_dates)]
        if len(evts) < 3:
            continue

        for h_val, h_label in [(1, "T+1"), (5, "T+5"), (20, "T+20")]:
            ser = evts[f"fwd_{h_val}"].dropna()
            if len(ser) >= 5:
                stats_rows[f"{code} {h_label}"] = _desc_stats(ser)
            fig.add_trace(go.Box(
                y=ser.values * 100,
                name=f"{code} {h_label}",
                marker_color=colors_idx.get(code, "#aaa"),
                boxmean=False,
                boxpoints=False,
                hovertemplate="%{y:.2f}%<extra></extra>",
            ))

    fig.update_layout(**_base_layout(
        title=dict(text=f"{event_label} 後各指數累積報酬",
                   font=dict(size=13, color=_TEXT)),
        height=420,
        yaxis=dict(title="累積報酬%", ticksuffix="%"),
        boxmode="group",
    ))
    chart_html = fig.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True})
    tbl = _stats_table_html(stats_rows) if stats_rows else ""
    return f"<div class='chart-wrap' style='min-height:440px;'>{chart_html}</div>{tbl}"


# ════════════════════════════════════════════════════════════════════════
# 7. 一個事件類型的完整 HTML 區塊
# ════════════════════════════════════════════════════════════════════════

def _event_section_html(df: pd.DataFrame, flag_col: str, title: str,
                        section_num: int) -> str:
    events = df[df[flag_col] == 1].copy()
    n_evt  = len(events)
    n_stk  = events["stock_code"].nunique()
    date_min = events["date"].min().strftime("%Y-%m-%d") if n_evt > 0 else "—"
    date_max = events["date"].max().strftime("%Y-%m-%d") if n_evt > 0 else "—"

    # 高持續性標記
    ps_col = "persist_amp" if flag_col == "amp_big" else "persist_amp"
    p80_thresh = events[ps_col].quantile(PERSIST_HI_PCT) if n_evt >= 10 else np.nan
    if not np.isnan(p80_thresh):
        events["high_persist"] = (events[ps_col] >= p80_thresh).astype(int)
    else:
        events["high_persist"] = 0

    # 注意 / 非注意分組
    attn_n  = int(events["is_attention"].sum()) if "is_attention" in events else 0
    nattn_n = n_evt - attn_n

    # 描述統計
    stats = {}
    for h in (1, 5, 20):
        stats[f"T+{h}"] = _desc_stats(events[f"fwd_ret_{h}"])

    exc_stats = {}
    for h in (1, 5, 20):
        exc_stats[f"T+{h}"] = _desc_stats(events[f"fwd_exc_{h}"])

    mdd_mean = events["mdd_20"].mean() * 100 if "mdd_20" in events else np.nan

    return f"""
<section class="rpt-section" id="sec{section_num}">
  <h2 class="rpt-h2">{section_num}. {title}</h2>

  <div class="info-grid">
    <div class="info-card"><div class="ic-val">{n_evt:,}</div><div class="ic-lbl">事件總數</div></div>
    <div class="info-card"><div class="ic-val">{n_stk:,}</div><div class="ic-lbl">涉及股票數</div></div>
    <div class="info-card"><div class="ic-val">{date_min}</div><div class="ic-lbl">最早事件日</div></div>
    <div class="info-card"><div class="ic-val">{date_max}</div><div class="ic-lbl">最晚事件日</div></div>
    <div class="info-card"><div class="ic-val">{attn_n:,}</div><div class="ic-lbl">注意股票期間</div></div>
    <div class="info-card"><div class="ic-val">{mdd_mean:.2f}%</div><div class="ic-lbl">平均最大回撤（T+20）</div></div>
  </div>

  <h3 class="rpt-h3">{section_num}.1 後續累積報酬分布（T+1 / T+5 / T+20）</h3>
  {_hist_3panel(events, ["fwd_ret_1","fwd_ret_5","fwd_ret_20"],
                f"{title}：後續累積報酬分布", "累積報酬%")}
  {_stats_table_html(stats, {"T+1":"T+1","T+5":"T+5","T+20":"T+20"})}

  <h3 class="rpt-h3">{section_num}.2 後續超額報酬分布（vs 大盤）</h3>
  {_hist_3panel(events, ["fwd_exc_1","fwd_exc_5","fwd_exc_20"],
                f"{title}：後續超額報酬", "超額報酬%")}
  {_stats_table_html(exc_stats)}

  <h3 class="rpt-h3">{section_num}.3 振幅持續性積分分析</h3>
  <p class="rpt-note">積分分數 = Σ 異常振幅(T+k)，k=1~20。高持續性 = 積分 ≥ 第80百分位（P80），其餘為一般。</p>
  {_persist_score_section(events, ps_col, PERSIST_HI_PCT, n_evt, title, flag_col)}

  <h3 class="rpt-h3">{section_num}.4 注意股票期間 vs 非注意期間</h3>
  {_attn_compare(events)}

  <h3 class="rpt-h3">{section_num}.5 股票特徵分析（各特徵三分組後續報酬 T+20）</h3>
  <div class="char-grid">
    {_char_analysis_section(events)}
  </div>
</section>"""


def _overlap_analysis_section(stock_df: pd.DataFrame) -> str:
    """振幅大高持續性 vs 振幅小高持續性：股票層級重疊分析。同一(股票,日期)不可能同時為兩者；分析有多少股票曾分別出現在兩組樣本中。"""
    big_evt = stock_df[stock_df["amp_big"] == 1].copy()
    sml_evt = stock_df[stock_df["amp_sml"] == 1].copy()
    if len(big_evt) < 10 or len(sml_evt) < 10:
        return "<p class='no-data'>樣本不足，無法計算重疊。</p>"
    t80_big = big_evt["persist_amp"].quantile(PERSIST_HI_PCT)
    t80_sml = sml_evt["persist_amp"].quantile(PERSIST_HI_PCT)
    big_hi = set(big_evt[big_evt["persist_amp"] >= t80_big]["stock_code"].unique())
    sml_hi = set(sml_evt[sml_evt["persist_amp"] >= t80_sml]["stock_code"].unique())
    overlap = big_hi & sml_hi
    union = big_hi | sml_hi
    n_big, n_sml = len(big_hi), len(sml_hi)
    n_overlap, n_union = len(overlap), len(union)
    jaccard = n_overlap / n_union if n_union > 0 else 0
    pct_of_big = (n_overlap / n_big * 100) if n_big > 0 else 0
    pct_of_sml = (n_overlap / n_sml * 100) if n_sml > 0 else 0
    return f"""
<section class="rpt-section" id="sec-overlap">
  <h2 class="rpt-h2">附加：高持續性樣本重疊分析</h2>
  <p class="rpt-note">同一(股票,日期)不可能同時為振幅大與振幅小事件。本表以「股票」為單位：有多少股票曾出現在「振幅大高持續性」樣本，且也曾出現在「振幅小高持續性」樣本（不同日期）。</p>
  <div class="tbl-wrap"><table class="stat-tbl">
  <thead><tr><th>項目</th><th>數值</th></tr></thead>
  <tbody>
  <tr><td>振幅大高持續性涉及股票數</td><td>{n_big:,}</td></tr>
  <tr><td>振幅小高持續性涉及股票數</td><td>{n_sml:,}</td></tr>
  <tr><td>重疊股票數（兩組皆曾出現）</td><td>{n_overlap:,}</td></tr>
  <tr><td>聯集股票數</td><td>{n_union:,}</td></tr>
  <tr><td>Jaccard 係數（重疊÷聯集）</td><td>{jaccard:.2%}</td></tr>
  <tr><td>重疊占振幅大高持續性比例</td><td>{pct_of_big:.1f}%</td></tr>
  <tr><td>重疊占振幅小高持續性比例</td><td>{pct_of_sml:.1f}%</td></tr>
  </tbody></table></div>
  <p style="font-size:.85rem; color:var(--muted); margin-top:8px;">解讀：Jaccard 愈高表示兩組愈多共同股票；愈低表示高持續性振幅大與高持續性振幅小往往發生在不同標的上。</p>
</section>"""


def _attn_compare(events: pd.DataFrame) -> str:
    """1.4 注意股票期間 vs 非注意期間 — T+20 超額報酬統計表。"""
    if "is_attention" not in events.columns:
        return "<p class='no-data'>無注意股票資料</p>"
    attn  = events[events["is_attention"] == 1]
    nattn = events[events["is_attention"] == 0]

    stats = {}
    if len(attn) >= 5:
        stats["注意股票期間"] = _desc_stats(attn["fwd_exc_20"].dropna())
    if len(nattn) >= 5:
        stats["非注意期間"] = _desc_stats(nattn["fwd_exc_20"].dropna())

    if not stats:
        return "<p class='no-data'>樣本不足</p>"
    return "<p style='margin-bottom:8px; font-size:.85rem; color:var(--muted);'>T+20 超額報酬（vs 大盤），公式 (1+R_s)/(1+R_m)−1。</p>" + _stats_table_html(stats)


# ════════════════════════════════════════════════════════════════════════
# 8. HTML 組裝
# ════════════════════════════════════════════════════════════════════════

_CSS = """
:root {
  --bg: #0d1117; --bg-card: #161b22; --bg2: #1c2128;
  --border: #30363d; --text: #e6edf3; --muted: #8b949e; --dim: #6e7681;
  --accent: #58a6ff; --green: #3fb950; --orange: #d29922; --red: #f85149;
  --radius: 8px; --shadow: 0 2px 12px rgba(0,0,0,.4);
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { font-size: 14px; scroll-behavior: smooth; }
body { background: var(--bg); color: var(--text);
       font-family: 'Noto Sans TC', system-ui, sans-serif;
       line-height: 1.65; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* Header */
.rpt-header {
  position: sticky; top: 0; z-index: 50;
  background: rgba(13,17,23,.92); backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--border);
  padding: 0 32px; height: 52px;
  display: flex; align-items: center; justify-content: space-between;
}
.rpt-title { font-size: 1.05rem; font-weight: 700; }
.rpt-header-actions { display: flex; align-items: center; gap: 12px; }
.rpt-btn-regenerate { font-size: .82rem; color: var(--orange); background: transparent;
                     border: 1px solid var(--orange); border-radius: var(--radius);
                     padding: 4px 14px; cursor: pointer; }
.rpt-btn-regenerate:hover { background: rgba(210,153,34,.12); }
.rpt-btn-regenerate:disabled { opacity: .6; cursor: not-allowed; }
.rpt-btn-pdf { font-size: .82rem; color: var(--green); background: transparent;
               border: 1px solid var(--green); border-radius: var(--radius);
               padding: 4px 14px; cursor: pointer; }
.rpt-btn-pdf:hover { background: rgba(63,185,80,.12); }
.rpt-btn-pdf:disabled { opacity: .6; cursor: not-allowed; }
.rpt-btn-consolidate { font-size: .82rem; color: var(--accent); background: transparent;
                      border: 1px solid var(--accent); border-radius: var(--radius);
                      padding: 4px 14px; cursor: pointer; }
.rpt-btn-consolidate:hover { background: rgba(88,166,255,.12); }
.rpt-btn-consolidate:disabled { opacity: .6; cursor: not-allowed; }
.rpt-back { font-size: .82rem; color: var(--accent);
            border: 1px solid var(--accent); border-radius: var(--radius);
            padding: 4px 14px; }
.rpt-back:hover { background: rgba(88,166,255,.12); }

/* TOC - 緊湊導覽列，與主內容同寬 */
.rpt-toc {
  display: flex; flex-wrap: wrap; gap: 8px 16px; padding: 12px 24px; margin: 0 auto 16px;
  max-width: 1200px; background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); font-size: .8rem;
}
.rpt-toc a { color: var(--muted); }
.rpt-toc a:hover { color: var(--accent); text-decoration: none; }
.toc-group { width: 100%; font-size: .7rem; font-weight: 700; color: var(--dim);
             text-transform: uppercase; letter-spacing: .05em; margin-top: 4px; }
.toc-group:first-child { margin-top: 0; }

/* Main content - 全寬 */
.rpt-main { padding: 0 24px 80px; max-width: 1200px; margin: 0 auto; }
.rpt-intro { background: var(--bg-card); border: 1px solid var(--border);
             border-radius: var(--radius); padding: 20px 24px; margin-bottom: 24px; }
.rpt-intro p { color: var(--muted); font-size: .88rem; margin-top: 6px; }
.rpt-meta { display: flex; gap: 24px; margin-top: 12px; flex-wrap: wrap; }
.meta-item { font-size: .82rem; color: var(--dim); }
.rpt-interpret { background: var(--bg-card); border: 1px solid var(--border);
                 border-radius: var(--radius); padding: 20px 24px; margin-bottom: 24px; }
.rpt-interpret h3 { font-size: 1rem; font-weight: 700; color: var(--accent); margin: 16px 0 8px; }
.rpt-interpret h3:first-child { margin-top: 0; }
.rpt-interpret h4 { font-size: .92rem; font-weight: 600; color: var(--text); margin: 12px 0 6px; }
.rpt-interpret ul { margin: 8px 0; padding-left: 20px; color: var(--muted); font-size: .88rem; line-height: 1.6; }
.rpt-interpret p { color: var(--muted); font-size: .88rem; line-height: 1.6; margin: 8px 0; }
.rpt-interpret .sub-item { margin-left: 12px; margin-top: 4px; }
.meta-item span { color: var(--text); font-weight: 600; margin-left: 4px; }

/* Sections */
.rpt-section { margin-bottom: 32px; }
.rpt-h2 { font-size: 1.15rem; font-weight: 800; color: var(--text);
          padding: 16px 0 12px; border-bottom: 2px solid var(--accent);
          margin-bottom: 20px; }
.rpt-h3 { font-size: .98rem; font-weight: 700; color: var(--accent);
          margin: 24px 0 12px; }
.rpt-note { font-size: .82rem; color: var(--muted); margin-bottom: 12px;
            background: var(--bg2); border-left: 3px solid var(--border);
            padding: 8px 14px; border-radius: 0 var(--radius) var(--radius) 0; }

/* Info grid */
.info-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
             gap: 12px; margin-bottom: 20px; }
.info-card { background: var(--bg-card); border: 1px solid var(--border);
             border-radius: var(--radius); padding: 14px; text-align: center; }
.ic-val { font-size: 1.3rem; font-weight: 800; color: var(--accent);
          font-variant-numeric: tabular-nums; }
.ic-lbl { font-size: .75rem; color: var(--dim); margin-top: 4px; }

/* Stats table */
.tbl-wrap { overflow-x: auto; margin-bottom: 16px; }
.stat-tbl { width: 100%; border-collapse: collapse; font-size: .82rem; }
.stat-tbl th, .stat-tbl td { padding: 7px 12px; border-bottom: 1px solid var(--border);
                              text-align: right; }
.stat-tbl th { background: rgba(255,255,255,.03); color: var(--muted); font-weight: 700; }
.stat-tbl td:first-child { text-align: left; }
.stat-tbl th:first-child { text-align: left; }

/* Char grid - 單欄排列，避免擠壓 */
.char-grid { display: flex; flex-direction: column; gap: 24px; }

/* Chart wrapper */
.chart-wrap { min-height: 400px; margin-bottom: 16px; }

/* No data */
.no-data { color: var(--dim); font-size: .85rem; padding: 16px;
           background: var(--bg-card); border: 1px solid var(--border);
           border-radius: var(--radius); margin: 8px 0; }

/* Responsive */
@media (max-width: 640px) { .rpt-main { padding: 0 16px 60px; } }
@media print {
  .rpt-toc { display: none !important; }
  .rpt-header { position: static; }
  .rpt-btn-regenerate, .rpt-back { display: none !important; }
}
"""

_TOC = """
<nav class="rpt-toc">
  <a href="#interpret-guide">📖 解讀指南</a>
  <div class="toc-group">個股層級</div>
  <a href="#sec1">1. 振幅大事件</a>
  <a href="#sec2">2. 振幅小事件</a>
  <div class="toc-group">市場層級</div>
  <a href="#sec3">3. 市場振幅偏多／偏少</a>
  <a href="#sec-overlap">附加：高持續性重疊分析</a>
  <div class="toc-group">附錄</div>
  <a href="#sec-conclusion">5. 結論</a>
  <a href="#sec6">6. 方法說明</a>
</nav>
"""

_CONCLUSION = """
<section class="rpt-section" id="sec-conclusion">
  <h2 class="rpt-h2">5. 結論</h2>

  <h3 class="rpt-h3">一、整體觀點</h3>
  <p>於樣本時期，單一振幅大／小事件本身並非決定後續報酬的唯一因素；報酬表現需搭配「高持續性」分組與市場環境一併解讀。振幅大事件具較高波動與純粹炒作風險，振幅小事件相對缺乏炒作動能；因振幅過大而列為注意股者，則往往反映較高的純粹炒作風險。</p>

  <h3 class="rpt-h3">二、個股層級：高持續性事件</h3>
  <p><strong>振幅大事件之高持續性：</strong>指 T 日振幅異常大後，T+1~T+20 積分分數仍持續增加、振幅仍相較於前 20 日均值偏大。若報告圖表顯示高持續性組之 T+20 累積報酬與超額報酬優於一般組，且勝率較高，可解讀為：後續波動延續者，往往伴隨較佳報酬表現。預測因子：小型股、低 Beta、事件強度（超出 P90 愈多）愈高者，愈易落入高持續性。</p>
  <p><strong>振幅小事件之高持續性：</strong>指 T 日振幅異常小後，積分分數回升或放大，即振幅自 T 日異常縮小後逐漸回升甚至超越均值。若報告圖表顯示高持續性組具較高超額報酬與勝率，可解讀為：低波後波動回升者，往往有較佳報酬。預測因子：小型股、低 Beta、非注意股、事件強度（壓縮愈深）愈高者，愈易落入高持續性；注意股則顯著降低高持續性機率。</p>

  <h3 class="rpt-h3">三、市場層級</h3>
  <p><strong>市場振幅偏少：</strong>當日多數個股振幅偏小、炒作氛圍淡。若報告顯示市場振幅偏少後，各指數 T+1／T+5／T+20 具較高勝率與正報酬，可解讀為市場冷卻期後較值得進場布局。</p>
  <p><strong>市場振幅偏多：</strong>當日多數個股振幅偏大，市場氣氛熱絡。若報告顯示該情境後短期內指數有明顯波動或資金行情，可視為炒短線的潛在時機；惟需留意回撤風險。</p>

  <h3 class="rpt-h3">四、注意股與炒作風險</h3>
  <p>因振幅過大而列為注意股者，往往反映監管警示與投機動能。報告 1.4／2.4 之「注意股票期間 vs 非注意期間」可協助評估：注意股期間的超額報酬是否較差或波動較大，以判斷純粹炒作風險的實際影響。</p>

  <h3 class="rpt-h3">五、回測策略建議（振幅＋成交量／籌碼／基本面）</h3>
  <p>若欲在振幅基礎上加入成交量、籌碼、基本面實行回測，建議參數與策略如下：</p>
  <ul>
    <li><strong>成交量：</strong>T 日成交量 ÷ 前 20 日均量 − 1（異常量能）。可設門檻：僅當異常量能 &gt; 0.5 時才進場，或作為加權分數。</li>
    <li><strong>籌碼面：</strong>外資／投信／自營 T 日或 T−1~T 累積買賣超；融資餘額變化、借券賣出餘額。可篩選：外資連 N 日買超、或法人合計買超 &gt; 門檻。</li>
    <li><strong>基本面：</strong>市值、本益比、股淨比、現金殖利率、近四季 EPS 成長。可排除本益比 &lt; 0 或 &gt; 100 之極端值，並依 Logit 係數方向設篩選（如僅小型股、低 Beta）。</li>
    <li><strong>策略設計：</strong>① 進場：T 日收盤符合振幅事件＋第二條件通過；② 出場：T+h 收盤（h=5, 10, 20）或移動停利／停損；③ 部位：等權、依市值或波動率倒數加權；④ 對照：與「僅振幅」策略比較夏普比、最大回撤、勝率；⑤ 樣本外：以 rolling 年度或 walk-forward 避免過度擬合。</li>
  </ul>
  <p><em>註：上述結論為基於報告架構與典型樣本之綜合解讀，實際數值與方向請以各章節圖表與統計表為準。</em></p>
</section>
"""

_METHODS = """
<section class="rpt-section" id="sec6">
  <h2 class="rpt-h2">6. 方法說明</h2>
  <div class="rpt-note">
    <b>振幅大事件：</b>今日 <code>高低價差%</code> &gt; 前20個交易日（不含當日）rolling 第90百分位數，且前20日有完整資料。<br><br>
    <b>振幅小事件：</b>今日 <code>高低價差%</code> &lt; 前20個交易日 rolling 第10百分位數。<br><br>
    <b>進場邏輯：</b>以 <b>T 日收盤價買進</b>，<b>T+h 日收盤價賣出</b>。報酬 = 持有 T+1 至 T+h 共 h 日之累積報酬。<br><br>
    <b>後續累積報酬：</b>以對數報酬加總法計算，T+h = exp(Σ ln(1+r_t)，t=T+1..T+h) - 1。<br><br>
    <b>後續超額報酬：</b>正確公式 (1+R_s)/(1+R_m)−1，其中 R_s、R_m 為個股與大盤（Y9999）之累積報酬。<br><br>
    <b>最大回撤（T+20）：</b>觀察 T+1 至 T+20 的累積報酬路徑，計算最大峰值至谷值的跌幅。<br><br>
    <b>異常振幅：</b>今日振幅 / 前20日均值 - 1。<br><br>
    <b>持續性積分：</b>Σ 異常振幅(T+k)，k=1..20。高持續性門檻 = 所有事件積分第80百分位數。<br><br>
    <b>市場振幅偏多：</b>當日振幅大個股比例 &gt; 該比例序列 rolling 第90百分位。<br><br>
    <b>共用篩選：</b>排除全額交割股、排除處置期間紀錄、排除交易日未滿252日個股、排除成交量為零紀錄。
  </div>
</section>
"""


def render_html(stock_df: pd.DataFrame, idx_df: pd.DataFrame, mkt_df: pd.DataFrame,
                gen_time: str) -> str:

    n_stocks = stock_df["stock_code"].nunique()
    n_rows   = len(stock_df)
    date_rng = f"{stock_df['date'].min().strftime('%Y-%m-%d')} ~ {stock_df['date'].max().strftime('%Y-%m-%d')}"

    intro = f"""
<div class="rpt-intro">
  <p>分析振幅異常事件（大/小）後的個股與市場表現，涵蓋累積報酬、超額報酬、振幅持續性、成交量行為及股票特徵分析。</p>
  <div class="rpt-meta">
    <div class="meta-item">資料期間：<span>{date_rng}</span></div>
    <div class="meta-item">分析股數：<span>{n_stocks:,} 檔</span></div>
    <div class="meta-item">有效紀錄：<span>{n_rows:,} 筆</span></div>
    <div class="meta-item">生成時間：<span>{gen_time}</span></div>
  </div>
</div>"""

    interpret_block = """
<div class="rpt-interpret" id="interpret-guide">
  <h3>📖 議題 a 數據呈現說明與解讀指南</h3>
  <p>本報告探討「個股振幅異常」事件發生後，後續報酬、相對大盤表現、以及振幅是否持續等議題。振幅定義為 <code>(當日最高價 − 當日最低價) ÷ 前日收盤價 × 100%</code>。事件日 T 為觸發日。假設以 T 日收盤價買進、T+h 日收盤價賣出，T+1、T+5、T+20 分別代表持有 1、5、20 個交易日後的累積報酬。</p>

  <h3>1. 振幅大事件</h3>
  <p><strong>定義：</strong>今日高低價差% &gt; 該股前 20 個交易日（不含當日）rolling 第 90 百分位數。</p>

  <h4>1.1 後續累積報酬分布</h4>
  <p><strong>衡量議題：</strong>振幅大事件發生後，持有該股票在 T+1、T+5、T+20 的「絕對報酬」表現。</p>

  <h4>1.2 後續超額報酬分布</h4>
  <p><strong>衡量議題：</strong>振幅大事件發生後，持有該股票在 T+1、T+5、T+20 相較於大盤的「相對報酬」表現。超額報酬公式為 (1+R_s)/(1+R_m)−1，其中 R_s、R_m 為個股與大盤累積報酬；可對應 TEJ 欄位「超額報酬(日)-大盤」之累計加總邏輯。</p>

  <h4>1.3 振幅持續性分析</h4>
  <p><strong>衡量議題：</strong>在所有振幅大事件中，依「積分分數」分為高持續性與一般，並比較兩組 T+20 的<strong>超額累積報酬</strong>（vs 大盤），較具相對績效意義。</p>
  <ul>
    <li><strong>分析對象：</strong>所有振幅大事件。</li>
    <li><strong>積分分數：</strong>Σ 異常振幅(T+k)，k=1~20。異常振幅 = 當日振幅 ÷ 基準期均值 − 1。<strong>基準期均值</strong>為該股前 20 個交易日（不含當日）振幅的滾動平均。積分愈高，表示振幅大事件發生後，往後 20 天振幅仍延續較高震盪。</li>
    <li><strong>高積分門檻（P80）：</strong>積分 ≥ 第 80 百分位數為「高持續性」；其餘為「一般」。P80 依樣本動態計算，實際門檻值見圖表說明。</li>
    <li><strong>圖例：</strong>高 vs 一般，置於圖下方。</li>
  </ul>

  <h4>1.4 加上第二條件（注意股）的後續累積報酬分布</h4>
  <p><strong>衡量議題：</strong>將振幅大事件再區分為「注意股票期間」（當日具 A 標記）與「非注意期間」，比較兩組 T+20 超額報酬（vs 大盤）。可觀察注意股標記是否與後續相對表現有關聯。</p>

  <h4>1.5 加上第二條件（財務特徵）的後續累積報酬分布</h4>
  <p>依各財務特徵的百分位數分為三組：&gt; P75 為高組、P25~P75 為中組、&lt; P25 為低組。適用於：市值、本益比、股淨比、現金殖利率、CAPM Beta。</p>

  <h3>2. 振幅小事件</h3>
  <p><strong>定義：</strong>今日高低價差% &lt; 該股前 20 個交易日（不含當日）rolling 第 10 百分位數。</p>

  <h4>2.1 後續累積報酬分布</h4>
  <p><strong>衡量議題：</strong>振幅小事件發生後，持有該股票在 T+1、T+5、T+20 的「絕對報酬」表現。</p>

  <h4>2.2 後續超額報酬分布</h4>
  <p><strong>衡量議題：</strong>振幅小事件發生後，持有該股票在 T+1、T+5、T+20 相較於大盤的「相對報酬」表現。超額報酬公式為 (1+R_s)/(1+R_m)−1。</p>

  <h4>2.3 振幅持續性分析</h4>
  <p><strong>衡量議題：</strong>在所有振幅小事件中，依「積分分數」分為高持續性與一般，並比較兩組 T+20 的<strong>超額累積報酬</strong>（vs 大盤）。</p>
  <ul>
    <li><strong>分析對象：</strong>所有振幅小事件。</li>
    <li><strong>積分分數：</strong>Σ 異常振幅(T+k)，k=1~20；異常振幅與基準期均值定義同 1.3。積分愈高，表示振幅小事件發生後，往後 20 天振幅逐漸回升或放大。</li>
    <li><strong>高積分門檻（P80）：</strong>積分 ≥ 第 80 百分位數為「高持續性」；其餘為「一般」。P80 依樣本動態計算。</li>
    <li><strong>圖例：</strong>高 vs 一般，置於圖下方。</li>
  </ul>

  <h4>2.4 加上第二條件（注意股）的後續累積報酬分布</h4>
  <p><strong>衡量議題：</strong>將振幅小事件再區分為「注意股票期間」與「非注意期間」，比較兩組 T+20 超額報酬。</p>

  <h4>2.5 加上第二條件（財務特徵）的後續累積報酬分布</h4>
  <p>依各財務特徵的百分位數分為三組：&gt; P75 為高組、P25~P75 為中組、&lt; P25 為低組。適用於：市值、本益比、股淨比、現金殖利率、CAPM Beta。</p>

  <h3>3. 市場振幅偏多／偏少（擇一呈現）</h3>
  <p><strong>定義：</strong>以「振幅大個股比例」為單一主軸。偏多：比例 &gt; rolling 第 90 百分位；偏少：比例 &lt; rolling 第 10 百分位。振幅小個股比例與振幅大比例互補（小高=大低），統計意義相同，故擇一呈現。</p>
  <h4>3.1 市場振幅偏多後指數累積報酬</h4>
  <p>市場發生振幅偏多事件後，各指數在 T+1、T+5、T+20 的累積報酬表現。</p>
  <h4>3.2 市場振幅偏少後指數累積報酬</h4>
  <p>市場發生振幅偏少事件後，各指數在 T+1、T+5、T+20 的累積報酬表現。</p>
</div>
"""

    sec1 = _event_section_html(stock_df, "amp_big", "振幅大事件", 1)
    sec2 = _event_section_html(stock_df, "amp_sml", "振幅小事件", 2)
    sec_overlap = _overlap_analysis_section(stock_df)

    sec3 = f"""
<section class="rpt-section" id="sec3">
  <h2 class="rpt-h2">3. 市場振幅偏多／偏少（擇一呈現）</h2>
  <p class="rpt-note">以振幅大個股比例為主軸。偏多：&gt; rolling 第90百分位；偏少：&lt; rolling 第10百分位。振幅小比例與其互補，統計意義相同，故擇一呈現。</p>
  {_market_amp_chart(mkt_df)}
  <h3 class="rpt-h3">3.1 市場振幅偏多後指數累積報酬</h3>
  {_market_event_index_perf(mkt_df, idx_df, "mkt_amp_hi", "市場振幅偏多")}
  <h3 class="rpt-h3">3.2 市場振幅偏少後指數累積報酬</h3>
  {_market_event_index_perf(mkt_df, idx_df, "mkt_amp_lo", "市場振幅偏少")}
</section>"""

    body_content = intro + interpret_block + sec1 + sec2 + sec3 + sec_overlap + _CONCLUSION + _METHODS

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>a. 振幅分析 | 財經數據分析平台</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>{_CSS}</style>
</head>
<body>
<header class="rpt-header">
  <span class="rpt-title">📊 議題 a：振幅分析</span>
  <div class="rpt-header-actions">
    <button type="button" class="rpt-btn-consolidate" id="btn-consolidate" title="統合 TEJ 來源資料至單一 CSV，加速後續報告產生">📦 更新統合資料</button>
    <button type="button" class="rpt-btn-regenerate" id="btn-regenerate">↺ 重新產生</button>
    <button type="button" class="rpt-btn-pdf" id="btn-export-pdf">📄 匯出 PDF</button>
    <a href="javascript:history.back()" class="rpt-back">← 返回</a>
  </div>
</header>
<script>
document.getElementById("btn-consolidate").onclick = async function() {{
  const btn = this;
  btn.disabled = true;
  btn.textContent = "統合中…";
  try {{
    const res = await fetch("/api/report-a/consolidate", {{ method: "POST" }});
    const data = await res.json();
    if (data.status === "ok") {{
      btn.textContent = "✓ 完成";
    }} else {{
      alert("統合失敗：" + (data.message || "未知錯誤"));
      btn.textContent = "📦 更新統合資料";
    }}
  }} catch (e) {{
    alert("連線失敗：" + e.message);
    btn.textContent = "📦 更新統合資料";
  }} finally {{
    btn.disabled = false;
  }}
}};
document.getElementById("btn-regenerate").onclick = async function() {{
  const btn = this;
  btn.disabled = true;
  btn.textContent = "產生中…";
  try {{
    const res = await fetch("/api/report/generate/a", {{ method: "POST" }});
    const data = await res.json();
    if (data.status === "ok") {{
      btn.textContent = "✓ 完成，重新載入…";
      setTimeout(() => location.reload(), 800);
    }} else {{
      alert("產生失敗：" + (data.message || "未知錯誤"));
      btn.disabled = false;
      btn.textContent = "↺ 重新產生";
    }}
  }} catch (e) {{
    alert("連線失敗：" + e.message);
    btn.disabled = false;
    btn.textContent = "↺ 重新產生";
  }}
}};
document.getElementById("btn-export-pdf").onclick = async function() {{
  const btn = this;
  btn.disabled = true;
  btn.textContent = "匯出中…";
  try {{
    const res = await fetch("/api/report/export-pdf/a", {{ method: "POST" }});
    if (!res.ok) {{
      const err = await res.json().catch(() => ({{}}));
      alert("匯出失敗：" + (err.message || res.statusText));
      return;
    }}
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "報告a_振幅分析.pdf";
    a.click();
    URL.revokeObjectURL(url);
  }} catch (e) {{
    alert("匯出失敗：" + e.message);
  }} finally {{
    btn.disabled = false;
    btn.textContent = "📄 匯出 PDF";
  }}
}};
</script>
{_TOC}
<main class="rpt-main">
{body_content}
</main>
</body>
</html>"""


# ════════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="議題 a 振幅分析報告產生器")
    parser.add_argument("--from-source", action="store_true",
                        help="強制從 TEJ 原始 CSVs 讀取，不使用統合 CSV")
    args = parser.parse_args()

    t0 = datetime.now()
    print("=" * 55)
    print("  議題 a：振幅分析報告產生器")
    print("=" * 55)

    df_raw = load_data(force_source=args.from_source)

    print("[2/6] 套用共用篩選...")
    stock_df, idx_df = apply_filters(df_raw)

    print("[3/6] 計算振幅事件與後續視窗...")
    stock_df = calc_events_and_windows(stock_df, idx_df)

    print("[4/6] 計算市場整體振幅比例...")
    mkt_df = calc_market_amplitude(stock_df)

    # 指數後續報酬由 _market_event_index_perf 內部計算，無需預先處理

    print("[5/6] 產生 HTML 報告...")
    gen_time = t0.strftime("%Y-%m-%d %H:%M")
    html = render_html(stock_df, idx_df, mkt_df, gen_time)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html, encoding="utf-8")

    # 寫出市場振幅比例供大盤監控區使用
    mkt_json = BASE_DIR / "All_Data" / "事件資料" / "市場振幅比例.json"
    mkt_json.parent.mkdir(parents=True, exist_ok=True)
    mkt_export = mkt_df[["date", "amp_big_pct", "mkt_hi90", "mkt_lo10"]].copy()
    mkt_export["date"] = mkt_export["date"].dt.strftime("%Y-%m-%d")
    mkt_export.to_json(mkt_json, orient="records", date_format="iso", force_ascii=False, indent=0)

    # 計算並寫出股票持續性機率 P(高持續性|振幅大事件)，供個股監控資料摘要使用
    prob_df = calc_stock_persist_prob(stock_df)
    prob_csv = BASE_DIR / "All_Data" / "事件資料" / "股票持續性機率.csv"
    prob_df.to_csv(prob_csv, index=False, encoding="utf-8-sig")
    print(f"      股票持續性機率：{len(prob_df):,} 檔")

    # 若統合 CSV 存在，將 stock_persist_prob 合併寫回
    if CONSOLIDATED_CSV.exists():
        try:
            consolidated = pd.read_csv(CONSOLIDATED_CSV, encoding="utf-8-sig")
            if "stock_code" in consolidated.columns and len(prob_df) > 0:
                for c in ("stock_persist_prob", "stock_persist_hi_n", "stock_persist_amp_n"):
                    consolidated = consolidated.drop(columns=[c], errors="ignore")
                consolidated = consolidated.merge(prob_df, on="stock_code", how="left")
                consolidated.to_csv(CONSOLIDATED_CSV, index=False, encoding="utf-8-sig")
        except Exception as e:
            print(f"      合併 stock_persist_prob 至統合 CSV 時略過：{e}")

    elapsed = (datetime.now() - t0).seconds
    print(f"\n[6/6] 完成！輸出至：{OUTPUT_PATH}")
    print(f"      檔案大小：{OUTPUT_PATH.stat().st_size / 1024:.0f} KB，耗時：{elapsed} 秒")
    print("=" * 55)


if __name__ == "__main__":
    main()
