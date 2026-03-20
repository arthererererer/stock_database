"""
app.py — Flask 主應用
"""

import json
import math
import os
import subprocess
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template, request

import data_service as ds

# 引入統計報告產生器
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "private"))
import generate_stats as _gs

app = Flask(__name__)

# ── 資料快取（啟動時載入一次，可透過 /api/reload 重新載入）──────────────
_df             = None
_intl_df        = None
_fx_df          = None
_stock_price_df = None   # TEJ 股價資料庫（大檔案，首次使用時才載入）
_chip_df        = None   # TEJ 籌碼資料庫
_monthly_df     = None   # 董監持股月資料
_quarterly_df   = None   # 季財務報表


def get_df():
    global _df
    if _df is None:
        _df = ds.load_all_data()
    return _df


def get_intl_df():
    global _intl_df
    if _intl_df is None:
        _intl_df = ds.load_intl_index_data()
    return _intl_df


def get_fx_df():
    global _fx_df
    if _fx_df is None:
        _fx_df = ds.load_fx_data()
    return _fx_df


def get_stock_price_df():
    global _stock_price_df
    if _stock_price_df is None:
        _stock_price_df = ds.load_stock_price_data()
    return _stock_price_df


def get_chip_df():
    global _chip_df
    if _chip_df is None:
        _chip_df = ds.load_chip_data()
    return _chip_df


def get_monthly_df():
    global _monthly_df
    if _monthly_df is None:
        _monthly_df = ds.load_monthly_director_data()
    return _monthly_df


def get_quarterly_df():
    global _quarterly_df
    if _quarterly_df is None:
        _quarterly_df = ds.load_quarterly_data()
    return _quarterly_df


class _SafeEncoder(json.JSONEncoder):
    """處理 float NaN / Inf，轉為 null。"""
    def iterencode(self, o, _one_shot=False):
        return super().iterencode(o, _one_shot)

    def default(self, obj):
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        return super().default(obj)


def _json_resp(data):
    txt = json.dumps(data, ensure_ascii=False, cls=_SafeEncoder)
    # 替換 JSON 中殘存的 NaN / Infinity 字串（pandas 偶爾直接輸出）
    txt = txt.replace(": NaN", ": null").replace(": Infinity", ": null").replace(": -Infinity", ": null")
    return app.response_class(response=txt, mimetype="application/json")


# ── 頁面路由 ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── API 路由 ────────────────────────────────────────────────────────────

@app.route("/api/meta")
def api_meta():
    return _json_resp(ds.get_meta(get_df()))


@app.route("/api/gauge")
def api_gauge():
    return _json_resp(ds.get_gauge_data(get_df()))


@app.route("/api/timeseries")
def api_timeseries():
    start = request.args.get("start")
    end = request.args.get("end")
    return _json_resp(ds.get_timeseries_data(get_df(), start, end))


@app.route("/api/capital-flow")
def api_capital_flow():
    start = request.args.get("start")
    end = request.args.get("end")
    return _json_resp(ds.get_capital_flow_data(get_df(), start, end))


@app.route("/api/heatmap")
def api_heatmap():
    return _json_resp(ds.get_heatmap_data(get_df()))


@app.route("/api/market-amp")
def api_market_amp():
    """市場振幅大個股比例（由報告 a 產生時寫出），供大盤監控區使用。"""
    start = request.args.get("start")
    end = request.args.get("end")
    data = ds.get_market_amp_data(start, end)
    if data is None:
        return _json_resp({"status": "no_data", "message": "請先產生報告 a 以產生市場振幅資料"})
    return _json_resp(data)


@app.route("/api/feature-premium/meta")
def api_feature_premium_meta():
    """特徵溢酬監控：可選維度與因子特徵表日期範圍。"""
    return _json_resp(ds.get_feature_premium_meta())


