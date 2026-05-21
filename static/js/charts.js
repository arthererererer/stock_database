/* charts.js — 財經數據分析平台前端圖表邏輯 */

'use strict';

// ── 顏色常數 ──────────────────────────────────────────────────────────
const C = {
  bg:        '#161b22',
  bgCard:    '#1c2128',
  border:    '#30363d',
  text:      '#e6edf3',
  textMuted: '#8b949e',
  textDim:   '#6e7681',
  green:     '#3fb950',
  red:       '#f85149',
  orange:    '#d29922',
  blue:      '#58a6ff',
  purple:    '#bc8cff',
  yellow:    '#e3b341',
  teal:      '#39d0d8',
  // 各市場專屬色
  secColors: {
    'OTC992 上櫃-股票':  '#58a6ff',
    'REG991 興櫃-一般版': '#d29922',
    'Y99992 上市-股票':  '#3fb950',
  },
};

// ── 共用 Plotly 版面配置 ───────────────────────────────────────────────
function baseLayout(extra = {}) {
  return Object.assign({
    paper_bgcolor: C.bg,
    plot_bgcolor:  C.bg,
    font:   { color: C.text, family: 'Inter, Noto Sans TC, system-ui' },
    xaxis:  { gridcolor: C.border, linecolor: C.border, zerolinecolor: C.border, tickfont: { color: C.textMuted } },
    yaxis:  { gridcolor: C.border, linecolor: C.border, zerolinecolor: C.border, tickfont: { color: C.textMuted } },
    legend: { bgcolor: 'rgba(0,0,0,0)', font: { color: C.text }, orientation: 'h', y: -0.18 },
    margin: { t: 36, r: 24, b: 60, l: 72 },
    hovermode: 'x unified',
    hoverlabel: { bgcolor: C.bgCard, bordercolor: C.border, font: { color: C.text } },
    autosize: true,
  }, extra);
}

const PLOTLY_CONFIG = {
  responsive: true,
  displaylogo: false,
  modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'],
};

/** 與後端 BREADTH_AMP_CORR_LAG_DEFAULT_* 一致：交叉相關滯後 k 範圍（交易日） */
const BREADTH_AMP_CORR_LAG_MIN = -20;
const BREADTH_AMP_CORR_LAG_MAX = 20;

function breadthAmpCorrUrl() {
  const fs = state.corrFullSample ? '1' : '0';
  const s = encodeURIComponent(state.startDate);
  const e = encodeURIComponent(state.endDate);
  return `/api/breadth-amp-correlation?start=${s}&end=${e}&full_sample=${fs}`
    + `&lag_min=${BREADTH_AMP_CORR_LAG_MIN}&lag_max=${BREADTH_AMP_CORR_LAG_MAX}`;
}

// ── 狀態 ──────────────────────────────────────────────────────────────
const state = {
  meta:            null,
  timeseriesData:  null,
  changeDistData:  null,
  marketAmpData:   null,
  breadthAmpCorr:  null,
  corrFullSample:  false,
  heatmapData:     null,
  startDate:       null,
  endDate:         null,
};

/** 大盤監控「類股表現」區塊：bootstrap 與比較個股代碼 */
const sectorPanelState = {
  bootstrap:    null,
  compareCodes: new Set(),
};
let sectorLinesDebounce = null;
let sectorPanelEventsBound = false;

// ── 工具函數 ──────────────────────────────────────────────────────────
function subtractMonths(dateStr, months) {
  const d = new Date(dateStr);
  d.setMonth(d.getMonth() - months);
  return d.toISOString().slice(0, 10);
}

/** 時序 API 中排除全市場合併鍵，僅回傳分市場標的 */
function timeseriesMarkets(ts) {
  if (!ts) return [];
  return Object.entries(ts).filter(
    ([k, d]) => k !== 'unified_breadth' && d && Array.isArray(d.dates),
  );
}

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`API 錯誤：${url}`);
  return res.json();
}

function showLoading(show) {
  const el = document.getElementById('loading-overlay');
  if (!el) return;
  if (show) el.classList.remove('hidden');
  else      el.classList.add('hidden');
}

// ── 1. 市場廣度熱力圖 ─────────────────────────────────────────────────
function renderHeatmap(data) {
  const z = data.securities.map(code => data.values[code]);
  const yLabels = data.labels;

  const trace = {
    type: 'heatmap',
    x: data.dates,
    y: yLabels,
    z: z,
    colorscale: [
      [0,    '#7b1d1d'],
      [0.25, '#c0392b'],
      [0.45, '#e67e22'],
      [0.5,  '#95a5a6'],
      [0.55, '#27ae60'],
      [0.75, '#1e8449'],
      [1,    '#0d4f2e'],
    ],
    zmin: 0, zmax: 100,
    colorbar: {
      title: { text: '上漲%', font: { color: C.textMuted } },
      tickfont: { color: C.textMuted },
      bgcolor: C.bg,
      bordercolor: C.border,
      len: 0.8,
    },
    hovertemplate: '%{x}<br>%{y}<br>上漲比例：%{z:.1f}%<extra></extra>',
  };

  const layout = baseLayout({
    height: 220,
    margin: { t: 16, r: 80, b: 60, l: 80 },
    xaxis: { tickangle: -45, nticks: 20 },
    yaxis: { autorange: 'reversed' },
    hovermode: 'closest',
  });

  Plotly.newPlot('chart-heatmap', [trace], layout, PLOTLY_CONFIG);
}

// ── 3. 各市場漲跌比例折線圖（3張）───────────────────────────────────
function renderLineCharts(data) {
  const container = document.getElementById('line-charts-row');
  container.innerHTML = '';

  Object.entries(data).forEach(([code, d]) => {
    const divId = `line-${code.replace(/\s+/g, '-')}`;
    const div = document.createElement('div');
    div.className = 'chart-card';
    div.id = divId;
    container.appendChild(div);

    const secColor = C.secColors[code] || C.blue;

    const traces = [
      {
        name: '上漲%', x: d.dates, y: d['上漲比例'],
        type: 'scatter', mode: 'lines',
        line: { color: C.green, width: 1.5 },
        hovertemplate: '%{y:.1f}%<extra>上漲</extra>',
      },
      {
        name: '下跌%', x: d.dates, y: d['下跌比例'],
        type: 'scatter', mode: 'lines',
        line: { color: C.red, width: 1.5 },
        hovertemplate: '%{y:.1f}%<extra>下跌</extra>',
      },
      {
        name: '漲停%', x: d.dates, y: d['漲停比例'],
        type: 'scatter', mode: 'lines',
        line: { color: '#00e676', width: 1.2, dash: 'dot' },
        hovertemplate: '%{y:.2f}%<extra>漲停</extra>',
      },
      {
        name: '跌停%', x: d.dates, y: d['跌停比例'],
        type: 'scatter', mode: 'lines',
        line: { color: '#ff5252', width: 1.2, dash: 'dot' },
        hovertemplate: '%{y:.2f}%<extra>跌停</extra>',
      },
    ];

    const layout = baseLayout({
      title: { text: `<b>${d.label}</b>`, font: { size: 13, color: secColor }, x: 0.04 },
      height: 320,
      yaxis: { ticksuffix: '%' },
      margin: { t: 40, r: 16, b: 70, l: 56 },
    });

    Plotly.newPlot(divId, traces, layout, PLOTLY_CONFIG);
  });
}

// ── 3a. 每日振幅大個股比例 ────────────────────────────────────────────
function renderMarketAmpChart(data) {
  const container = document.getElementById('chart-market-amp');
  if (!container) return;
  if (!data || data.status === 'no_data' || !data.dates || data.dates.length === 0) {
    container.innerHTML = '<div class="no-data-hint" style="padding:24px;text-align:center;color:var(--muted);">請先產生報告 a 以產生市場振幅資料</div>';
    return;
  }
  const traces = [
    { name: '振幅大比例%', x: data.dates, y: data.amp_big_pct, type: 'scatter', mode: 'lines',
      line: { color: C.blue, width: 1.5 }, hovertemplate: '%{y:.2f}%<extra>振幅大比例</extra>' },
    { name: '90th（偏多門檻）', x: data.dates, y: data.mkt_hi90, type: 'scatter', mode: 'lines',
      line: { color: C.yellow, width: 1, dash: 'dash' }, hovertemplate: '%{y:.2f}%<extra>90th</extra>' },
    { name: '10th（偏少門檻）', x: data.dates, y: data.mkt_lo10, type: 'scatter', mode: 'lines',
      line: { color: C.textDim, width: 1, dash: 'dash' }, hovertemplate: '%{y:.2f}%<extra>10th</extra>' },
  ];
  const layout = baseLayout({
    height: 320, yaxis: { ticksuffix: '%', title: { text: '振幅大個股比例（%）', font: { color: C.textMuted } } },
  });
  Plotly.newPlot('chart-market-amp', traces, layout, PLOTLY_CONFIG);
}

// ── 3b. 合併廣度滾動標準差 σ_t = std(B 過去 n 日)（上市＋上櫃＋興櫃）────────
function renderBreadthVolatility(ts) {
  const u = ts && ts.unified_breadth;
  const el = document.getElementById('chart-breadth-volatility');
  if (!el) return;
  if (!u || !u.dates || u.dates.length === 0) {
    el.innerHTML = '<div class="no-data-hint" style="padding:24px;text-align:center;color:#8b949e;">無廣度資料</div>';
    return;
  }
  const w = Number(u.滾動標準差視窗 ?? u.滾動波動視窗) || 10;
  const yVol = u.滾動標準差 ?? u.滾動波動率;
  if (!yVol || !Array.isArray(yVol)) {
    el.innerHTML = '<div class="no-data-hint" style="padding:24px;text-align:center;color:#8b949e;">無滾動標準差資料</div>';
    return;
  }

  const trace = {
    name: `σ（${w}日廣度）`,
    x: u.dates,
    y: yVol,
    type: 'scatter',
    mode: 'lines',
    line: { color: C.purple, width: 1.8 },
    connectgaps: false,
    hovertemplate: '%{y:.2f} 百分點<extra>廣度滾動標準差</extra>',
  };

  const layout = baseLayout({
    height: 320,
    yaxis: {
      title: { text: '滾動標準差（百分點）', font: { color: C.textMuted } },
      rangemode: 'tozero',
    },
    margin: { t: 28, r: 16, b: 60, l: 72 },
    legend: { orientation: 'h', y: -0.12 },
  });

  Plotly.newPlot('chart-breadth-volatility', [trace], layout, PLOTLY_CONFIG);
}

/** σ（廣度滾動標準差）與振幅大比例之皮爾森相關（滯後 k 由 API／lag_range 決定，預設 ±20 交易日） */
function renderBreadthAmpCorrelation(data) {
  const el = document.getElementById('breadth-amp-corr-panel');
  if (!el) return;
  if (!data || data.status !== 'ok' || !Array.isArray(data.lags)) {
    const msg = (data && data.message) || '無法計算相關係數（需廣度資料且已產生報告 a）';
    el.innerHTML = `<div class="breadth-amp-corr-hint">${msg}</div>`;
    return;
  }
  const dr = data.date_range || {};
  const lr = data.lag_range || {};
  const lrTxt = (lr.min != null && lr.max != null) ? `滯後 k：${lr.min}～${lr.max}` : '';
  const sampleTag = data.full_sample ? '全樣本' : '依上方時間範圍';
  const sub = (data.definition || '').replace(/</g, '&lt;');
  const rows = data.lags.map((row) => {
    const r = row.pearson_r;
    const rs = r === null || r === undefined || Number.isNaN(r) ? '—' : Number(r).toFixed(4);
    return `<tr><td>${row.label}</td><td class="num">${rs}</td><td class="num">${row.n}</td></tr>`;
  }).join('');
  el.innerHTML = `
    <div class="breadth-amp-corr-head">
      <span class="breadth-amp-corr-title">σ 與振幅大比例：皮爾森相關（滯後對齊）</span>
      <span class="breadth-amp-corr-meta">${dr.start || ''} ～ ${dr.end || ''} · 交集 ${data.intersection_trading_days ?? '—'} 交易日 · ${sampleTag}${lrTxt ? ` · ${lrTxt}` : ''}</span>
    </div>
    <p class="breadth-amp-corr-def">${sub}</p>
    <div class="breadth-amp-corr-table-wrap">
    <table class="breadth-amp-corr-table">
      <thead><tr><th>振幅比例時點（相對 σ）</th><th>皮爾森 r</th><th>配對 n</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    </div>`;
}

