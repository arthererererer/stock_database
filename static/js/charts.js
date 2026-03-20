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

// ── 狀態 ──────────────────────────────────────────────────────────────
const state = {
  meta:          null,
  gaugeData:     null,
  timeseriesData: null,
  capitalFlowData: null,
  heatmapData:   null,
  startDate:     null,
  endDate:       null,
};

// ── 工具函數 ──────────────────────────────────────────────────────────
function fmtAmount(v) {
  if (v == null) return 'N/A';
  if (v >= 1e8) return (v / 1e8).toFixed(2) + ' 億';
  if (v >= 1e4) return (v / 1e4).toFixed(0) + ' 萬';
  return v.toLocaleString();
}

function subtractMonths(dateStr, months) {
  const d = new Date(dateStr);
  d.setMonth(d.getMonth() - months);
  return d.toISOString().slice(0, 10);
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

// ── 百分位 → 標籤與顏色 ───────────────────────────────────────────────
function pctMeta(pct) {
  if (pct === null || pct === undefined) return { label: 'N/A', color: C.textDim };
  if (pct < 20) return { label: '極低量', color: '#2d6a9f' };
  if (pct < 40) return { label: '偏低量', color: '#58a6ff' };
  if (pct < 60) return { label: '正常量', color: '#8b949e' };
  if (pct < 80) return { label: '偏高量', color: '#d29922' };
  return               { label: '極高量', color: '#f85149' };
}

// ── 1. 儀表板（Gauge）+ 四期比較表 ────────────────────────────────────
function renderGauges(data) {
  const container = document.getElementById('gauges-row');
  container.innerHTML = '';

  data.forEach(item => {
    const plotId = `gauge-plot-${item.code.replace(/\s+/g, '-')}`;
    const { label, color: barColor } = pctMeta(item.percentile);

    // ── 外層 card ──
    const card = document.createElement('div');
    card.className = 'gauge-card';

    // ── Plotly 容器 ──
    const plotDiv = document.createElement('div');
    plotDiv.id = plotId;
    card.appendChild(plotDiv);

    // ── 成交金額標示 ──
    const amtDiv = document.createElement('div');
    amtDiv.className = 'gauge-amount';
    amtDiv.innerHTML =
      `<span class="gauge-amt-label">成交金額</span>` +
      `<span class="gauge-amt-val">${fmtAmount(item.latest_amount)}</span>` +
      `<span class="gauge-amt-sub">一年中位數 ${fmtAmount(item.one_year_median)}</span>`;
    card.appendChild(amtDiv);

    // ── 四期比較表 ──
    const cmpDiv = document.createElement('div');
    cmpDiv.className = 'gauge-cmp';
    (item.comparisons || []).forEach(c => {
      const { label: cLabel, color: cColor } = pctMeta(c.percentile);
      const pctStr = c.percentile !== null && c.percentile !== undefined
        ? c.percentile.toFixed(1) : 'N/A';
      const dateStr = c.date || '';
      cmpDiv.innerHTML += `
        <div class="gc-row">
          <div class="gc-time">
            <span class="gc-lbl">${c.label}</span>
            <span class="gc-date">${dateStr}</span>
          </div>
          <div class="gc-dots"></div>
          <div class="gc-tag" style="background:${cColor}22;color:${cColor};border-color:${cColor}55">${cLabel}</div>
          <div class="gc-pct" style="color:${cColor}">${pctStr}</div>
        </div>`;
    });
    card.appendChild(cmpDiv);

    container.appendChild(card);

    // ── Plotly Gauge ──
    const trace = {
      type: 'indicator',
      mode: 'gauge+number',
      value: item.percentile,
      number: { suffix: '', font: { size: 38, color: barColor } },
      title: {
        text: `<b>${item.label}</b><br><span style="font-size:.75em;color:${C.textMuted}">${label}</span>`,
        font: { size: 14, color: C.text },
      },
      gauge: {
        axis: {
          range: [0, 100],
          tickwidth: 1,
          tickcolor: C.border,
          tickfont: { color: C.textMuted, size: 11 },
          tickvals: [0, 20, 40, 60, 80, 100],
        },
        bar: { color: barColor, thickness: 0.25 },
        bgcolor: C.bgCard,
        bordercolor: C.border,
        steps: [
          { range: [0,  20], color: 'rgba(45,106,159,.25)' },
          { range: [20, 40], color: 'rgba(88,166,255,.18)' },
          { range: [40, 60], color: 'rgba(139,148,158,.15)' },
          { range: [60, 80], color: 'rgba(210,153,34,.22)' },
          { range: [80,100], color: 'rgba(248,81,73,.25)' },
        ],
        threshold: {
          line: { color: C.yellow, width: 2 },
          thickness: 0.75,
          value: 50,
        },
      },
    };

    Plotly.newPlot(plotId, [trace], {
      paper_bgcolor: C.bg,
      plot_bgcolor:  C.bg,
      font: { color: C.text, family: 'Inter, Noto Sans TC, system-ui' },
      margin: { t: 55, r: 16, b: 0, l: 16 },
      height: 220,
    }, { ...PLOTLY_CONFIG, displayModeBar: false });
  });
}

// ── 2. 市場廣度熱力圖 ─────────────────────────────────────────────────
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

// ── 4. 委買/委賣力道比 ────────────────────────────────────────────────
function renderBuySell(data) {
  const traces = Object.entries(data).map(([code, d]) => ({
    name: d.label,
    x: d.dates, y: d['委買委賣比'],
    type: 'scatter', mode: 'lines',
    line: { color: C.secColors[code] || C.blue, width: 1.8 },
    hovertemplate: '%{y:.3f}<extra>' + d.label + '</extra>',
  }));

  const layout = baseLayout({
    height: 360,
    shapes: [{
      type: 'line', xref: 'paper', x0: 0, x1: 1,
      y0: 1, y1: 1,
      line: { color: C.textDim, width: 1, dash: 'dash' },
    }],
    annotations: [{
      x: 1, y: 1, xref: 'paper', yref: 'y',
      text: '均衡線', showarrow: false,
      font: { color: C.textDim, size: 11 },
      xanchor: 'right', yanchor: 'bottom',
    }],
  });

  Plotly.newPlot('chart-buysell', traces, layout, PLOTLY_CONFIG);
}

// ── 5. 成交金額趨勢 + MA + 百分位帶 ──────────────────────────────────
function renderAmountTrend(data) {
  const traces = [];

  Object.entries(data).forEach(([code, d]) => {
    const col = C.secColors[code] || C.blue;
    const lbl = d.label;

    // 百分位帶（P20~P80 填色）
    traces.push({
      name: `${lbl} P80`, x: d.dates,
      y: Array(d.dates.length).fill(d['成交金額_P80']),
      type: 'scatter', mode: 'lines',
      line: { color: 'transparent' },
      showlegend: false,
      hoverinfo: 'skip',
    });
    traces.push({
      name: `${lbl} P20↔P80`, x: d.dates,
      y: Array(d.dates.length).fill(d['成交金額_P20']),
      type: 'scatter', mode: 'lines', fill: 'tonexty',
      fillcolor: hexToRgba(C.secColors[code] || C.blue, 0.12),
      line: { color: 'transparent' },
      showlegend: true,
      hoverinfo: 'skip',
      legendgroup: code,
    });

    // 成交金額主線
    traces.push({
      name: lbl, x: d.dates, y: d['成交金額'],
      type: 'scatter', mode: 'lines',
      line: { color: col, width: 1.5 },
      legendgroup: code,
      hovertemplate: '%{y:,.0f}<extra>' + lbl + '</extra>',
    });
    // MA5
    traces.push({
      name: `${lbl} MA5`, x: d.dates, y: d['成交金額_MA5'],
      type: 'scatter', mode: 'lines',
      line: { color: C.yellow, width: 1.2, dash: 'dot' },
      legendgroup: code,
      hovertemplate: '%{y:,.0f}<extra>' + lbl + ' MA5</extra>',
    });
    // MA20
    traces.push({
      name: `${lbl} MA20`, x: d.dates, y: d['成交金額_MA20'],
      type: 'scatter', mode: 'lines',
      line: { color: C.purple, width: 1.2, dash: 'dash' },
      legendgroup: code,
      hovertemplate: '%{y:,.0f}<extra>' + lbl + ' MA20</extra>',
    });
  });

  const layout = baseLayout({ height: 420, yaxis: { title: { text: '成交金額（元）', font: { color: C.textMuted } } } });
  Plotly.newPlot('chart-amount', traces, layout, PLOTLY_CONFIG);
}

// ── 6. 資金流向堆疊面積圖 ─────────────────────────────────────────────
function renderCapitalFlow(data) {
  const codes = Object.keys(data).filter(k => k !== 'dates');
  const traces = codes.map(code => ({
    name: (state.meta?.security_labels?.[code]) || code,
    x: data.dates, y: data[code],
    type: 'scatter', mode: 'lines',
    stackgroup: 'one', groupnorm: 'percent',
    line: { width: 0.5 },
    fillcolor: hexToRgba(C.secColors[code] || C.blue, 0.55),
    hovertemplate: '%{y:.1f}%<extra>' + ((state.meta?.security_labels?.[code]) || code) + '</extra>',
  }));

  const layout = baseLayout({
    height: 360,
    yaxis: { ticksuffix: '%', range: [0, 100] },
  });

  Plotly.newPlot('chart-capital-flow', traces, layout, PLOTLY_CONFIG);
}

// ── 7. 市場廣度震盪指標柱狀圖 ────────────────────────────────────────
function renderBreadth(data) {
  const traces = Object.entries(data).map(([code, d]) => ({
    name: d.label,
    x: d.dates, y: d['廣度震盪'],
    type: 'bar',
    marker: {
      color: d['廣度震盪'].map(v => v === null ? C.textDim : (v >= 0 ? C.green : C.red)),
    },
    hovertemplate: '%{y:.1f}%<extra>' + d.label + '</extra>',
  }));

  const layout = baseLayout({
    height: 380,
    barmode: 'group',
    yaxis: { ticksuffix: '%', zeroline: true, zerolinecolor: C.textMuted, zerolinewidth: 1 },
    shapes: [{
      type: 'line', xref: 'paper', x0: 0, x1: 1,
      y0: 0, y1: 0, line: { color: C.textMuted, width: 1 },
    }],
  });

  Plotly.newPlot('chart-breadth', traces, layout, PLOTLY_CONFIG);
}

// ── 8. 漲停/跌停比率折線圖 ───────────────────────────────────────────
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
  const cf = state.capitalFlowData;
  if (!ts || !cf) return;

  renderBuySell(ts);
  renderAmountTrend(ts);
  renderCapitalFlow(cf);
  renderBreadth(ts);
}

