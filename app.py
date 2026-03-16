"""
app.py — Flask 主應用
"""

import json
import math

from flask import Flask, jsonify, render_template, request

import data_service as ds

app = Flask(__name__)

# ── 資料快取（啟動時載入一次，可透過 /api/reload 重新載入）──────────────
_df      = None
_intl_df = None
_fx_df   = None


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
    global _df, _intl_df, _fx_df
    _df = _intl_df = _fx_df = None
    df = get_df()
    return jsonify({"status": "ok", "rows": len(df)})


# ── 啟動 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=5000)