// ── 4. 市場廣度震盪指標（全市場合併）──────────────────────────────────
function renderBreadth(ts) {
  const u = ts && ts.unified_breadth;
  const el = document.getElementById('chart-breadth');
  if (!el) return;
  if (!u || !u.dates || u.dates.length === 0) {
    el.innerHTML = '<div class="no-data-hint" style="padding:24px;text-align:center;color:#8b949e;">無廣度資料</div>';
    return;
  }
  const trace = {
    name: u.label,
    x: u.dates,
    y: u['廣度震盪'],
    type: 'bar',
    marker: {
      color: u['廣度震盪'].map(v => (v === null ? C.textDim : (v >= 0 ? C.red : C.green))),
    },
    hovertemplate: '%{y:.1f}%<extra>' + u.label + '</extra>',
  };

  const layout = baseLayout({
    height: 380,
    yaxis: { ticksuffix: '%', zeroline: true, zerolinecolor: C.textMuted, zerolinewidth: 1 },
    shapes: [{
      type: 'line', xref: 'paper', x0: 0, x1: 1,
      y0: 0, y1: 0, line: { color: C.textMuted, width: 1 },
    }],
  });

  Plotly.newPlot('chart-breadth', [trace], layout, PLOTLY_CONFIG);
}

// ── 5. 漲跌幅區間家數長條圖（與廣度同列）──────────────────────────────
const DIST_BAR_COLORS = [
  '#c62828', '#e53935', '#ef5350', '#ffab91',
  '#78909c',
  '#a5d6a7', '#66bb6a', '#2e7d32', '#1b5e20',
];

function renderChangeDistribution(dist) {
  const plotEl = document.getElementById('chart-change-dist');
  const sumEl  = document.getElementById('change-dist-summary');
  if (!plotEl) return;

  if (!dist || dist.status === 'no_data' || !dist.counts || dist.counts.length === 0) {
    plotEl.innerHTML =
      '<div class="no-data-hint" style="padding:20px;text-align:center;color:#8b949e;font-size:.88rem;">' +
      (dist && dist.message ? dist.message : '無法載入漲跌幅分布（請確認 TEJ 股價資料庫路徑與檔案）') +
      '</div>';
    if (sumEl) sumEl.innerHTML = '';
    return;
  }

  const labels = dist.labels || [];
  const counts = dist.counts;
  const text = counts.map(n => (n != null ? String(n) : ''));

  const trace = {
    type: 'bar',
    x: labels,
    y: counts,
    text,
    textposition: 'outside',
    textfont: { color: C.text, size: 11 },
    marker: {
      color: DIST_BAR_COLORS,
      line: { width: 0 },
    },
    hovertemplate: '%{x}<br>家數：%{y}<extra></extra>',
  };

  const layout = baseLayout({
    height: 380,
    margin: { t: 28, r: 16, b: 88, l: 56 },
    xaxis: {
      tickangle: -48,
      tickfont: { size: 10, color: C.textMuted },
      automargin: true,
    },
    yaxis: {
      title: { text: '家數', font: { color: C.textMuted } },
      rangemode: 'tozero',
    },
    showlegend: false,
  });

  Plotly.newPlot('chart-change-dist', [trace], layout, PLOTLY_CONFIG);

  if (sumEl) {
    const adv = dist.advancing || 0;
    const fl  = dist.flat || 0;
    const dec = dist.declining || 0;
    const tot = adv + fl + dec;
    const pct = t => (tot > 0 ? ((t / tot) * 100).toFixed(1) : '0.0');
    sumEl.innerHTML = `
      <div class="dist-summary-caption">上漲／平盤／下跌 概況（${dist.date || ''}，共 ${tot} 檔）</div>
      <div class="dist-summary-bar" role="img" aria-label="上漲平盤下跌比例">
        <span class="ds-seg ds-up" style="width:${pct(adv)}%"></span>
        <span class="ds-seg ds-flat" style="width:${pct(fl)}%"></span>
        <span class="ds-seg ds-down" style="width:${pct(dec)}%"></span>
      </div>
      <div class="dist-summary-legend">
        <span><i class="ds-dot ds-up"></i>上漲 ${adv}（${pct(adv)}%）</span>
        <span><i class="ds-dot ds-flat"></i>平盤 ${fl}（${pct(fl)}%）</span>
        <span><i class="ds-dot ds-down"></i>下跌 ${dec}（${pct(dec)}%）</span>
      </div>`;
  }
}

// ── 6. 漲停/跌停比率折線圖 ───────────────────────────────────────────
function renderLimitRatio(data) {
  const traces = Object.entries(data).map(([code, d]) => ({
    name: d.label,
    x: d.dates, y: d['漲跌停比'],
    type: 'scatter', mode: 'lines',
    line: { color: C.secColors[code] || C.blue, width: 1.8 },
    hovertemplate: '%{y:.2f}<extra>' + d.label + '</extra>',
  }));

  const layout = baseLayout({
    height: 360,
    shapes: [{
      type: 'line', xref: 'paper', x0: 0, x1: 1,
      y0: 1, y1: 1, line: { color: C.textDim, width: 1, dash: 'dash' },
    }],
    annotations: [{
      x: 1, y: 1, xref: 'paper', yref: 'y',
      text: '1.0 均衡線', showarrow: false,
      font: { color: C.textDim, size: 11 },
      xanchor: 'right', yanchor: 'bottom',
    }],
    yaxis: { title: { text: '漲停 ÷ 跌停', font: { color: C.textMuted } } },
  });

  Plotly.newPlot('chart-limit-ratio', traces, layout, PLOTLY_CONFIG);
}

// ── 工具：hex 轉 rgba ─────────────────────────────────────────────────
function hexToRgba(hex, alpha) {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ── 渲染所有時序圖表 ──────────────────────────────────────────────────
function renderTimeCharts() {
  const ts = state.timeseriesData;
  if (!ts) return;

  renderBreadth(ts);
  renderChangeDistribution(state.changeDistData);
  renderBreadthVolatility(ts);
  renderMarketAmpChart(state.marketAmpData);
  renderBreadthAmpCorrelation(state.breadthAmpCorr);
}

// ── 載入時序資料並更新圖表 ────────────────────────────────────────────
async function loadAndRenderTimeCharts() {
  const s = state.startDate;
  const e = state.endDate;
  const [ts, dist, marketAmp, breadthAmpCorr] = await Promise.all([
    fetchJSON(`/api/timeseries?start=${s}&end=${e}`),
    fetchJSON('/api/change-distribution').catch(() => ({ status: 'no_data', message: '漲跌幅分布載入失敗' })),
    fetchJSON(`/api/market-amp?start=${s}&end=${e}`).catch(() => null),
    fetchJSON(breadthAmpCorrUrl()).catch(() => null),
  ]);
  state.timeseriesData  = ts;
  state.changeDistData  = dist;
  state.marketAmpData   = marketAmp;
  state.breadthAmpCorr  = breadthAmpCorr;
  renderTimeCharts();
  if (!sectorPanelState.bootstrap) {
    await loadSectorPanelBootstrap().catch((err) =>
      console.error('類股面板載入失敗', err),
    );
  } else {
    scheduleSectorLinesLoad();
  }
}

// ── 日期篩選器 ────────────────────────────────────────────────────────
function initDatePicker() {
  const meta = state.meta;
  const maxDate = meta.date_range.max;
  const defStart = subtractMonths(maxDate, 12);

  state.startDate = defStart;
  state.endDate   = maxDate;

  const startEl = document.getElementById('date-start');
  const endEl   = document.getElementById('date-end');
  startEl.value = defStart;
  endEl.value   = maxDate;
  startEl.min   = meta.date_range.min;
  startEl.max   = maxDate;
  endEl.min     = meta.date_range.min;
  endEl.max     = maxDate;

  document.getElementById('btn-apply').addEventListener('click', async () => {
    state.startDate = startEl.value;
    state.endDate   = endEl.value;
    showLoading(true);
    await loadAndRenderTimeCharts();
    showLoading(false);
  });

  document.querySelectorAll('.btn-preset').forEach(btn => {
    btn.addEventListener('click', async () => {
      document.querySelectorAll('.btn-preset').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const months = parseInt(btn.dataset.months, 10);
      const newStart = subtractMonths(maxDate, months);
      startEl.value   = newStart;
      state.startDate = newStart;
      state.endDate   = maxDate;
      showLoading(true);
      await loadAndRenderTimeCharts();
      showLoading(false);
    });
  });
}

async function loadBreadthAmpCorrelationOnly() {
  try {
    const d = await fetchJSON(breadthAmpCorrUrl());
    state.breadthAmpCorr = d;
    renderBreadthAmpCorrelation(d);
  } catch (e) {
    state.breadthAmpCorr = null;
    renderBreadthAmpCorrelation(null);
  }
}

function initBreadthAmpCorrOptions() {
  const cb = document.getElementById('breadth-amp-corr-fullsample');
  if (!cb) return;
  cb.checked = state.corrFullSample;
  cb.addEventListener('change', async () => {
    state.corrFullSample = cb.checked;
    await loadBreadthAmpCorrelationOnly();
  });
}

// ── 重新載入按鈕 ──────────────────────────────────────────────────────
function initReloadBtn() {
  document.getElementById('btn-reload').addEventListener('click', async () => {
    showLoading(true);
    await fetchJSON('/api/reload');
    sectorPanelState.bootstrap = null;
    await loadAndRenderTimeCharts();
    showLoading(false);
  });
}

// ── 頁籤切換 ─────────────────────────────────────────────────────────
function initTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
      const tab = document.getElementById(`tab-${btn.dataset.tab}`);
      if (tab) tab.classList.add('active');

      // 各區首次切換時初始化
      if (btn.dataset.tab === 'intl')  initIntlTab();
      if (btn.dataset.tab === 'stock') initStockTab();
    });
  });
}

// ── 大盤監控：類股表現（橫條 + 折線）───────────────────────────────────
function bindSectorPanelEventsOnce() {
  if (sectorPanelEventsBound) return;
  sectorPanelEventsBound = true;
  const addBtn = document.getElementById('sector-compare-add');
  const inp = document.getElementById('sector-compare-stock-input');
  const filt = document.getElementById('sector-filter-input');
  if (addBtn && inp) {
    addBtn.addEventListener('click', () => {
      if (inp.value.trim()) sectorPanelAddCompareStocks(inp.value);
      inp.value = '';
    });
  }
  if (filt) {
    filt.addEventListener('input', () => {
      const q = filt.value.trim().toLowerCase();
      document.querySelectorAll('.spc-sector-block').forEach((block) => {
        const nm = (block.dataset.sectorName || '').toLowerCase();
        block.classList.toggle('hidden-filter', q.length > 0 && !nm.includes(q));
      });
    });
  }
}

function sectorPanelStockMap() {
  const b = sectorPanelState.bootstrap;
  if (!b || !b.stock_universe) return new Map();
  return new Map(b.stock_universe.map((s) => [s.code, s.name]));
}