// ── 載入時序資料並更新圖表 ────────────────────────────────────────────
async function loadAndRenderTimeCharts() {
  const s = state.startDate;
  const e = state.endDate;
  const [ts, cf, marketAmp] = await Promise.all([
    fetchJSON(`/api/timeseries?start=${s}&end=${e}`),
    fetchJSON(`/api/capital-flow?start=${s}&end=${e}`),
    fetchJSON(`/api/market-amp?start=${s}&end=${e}`).catch(() => null),
  ]);
  state.timeseriesData  = ts;
  state.capitalFlowData = cf;
  state.marketAmpData   = marketAmp;
  renderTimeCharts();
  renderMarketAmpChart(marketAmp);
  if (fpState.features.length) await loadFeaturePremiumChart();
}

// ── 特徵溢酬監控（月再平衡 tercile LS）───────────────────────────────
const fpState = { features: [], controlsBound: false };

function refreshFpDim2Options() {
  const d1 = document.getElementById('fp-dim1');
  const d2 = document.getElementById('fp-dim2');
  if (!d1 || !d2) return;
  const v1 = d1.value;
  const keep = d2.value;
  d2.innerHTML = '';
  fpState.features.forEach((f) => {
    if (f === v1) return;
    const opt = document.createElement('option');
    opt.value = f;
    opt.textContent = f;
    d2.appendChild(opt);
  });
  if (keep && keep !== v1 && fpState.features.includes(keep)) d2.value = keep;
  else if (d2.options[0]) d2.value = d2.options[0].value;
}

