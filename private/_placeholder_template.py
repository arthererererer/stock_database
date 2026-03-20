"""生成 9 份研究報告的佔位 HTML（正式 RMarkdown 完成後以實際報告替換）。"""
import os

REPORTS = [
    ("report_a.html", "a", "a. 振幅分析",
     "分析個股振幅變大 / 變小事件的後續績效，含持續性積分、累積報酬率、超額報酬、成交量行為與股票特徵分析；以及市場整體振幅偏多 / 偏少時各大指數的反應。"),
    ("report_b.html", "b", "b. 指數穩定 / 連續上漲",
     "定義並分析 SC300 / TM100 / TWN50 / Y9999 四大指數「連續上漲（N日正報酬）」與「穩定上漲（20日累報 > 閾值且波動低）」期間，其餘個股漲跌幅、振幅、成交量變化，及表現最佳個股的特徵分析。"),
    ("report_c.html", "c", "c. 缺口開盤分析",
     "定義今日開盤 > 前日最高價為缺口開盤事件，依前日成交量分為偏高 / 偏低量兩組，分析後續今日最低 > 前日收盤的比例與幅度，及 T+1、T+5、T+20 的累積報酬分布、超額報酬、成交量變化與股票特徵。"),
    ("report_d.html", "d", "d. 變數統計分布",
     "呈現當日高點報酬、當日低點報酬、週轉率、市值、市值比重、本益比、股淨比、股價營收比、現金殖利率、CAPM Beta 等十項變數的全市場分布（直方圖 + KDE），以及依類股清單分層的盒鬚圖 / 小提琴圖比較。"),
    ("report_e.html", "e", "e. 事件重疊觀察",
     "將振幅變大、振幅變小、注意股票（A）、處置股票（D）、全額交割（Y）等事件在時間軸上對齊，觀察個股事件時間線（甘特圖）、市場層面日曆熱力圖，並計算事件共現條件機率（卡方檢定）。"),
    ("report_f.html", "f", "f. 融資維持率分析",
     "分析個股融資維持率跌破 130% 後的後續股價行為，含 T+1、T+5、T+20 累積報酬、超額報酬分布、勝率、最大回撤，及觸發股票的市值、估值與 Beta 特徵。"),
    ("report_g.html", "g", "g. 借券賣超分析",
     "定義借券賣出張數 > 前20日 rolling 第90百分位數為借券賣超事件，分析後續 T+1、T+5、T+20 累積報酬分布、超額報酬、成交量變化，並探討觸發股票特徵。"),
    ("report_h.html", "h", "h. 連板研究",
     "分析連續 N 日（預設 N=2）漲停後的股票後續表現，含累積報酬分布、超額報酬、持續性（第 N+1 日是否仍漲停）、股票特徵分析，並區分注意股票期間 vs. 非注意期間。"),
    ("report_i.html", "i", "i. 法人買賣超分析",
     "分析外資、投信、自營商或三大法人合計連續 N 日（預設 N=5）淨買超後的後續股價行為，含累積報酬、超額報酬分布、勝率、成交量變化與股票特徵分析。"),
]

TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | 財經數據分析平台</title>
<style>
  :root {{
    --bg: #0d1117; --bg-card: #161b22; --border: #30363d;
    --text: #e6edf3; --text-muted: #8b949e; --accent: #58a6ff;
    --orange: #d29922; --green: #3fb950; --radius: 8px;
  }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg); color: var(--text);
    font-family: 'Noto Sans TC', system-ui, sans-serif;
    min-height: 100vh; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 20px;
    padding: 40px 24px;
  }}
  .badge {{
    background: rgba(210,153,34,.15); color: var(--orange);
    border: 1px solid rgba(210,153,34,.35); border-radius: 20px;
    font-size: .78rem; font-weight: 700; padding: 4px 14px;
    letter-spacing: .06em; text-transform: uppercase;
  }}
  h1 {{ font-size: 1.6rem; font-weight: 800; color: var(--text); text-align: center; }}
  .desc {{
    max-width: 580px; text-align: center; font-size: .92rem;
    color: var(--text-muted); line-height: 1.8;
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 20px 24px;
  }}
  .btn-row {{ display: flex; gap: 12px; flex-wrap: wrap; justify-content: center; }}
  .btn-gen {{
    padding: 10px 28px; background: var(--green); border: none;
    border-radius: var(--radius); color: #fff; font-size: .92rem;
    font-weight: 700; cursor: pointer; transition: opacity .18s;
  }}
  .btn-gen:hover {{ opacity: .85; }}
  .btn-gen:disabled {{ opacity: .5; cursor: not-allowed; }}
  .back {{
    padding: 10px 24px; background: transparent;
    border: 1px solid var(--accent); border-radius: var(--radius);
    color: var(--accent); font-size: .88rem; text-decoration: none;
    transition: background .18s;
  }}
  .back:hover {{ background: rgba(88,166,255,.12); }}
  .status {{ font-size: .85rem; color: var(--text-muted); min-height: 24px; }}
  .note {{ font-size: .76rem; color: #6e7681; max-width: 480px; text-align: center; }}
</style>
</head>
<body>
  <div class="badge">報告建置中</div>
  <h1>{title}</h1>
  <div class="desc">{desc}</div>
  <div class="btn-row">
    <button class="btn-gen" id="gen-btn" onclick="generateReport()">⚙ 產生分析報告</button>
    <a href="javascript:history.back()" class="back">← 返回平台</a>
  </div>
  <div class="status" id="status-msg"></div>
  <p class="note">點擊「產生」後，腳本將載入全部股價資料並計算，需要數分鐘，完成後頁面自動重整。</p>
  <script>
  async function generateReport() {{
    const btn = document.getElementById('gen-btn');
    const msg = document.getElementById('status-msg');
    btn.disabled = true;
    btn.textContent = '⚙ 產生中，請稍候…';
    msg.textContent = '正在載入資料並計算，依資料量約需 2~5 分鐘…';
    try {{
      const res = await fetch('/api/report/generate/{report_id}', {{method:'POST'}});
      const data = await res.json();
      if (data.status === 'ok') {{
        msg.style.color = '#3fb950';
        msg.textContent = '✓ 報告產生完成，即將重新載入…';
        setTimeout(() => location.reload(), 1500);
      }} else {{
        msg.style.color = '#f85149';
        msg.textContent = '✗ 產生失敗：' + (data.message || '未知錯誤');
        btn.disabled = false; btn.textContent = '⚙ 重試';
      }}
    }} catch(e) {{
      msg.style.color = '#f85149';
      msg.textContent = '✗ 連線失敗：' + e.message;
      btn.disabled = false; btn.textContent = '⚙ 重試';
    }}
  }}
  </script>
</body>
</html>
"""

def main():
    base = os.path.dirname(os.path.abspath(__file__))
    for filename, report_id, title, desc in REPORTS:
        path = os.path.join(base, filename)
        html = TEMPLATE.format(title=title, desc=desc, report_id=report_id)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  建立：{filename}")
    print("完成")

if __name__ == "__main__":
    main()