function sectorPanelAddCompareStocks(raw) {
  const map = sectorPanelStockMap();
  String(raw)
    .split(/[,，\s]+/)
    .map((x) => x.trim())
    .filter(Boolean)
    .forEach((c) => {
      if (map.has(c)) sectorPanelState.compareCodes.add(c);
    });
  sectorPanelRenderStockTags();
  scheduleSectorLinesLoad();
}

function sectorPanelRenderStockTags() {
  const div = document.getElementById('sector-line-stock-tags');
  if (!div) return;
  const map = sectorPanelStockMap();
  div.innerHTML = '';
  sectorPanelState.compareCodes.forEach((code) => {
    const tag = document.createElement('span');
    tag.className = 'spc-stock-tag';
    const nm = map.get(code) || '';
    tag.appendChild(document.createTextNode(`${code} ${nm}`.trim() + ' '));
    const rm = document.createElement('button');
    rm.type = 'button';
    rm.setAttribute('aria-label', '移除');
    rm.textContent = '×';
    rm.addEventListener('click', () => {
      sectorPanelState.compareCodes.delete(code);
      sectorPanelRenderStockTags();
      scheduleSectorLinesLoad();
    });
    tag.appendChild(rm);
    div.appendChild(tag);
  });
}

function renderSectorBarChart(b) {
  const el = document.getElementById('chart-sector-bars');
  if (!el) return;
  if (!b.bars || b.bars.length === 0) {
    el.innerHTML =
      '<div class="no-data-hint" style="padding:24px;text-align:center;color:#8b949e;">無符合條件之類股（清單內需至少 3 檔有效成分）</div>';
    return;
  }
  const names = b.bars.map((x) => x.name);
  const weights = b.bars.map((x) =>
    x.weight_pct_sum != null ? Number(x.weight_pct_sum) : 0,
  );
  const changes = b.bars.map((x) =>
    x.avg_change_pct != null ? Number(x.avg_change_pct) : null,
  );
  const maxW = Math.max(...weights, 0.01);
  const maxLabelLen = Math.max(...names.map((s) => s.length), 4);

  const textOnBar = b.bars.map((row, i) =>
    row.weight_pct_sum != null ? `${Number(row.weight_pct_sum).toFixed(2)}%` : '—',
  );

  const trace = {
    type: 'bar',
    orientation: 'h',
    y: names,
    x: weights,
    text: textOnBar,
    textposition: weights.map((w) => (w >= maxW * 0.14 ? 'inside' : 'outside')),
    insidetextfont: { color: '#fff', size: 11 },
    outsidetextfont: { color: C.textMuted, size: 11 },
    marker: { color: '#3b82f6' },
    hovertemplate: '%{y}<br>市值占比加總：%{x:.2f}%<extra></extra>',
  };

  const annotations = changes.map((c, i) => ({
    x: maxW * 1.05,
    y: names[i],
    xref: 'x',
    yref: 'y',
    text: c === null ? '—' : `${c >= 0 ? '+' : ''}${c.toFixed(2)}%`,
    showarrow: false,
    xanchor: 'left',
    font: {
      color: c === null ? C.textMuted : c >= 0 ? C.red : C.green,
      size: 12,
    },
  }));
  annotations.push({
    xref: 'paper',
    yref: 'paper',
    x: 1,
    y: 1.02,
    text: '較前一日',
    showarrow: false,
    xanchor: 'right',
    font: { color: C.textMuted, size: 11 },
  });

  const layout = baseLayout({
    title: {
      text: `<b>平均漲幅前八大類股</b> <span style="font-size:11px;color:${C.textMuted}">${b.as_of}</span>`,
      font: { size: 14 },
    },
    height: Math.max(460, names.length * 46 + 88),
    margin: { t: 52, r: 96, b: 44, l: Math.min(200, 8 + maxLabelLen * 14) },
    xaxis: {
      title: { text: '市值比重％（類股內加總）', font: { color: C.textMuted } },
      range: [0, maxW * 1.28],
      gridcolor: C.border,
    },
    yaxis: { automargin: true, autorange: 'reversed' },
    annotations,
    showlegend: false,
  });

  Plotly.newPlot(el, [trace], layout, PLOTLY_CONFIG);
}

function buildSectorLineControls(b) {
  const wrap = document.getElementById('sector-line-sector-checks');
  if (!wrap) return;
  wrap.innerHTML = '';

  b.sectors.forEach((s) => {
    const block = document.createElement('div');
    block.className = 'spc-sector-block';
    block.dataset.sectorName = s.name;

    const row = document.createElement('div');
    row.className = 'spc-sector-head';

    const master = document.createElement('input');
    master.type = 'checkbox';
    master.className = 'spc-sector-master';
    master.dataset.sectorId = s.id;
    master.dataset.sectorName = s.name;
    master.checked = false;

    const lbl = document.createElement('label');
    lbl.appendChild(master);
    lbl.appendChild(
      document.createTextNode(` ${s.name}（${s.member_count}檔）`),
    );

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'spc-toggle-mem';
    btn.textContent = '展開成分';
    let expanded = false;

    const memDiv = document.createElement('div');
    memDiv.className = 'spc-members';
    memDiv.style.display = 'none';

    s.members.forEach((m) => {
      const lab = document.createElement('label');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.className = 'spc-mem-chk';
      cb.dataset.sectorId = s.id;
      cb.dataset.code = m.code;
      cb.checked = !!m.in_default_avg;
      lab.appendChild(cb);
      lab.appendChild(document.createTextNode(` ${m.code} ${m.name}`));
      memDiv.appendChild(lab);
    });

    btn.addEventListener('click', () => {
      expanded = !expanded;
      memDiv.style.display = expanded ? 'flex' : 'none';
      btn.textContent = expanded ? '收合成分' : '展開成分';
    });

    const syncMemDisabled = () => {
      memDiv.querySelectorAll('.spc-mem-chk').forEach((ic) => {
        ic.disabled = !master.checked;
      });
    };
    syncMemDisabled();
    master.addEventListener('change', () => {
      syncMemDisabled();
      scheduleSectorLinesLoad();
    });
    memDiv.querySelectorAll('.spc-mem-chk').forEach((ic) => {
      ic.addEventListener('change', scheduleSectorLinesLoad);
    });

    row.appendChild(lbl);
    row.appendChild(btn);
    block.appendChild(row);
    block.appendChild(memDiv);
    wrap.appendChild(block);
  });
}

function collectSectorPanelSelection() {
  const sector_series = [];
  document.querySelectorAll('.spc-sector-master:checked').forEach((master) => {
    const id = master.dataset.sectorId;
    const name = master.dataset.sectorName;
    const codes = [];
    document
      .querySelectorAll(`.spc-mem-chk[data-sector-id="${id}"]:checked`)
      .forEach((cb) => {
        if (!cb.disabled) codes.push(cb.dataset.code);
      });
    if (codes.length) sector_series.push({ id, name, codes });
  });
  const stock_codes = Array.from(sectorPanelState.compareCodes);
  return { sector_series, stock_codes };
}

function scheduleSectorLinesLoad() {
  if (sectorLinesDebounce) clearTimeout(sectorLinesDebounce);
  sectorLinesDebounce = setTimeout(() => {
    sectorLinesDebounce = null;
    loadSectorLineChart();
  }, 320);
}

async function loadSectorLineChart() {
  const el = document.getElementById('chart-sector-lines');
  if (!el) return;
  const b = sectorPanelState.bootstrap;
  if (!b || b.status !== 'ok') {
    renderSectorInstitutionalEmpty();
    return;
  }

  const { sector_series, stock_codes } = collectSectorPanelSelection();

  if (sector_series.length === 0 && stock_codes.length === 0) {
    renderSectorLineChart({ status: 'ok', series: [] });
    renderSectorValuationEmpty();
    renderSectorInstitutionalEmpty();
    return;
  }

  const body = JSON.stringify({
    start: state.startDate,
    end: state.endDate,
    sector_series,
    stock_codes,
  });
  let res;
  let val;
  let inst;
  try {
    [res, val, inst] = await Promise.all([
      fetch('/api/sector-performance/lines', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
      }).then((r) => r.json()),
      fetch('/api/sector-performance/valuation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
      }).then((r) => r.json()),
      fetch('/api/sector-performance/institutional', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
      }).then((r) => r.json()),
    ]);
  } catch (e) {
    console.error(e);
    res = { status: 'error', series: [] };
    val = { status: 'error', series: [] };
    inst = { status: 'no_data', message: String(e.message || e) };
  }
  renderSectorLineChart(res);
  renderSectorValuation(val);
  renderSectorInstitutionalLines(inst);
}

function renderSectorLineChart(res) {
  const el = document.getElementById('chart-sector-lines');
  if (!el) return;
  const hasSeries =
    res &&
    res.status === 'ok' &&
    res.series &&
    res.series.length > 0;

  if (!hasSeries) {
    el.innerHTML = '';
    const layout = baseLayout({
      title: {
        text: '<b>累積報酬率％</b>（類股平均／個股）',
        font: { size: 14 },
      },
      height: 460,
      yaxis: {
        title: { text: '累積報酬率％', font: { color: C.textMuted } },
        ticksuffix: '%',
        zeroline: true,
        zerolinecolor: C.textMuted,
      },
      xaxis: {
        title: { text: '日期', font: { color: C.textMuted } },
        type: 'date',
      },
      showlegend: false,
    });
    if (state.startDate && state.endDate) {
      layout.xaxis.range = [state.startDate, state.endDate];
    }
    Plotly.newPlot(el, [], layout, PLOTLY_CONFIG);
    return;
  }
  el.innerHTML = '';
  const traces = res.series.map((s) => ({
    name: s.label,
    x: s.dates,
    y: s.values,
    type: 'scatter',
    mode: 'lines',
    line: Object.assign({ width: 2 }, s.line || {}),
    hovertemplate: '%{y:.2f}%<extra></extra>',
  }));
  const layout = baseLayout({
    title: {
      text: '<b>累積報酬率％</b>（類股平均／個股）',
      font: { size: 14 },
    },
    height: 460,
    yaxis: {
      title: { text: '累積報酬率％', font: { color: C.textMuted } },
      ticksuffix: '%',
    },
  });
  Plotly.newPlot(el, traces, layout, PLOTLY_CONFIG);
}

function renderSectorInstitutionalEmpty(hintMessage) {
  const noteEl = document.getElementById('sector-inst-note');
  if (noteEl) {
    noteEl.textContent = hintMessage
      ? String(hintMessage)
      : '金額為當日收盤價×買賣超張數×1000 之估算值（億元）。勾選類股或比較個股後顯示外資／投信／自營折線。';
  }
  const titles = ['外資買賣超（億元）', '投信買賣超（億元）', '自營買賣超（億元）'];
  const ids = ['chart-sector-inst-foreign', 'chart-sector-inst-trust', 'chart-sector-inst-dealer'];
  const hint = hintMessage || '請勾選類股或加入比較個股';
  ids.forEach((id, i) => {
    const cel = document.getElementById(id);
    if (!cel) return;
    Plotly.purge(cel);
    cel.innerHTML = '';
    const layout = baseLayout({
      title: { text: `<b>${titles[i]}</b>`, font: { size: 13 } },
      height: 300,
      margin: { t: 40, r: 20, b: 52, l: 64 },
      xaxis: {
        type: 'date',
        title: { text: '日期', font: { color: C.textMuted } },
      },
      yaxis: {
        title: { text: '億元', font: { color: C.textMuted } },
        zeroline: true,
        zerolinecolor: C.textMuted,
      },
      annotations: [{
        text: hint,
        xref: 'paper',
        yref: 'paper',
        x: 0.5,
        y: 0.42,
        showarrow: false,
        font: { color: C.textMuted, size: 12 },
      }],
      showlegend: false,
    });
    if (state.startDate && state.endDate) {
      layout.xaxis.range = [state.startDate, state.endDate];
    }
    Plotly.newPlot(cel, [], layout, PLOTLY_CONFIG);
  });
}