function bindFeaturePremiumControls() {
  if (fpState.controlsBound) return;
  fpState.controlsBound = true;
  document.getElementById('fp-dim1').addEventListener('change', () => {
    refreshFpDim2Options();
    loadFeaturePremiumChart();
  });
  document.getElementById('fp-dim2').addEventListener('change', loadFeaturePremiumChart);
  document.getElementById('fp-show-mkt').addEventListener('change', loadFeaturePremiumChart);
}

async function setupFeaturePremiumFromMeta() {
  const st = document.getElementById('fp-status');
  try {
    const meta = await fetchJSON('/api/feature-premium/meta');
    if (!meta.ok) {
      st.textContent = meta.message || '無法載入因子特徵';
      return;
    }
    fpState.features = meta.features || [];
    const d1 = document.getElementById('fp-dim1');
    d1.innerHTML = '';
    fpState.features.forEach((f) => {
      const o = document.createElement('option');
      o.value = f;
      o.textContent = f;
      d1.appendChild(o);
    });
    d1.value = fpState.features.includes('規模') ? '規模' : fpState.features[0];
    refreshFpDim2Options();
    const d2 = document.getElementById('fp-dim2');
    if (fpState.features.includes('淨值市價比')) d2.value = '淨值市價比';
    bindFeaturePremiumControls();
    await loadFeaturePremiumChart();
  } catch (e) {
    st.textContent = '載入失敗：' + e.message;
  }
}

