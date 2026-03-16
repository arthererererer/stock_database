"""
generate_stats.py — 私下統計分布報告產生器
執行後於同資料夾產生 stats_report.html，可用瀏覽器直接開啟。
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')
import os

# 將上層目錄加入路徑以存取 data_service
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import math
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio

import data_service as ds

# ── 設定 ─────────────────────────────────────────────────────────────
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), 'stats_report.html')

DARK = {
    'bg':       '#0d1117',
    'card':     '#161b22',
    'border':   '#30363d',
    'text':     '#e6edf3',
    'muted':    '#8b949e',
    'dim':      '#6e7681',
    'blue':     '#58a6ff',
    'green':    '#3fb950',
    'red':      '#f85149',
    'orange':   '#d29922',
    'purple':   '#bc8cff',
    'yellow':   '#e3b341',
}

SEC_COLORS = {
    'OTC992 上櫃-股票':   DARK['blue'],
    'REG991 興櫃-一般版':  DARK['orange'],
    'Y99992 上市-股票':   DARK['green'],
}

NUMERIC_COLS = ds.NUMERIC_COLS


# ── 工具函數 ─────────────────────────────────────────────────────────

def fmt_num(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return 'N/A'
    if abs(v) >= 1e8:
        return f'{v/1e8:.2f} 億'
    if abs(v) >= 1e4:
        return f'{v/1e4:.1f} 萬'
    return f'{v:,.2f}'


def stats_table_html(series: pd.Series, col: str) -> str:
    """產生單欄統計摘要 HTML 表格。"""
    desc = series.describe(percentiles=[.1, .25, .5, .75, .9])
    rows = [
        ('計數',    int(desc['count'])),
        ('平均值',   fmt_num(desc['mean'])),
        ('標準差',   fmt_num(desc['std'])),
        ('最小值',   fmt_num(desc['min'])),
        ('10th 百分位', fmt_num(desc.get('10%', float('nan')))),
        ('25th 百分位', fmt_num(desc['25%'])),
        ('中位數',   fmt_num(desc['50%'])),
        ('75th 百分位', fmt_num(desc['75%'])),
        ('90th 百分位', fmt_num(desc.get('90%', float('nan')))),
        ('最大值',   fmt_num(desc['max'])),
        ('偏態係數',  f'{series.skew():.3f}'),
        ('峰態係數',  f'{series.kurt():.3f}'),
    ]
    trs = ''.join(
        f'<tr><td class="tb-label">{k}</td><td class="tb-val">{v}</td></tr>'
        for k, v in rows
    )
    return f'<table class="stats-table"><tbody>{trs}</tbody></table>'


# ── 圖表產生 ──────────────────────────────────────────────────────────

def make_dist_figure(df: pd.DataFrame, col: str) -> str:
    """
    針對某欄位，為每個標的產生：
    - 直方圖（+ KDE 近似）
    - Box plot
    回傳 HTML div 字串。
    """
    securities = sorted(df['證券代碼'].unique())
    fig = make_subplots(
        rows=2, cols=len(securities),
        subplot_titles=[f'{ds.SECURITY_LABELS.get(s, s)}' for s in securities] * 2,
        row_heights=[0.65, 0.35],
        vertical_spacing=0.08,
        horizontal_spacing=0.06,
    )

    for col_idx, code in enumerate(securities, start=1):
        sec = df[df['證券代碼'] == code][col].dropna()
        color = SEC_COLORS.get(code, DARK['blue'])

        # 直方圖
        fig.add_trace(
            go.Histogram(
                x=sec,
                nbinsx=40,
                name=ds.SECURITY_LABELS.get(code, code),
                marker_color=color,
                opacity=0.75,
                showlegend=(col_idx == 1),
                hovertemplate='區間：%{x}<br>筆數：%{y}<extra></extra>',
            ),
            row=1, col=col_idx,
        )

        # 中位數垂直線
        med = sec.median()
        fig.add_vline(
            x=med, line_width=1.5, line_dash='dash',
            line_color=DARK['yellow'] if col_idx == 1 else DARK['orange'],
            row=1, col=col_idx,
        )

        # Box plot
        fig.add_trace(
            go.Box(
                x=sec,
                name=ds.SECURITY_LABELS.get(code, code),
                marker_color=color,
                line_color=color,
                showlegend=False,
                boxmean='sd',
                hovertemplate='%{x}<extra></extra>',
            ),
            row=2, col=col_idx,
        )

    fig.update_layout(
        paper_bgcolor=DARK['bg'],
        plot_bgcolor=DARK['bg'],
        font={'color': DARK['text'], 'family': 'Inter, Noto Sans TC, system-ui'},
        height=460,
        title={'text': f'<b>{col}</b>', 'font': {'size': 15, 'color': DARK['text']}, 'x': 0.02},
        margin={'t': 60, 'r': 24, 'b': 40, 'l': 60},
        showlegend=False,
        bargap=0.05,
    )
    fig.update_xaxes(gridcolor=DARK['border'], linecolor=DARK['border'], tickfont={'color': DARK['muted']})
    fig.update_yaxes(gridcolor=DARK['border'], linecolor=DARK['border'], tickfont={'color': DARK['muted']})

    return pio.to_html(fig, full_html=False, include_plotlyjs=False, config={'responsive': True})


# ── HTML 模板組裝 ─────────────────────────────────────────────────────

def build_html(df: pd.DataFrame) -> str:
    sections = []
    securities = sorted(df['證券代碼'].unique())

    for col in NUMERIC_COLS:
        if col not in df.columns:
            continue

        fig_html = make_dist_figure(df, col)

        # 各標的統計表
        tables_html = ''
        for code in securities:
            label = ds.SECURITY_LABELS.get(code, code)
            sec_series = df[df['證券代碼'] == code][col].dropna()
            color = SEC_COLORS.get(code, DARK['blue'])
            tables_html += f'''
            <div class="stat-block">
              <div class="stat-title" style="color:{color}">{label}</div>
              {stats_table_html(sec_series, col)}
            </div>'''

        sections.append(f'''
        <div class="section">
          <div class="section-header">
            <h2 class="col-title">{col}</h2>
          </div>
          {fig_html}
          <div class="tables-row">{tables_html}</div>
        </div>''')

    body = '\n'.join(sections)

    data_range = f"{df['date'].min().strftime('%Y-%m-%d')} ～ {df['date'].max().strftime('%Y-%m-%d')}"

    return f'''<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>大盤統計 — 私下統計分布報告</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root{{
  --bg:#0d1117; --card:#161b22; --card2:#1c2128;
  --border:#30363d; --text:#e6edf3; --muted:#8b949e; --dim:#6e7681;
  --accent:#58a6ff; --green:#3fb950; --red:#f85149;
  --radius:8px; --radius-lg:12px;
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'Inter','Noto Sans TC',system-ui;padding:0 0 60px}}
header{{background:var(--card);border-bottom:1px solid var(--border);padding:18px 32px;display:flex;align-items:baseline;gap:16px}}
header h1{{font-size:1.1rem;font-weight:700}}
header .sub{{font-size:.82rem;color:var(--muted)}}
.main{{max-width:1440px;margin:0 auto;padding:24px 24px}}
.section{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius-lg);padding:22px;margin-bottom:20px}}
.section-header{{margin-bottom:12px}}
.col-title{{font-size:1rem;font-weight:700;color:var(--text)}}
.tables-row{{display:flex;gap:16px;flex-wrap:wrap;margin-top:14px}}
.stat-block{{flex:1;min-width:200px;background:var(--card2);border:1px solid var(--border);border-radius:var(--radius);padding:14px}}
.stat-title{{font-size:.85rem;font-weight:700;margin-bottom:8px}}
.stats-table{{width:100%;border-collapse:collapse;font-size:.8rem}}
.stats-table td{{padding:4px 6px;border-bottom:1px solid var(--border)}}
.stats-table tr:last-child td{{border-bottom:none}}
.tb-label{{color:var(--muted);width:55%}}
.tb-val{{color:var(--text);text-align:right;font-variant-numeric:tabular-nums}}
::-webkit-scrollbar{{width:6px;height:6px}}
::-webkit-scrollbar-track{{background:var(--bg)}}
::-webkit-scrollbar-thumb{{background:var(--border);border-radius:3px}}
@media(max-width:640px){{.main{{padding:12px}}.tables-row{{flex-direction:column}}}}
</style>
</head>
<body>
<header>
  <h1>📊 大盤統計 — 統計分布報告</h1>
  <span class="sub">資料期間：{data_range} ／ 共 {len(df)} 筆</span>
</header>
<div class="main">
{body}
</div>
</body>
</html>'''


# ── 主程式 ────────────────────────────────────────────────────────────

def main():
    print('載入資料中…')
    df = ds.load_all_data()
    print(f'  共 {len(df)} 筆，{len(df["證券代碼"].unique())} 個標的')

    print('產生報告中…')
    html = build_html(df)

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'[完成] 報告已儲存至：{OUTPUT_PATH}')
    print('   請用瀏覽器開啟該 HTML 檔案即可查閱。')


if __name__ == '__main__':
    main()