@app.route("/api/feature-premium/series")
def api_feature_premium_series():
    """
    特徵溢酬監控：月再平衡雙重排序 tercile long–short 日序列與累積％、Y9999 超額對照。
    參數：dim1, dim2, start, end, show_mkt=1|0
    """
    dim1 = request.args.get("dim1", "")
    dim2 = request.args.get("dim2", "")
    start = request.args.get("start")
    end = request.args.get("end")
    show_mkt = request.args.get("show_mkt", "1") not in ("0", "false", "False", "")
    return _json_resp(
        ds.get_feature_premium_series(get_stock_price_df(), dim1, dim2, start, end, include_mkt=show_mkt)
    )


@app.route("/api/intl/indices")
def api_intl_indices():
    """回傳可用的國際指數清單與日期範圍。"""
    return _json_resp(ds.get_intl_indices_meta(get_intl_df()))


@app.route("/api/intl/chart-data")
def api_intl_chart_data():
    """回傳指定指數的原始數值、本幣/匯率/台幣累積報酬率數列。"""
    codes      = request.args.getlist("codes")
    start_date = request.args.get("start")
    end_date   = request.args.get("end")
    base_date  = request.args.get("base")
    return _json_resp(
        ds.get_intl_chart_data(get_intl_df(), get_fx_df(), codes, start_date, end_date, base_date)
    )


@app.route("/api/reload")
def api_reload():
    """重新載入所有 CSV（新增檔案後呼叫）。"""
    global _df, _intl_df, _fx_df, _stock_price_df, _chip_df, _monthly_df, _quarterly_df
    _df = _intl_df = _fx_df = None
    _stock_price_df = _chip_df = _monthly_df = _quarterly_df = None
    ds.invalidate_factor_chars_cache()
    df = get_df()
    return jsonify({"status": "ok", "rows": len(df)})


# ── 個股監控 API ─────────────────────────────────────────────────────────

@app.route("/api/stock/meta")
def api_stock_meta():
    """回傳個股清單、季資料可選欄位、日期範圍。"""
    price_df    = get_stock_price_df()
    quarterly_df = get_quarterly_df()
    return _json_resp({
        "stocks":            ds.get_stock_list(price_df),
        "quarterly_columns": ds.get_quarterly_columns(quarterly_df),
        "date_range":        ds.get_stock_date_range(price_df),
    })


@app.route("/api/stock/series")
def api_stock_series():
    """回傳指定個股的日頻股價 + 籌碼時序。"""
    codes = [c.strip() for c in request.args.get("codes", "").split(",") if c.strip()]
    start = request.args.get("start")
    end   = request.args.get("end")
    return _json_resp(
        ds.get_stock_series(get_stock_price_df(), get_chip_df(), codes, start, end)
    )


@app.route("/api/stock/monthly")
def api_stock_monthly():
    """回傳指定個股的月頻董監持股資料。"""
    codes = [c.strip() for c in request.args.get("codes", "").split(",") if c.strip()]
    return _json_resp(ds.get_monthly_director(get_monthly_df(), codes))


@app.route("/api/stock/quarterly")
def api_stock_quarterly():
    """回傳指定個股的季頻財務資料（使用者指定欄位）。"""
    codes = [c.strip() for c in request.args.get("codes", "").split(",") if c.strip()]
    cols  = [c.strip() for c in request.args.get("cols",  "").split(",") if c.strip()]
    return _json_resp(ds.get_quarterly_series(get_quarterly_df(), codes, cols))


# ── 事件研究 CSV API ─────────────────────────────────────────────────────