function renderFeaturePremiumChart(data) {
  const el = document.getElementById('chart-feature-premium');
  const st = document.getElementById('fp-status');
  if (!data || !data.ok) {
    st.textContent = (data && data.message) ? data.message : '計算失敗';
    if (el) Plotly.purge(el);
    return;
  }
  st.textContent = `${data.dim1} × ${data.dim2} · ${data.dates.length} 交易日`;
  const traces = [{
    name: 'LS 累積超額％',
    x: data.dates,
    y: data.ls_cum,
    type: 'scatter',
    mode: 'lines',
    line: { color: C.purple, width: 2 },
    hovertemplate: '%{y:.3f}%<extra>' + data.dim1 + '×' + data.dim2 + '</extra>',
  }];
  const hasMkt = data.mkt_excess_cum && data.mkt_excess_cum.some((v) => v != null);
  if (hasMkt && document.getElementById('fp-show-mkt').checked) {
    traces.push({
      name: 'Y9999 累積超額％',
      x: data.dates,
      y: data.mkt_excess_cum,
      type: 'scatter',
      mode: 'lines',
      line: { color: C.textDim, width: 1.5, dash: 'dash' },
      hovertemplate: '%{y:.3f}%<extra>加權指數</extra>',
    });
  }
  const layout = baseLayout({
    height: 380,
    yaxis: {
      title: { text: '累積超額報酬（％）', font: { color: C.textMuted } },
      ticksuffix: '%',
    },
    xaxis: { title: { text: '交易日', font: { color: C.textMuted } } },
  });
  Plotly.newPlot(el, traces, layout, PLOTLY_CONFIG);
}