function renderSectorInstitutionalLines(inst) {
  const noteEl = document.getElementById('sector-inst-note');
  if (noteEl && inst && inst.note) noteEl.textContent = inst.note;

  if (!inst || inst.status === 'no_data') {
    renderSectorInstitutionalEmpty(inst && inst.message ? inst.message : null);
    return;
  }

  const lines = inst.lines || [];
  const dates = inst.dates || [];
  if (lines.length === 0 || dates.length === 0) {
    renderSectorInstitutionalEmpty(
      inst.message || '區間內無可對齊之籌碼資料，或請勾選類股／比較個股',
    );
    return;
  }

  const plotOne = (chartId, titleHtml, keyBn) => {
    const cel = document.getElementById(chartId);
    if (!cel) return;
    const traces = lines.map((ln) => ({
      name: ln.label,
      x: dates,
      y: ln[keyBn],
      type: 'scatter',
      mode: 'lines',
      line: Object.assign({ width: 2 }, ln.line || {}),
      hovertemplate: '%{y:.2f} 億<extra>' + ln.label + '</extra>',
    }));
    const layout = baseLayout({
      title: { text: titleHtml, font: { size: 13 } },
      height: 300,
      margin: { t: 44, r: 20, b: 68, l: 64 },
      yaxis: {
        title: { text: '億元', font: { color: C.textMuted } },
        zeroline: true,
        zerolinecolor: C.textMuted,
      },
      xaxis: {
        type: 'date',
        title: { text: '日期', font: { color: C.textMuted } },
      },
      legend: {
        bgcolor: 'rgba(0,0,0,0)',
        font: { color: C.text },
        orientation: 'h',
        y: -0.32,
      },
    });
    if (state.startDate && state.endDate) {
      layout.xaxis.range = [state.startDate, state.endDate];
    }
    cel.innerHTML = '';
    Plotly.newPlot(cel, traces, layout, PLOTLY_CONFIG);
  };

  plotOne(
    'chart-sector-inst-foreign',
    `<b>外資買賣超</b> <span style="font-size:11px;color:${C.textMuted}">（億元）</span>`,
    'foreign_bn',
  );
  plotOne(
    'chart-sector-inst-trust',
    `<b>投信買賣超</b> <span style="font-size:11px;color:${C.textMuted}">（億元）</span>`,
    'trust_bn',
  );
  plotOne(
    'chart-sector-inst-dealer',
    `<b>自營買賣超</b> <span style="font-size:11px;color:${C.textMuted}">（億元）</span>`,
    'dealer_bn',
  );
}

const SECTOR_VAL_BAND_FILLS = [
  'rgba(144,202,249,0.38)',
  'rgba(100,181,246,0.32)',
  'rgba(255,241,118,0.34)',
  'rgba(255,183,77,0.32)',
  'rgba(255,138,101,0.34)',
];

function _metricValuesForRange(seriesList, key) {
  const o = [];
  seriesList.forEach((s) => {
    (s[key] || []).forEach((v) => {
      if (v != null && !Number.isNaN(Number(v))) o.push(Number(v));
    });
  });
  return o;
}

function _buildValuationBandShapes(months, bandEdges, yMin, yMax) {
  if (!bandEdges || !bandEdges.length || !months.length) return [];
  const qs = [...bandEdges].sort((a, b) => a - b);
  const x0 = months[0];
  const x1 = months[months.length - 1];
  const lo = Math.min(yMin, qs[0] * 0.92);
  const hi = Math.max(yMax, qs[qs.length - 1] * 1.08);
  const bounds = [lo, ...qs, hi];
  const shapes = [];
  for (let i = 0; i < bounds.length - 1; i += 1) {
    shapes.push({
      type: 'rect',
      xref: 'x',
      yref: 'y',
      x0,
      x1,
      y0: bounds[i],
      y1: bounds[i + 1],
      fillcolor: SECTOR_VAL_BAND_FILLS[Math.min(i, SECTOR_VAL_BAND_FILLS.length - 1)],
      line: { width: 0 },
      layer: 'below',
    });
  }
  return shapes;
}

function _fmtValDelta(v) {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  const sign = n > 0 ? '+' : '';
  return sign + n.toFixed(2);
}

function _deltaClass(v) {
  if (v == null || Number.isNaN(Number(v))) return '';
  const n = Number(v);
  if (n > 0) return 'val-up';
  if (n < 0) return 'val-down';
  return '';
}

function renderSectorValTable(containerId, rows, unitLabel) {
  const wrap = document.getElementById(containerId);
  if (!wrap) return;
  if (!rows || rows.length === 0) {
    wrap.innerHTML = '';
    return;
  }
  const th = ['標的', '資料月', `本月（${unitLabel}）`, '上月比較', '去年同期'];
  let html = '<table class="sector-val-table"><thead><tr>';
  th.forEach((t) => {
    html += `<th>${t}</th>`;
  });
  html += '</tr></thead><tbody>';
  rows.forEach((r) => {
    html += '<tr>';
    html += `<td>${r.label}</td>`;
    html += `<td>${r.month || '—'}</td>`;
    html += `<td>${r.value != null ? Number(r.value).toFixed(2) : '—'}</td>`;
    html += `<td class="${_deltaClass(r.mom)}">${_fmtValDelta(r.mom)}</td>`;
    html += `<td class="${_deltaClass(r.yoy)}">${_fmtValDelta(r.yoy)}</td>`;
    html += '</tr>';
  });
  html += '</tbody></table>';
  wrap.innerHTML = html;
}

function renderSectorValuationEmpty() {
  const emptyLayout = (titleHtml, yTitle) => {
    const layout = baseLayout({
      title: { text: titleHtml, font: { size: 13 } },
      height: 380,
      xaxis: {
        type: 'date',
        title: { text: '月底', font: { color: C.textMuted } },
      },
      yaxis: {
        title: { text: yTitle, font: { color: C.textMuted } },
      },
      showlegend: false,
    });
    if (state.startDate && state.endDate) {
      layout.xaxis.range = [state.startDate, state.endDate];
    }
    return layout;
  };
  [['chart-sector-pe', '<b>本益比（月）</b>', '本益比（倍）'], ['chart-sector-pb', '<b>淨值比（月）</b>', '淨值比（倍）']].forEach(
    ([id, tit, yTit]) => {
      const el = document.getElementById(id);
      if (!el) return;
      Plotly.purge(el);
      el.innerHTML = '';
      Plotly.newPlot(el, [], emptyLayout(tit, yTit), PLOTLY_CONFIG);
    },
  );
  ['table-sector-pe', 'table-sector-pb'].forEach((tid) => {
    const t = document.getElementById(tid);
    if (t) t.innerHTML = '';
  });
}

function renderSectorValuation(data) {
  const months = data && data.months;
  const series = data && data.series;
  if (
    !data ||
    data.status !== 'ok' ||
    !series ||
    series.length === 0 ||
    !months ||
    months.length === 0
  ) {
    renderSectorValuationEmpty();
    return;
  }

  const peVals = _metricValuesForRange(series, 'pe');
  let peYMin = peVals.length ? Math.min(...peVals) : 0;
  let peYMax = peVals.length ? Math.max(...peVals) : 1;
  if (data.pe_bands && data.pe_bands.edges) {
    data.pe_bands.edges.forEach((e) => {
      peYMin = Math.min(peYMin, e);
      peYMax = Math.max(peYMax, e);
    });
  }
  if (peYMin === peYMax) {
    peYMin = peYMin > 0 ? peYMin * 0.85 : -1;
    peYMax = peYMax > 0 ? peYMax * 1.15 : 1;
  }
  const peShapes = _buildValuationBandShapes(
    months,
    data.pe_bands && data.pe_bands.edges,
    peYMin,
    peYMax,
  );

  const peTraces = [];
  series.forEach((s) => {
    peTraces.push({
      name: s.label,
      x: months,
      y: s.pe,
      type: 'scatter',
      mode: 'lines',
      line: Object.assign({ width: 2 }, s.line || {}),
      hovertemplate: '%{x}<br>' + s.label + ' 本益比：%{y:.2f}<extra></extra>',
    });
  });
  const peLayout = baseLayout({
    title: {
      text:
        '<b>本益比（月）</b> <span style="font-size:11px;color:' +
        C.textMuted +
        '">背景帶：首條序列歷史分位 10/30/50/70/90%</span>',
      font: { size: 13 },
    },
    height: 400,
    shapes: peShapes,
    yaxis: {
      title: { text: '本益比（倍）', font: { color: C.textMuted } },
      range: [peYMin * 0.9, peYMax * 1.08],
    },
    xaxis: {
      type: 'date',
      title: { text: '月底（最後交易日）', font: { color: C.textMuted } },
    },
    legend: {
      bgcolor: 'rgba(0,0,0,0)',
      font: { color: C.text },
      orientation: 'h',
      y: -0.2,
    },
  });
  const elPe = document.getElementById('chart-sector-pe');
  if (elPe) {
    elPe.innerHTML = '';
    Plotly.newPlot(elPe, peTraces, peLayout, PLOTLY_CONFIG);
  }
  renderSectorValTable('table-sector-pe', data.pe_summary || [], '倍');

  const pbVals = _metricValuesForRange(series, 'pb');
  let pbYMin = pbVals.length ? Math.min(...pbVals) : 0;
  let pbYMax = pbVals.length ? Math.max(...pbVals) : 1;
  if (data.pb_bands && data.pb_bands.edges) {
    data.pb_bands.edges.forEach((e) => {
      pbYMin = Math.min(pbYMin, e);
      pbYMax = Math.max(pbYMax, e);
    });
  }
  if (pbYMin === pbYMax) {
    pbYMin = pbYMin > 0 ? pbYMin * 0.85 : -1;
    pbYMax = pbYMax > 0 ? pbYMax * 1.15 : 1;
  }
  const pbShapes = _buildValuationBandShapes(
    months,
    data.pb_bands && data.pb_bands.edges,
    pbYMin,
    pbYMax,
  );
  const pbTraces = [];
  series.forEach((s) => {
    pbTraces.push({
      name: s.label,
      x: months,
      y: s.pb,
      type: 'scatter',
      mode: 'lines',
      line: Object.assign({ width: 2 }, s.line || {}),
      hovertemplate: '%{x}<br>' + s.label + ' 淨值比：%{y:.2f}<extra></extra>',
    });
  });
  const pbLayout = baseLayout({
    title: {
      text:
        '<b>淨值比（月）</b> <span style="font-size:11px;color:' +
        C.textMuted +
        '">背景帶：首條序列歷史分位 10/30/50/70/90%</span>',
      font: { size: 13 },
    },
    height: 400,
    shapes: pbShapes,
    yaxis: {
      title: { text: '淨值比（倍）', font: { color: C.textMuted } },
      range: [pbYMin * 0.9, pbYMax * 1.08],
    },
    xaxis: {
      type: 'date',
      title: { text: '月底（最後交易日）', font: { color: C.textMuted } },
    },
    legend: {
      bgcolor: 'rgba(0,0,0,0)',
      font: { color: C.text },
      orientation: 'h',
      y: -0.2,
    },
  });
  const elPb = document.getElementById('chart-sector-pb');
  if (elPb) {
    elPb.innerHTML = '';
    Plotly.newPlot(elPb, pbTraces, pbLayout, PLOTLY_CONFIG);
  }
  renderSectorValTable('table-sector-pb', data.pb_summary || [], '倍');
}