@app.route("/api/event-csv/generate", methods=["POST"])
def api_generate_event_csv():
    """觸發事件研究 CSV 產生腳本。"""
    script = Path(__file__).parent / "scripts" / "generate_event_csv.py"
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            return jsonify({"status": "ok", "message": result.stdout.strip()})
        else:
            return jsonify({"status": "error", "message": result.stderr.strip()}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "message": "腳本執行超時（>5 分鐘）"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/report-a/consolidate", methods=["POST"])
def api_consolidate_report_a():
    """觸發報告 a 來源資料統合腳本，產生單一 CSV 以加速報告產生。"""
    script = Path(__file__).parent / "scripts" / "consolidate_report_a_data.py"
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            return jsonify({"status": "ok", "message": result.stdout.strip()})
        else:
            return jsonify({"status": "error", "message": result.stderr.strip()}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "message": "腳本執行超時（>5 分鐘）"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/stats")
def stats_page():
    """提供統計分布報告頁面（初次訪問時若報告不存在則自動產生）。"""
    if not os.path.exists(_gs.OUTPUT_PATH):
        _gs.generate(get_df())
    with open(_gs.OUTPUT_PATH, "r", encoding="utf-8") as f:
        return f.read()


@app.route("/private/<path:filename>")
def private_file(filename):
    """提供 private/ 資料夾內的靜態 HTML 研究報告。"""
    from flask import abort, send_from_directory
    private_dir = os.path.join(os.path.dirname(__file__), "private")
    filepath = os.path.join(private_dir, filename)
    if not os.path.exists(filepath):
        abort(404)
    return send_from_directory(private_dir, filename)


# 報告代碼 → 腳本檔名對照
_REPORT_SCRIPTS = {
    "a": "generate_report_a.py",
    "b": "generate_report_b.py",
    "c": "generate_report_c.py",
    "d": "generate_report_d.py",
    "e": "generate_report_e.py",
    "f": "generate_report_f.py",
    "g": "generate_report_g.py",
    "h": "generate_report_h.py",
    "i": "generate_report_i.py",
}


@app.route("/api/report/generate/<report_id>", methods=["POST"])
def api_generate_report(report_id):
    """觸發指定研究報告的 Python 腳本重新產生 HTML。"""
    if report_id not in _REPORT_SCRIPTS:
        return jsonify({"status": "error", "message": f"未知報告代碼：{report_id}"}), 400

    script = Path(__file__).parent / "scripts" / _REPORT_SCRIPTS[report_id]
    if not script.exists():
        return jsonify({"status": "error", "message": f"腳本尚未建立：{script.name}"}), 404

    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode == 0:
            msg = (result.stdout or "")[-500:]
            return jsonify({"status": "ok", "message": msg})
        else:
            msg = (result.stderr or "")[-500:]
            return jsonify({"status": "error", "message": msg}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "message": "腳本執行超時（>10 分鐘）"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


_REPORT_PDF_IDS = {"a"}  # 目前支援 PDF 匯出的報告

@app.route("/api/report/export-pdf/<report_id>", methods=["POST"], endpoint="report_export_pdf")
def api_export_report_pdf(report_id):
    """將指定報告 HTML 轉為 PDF 並回傳下載。"""
    if report_id not in _REPORT_PDF_IDS:
        return jsonify({"status": "error", "message": f"報告 {report_id} 尚未支援 PDF 匯出"}), 400

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return jsonify({"status": "error", "message": "請先執行：pip install playwright && playwright install chromium"}), 500

    base_url = request.url_root.rstrip("/")
    report_url = f"{base_url}/private/report_{report_id}.html"

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        pdf_path = tmp.name

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(report_url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(6000)  # 等待所有 Plotly 圖表渲染
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")  # 捲到底觸發 lazy render
            page.wait_for_timeout(2000)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)
            page.pdf(path=pdf_path, format="A4", margin={"top": "12mm", "right": "12mm", "bottom": "12mm", "left": "12mm"},
                    print_background=True)
            browser.close()

        from flask import send_file
        filename = f"報告{report_id}_振幅分析.pdf" if report_id == "a" else f"報告{report_id}.pdf"
        return send_file(pdf_path, mimetype="application/pdf", as_attachment=True, download_name=filename)
    except Exception as e:
        if os.path.exists(pdf_path):
            try:
                os.unlink(pdf_path)
            except OSError:
                pass
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/regen-stats")
def api_regen_stats():
    """重新產生統計分布報告（讀取最新 CSV 資料）。"""
    global _df
    _df = None  # 強制重新載入 CSV
    try:
        _gs.generate(get_df())
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# ── 啟動 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=5000)