async function loadFeaturePremiumChart() {
  const d1 = document.getElementById('fp-dim1');
  const d2 = document.getElementById('fp-dim2');
  if (!d1 || !d2 || !fpState.features.length) return;
  const showMkt = document.getElementById('fp-show-mkt').checked;
  const q = new URLSearchParams({
    dim1: d1.value,
    dim2: d2.value,
    start: state.startDate,
    end: state.endDate,
    show_mkt: showMkt ? '1' : '0',
  });
  try {
    const data = await fetchJSON('/api/feature-premium/series?' + q.toString());
    renderFeaturePremiumChart(data);
  } catch (e) {
    document.getElementById('fp-status').textContent = e.message;
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

// ── 重新載入按鈕 ──────────────────────────────────────────────────────
function initReloadBtn() {
  document.getElementById('btn-reload').addEventListener('click', async () => {
    showLoading(true);
    await fetchJSON('/api/reload');
    state.gaugeData = await fetchJSON('/api/gauge');
    await loadAndRenderTimeCharts();
    renderGauges(state.gaugeData);
    if (fpState.features.length) await loadFeaturePremiumChart();
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

// ── 主初始化 ──────────────────────────────────────────────────────────
async function init() {
  showLoading(true);
  try {
    // 並行載入靜態資料
    const [meta, gauge] = await Promise.all([
      fetchJSON('/api/meta'),
      fetchJSON('/api/gauge'),
    ]);

    state.meta      = meta;
    state.gaugeData = gauge;

    // 更新最後資料日期標示
    document.getElementById('last-update').textContent =
      `資料截至：${meta.date_range.max}`;

    // 初始化元件
    initTabs();
    initDatePicker();
    initReloadBtn();

    // 渲染靜態圖表
    renderGauges(gauge);

    // 載入並渲染時序圖表
    await loadAndRenderTimeCharts();

    await setupFeaturePremiumFromMeta();

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

const INTL_PALETTE = [
  '#58a6ff','#3fb950','#f85149','#d29922','#bc8cff','#39d0d8',
  '#e3b341','#ff7b72','#56d364','#ffa657','#d2a8ff','#7ee787',
  '#79c0ff','#ff9e6a','#ffd700','#00bfff','#ff69b4','#32cd32',
  '#ff6347','#4169e1',
];

function intlColorOf(code) {
  let h = 0;
  for (const c of code) h = (h * 31 + c.charCodeAt(0)) & 0xffff;
  return INTL_PALETTE[h % INTL_PALETTE.length];
}

const intlState = {
  initialized: false,
  allIndices:  [],          // [{code, name, currency, group}]
  selected:    {},          // code → 'primary' | 'secondary'
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
  } else {
    if (intlState.selected[code] === axis) delete intlState.selected[code];
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
    line:          { color: intlColorOf(code), width: 1.8 },
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
    const col   = intlColorOf(code);

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
  stockState.initialized = true;

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

    // 填充季資料欄位下拉選單
    const sel = document.getElementById('quarterly-col-select');
    (meta.quarterly_columns || []).forEach(col => {
      const opt = document.createElement('option');
      opt.value = col;
      opt.textContent = col;
      sel.appendChild(opt);
    });

    // 建立快捷股票列（預設幾檔常用）
    _buildQuickBar(['2330', '2317', '2454', '2308', '3008']);

    bindStockEvents();
  } finally {
    showLoading(false);
  }
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
    if (stockState.seriesData) renderStockPrice();
  });

  // 個股頁籤重新載入
  document.getElementById('stock-reload-btn').addEventListener('click', async () => {
    showLoading(true);
    await fetchJSON('/api/reload');
    // 清空快取，重新查詢
    stockState.seriesData = stockState.monthlyData = stockState.quarterlyData = null;
    stockState.stockMeta  = null;
    stockState.initialized = false;
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

  renderStockPrice();
  renderStockReturn();
  renderStockAmplitude();
  renderStockChip();
  renderStockValuation();
  renderStockSummaryTable();
}

function showStockEmpty(show) {
  document.getElementById('stock-empty-hint').style.display = show ? '' : 'none';
  const sections = [
    'section-stock-price', 'section-stock-return', 'section-stock-amplitude',
    'section-stock-chip', 'section-stock-valuation', 'section-stock-table',
  ];
  sections.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = show ? 'none' : '';
  });
}

// ── 共用：為缺失日期填 null（讓折線圖不連線）──────────────────────────
function _seriesByDates(allDates, srcDates, srcVals) {
  const map = {};
  srcDates.forEach((d, i) => { map[d] = srcVals[i]; });
  return allDates.map(d => (d in map ? map[d] : null));
}

// ── 圖表 1：收盤價走勢（主軸）+ 季資料（副軸）────────────────────────
function renderStockPrice() {
  const data = stockState.seriesData;
  const codes = Object.keys(data || {});
  if (codes.length === 0) return;

  const traces = [];
  const hasQuarterly = stockState.quarterlyData && stockState.quarterlyCol;

  // 合併所有日期（取聯集）
  const allDatesSet = new Set();
  codes.forEach(c => (data[c]?.dates || []).forEach(d => allDatesSet.add(d)));
  const allDates = [...allDatesSet].sort();

  codes.forEach(code => {
    const s = data[code];
    if (!s) return;
    const col = stockColor(code);

    // 主軸：收盤價折線
    traces.push({
      name: `${code} ${s.name}`,
      x: s.dates, y: s.close,
      type: 'scatter', mode: 'lines',
      line: { color: col, width: 2 },
      hovertemplate: `%{y:,.2f}<extra>${code} 收盤價</extra>`,
    });

    // 事件標記（注意/處置/全額交割）
    const evtMap = { '注意': s.attention, '處置': s.disposal, '全額交割': s.full_delivery };
    const evtColors = { '注意': C.orange, '處置': C.red, '全額交割': '#ff00ff' };
    Object.entries(evtMap).forEach(([label, flags]) => {
      if (!flags) return;
      const xs = [], ys = [];
      flags.forEach((f, i) => {
        if (f === 1 && s.close[i] != null) { xs.push(s.dates[i]); ys.push(s.close[i]); }
      });
      if (xs.length > 0) {
        traces.push({
          name: `${code} ${label}`,
          x: xs, y: ys,
          type: 'scatter', mode: 'markers',
          marker: { symbol: 'circle', size: 8, color: evtColors[label], opacity: 0.85 },
          hovertemplate: `%{x}<br>${label}<extra>${code}</extra>`,
        });
      }
    });
  });

  // 副軸：季資料（step 折線）
  let hasY2 = false;
  if (hasQuarterly) {
    codes.forEach(code => {
      const q = stockState.quarterlyData?.[code];
      if (!q) return;
      const col = stockColor(code);
      const colName = stockState.quarterlyCol;
      const vals = q.series?.[colName];
      if (!vals) return;
      hasY2 = true;

      // 季資料日期格式為 YYYYMM，轉換成每季最後一天（近似：取 YYYYMM + '01'）
      const qDates = q.periods.map(p => {
        const y = p.substring(0, 4);
        const m = p.substring(4, 6);
        return `${y}-${m}-01`;
      });

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
    height: 440,
    margin: { t: 36, r: hasY2 ? 80 : 28, b: 60, l: 72 },
    yaxis: {
      title: { text: '收盤價（元）', font: { color: C.textMuted } },
    },
  });
  if (hasY2) {
    layout.yaxis2 = {
      title: { text: stockState.quarterlyCol, font: { color: C.textMuted } },
      side: 'right', overlaying: 'y',
      showgrid: false, zeroline: false,
    };
  }

  // 更新 sub 標題
  const sub = document.getElementById('stock-price-sub');
  if (sub) sub.textContent = hasY2
    ? `日收盤價（主軸）＋ ${stockState.quarterlyCol}（副軸，季頻）`
    : '日收盤價走勢';

  Plotly.newPlot('chart-stock-price', traces, layout, PLOTLY_CONFIG);
}

// ── 圖表 2：指數化累積報酬（疊加）或 各股收盤子圖 ─────────────────────
function renderStockReturn() {
  const data  = stockState.seriesData;
  const codes = Object.keys(data || {});
  if (codes.length === 0) return;

  const titleEl = document.getElementById('stock-return-title');
  const subEl   = document.getElementById('stock-return-sub');

  if (stockState.mode === 'overlay') {
    // 疊加模式：指數化報酬（=100 起點）
    const traces = codes.map(code => {
      const s = data[code];
      return {
        name: `${code} ${s?.name || ''}`,
        x: s?.dates, y: s?.indexed_return,
        type: 'scatter', mode: 'lines',
        line: { color: stockColor(code), width: 2 },
        hovertemplate: `%{y:.2f}<extra>${code}</extra>`,
      };
    });

    const layout = baseLayout({
      height: 400,
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

    if (titleEl) titleEl.textContent = '累積報酬率比較（疊加）';
    if (subEl) subEl.textContent = '以查詢區間起始日為基準（=100），比較各股相對表現';
    Plotly.newPlot('chart-stock-return', traces, layout, PLOTLY_CONFIG);

  } else {
    // 子圖模式：各股收盤價，使用 Plotly subplots
    const n = codes.length;
    const rowH = Math.max(200, Math.min(300, 1000 / n));
    const totalH = n * rowH + 80;

    const specs = codes.map(() => [{ type: 'scatter' }]);
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
      },
    };

    codes.forEach((code, i) => {
      const s   = data[code];
      const ax  = i === 0 ? '' : String(i + 1);
      const col = stockColor(code);

      fig.data.push({
        name: `${code} ${s?.name || ''}`,
        x: s?.dates, y: s?.close,
        type: 'scatter', mode: 'lines',
        xaxis: `x${ax}`, yaxis: `y${ax}`,
        line: { color: col, width: 1.8 },
        hovertemplate: `%{y:,.2f}<extra>${code}</extra>`,
      });

      // 軸樣式
      const axCfg = {
        gridcolor: C.border, linecolor: C.border,
        tickfont: { color: C.textMuted },
        title: { text: `${code} ${s?.name || ''}（元）`, font: { color: col, size: 12 } },
      };
      fig.layout[`xaxis${ax}`] = { ...axCfg, title: {} };
      fig.layout[`yaxis${ax}`] = axCfg;
    });

    if (titleEl) titleEl.textContent = '各股收盤價（子圖）';
    if (subEl) subEl.textContent = '各股收盤價個別顯示';
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
  codes.forEach(code => {
    const s = data[code];
    if (!s) return;
    const col = stockColor(code);

    if (s.pe) traces.push({
      name: `${code} 本益比`,
      x: s.dates, y: s.pe,
      type: 'scatter', mode: 'lines',
      line: { color: col, width: 1.8 },
      hovertemplate: `%{y:.2f}x<extra>${code} PE</extra>`,
    });
    if (s.pb) traces.push({
      name: `${code} 股淨比`,
      x: s.dates, y: s.pb,
      type: 'scatter', mode: 'lines',
      line: { color: hexToRgba(col, 0.65), width: 1.5, dash: 'dash' },
      hovertemplate: `%{y:.2f}x<extra>${code} PB</extra>`,
    });
    if (s.dividend_yield) traces.push({
      name: `${code} 殖利率%`,
      x: s.dates, y: s.dividend_yield,
      type: 'scatter', mode: 'lines', yaxis: 'y2',
      line: { color: hexToRgba(col, 0.5), width: 1.5, dash: 'dot' },
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
  const rows = [
    ['收盤價(元)',   codes.map(c => _lastVal(data[c]?.close)), ''],
    ['成交量(千股)',  codes.map(c => _lastVal(data[c]?.volume, true)), ''],
    ['本益比',       codes.map(c => _lastVal(data[c]?.pe)), ''],
    ['股淨比',       codes.map(c => _lastVal(data[c]?.pb)), ''],
    ['現金殖利率%',  codes.map(c => _lastVal(data[c]?.dividend_yield)), ''],
    ['高低價差%',    codes.map(c => _lastVal(data[c]?.amplitude)), ''],
    ['CAPM Beta',    codes.map(c => _lastVal(data[c]?.capm_beta)), ''],
    ['振幅大後高持續性機率', codes.map(c => fmtProb(data[c]?.stock_persist_prob)), ''],
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