async function loadSectorPanelBootstrap() {
  const barEl = document.getElementById('chart-sector-bars');
  const wrap = document.getElementById('sector-line-sector-checks');
  if (!barEl || !wrap) return;

  const prevCompare = new Set(sectorPanelState.compareCodes);

  let b;
  try {
    b = await fetchJSON('/api/sector-performance');
  } catch (e) {
    b = { status: 'no_data', message: String(e.message || e) };
  }
  sectorPanelState.bootstrap = b;
  sectorPanelState.compareCodes = new Set();
  if (b.status === 'ok' && Array.isArray(b.stock_universe)) {
    const valid = new Set(b.stock_universe.map((s) => s.code));
    prevCompare.forEach((c) => {
      if (valid.has(c)) sectorPanelState.compareCodes.add(c);
    });
  }

  if (b.status !== 'ok') {
    Plotly.purge(barEl);
    barEl.innerHTML = `<div class="no-data-hint" style="padding:24px;text-align:center;color:#8b949e;">${
      b.message || '無法載入類股資料'
    }</div>`;
    wrap.innerHTML = '';
    const lineEl = document.getElementById('chart-sector-lines');
    if (lineEl) {
      Plotly.purge(lineEl);
      lineEl.innerHTML =
        '<div class="no-data-hint" style="padding:32px;text-align:center;color:#8b949e;">—</div>';
    }
    renderSectorValuationEmpty();
    renderSectorInstitutionalEmpty();
    return;
  }

  renderSectorBarChart(b);
  buildSectorLineControls(b);
  sectorPanelRenderStockTags();
  scheduleSectorLinesLoad();
}

// ── 主初始化 ──────────────────────────────────────────────────────────
async function init() {
  showLoading(true);
  try {
    const meta = await fetchJSON('/api/meta');
    state.meta = meta;

    // 更新最後資料日期標示
    document.getElementById('last-update').textContent =
      `資料截至：${meta.date_range.max}`;

    // 初始化元件
    initTabs();
    initDatePicker();
    initBreadthAmpCorrOptions();
    initReloadBtn();
    bindStockEventsOnce();
    bindSectorPanelEventsOnce();

    // 載入並渲染時序圖表
    await loadAndRenderTimeCharts();

  } catch (err) {
    console.error('初始化失敗：', err);
    alert('資料載入失敗，請確認後端已啟動。\n' + err.message);
  } finally {
    showLoading(false);
  }
}

// ════════════════════════════════════════════════════════════════════════
// 國際股市區
// ════════════════════════════════════════════════════════════════════════

// 國際指數折線：依使用者勾選順序 — 水藍、土黃、紅、綠、紫；第六條起再循環
const INTL_SEQ_COLORS = ['#6ec8ff', '#c9a227', '#f85149', '#3fb950', '#8E44AD'];

function intlColorForCode(code) {
  const order = intlState.selectionOrder;
  const i = order.indexOf(code);
  const idx = i >= 0 ? i : 0;
  return INTL_SEQ_COLORS[idx % INTL_SEQ_COLORS.length];
}

const intlState = {
  initialized: false,
  allIndices:  [],          // [{code, name, currency, group}]
  selected:    {},          // code → 'primary' | 'secondary'
  selectionOrder: [],       // 勾選順序（決定折線預設色）
  startDate:   null,
  endDate:     null,
  baseDate:    null,
  chartData:   null,        // 最近一次 API 回傳
};

// ── 初始化（頁籤首次切換時呼叫）────────────────────────────────────────
async function initIntlTab() {
  if (intlState.initialized) return;
  intlState.initialized = true;

  showLoading(true);
  try {
    const data = await fetchJSON('/api/intl/indices');
    intlState.allIndices = data.indices;

    const maxDate  = data.date_range.max;
    const defStart = subtractMonths(maxDate, 12);

    intlState.startDate = defStart;
    intlState.endDate   = maxDate;
    intlState.baseDate  = defStart;

    // 設定日期輸入
    const ids = ['intl-start', 'intl-end', 'intl-base'];
    const vals = [defStart, maxDate, defStart];
    ids.forEach((id, i) => {
      const el = document.getElementById(id);
      el.value = vals[i];
      el.min   = data.date_range.min;
      el.max   = maxDate;
    });

    // 建立兩欄清單
    buildIntlChecklist();

    // 預設勾選主要市場（主軸：美、日、德；副軸：台灣）
    const primaryDefaults   = ['SB22', 'SB04', 'SB08', 'SB12'];
    const secondaryDefaults = ['SB01'];

    primaryDefaults.forEach(c => {
      if (intlState.allIndices.find(i => i.code === c)) {
        intlState.selected[c] = 'primary';
        const cb = document.getElementById(`p-${c}`);
        if (cb) cb.checked = true;
      }
    });
    secondaryDefaults.forEach(c => {
      if (intlState.allIndices.find(i => i.code === c)) {
        intlState.selected[c] = 'secondary';
        const cb = document.getElementById(`s-${c}`);
        if (cb) cb.checked = true;
      }
    });

    // 預設選取順序：主軸預設代碼順序 → 副軸預設，其餘補尾
    intlState.selectionOrder = [];
    primaryDefaults.forEach(c => {
      if (intlState.selected[c] === 'primary') intlState.selectionOrder.push(c);
    });
    secondaryDefaults.forEach(c => {
      if (intlState.selected[c] === 'secondary') intlState.selectionOrder.push(c);
    });
    Object.keys(intlState.selected).forEach(c => {
      if (!intlState.selectionOrder.includes(c)) intlState.selectionOrder.push(c);
    });

    bindIntlEvents();
    await loadAndRenderIntlCharts();

  } finally {
    showLoading(false);
  }
}

// ── 建立兩欄勾選清單 ────────────────────────────────────────────────────
function buildIntlChecklist() {
  const groupOrder = ['台灣', '亞洲', '歐洲', '美洲', 'MSCI', '其他'];
  const byGroup    = {};
  groupOrder.forEach(g => { byGroup[g] = []; });
  intlState.allIndices.forEach(idx => {
    const g = idx.group || '其他';
    (byGroup[g] || (byGroup['其他'] = byGroup['其他'] || [])).push(idx);
  });

  ['primary', 'secondary'].forEach(axis => {
    const prefix    = axis === 'primary' ? 'p' : 's';
    const container = document.getElementById(`intl-list-${axis}`);
    container.innerHTML = '';

    groupOrder.forEach(group => {
      const items = byGroup[group];
      if (!items || items.length === 0) return;

      const hdr = document.createElement('div');
      hdr.className    = 'intl-group-hdr';
      hdr.textContent  = group;
      hdr.dataset.group = group;
      container.appendChild(hdr);

      items.forEach(idx => {
        const div    = document.createElement('div');
        div.className       = 'intl-check-item';
        div.dataset.code    = idx.code;
        div.dataset.srchkey = (idx.name + ' ' + idx.code).toLowerCase();
        div.dataset.group   = group;

        const cbId = `${prefix}-${idx.code}`;
        div.innerHTML = `
          <input type="checkbox" class="intl-cb" id="${cbId}"
                 data-axis="${axis}" data-code="${idx.code}">
          <label for="${cbId}" class="intl-cb-label">
            <span class="intl-cb-name" title="${idx.name}">${idx.name}</span>
            <span class="ccy-badge ${idx.currency}">${idx.currency}</span>
          </label>`;
        container.appendChild(div);
      });
    });
  });

  // 綁定 checkbox 事件
  document.querySelectorAll('.intl-cb').forEach(cb => {
    cb.addEventListener('change', onIntlCbChange);
  });
}

// ── Checkbox 互斥邏輯 ───────────────────────────────────────────────────
function onIntlCbChange(e) {
  const code      = e.target.dataset.code;
  const axis      = e.target.dataset.axis;
  const otherAxis = axis === 'primary' ? 'secondary' : 'primary';
  const otherPfx  = otherAxis === 'primary' ? 'p' : 's';

  if (e.target.checked) {
    intlState.selected[code] = axis;
    const otherCb = document.getElementById(`${otherPfx}-${code}`);
    if (otherCb) otherCb.checked = false;
    if (!intlState.selectionOrder.includes(code)) intlState.selectionOrder.push(code);
  } else {
    if (intlState.selected[code] === axis) delete intlState.selected[code];
    if (!intlState.selected[code]) {
      intlState.selectionOrder = intlState.selectionOrder.filter(c => c !== code);
    }
  }
}

// ── 搜尋過濾 ────────────────────────────────────────────────────────────
function applyIntlSearch() {
  const q = (document.getElementById('intl-search').value || '').trim().toLowerCase();

  ['primary', 'secondary'].forEach(axis => {
    const container = document.getElementById(`intl-list-${axis}`);

    container.querySelectorAll('.intl-check-item').forEach(item => {
      const match = !q || item.dataset.srchkey.includes(q);
      item.classList.toggle('hidden', !match);
    });

    // 若某分組下無可見項目，隱藏分組標題
    container.querySelectorAll('.intl-group-hdr').forEach(hdr => {
      let sibling = hdr.nextElementSibling;
      let anyVisible = false;
      while (sibling && !sibling.classList.contains('intl-group-hdr')) {
        if (!sibling.classList.contains('hidden')) { anyVisible = true; break; }
        sibling = sibling.nextElementSibling;
      }
      hdr.classList.toggle('hidden', !anyVisible);
    });
  });
}

// ── 載入資料並渲染兩張圖 ────────────────────────────────────────────────
async function loadAndRenderIntlCharts() {
  const codes = Object.keys(intlState.selected).filter(c => intlState.selected[c]);

  if (codes.length === 0) {
    ['intl-chart-normalized', 'intl-chart-returns'].forEach(id => {
      document.getElementById(id).innerHTML =
        '<div class="intl-empty">請在上方選擇指數並按「套用」以顯示圖表</div>';
    });
    return;
  }

  const params = new URLSearchParams({
    start: intlState.startDate,
    end:   intlState.endDate,
    base:  intlState.baseDate,
  });
  codes.forEach(c => params.append('codes', c));

  const data = await fetchJSON(`/api/intl/chart-data?${params}`);
  intlState.chartData = data;

  renderIntlNormalized(data);
  renderIntlReturns(data);
}

// ── 建立走勢圖 Plotly 數列（原始指數數值）─────────────────────────────
function buildIntlRawTraces(data) {
  return Object.entries(data).map(([code, s]) => ({
    name:          s.name,
    x:             s.dates,
    y:             s.raw,
    type:          'scatter',
    mode:          'lines',
    yaxis:         (intlState.selected[code] === 'secondary') ? 'y2' : 'y',
    line:          { color: intlColorForCode(code), width: 1.8 },
    hovertemplate: `%{y:,.2f}<extra>${s.name}</extra>`,
  }));
}

// ── 取得 Y 軸設定（由輸入框讀取，空白則不設）──────────────────────────
function readAxisCfg(prefix) {
  const min  = parseFloat(document.getElementById(`intl-${prefix}-min`)?.value);
  const max  = parseFloat(document.getElementById(`intl-${prefix}-max`)?.value);
  const tick = parseFloat(document.getElementById(`intl-${prefix}-tick`)?.value);
  const cfg  = {};
  if (!isNaN(min) && !isNaN(max)) cfg.range = [min, max];
  if (!isNaN(tick) && tick > 0)   cfg.dtick  = tick;
  return cfg;
}

// ── 建立雙 Y 軸 layout ─────────────────────────────────────────────────
function buildIntlLayout(yLabel, chartKey, hasSecondary) {
  const isRet = chartKey === 'returns';
  const y1cfg = readAxisCfg(`${chartKey[0]}-y1`);
  const y2cfg = readAxisCfg(`${chartKey[0]}-y2`);

  const layout = baseLayout({
    height: 460,
    margin: { t: 36, r: hasSecondary ? 80 : 28, b: 80, l: 80 },
    yaxis: {
      title:      { text: yLabel, font: { color: C.textMuted } },
      side:       'left',
      ticksuffix: isRet ? '%' : '',
      zeroline:   isRet,
      zerolinecolor: isRet ? C.textDim : undefined,
      zerolinewidth: 1,
      ...y1cfg,
    },
  });

  if (hasSecondary) {
    layout.yaxis2 = {
      title:      { text: yLabel, font: { color: C.textMuted } },
      side:       'right',
      overlaying: 'y',
      showgrid:   false,
      zeroline:   false,
      ticksuffix: isRet ? '%' : '',
      ...y2cfg,
    };
  }

  if (isRet) {
    layout.shapes = [{
      type: 'line', xref: 'paper', x0: 0, x1: 1,
      y0: 0, y1: 0,
      line: { color: C.textDim, width: 1, dash: 'dash' },
    }];
  }

  return layout;
}

// ── 渲染走勢圖（原始指數數值）───────────────────────────────────────────
function renderIntlNormalized(data) {
  const traces       = buildIntlRawTraces(data);
  const hasSecondary = traces.some(t => t.yaxis === 'y2');
  const layout       = buildIntlLayout('指數原始數值', 'normalized', hasSecondary);
  layout.yaxis.zeroline = false;
  Plotly.newPlot('intl-chart-normalized', traces, layout, PLOTLY_CONFIG);
}

// ── 渲染累積報酬率圖 ────────────────────────────────────────────────────
function renderIntlReturns(data) {
  // LOCAL 指數無法計算台幣報酬率，完全排除
  const entries = Object.entries(data).filter(([, s]) => s.currency !== 'LOCAL');

  if (entries.length === 0) {
    document.getElementById('intl-chart-returns').innerHTML =
      '<div class="intl-empty">所選指數均為 LOCAL 類型，無法計算台幣報酬率</div>';
    return;
  }

  const isSingle = entries.length === 1;
  const traces   = [];

  entries.forEach(([code, s]) => {
    const yaxis = intlState.selected[code] === 'secondary' ? 'y2' : 'y';
    const col   = intlColorForCode(code);

    if (isSingle && s.can_decompose) {
      // ── 單指數且有匯率資料：顯示 3 條拆解線 ───────────────────────
      traces.push({
        name:          `${s.name}　台幣總報酬`,
        x: s.dates,    y: s.twd_return,
        type: 'scatter', mode: 'lines', yaxis,
        line: { color: col, width: 2 },
        hovertemplate: `%{y:.2f}%<extra>${s.name} 台幣總報酬</extra>`,
      });
      traces.push({
        name:          `${s.name}　本幣指數報酬`,
        x: s.dates,    y: s.local_return,
        type: 'scatter', mode: 'lines', yaxis,
        line: { color: col, width: 1.5, dash: 'dash' },
        hovertemplate: `%{y:.2f}%<extra>${s.name} 本幣指數報酬</extra>`,
      });
      traces.push({
        name:          `匯率貢獻（${s.currency}/TWD）`,
        x: s.dates,    y: s.fx_return,
        type: 'scatter', mode: 'lines', yaxis,
        line: { color: C.yellow, width: 1.5, dash: 'dot' },
        hovertemplate: `%{y:.2f}%<extra>匯率貢獻（${s.currency}/TWD）</extra>`,
      });
    } else {
      // ── 多指數或無匯率資料：每指數顯示 1 條線 ──────────────────────
      // TWD 指數：本幣報酬即為台幣報酬；其餘顯示台幣計價總報酬
      const yData = s.currency === 'TWD' ? s.local_return : s.twd_return;
      traces.push({
        name:          s.name,
        x: s.dates,    y: yData,
        type: 'scatter', mode: 'lines', yaxis,
        line: { color: col, width: 1.8 },
        hovertemplate: `%{y:.2f}%<extra>${s.name}</extra>`,
      });
    }
  });

  const hasSecondary = entries.some(([code]) => intlState.selected[code] === 'secondary');
  const layout = buildIntlLayout('累積報酬率 (%)', 'returns', hasSecondary);
  Plotly.newPlot('intl-chart-returns', traces, layout, PLOTLY_CONFIG);
}

// ── 套用軸設定（不重新 fetch，只更新 layout）──────────────────────────
function applyIntlAxisRelayout(chartKey) {
  const divId  = chartKey === 'normalized' ? 'intl-chart-normalized' : 'intl-chart-returns';
  const prefix = chartKey[0];
  const y1cfg  = readAxisCfg(`${prefix}-y1`);
  const y2cfg  = readAxisCfg(`${prefix}-y2`);

  const update = {};
  if (y1cfg.range)  update['yaxis.range']  = y1cfg.range;
  if (y1cfg.dtick)  update['yaxis.dtick']  = y1cfg.dtick;
  if (y2cfg.range)  update['yaxis2.range'] = y2cfg.range;
  if (y2cfg.dtick)  update['yaxis2.dtick'] = y2cfg.dtick;

  if (Object.keys(update).length > 0) Plotly.relayout(divId, update);
}

// ── 重置軸設定 ──────────────────────────────────────────────────────────
function resetIntlAxis(chartKey) {
  const prefix = chartKey[0];
  ['y1-min','y1-max','y1-tick','y2-min','y2-max','y2-tick'].forEach(sfx => {
    const el = document.getElementById(`intl-${prefix}-${sfx}`);
    if (el) el.value = '';
  });
  const divId = chartKey === 'normalized' ? 'intl-chart-normalized' : 'intl-chart-returns';
  Plotly.relayout(divId, {
    'yaxis.autorange':  true,
    'yaxis.dtick':      null,
    'yaxis2.autorange': true,
    'yaxis2.dtick':     null,
  });
}

// ── 綁定所有事件 ────────────────────────────────────────────────────────
function bindIntlEvents() {
  // 套用日期
  document.getElementById('intl-btn-apply').addEventListener('click', async () => {
    intlState.startDate = document.getElementById('intl-start').value;
    intlState.endDate   = document.getElementById('intl-end').value;
    intlState.baseDate  = document.getElementById('intl-base').value;
    showLoading(true);
    await loadAndRenderIntlCharts();
    showLoading(false);
  });

  // 快速預設
  document.querySelectorAll('.intl-preset').forEach(btn => {
    btn.addEventListener('click', async () => {
      document.querySelectorAll('.intl-preset').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const months   = parseInt(btn.dataset.months, 10);
      const maxDate  = document.getElementById('intl-end').value || intlState.endDate;
      const newStart = subtractMonths(maxDate, months);
      document.getElementById('intl-start').value = newStart;
      document.getElementById('intl-base').value  = newStart;
      intlState.startDate = newStart;
      intlState.baseDate  = newStart;
      showLoading(true);
      await loadAndRenderIntlCharts();
      showLoading(false);
    });
  });

  // 搜尋
  document.getElementById('intl-search').addEventListener('input', applyIntlSearch);

  // 清除按鈕
  ['primary', 'secondary'].forEach(axis => {
    const pfx = axis === 'primary' ? 'p' : 's';
    document.getElementById(`intl-clear-${axis}`).addEventListener('click', () => {
      Object.keys(intlState.selected).forEach(code => {
        if (intlState.selected[code] === axis) {
          delete intlState.selected[code];
          const cb = document.getElementById(`${pfx}-${code}`);
          if (cb) cb.checked = false;
        }
      });
      intlState.selectionOrder = intlState.selectionOrder.filter(c => intlState.selected[c]);
    });
  });

  // 軸設定套用 / 重置（delegated）
  document.querySelectorAll('.btn-apply-axis').forEach(btn => {
    btn.addEventListener('click', () => applyIntlAxisRelayout(btn.dataset.chart));
  });
  document.querySelectorAll('.btn-reset-axis').forEach(btn => {
    btn.addEventListener('click', () => resetIntlAxis(btn.dataset.chart));
  });
}

document.addEventListener('DOMContentLoaded', init);

// ════════════════════════════════════════════════════════════════════════
// 個股監控模組
// ════════════════════════════════════════════════════════════════════════

const stockState = {
  initialized:   false,
  stockMeta:     null,   // { stocks, quarterly_columns, date_range }
  currentCodes:  [],     // 目前已查詢的代碼陣列
  seriesData:    null,   // /api/stock/series 回傳
  monthlyData:   null,   // /api/stock/monthly 回傳
  quarterlyData: null,   // /api/stock/quarterly 回傳
  startDate:     null,
  endDate:       null,
  mode:          'overlay',   // 'overlay' | 'separate'
  quarterlyCol:  '',          // 選中的季資料欄位
};

/** 併發時只跑一個 initStockTab（避免分頁切換與查詢同時觸發兩次 meta） */
let _stockTabInitPromise = null;

// ── 顏色池（個股用，每支股票固定同一色）──────────────────────────────
const STOCK_PALETTE = [
  '#58a6ff', '#3fb950', '#f85149', '#d29922', '#bc8cff',
  '#39d0d8', '#e3b341', '#ff7b72', '#56d364', '#ffa657',
];
function stockColor(code) {
  let h = 0;
  for (const c of code) h = (h * 31 + c.charCodeAt(0)) & 0xffff;
  return STOCK_PALETTE[h % STOCK_PALETTE.length];
}

// ── 頁籤首次切換時初始化 ─────────────────────────────────────────────
async function initStockTab() {
  if (stockState.initialized) return;
  if (_stockTabInitPromise) {
    await _stockTabInitPromise;
    return;
  }

  _stockTabInitPromise = (async () => {
    showLoading(true);
    try {
      const meta = await fetchJSON('/api/stock/meta');
      stockState.stockMeta = meta;

      // 設定日期預設值（近1年）
      const maxDate  = meta.date_range.max;
      const defStart = subtractMonths(maxDate, 12);
      stockState.startDate = defStart;
      stockState.endDate   = maxDate;

      const startEl = document.getElementById('stock-start');
      const endEl   = document.getElementById('stock-end');
      startEl.value = defStart;
      endEl.value   = maxDate;
      startEl.min   = meta.date_range.min;
      startEl.max   = maxDate;
      endEl.min     = meta.date_range.min;
      endEl.max     = maxDate;

      // 填充季資料欄位下拉選單（避免「重新載入」重複附加 option）
      const sel = document.getElementById('quarterly-col-select');
      sel.innerHTML = '<option value="">— 不疊加 —</option>';
      (meta.quarterly_columns || []).forEach(col => {
        const opt = document.createElement('option');
        opt.value = col;
        opt.textContent = col;
        sel.appendChild(opt);
      });

      // 建立快捷股票列（預設幾檔常用）
      _buildQuickBar(['2330', '2317', '2454', '2308', '3008']);

      stockState.initialized = true;
    } catch (err) {
      console.error('個股 meta 載入失敗：', err);
      alert('個股資料載入失敗：' + err.message);
    } finally {
      showLoading(false);
    }
  })();

  await _stockTabInitPromise;
  _stockTabInitPromise = null;
}

// ── 快捷股票列 ──────────────────────────────────────────────────────────
function _buildQuickBar(codes) {
  const bar = document.getElementById('stock-quick-bar');
  bar.innerHTML = '<span class="quick-label">快捷：</span>';
  codes.forEach(code => {
    const btn = document.createElement('button');
    btn.className = 'btn-quick-stock';
    btn.textContent = code;
    btn.addEventListener('click', () => {
      document.getElementById('stock-input').value = code;
      triggerStockSearch();
    });
    bar.appendChild(btn);
  });
}

// ── 綁定事件（僅一次；須早於 /api/stock/meta 完成，否則查詢鈕在載入期間無反應）──
function bindStockEventsOnce() {
  if (stockState._eventsBound) return;
  stockState._eventsBound = true;
  bindStockEvents();
}

// ── 綁定事件 ────────────────────────────────────────────────────────────
function bindStockEvents() {
  // 查詢按鈕
  document.getElementById('stock-search-btn').addEventListener('click', triggerStockSearch);

  // Enter 鍵查詢
  document.getElementById('stock-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') triggerStockSearch();
  });

  // 套用日期
  document.getElementById('stock-date-apply').addEventListener('click', async () => {
    stockState.startDate = document.getElementById('stock-start').value;
    stockState.endDate   = document.getElementById('stock-end').value;
    if (stockState.currentCodes.length > 0) await loadAndRenderStock();
  });

  // 快速預設
  document.querySelectorAll('.stock-preset').forEach(btn => {
    btn.addEventListener('click', async () => {
      document.querySelectorAll('.stock-preset').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const months   = parseInt(btn.dataset.months, 10);
      const maxDate  = stockState.stockMeta?.date_range?.max || stockState.endDate;
      const newStart = subtractMonths(maxDate, months);
      document.getElementById('stock-start').value = newStart;
      stockState.startDate = newStart;
      stockState.endDate   = maxDate;
      if (stockState.currentCodes.length > 0) await loadAndRenderStock();
    });
  });

  // 多股模式切換
  document.querySelectorAll('input[name="stock-mode"]').forEach(radio => {
    radio.addEventListener('change', () => {
      stockState.mode = radio.value;
      if (stockState.seriesData) renderAllStockCharts();
    });
  });

  // 季資料欄位切換
  document.getElementById('quarterly-col-select').addEventListener('change', async e => {
    stockState.quarterlyCol = e.target.value;
    if (stockState.currentCodes.length > 0 && stockState.quarterlyCol) {
      const params = new URLSearchParams({
        codes: stockState.currentCodes.join(','),
        cols:  stockState.quarterlyCol,
      });
      stockState.quarterlyData = await fetchJSON(`/api/stock/quarterly?${params}`);
    } else {
      stockState.quarterlyData = null;
    }
    if (stockState.seriesData) renderStockReturn();
  });

  // 個股頁籤重新載入
  document.getElementById('stock-reload-btn').addEventListener('click', async () => {
    showLoading(true);
    await fetchJSON('/api/reload');
    // 清空快取，重新查詢
    stockState.seriesData = stockState.monthlyData = stockState.quarterlyData = null;
    stockState.stockMeta  = null;
    stockState.initialized = false;
    _stockTabInitPromise = null;
    await initStockTab();
    if (stockState.currentCodes.length > 0) await loadAndRenderStock();
    showLoading(false);
  });

  // 事件CSV按鈕
  const evtBtn = document.getElementById('btn-event-csv');
  if (evtBtn) {
    evtBtn.addEventListener('click', async () => {
      evtBtn.disabled = true;
      evtBtn.textContent = '⚡ 產生中…';
      try {
        const res = await fetch('/api/event-csv/generate', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
          alert('事件研究 CSV 已更新！\n' + (data.message || ''));
        } else {
          alert('產生失敗：\n' + (data.message || '未知錯誤'));
        }
      } catch (err) {
        alert('連線失敗：' + err.message);
      } finally {
        evtBtn.disabled = false;
        evtBtn.textContent = '⚡ 更新事件CSV';
      }
    });
  }

  // 研究報告下拉選單
  const toggle = document.getElementById('btn-report-toggle');
  const menu   = document.getElementById('report-dropdown-menu');
  if (toggle && menu) {
    toggle.addEventListener('click', e => {
      e.stopPropagation();
      menu.classList.toggle('open');
    });
    document.addEventListener('click', () => menu.classList.remove('open'));
    menu.addEventListener('click', e => e.stopPropagation());
  }
}

// ── 觸發查詢 ────────────────────────────────────────────────────────────
async function triggerStockSearch() {
  const raw = document.getElementById('stock-input').value.trim();
  if (!raw) return;
  await initStockTab();
  if (!stockState.initialized || !stockState.startDate || !stockState.endDate) return;

  const codes = raw.split(',').map(s => s.trim()).filter(Boolean);
  stockState.currentCodes = codes;
  await loadAndRenderStock();
}

// ── 載入所有資料並渲染 ─────────────────────────────────────────────────
async function loadAndRenderStock() {
  if (stockState.currentCodes.length === 0) return;

  showLoading(true);
  try {
    const codes   = stockState.currentCodes.join(',');
    const start   = stockState.startDate;
    const end     = stockState.endDate;

    // 並行請求日頻 + 月頻
    const [series, monthly] = await Promise.all([
      fetchJSON(`/api/stock/series?codes=${codes}&start=${start}&end=${end}`),
      fetchJSON(`/api/stock/monthly?codes=${codes}`),
    ]);
    stockState.seriesData  = series;
    stockState.monthlyData = monthly;

    // 季資料（若已選欄位）
    if (stockState.quarterlyCol) {
      const qParams = new URLSearchParams({ codes, cols: stockState.quarterlyCol });
      stockState.quarterlyData = await fetchJSON(`/api/stock/quarterly?${qParams}`);
    }

    renderAllStockCharts();
  } catch (err) {
    console.error('個股查詢失敗：', err);
    alert('查詢失敗：' + err.message);
  } finally {
    showLoading(false);
  }
}

// ── 渲染所有個股圖表 ────────────────────────────────────────────────────
function renderAllStockCharts() {
  const data = stockState.seriesData;
  const codes = Object.keys(data || {});
  if (codes.length === 0) {
    showStockEmpty(true);
    return;
  }
  showStockEmpty(false);

  renderStockReturn();
  renderStockAmplitude();
  renderStockChip();
  renderStockValuation();
  renderStockSummaryTable();
}

function showStockEmpty(show) {
  document.getElementById('stock-empty-hint').style.display = show ? '' : 'none';
  const grid = document.getElementById('stock-charts-grid');
  if (grid) grid.style.display = show ? 'none' : 'grid';
  const tableEl = document.getElementById('section-stock-table');
  if (tableEl) tableEl.style.display = show ? 'none' : '';
}

// ── 共用：為缺失日期填 null（讓折線圖不連線）──────────────────────────
function _seriesByDates(allDates, srcDates, srcVals) {
  const map = {};
  srcDates.forEach((d, i) => { map[d] = srcVals[i]; });
  return allDates.map(d => (d in map ? map[d] : null));
}

// ── 事件標記（注意／處置／全額交割）：Y 為指數化報酬，與事件 CSV 一致 ─────
function _pushStockEventTracesOnIndexedReturn(traces, s, code) {
  if (!s?.indexed_return) return;
  const ys = s.indexed_return;
  const evtMap = { '注意': s.attention, '處置': s.disposal, '全額交割': s.full_delivery };
  const evtColors = { '注意': C.orange, '處置': C.red, '全額交割': '#ff00ff' };
  Object.entries(evtMap).forEach(([label, flags]) => {
    if (!flags) return;
    const xs = [], yv = [];
    flags.forEach((f, i) => {
      if (f === 1 && ys[i] != null) { xs.push(s.dates[i]); yv.push(ys[i]); }
    });
    if (xs.length > 0) {
      traces.push({
        name: `${code} ${label}`,
        x: xs, y: yv,
        type: 'scatter', mode: 'markers',
        marker: { symbol: 'circle', size: 8, color: evtColors[label], opacity: 0.85 },
        hovertemplate: `%{x}<br>${label}<extra>${code}</extra>`,
      });
    }
  });
}

// ── 累積報酬（疊加／子圖）+ 事件標記 + 可選季資料副軸（僅疊加）──────────
function renderStockReturn() {
  const data  = stockState.seriesData;
  const codes = Object.keys(data || {});
  if (codes.length === 0) return;

  const titleEl = document.getElementById('stock-return-title');
  const subEl   = document.getElementById('stock-return-sub');

  if (stockState.mode === 'overlay') {
    const traces = [];
    codes.forEach(code => {
      const s = data[code];
      traces.push({
        name: `${code} ${s?.name || ''}`,
        x: s?.dates, y: s?.indexed_return,
        type: 'scatter', mode: 'lines',
        line: { color: stockColor(code), width: 2 },
        hovertemplate: `%{y:.2f}<extra>${code}</extra>`,
      });
      _pushStockEventTracesOnIndexedReturn(traces, s, code);
    });

    const hasQuarterly = !!(stockState.quarterlyData && stockState.quarterlyCol);
    let hasY2 = false;
    if (hasQuarterly) {
      codes.forEach(code => {
        const q = stockState.quarterlyData?.[code];
        if (!q) return;
        const colName = stockState.quarterlyCol;
        const vals = q.series?.[colName];
        if (!vals) return;
        hasY2 = true;
        const col = stockColor(code);
        const qDates = q.periods.map(p => `${p.substring(0, 4)}-${p.substring(4, 6)}-01`);
        traces.push({
          name: `${code} ${colName}（季）`,
          x: qDates, y: vals,
          type: 'scatter', mode: 'lines+markers',
          yaxis: 'y2',
          line: { color: hexToRgba(col, 0.55), width: 2, shape: 'linear', dash: 'dot' },
          marker: { size: 6, color: col },
          connectgaps: false,
          hovertemplate: `%{x}<br>${colName}：%{y}<extra>${code} 季資料</extra>`,
        });
      });
    }

    const layout = baseLayout({
      height: 400,
      margin: { t: 36, r: hasY2 ? 80 : 28, b: 60, l: 72 },
      yaxis: {
        title: { text: '指數化報酬（起始=100）', font: { color: C.textMuted } },
        zeroline: false,
      },
      shapes: [{
        type: 'line', xref: 'paper', x0: 0, x1: 1,
        y0: 100, y1: 100,
        line: { color: C.textDim, width: 1, dash: 'dash' },
      }],
    });
    if (hasY2) {
      layout.yaxis2 = {
        title: { text: stockState.quarterlyCol, font: { color: C.textMuted } },
        side: 'right', overlaying: 'y',
        showgrid: false, zeroline: false,
      };
    }

    if (titleEl) titleEl.textContent = '累積報酬率比較（疊加）';
    if (subEl) {
      subEl.textContent = hasY2
        ? `以查詢區間起始日為基準（=100）＋ ${stockState.quarterlyCol}（副軸）；事件標記依事件 CSV`
        : '以查詢區間起始日為基準（=100）；事件標記（注意／處置／全額交割）依事件 CSV';
    }
    Plotly.newPlot('chart-stock-return', traces, layout, PLOTLY_CONFIG);

  } else {
    const n = codes.length;
    const rowH = Math.max(200, Math.min(300, 1000 / n));
    const totalH = n * rowH + 80;

    const fig = {
      data: [],
      layout: {
        paper_bgcolor: C.bg, plot_bgcolor: C.bg,
        font: { color: C.text, family: 'Inter, Noto Sans TC, system-ui' },
        height: totalH,
        grid: { rows: n, columns: 1, pattern: 'independent', roworder: 'top to bottom' },
        showlegend: false,
        hovermode: 'x unified',
        margin: { t: 30, r: 24, b: 50, l: 72 },
        shapes: [],
      },
    };

    codes.forEach((code, i) => {
      const s   = data[code];
      const ax  = i === 0 ? '' : String(i + 1);
      const col = stockColor(code);

      fig.data.push({
        name: `${code} ${s?.name || ''}`,
        x: s?.dates, y: s?.indexed_return,
        type: 'scatter', mode: 'lines',
        xaxis: `x${ax}`, yaxis: `y${ax}`,
        line: { color: col, width: 1.8 },
        hovertemplate: `%{y:.2f}<extra>${code}</extra>`,
      });

      const evtMap = { '注意': s.attention, '處置': s.disposal, '全額交割': s.full_delivery };
      const evtColors = { '注意': C.orange, '處置': C.red, '全額交割': '#ff00ff' };
      Object.entries(evtMap).forEach(([label, flags]) => {
        if (!flags) return;
        const xs = [], yv = [];
        flags.forEach((f, j) => {
          if (f === 1 && s.indexed_return[j] != null) { xs.push(s.dates[j]); yv.push(s.indexed_return[j]); }
        });
        if (xs.length > 0) {
          fig.data.push({
            name: `${code} ${label}`,
            x: xs, y: yv,
            type: 'scatter', mode: 'markers',
            xaxis: `x${ax}`, yaxis: `y${ax}`,
            marker: { symbol: 'circle', size: 7, color: evtColors[label], opacity: 0.9 },
            hovertemplate: `%{x}<br>${label}<extra>${code}</extra>`,
            showlegend: false,
          });
        }
      });

      const axCfg = {
        gridcolor: C.border, linecolor: C.border,
        tickfont: { color: C.textMuted },
        title: { text: `${code} 指數化報酬（=100）`, font: { color: col, size: 12 } },
      };
      fig.layout[`xaxis${ax}`] = { ...axCfg, title: {} };
      fig.layout[`yaxis${ax}`] = axCfg;

      fig.layout.shapes.push({
        type: 'line',
        xref: `x${ax}`, yref: `y${ax}`,
        x0: s.dates[0], x1: s.dates[s.dates.length - 1],
        y0: 100, y1: 100,
        line: { color: C.textDim, width: 1, dash: 'dash' },
      });
    });

    if (titleEl) titleEl.textContent = '累積報酬率比較（子圖）';
    if (subEl) subEl.textContent = '各股以區間起始日為基準（=100）；事件標記依事件 CSV';
    Plotly.newPlot('chart-stock-return', fig.data, fig.layout, PLOTLY_CONFIG);
  }
}

// ── 圖表 3：振幅 + 20日均值 + 月董監持股（副軸）─────────────────────
function renderStockAmplitude() {
  const data  = stockState.seriesData;
  const mData = stockState.monthlyData;
  const codes = Object.keys(data || {});
  if (codes.length === 0) return;

  const traces = [];
  let hasY2 = false;

  codes.forEach(code => {
    const s = data[code];
    if (!s?.amplitude) return;
    const col = stockColor(code);

    // 振幅折線
    traces.push({
      name: `${code} 振幅%`,
      x: s.dates, y: s.amplitude,
      type: 'scatter', mode: 'lines',
      line: { color: col, width: 1.5 },
      hovertemplate: `%{y:.2f}%<extra>${code} 振幅</extra>`,
    });

    // 20日滾動均值（在前端計算）
    const ma20 = _rollingMean(s.amplitude, 20);
    traces.push({
      name: `${code} 振幅MA20`,
      x: s.dates, y: ma20,
      type: 'scatter', mode: 'lines',
      line: { color: hexToRgba(col, 0.5), width: 1.5, dash: 'dash' },
      hovertemplate: `%{y:.2f}%<extra>${code} MA20</extra>`,
    });

    // 副軸：月董監持股
    const m = mData?.[code];
    if (m?.director_pct) {
      hasY2 = true;
      const mDates = m.periods.map(p => {
        const y = p.substring(0, 4); const mo = p.substring(4, 6);
        return `${y}-${mo}-01`;
      });
      traces.push({
        name: `${code} 董監持股%（月）`,
        x: mDates, y: m.director_pct,
        type: 'scatter', mode: 'lines+markers', yaxis: 'y2',
        line: { color: hexToRgba(col, 0.6), width: 1.8, shape: 'linear', dash: 'dot' },
        marker: { size: 5, color: col },
        hovertemplate: `%{y:.2f}%<extra>${code} 董監持股</extra>`,
      });
    }
  });

  const layout = baseLayout({
    height: 380,
    margin: { t: 36, r: hasY2 ? 80 : 28, b: 60, l: 72 },
    yaxis: { title: { text: '高低價差%', font: { color: C.textMuted } }, ticksuffix: '%' },
  });
  if (hasY2) {
    layout.yaxis2 = {
      title: { text: '董監持股%', font: { color: C.textMuted } },
      side: 'right', overlaying: 'y',
      showgrid: false, ticksuffix: '%',
    };
  }

  Plotly.newPlot('chart-stock-amplitude', traces, layout, PLOTLY_CONFIG);
}

// ── 圖表 4：法人籌碼（外資/投信/自營 買賣超）────────────────────────
function renderStockChip() {
  const data  = stockState.seriesData;
  const codes = Object.keys(data || {});
  if (codes.length === 0) return;

  const traces = [];
  const chipLabels = [
    { key: 'foreign_net', label: '外資', col: '#58a6ff' },
    { key: 'trust_net',   label: '投信', col: '#3fb950' },
    { key: 'dealer_net',  label: '自營', col: '#d29922' },
  ];

  codes.forEach(code => {
    const s = data[code];
    const chip = s?.chip;
    if (!chip) return;

    chipLabels.forEach(({ key, label, col }) => {
      traces.push({
        name: `${code} ${label}`,
        x: chip.dates, y: chip[key],
        type: 'bar',
        marker: { color: col, opacity: 0.75 },
        hovertemplate: `%{y:,.0f} 張<extra>${code} ${label}</extra>`,
      });
    });
  });

  if (traces.length === 0) {
    document.getElementById('chart-stock-chip').innerHTML =
      '<div class="stock-no-data">無籌碼資料</div>';
    return;
  }

  const layout = baseLayout({
    height: 360,
    barmode: 'group',
    yaxis: {
      title: { text: '買賣超（張）', font: { color: C.textMuted } },
      zeroline: true, zerolinecolor: C.textMuted,
    },
  });

  Plotly.newPlot('chart-stock-chip', traces, layout, PLOTLY_CONFIG);
}

// ── 圖表 5：估值指標（PE / PB / 殖利率）────────────────────────────
function renderStockValuation() {
  const data  = stockState.seriesData;
  const codes = Object.keys(data || {});
  if (codes.length === 0) return;

  const traces = [];
  const valLine = { width: 1.8 };
  const peCol  = INTL_SEQ_COLORS[0];
  const pbCol  = INTL_SEQ_COLORS[1];
  const divCol = INTL_SEQ_COLORS[2];

  codes.forEach(code => {
    const s = data[code];
    if (!s) return;

    if (s.pe) traces.push({
      name: `${code} 本益比`,
      x: s.dates, y: s.pe,
      type: 'scatter', mode: 'lines',
      line: { color: peCol, ...valLine },
      hovertemplate: `%{y:.2f}x<extra>${code} PE</extra>`,
    });
    if (s.pb) traces.push({
      name: `${code} 股淨比`,
      x: s.dates, y: s.pb,
      type: 'scatter', mode: 'lines',
      line: { color: pbCol, ...valLine },
      hovertemplate: `%{y:.2f}x<extra>${code} PB</extra>`,
    });
    if (s.dividend_yield) traces.push({
      name: `${code} 殖利率%`,
      x: s.dates, y: s.dividend_yield,
      type: 'scatter', mode: 'lines', yaxis: 'y2',
      line: { color: divCol, ...valLine },
      hovertemplate: `%{y:.2f}%<extra>${code} 殖利率</extra>`,
    });
  });

  const layout = baseLayout({
    height: 360,
    margin: { t: 36, r: 80, b: 60, l: 72 },
    yaxis: { title: { text: '本益比 / 股淨比（倍）', font: { color: C.textMuted } } },
    yaxis2: {
      title: { text: '殖利率%', font: { color: C.textMuted } },
      side: 'right', overlaying: 'y', showgrid: false, ticksuffix: '%',
    },
  });

  Plotly.newPlot('chart-stock-valuation', traces, layout, PLOTLY_CONFIG);
}

// ── 摘要統計表 ──────────────────────────────────────────────────────────
function renderStockSummaryTable() {
  const data   = stockState.seriesData;
  const mData  = stockState.monthlyData;
  const qData  = stockState.quarterlyData;
  const codes  = Object.keys(data || {});
  const wrap   = document.getElementById('stock-summary-table');
  if (!wrap || codes.length === 0) return;

  const fmtProb = (v) => (v != null && !isNaN(v)) ? (Number(v) * 100).toFixed(1) + '%' : '—';
  /** 機率 +（歷史樣本內：高持續性次數／振幅大事件次數），與報告 a 之估計一致 */
  const fmtPersistProb = (c) => {
    const s = data[c];
    const p = s?.stock_persist_prob;
    const hi = s?.stock_persist_hi_n;
    const amp = s?.stock_persist_amp_n;
    const probStr = fmtProb(p);
    if (probStr !== '—' && hi != null && amp != null && Number(amp) > 0) {
      return `${probStr}（${hi}/${amp}）`;
    }
    return probStr;
  };
  const rows = [
    ['收盤價(元)',   codes.map(c => _lastVal(data[c]?.close)), ''],
    ['成交量(千股)',  codes.map(c => _lastVal(data[c]?.volume, true)), ''],
    ['本益比',       codes.map(c => _lastVal(data[c]?.pe)), ''],
    ['股淨比',       codes.map(c => _lastVal(data[c]?.pb)), ''],
    ['現金殖利率%',  codes.map(c => _lastVal(data[c]?.dividend_yield)), ''],
    ['高低價差%',    codes.map(c => _lastVal(data[c]?.amplitude)), ''],
    ['CAPM Beta',    codes.map(c => _lastVal(data[c]?.capm_beta)), ''],
    ['振幅大後高持續性機率', codes.map(c => fmtPersistProb(c)), ''],
  ];

  // 月資料
  const mRows = [
    ['董監持股%（最新月）', codes.map(c => _lastVal(mData?.[c]?.director_pct)), '月頻'],
    ['大股東持股%',         codes.map(c => _lastVal(mData?.[c]?.major_holding_pct)), '月頻'],
  ];

  // 季資料
  const qRows = stockState.quarterlyCol
    ? [[stockState.quarterlyCol + '（最新季）',
        codes.map(c => _lastVal(qData?.[c]?.series?.[stockState.quarterlyCol])), '季頻']]
    : [];

  let html = `<table class="stock-sum-tbl">
    <thead>
      <tr>
        <th>指標</th>
        ${codes.map(c => `<th>${c}<br><small>${data[c]?.name || ''}</small></th>`).join('')}
        <th class="freq-col">頻率</th>
      </tr>
    </thead>
    <tbody>`;

  const renderSection = (label, rArr) => {
    html += `<tr class="sum-section-hdr"><td colspan="${codes.length + 2}">${label}</td></tr>`;
    rArr.forEach(([name, vals, freq]) => {
      html += `<tr>
        <td class="sum-row-lbl">${name}</td>
        ${vals.map(v => `<td class="sum-val">${v}</td>`).join('')}
        <td class="freq-col">${freq || '日頻'}</td>
      </tr>`;
    });
  };

  renderSection('📈 日頻資料', rows);
  if (mRows.some(r => r[1].some(v => v !== '—'))) renderSection('📅 月頻資料', mRows);
  if (qRows.length > 0) renderSection('📋 季頻資料', qRows);

  html += '</tbody></table>';
  wrap.innerHTML = html;
}

function _lastVal(arr, integer = false) {
  if (!Array.isArray(arr)) return '—';
  for (let i = arr.length - 1; i >= 0; i--) {
    if (arr[i] != null) {
      if (integer) return Number(arr[i]).toLocaleString();
      return Number(arr[i]).toFixed(2);
    }
  }
  return '—';
}

// ── 滾動平均（前端計算） ─────────────────────────────────────────────
function _rollingMean(arr, window) {
  return arr.map((_, i) => {
    if (i < window - 1) return null;
    const slice = arr.slice(i - window + 1, i + 1).filter(v => v != null);
    if (slice.length === 0) return null;
    return slice.reduce((a, b) => a + b, 0) / slice.length;
  });
}

