// P3-14/P3-17 修复：图表标记点最大数量，超过则按步长间隔取点，避免点位密集时重叠渲染。
// 原代码以裸魔法数字 24 出现在 drawSavingsChart 与 drawChart 两处，提取为命名常量便于统一调整。
const MARKER_MAX_COUNT = 24;

async function renderOverview(main) {
  const recs = state.dashboard.recommendations;
  if (!recs.length) {
    main.innerHTML = `
      <section class="panel">
        <div class="panel-header"><div class="panel-title">总览</div></div>
        <div class="panel-body"><div class="empty">暂无投加点和推荐结果，请先到工艺配置新增投加点并配置工艺参数。</div></div>
      </section>
    `;
    return;
  }
  const selected = recs.find((item) => item.dosing_point_id === state.selectedPointId) || recs[0];
  if (selected) state.selectedPointId = selected.dosing_point_id;
  main.innerHTML = `
    <section class="overview-card-scroll"><div class="grid overview-grid">${recs.map(metricCard).join("")}</div></section>
    <div class="overview-row-scroll" style="margin-top:14px">
      <section class="grid overview-row overview-second-row">
      ${trendPanel("出水TP趋势", "tp", state.trendHours)}
      ${trendPanel("加药流量趋势", "pac", state.trendHours)}
      ${savingsPanel()}
      </section>
    </div>
    <div class="overview-row-scroll" style="margin-top:14px">
      <section class="grid overview-row overview-third-row">
      <article class="panel overview-fixed-panel overview-explain-panel">
        <div class="panel-header"><div class="panel-title">推荐解释</div></div>
        <div class="panel-body overview-scroll-body">${explainBlock(selected)}</div>
      </article>
      <article class="panel overview-fixed-panel overview-alarm-panel">
        <div class="panel-header">
          <div class="panel-title">报警事件</div>
          <button class="btn ghost" id="ackAllOverview" type="button">全部确认</button>
        </div>
        <div class="panel-body overview-scroll-body">${alarmList(state.dashboard.alarms, 8)}</div>
      </article>
      ${plcSmallPanel()}
      </section>
    </div>
  `;
  document.querySelectorAll(".metric-card").forEach((card) => {
    card.addEventListener("click", async () => {
      state.selectedPointId = Number(card.dataset.pointId);
      await renderPage();
    });
  });
  document.querySelectorAll("[data-chart-hours]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      state.trendHours = Number(btn.dataset.chartHours);
      await loadAndDrawTrends(state.selectedPointId, state.trendHours);
    });
  });
  const savingsStartInput = document.getElementById("savingsStart");
  const savingsEndInput = document.getElementById("savingsEnd");
  if (savingsStartInput && savingsEndInput) {
    const refreshSavings = async () => {
      const start = savingsStartInput.value;
      const end = savingsEndInput.value;
      if (start && end) {
        state.savingsStart = start;
        state.savingsEnd = end;
        await loadAndDrawSavings(state.selectedPointId, start, end);
      }
    };
    savingsStartInput.addEventListener("change", refreshSavings);
    savingsEndInput.addEventListener("change", refreshSavings);
  }
  document.getElementById("ackAllOverview")?.addEventListener("click", ackAll);
  wireJumpButtons();
  const savingsStart = state.savingsStart || toDateTimeLocal(new Date(Date.now() - 3 * 3600 * 1000));
  const savingsEnd = state.savingsEnd || toDateTimeLocal(new Date());
  await Promise.all([
    loadAndDrawTrends(state.selectedPointId, state.trendHours),
    loadAndDrawSavings(state.selectedPointId, savingsStart, savingsEnd),
  ]);
}

function trendPanel(title, chartId, hours) {
  return `
    <article class="panel overview-fixed-panel overview-chart-panel" data-chart-id="${chartId}">
      <div class="panel-header">
        <div class="panel-title">${htmlEscape(title)}</div>
        <div class="chart-toolbar overview-chart-inline-toolbar">
          ${[3, 6, 12].map((h) => `<button class="seg ${hours === h ? "active" : ""}" data-chart-hours="${h}" type="button">${h}h</button>`).join("")}
        </div>
      </div>
      <div class="panel-body">
        <div id="${chartId}Legend" class="legend"></div>
        <div class="chart-wrap overview-chart-wrap"><canvas id="${chartId}Chart"></canvas><div id="${chartId}Tooltip" class="chart-tooltip"></div></div>
      </div>
    </article>
  `;
}

function savingsPanel() {
  const now = new Date();
  const defaultEnd = toDateTimeLocal(now);
  const defaultStart = toDateTimeLocal(new Date(now.getTime() - 3 * 3600 * 1000));
  return `
    <article class="panel overview-fixed-panel overview-chart-panel" data-chart-id="savings">
      <div class="panel-header">
        <div class="panel-title">节省加药流量</div>
        <div class="chart-toolbar overview-chart-inline-toolbar savings-time-range">
          <input type="datetime-local" id="savingsStart" value="${state.savingsStart || defaultStart}">
          <span style="color:#94a3b8;font-size:12px">~</span>
          <input type="datetime-local" id="savingsEnd" value="${state.savingsEnd || defaultEnd}">
        </div>
      </div>
      <div class="panel-body">
        <div id="savingsSummary" class="savings-summary"></div>
        <div class="chart-wrap overview-chart-wrap"><canvas id="savingsChart"></canvas><div id="savingsTooltip" class="chart-tooltip"></div></div>
      </div>
    </article>
  `;
}

function metricCard(rec) {
  const data = rec.data || {};
  const mode = rec.mode;
  const configured = [data.Q, data.IN_Q, data.TP_BEFORE, data.TP_OUT, data.PAC_ACTUAL].filter(Boolean);
  const latest = configured
    .filter((item) => item.sample_time)
    .sort((a, b) => new Date(b.sample_time) - new Date(a.sample_time))[0];
  const time = latest?.source === "manual" ? "手动" : dateSecond(latest?.sample_time || rec.recommend_time);
  const predictedTp = rec.tp_forecast?.predicted_tp_out;
  return `
    <article class="panel metric-card ${rec.dosing_point_id === state.selectedPointId ? "selected" : ""}" data-point-id="${rec.dosing_point_id}">
      <div class="card-top">
        <div class="point-name">${htmlEscape(rec.dosing_point_name)}</div>
        <span class="mode-tag mode-${mode}">${localizedStatus(mode)}</span>
      </div>
      <div class="metric-value">${fmt(rec.final_l_h, 1)}<small>L/h</small></div>
      <table class="mini-table">
        <thead><tr><th>参考流量</th><th>进水TP</th><th>出水TP</th><th>预测TP</th><th>加药流量</th></tr></thead>
        <tbody><tr>
          <td>${fmtCompact(data.Q?.value, 0)}</td>
          <td>${fmtCompact(data.TP_BEFORE?.value, 2)}</td>
          <td>${fmtCompact(data.TP_OUT?.value, 2)}</td>
          <td>${fmtCompact(predictedTp, 2)}</td>
          <td>${fmtCompact(data.PAC_ACTUAL?.value, 1)}</td>
        </tr></tbody>
      </table>
      <div class="data-time">数据时间：${time}${latest?.age_minutes > 10 ? `（${fmtCompact(latest.age_minutes, 0)} min 前）` : ""}</div>
    </article>
  `;
}

function explainBlock(rec) {
  if (!rec) return `<div class="empty">暂无推荐结果</div>`;
  const forecastText = tpForecastText(rec.tp_forecast);
  return `
    <div class="formula">
      <div class="formula-box"><div class="formula-label">保守公式</div><div class="formula-number">${fmt(rec.base_l_h, 1)}</div><div class="formula-unit">L/h</div></div>
      <div class="operator">→</div>
      <div class="formula-box"><div class="formula-label">原始建议</div><div class="formula-number">${fmt(rec.raw_l_h, 1)}</div><div class="formula-unit">L/h</div></div>
      <div class="operator">→</div>
      <div class="formula-box"><div class="formula-label">限幅后</div><div class="formula-number">${fmt(rec.final_l_h, 1)}</div><div class="formula-unit">L/h</div></div>
    </div>
    ${forecastText ? `<div class="muted" style="margin-bottom:10px">${forecastText}</div>` : ""}
    <div class="muted" style="font-weight:700;margin-bottom:10px">推荐理由</div>
    <div class="reason-tags">${rec.reasons.slice(0, 6).map((reason) => `<span class="reason">${icon("i-check")}${htmlEscape(reason)}</span>`).join("")}</div>
  `;
}

function tpForecastText(forecast) {
  if (!forecast) return "";
  if (forecast.predicted_tp_out == null) return "";
  return `预测下一次出水TP检测数据：${fmtCompact(forecast.predicted_tp_out, 4)} mg/L`;
}

function plcSmallPanel() {
  const devices = state.dashboard.plc || [];
  const connected = devices.filter((device) => device.status === "connected");
  return `
    <article class="panel">
      <div class="panel-header"><div class="panel-title">PLC 通讯</div></div>
      <div class="panel-body plc-overview-body">
        <div class="plc-online-summary"><span>设备在线</span><strong>${connected.length} / ${devices.length}</strong><span>台</span></div>
        <div class="plc-status-card-list">
          ${devices.length ? devices.map((device) => `
            <div class="plc-status-card">
              <span class="plc-status-card-name" title="${htmlEscape(device.name || "未命名设备")}">${htmlEscape(device.name || "未命名设备")}</span>
              <span class="plc-status-card-protocol">${htmlEscape(device.protocol || "—")}</span>
              <span class="plc-status-card-ip" title="${htmlEscape(device.ip_address || "未配置 IP")}">${htmlEscape(device.ip_address || "未配置 IP")}</span>
              <span class="status-tag status-${plcStatusClass(device.status)}">${plcStatusLabel(device.status)}</span>
            </div>
          `).join("") : '<div class="empty">未配置 PLC 设备</div>'}
        </div>
      </div>
    </article>
  `;
}

function alarmList(rows, limit = 20) {
  const alarms = (rows || []).slice(0, limit);
  if (!alarms.length) return `<div class="empty">当前无活动报警</div>`;
  return `<div class="alarm-list">${alarms.map((alarm) => `
    <div class="alarm-row">
      <svg class="alarm-icon severity-${alarm.severity}"><use href="#${alarm.severity === "low" ? "i-check" : "i-alert"}"></use></svg>
      <div>
        <div class="alarm-title">${htmlEscape(alarm.title)}</div>
        <div class="alarm-meta"><span>${htmlEscape(alarm.dosing_point_name || alarm.category)}</span><span>${dateMinute(alarm.event_time)}</span></div>
      </div>
      <span class="severity-tag severity-${alarm.severity}">${severityName(alarm.severity)}</span>
    </div>
  `).join("")}</div>`;
}

function severityName(severity) {
  return severity === "high" ? "高" : severity === "medium" ? "中" : "低";
}

function wireJumpButtons() {
  document.querySelectorAll("[data-jump]").forEach((btn) => btn.addEventListener("click", async () => {
    state.activePage = btn.dataset.jump;
    renderNav();
    await renderPage();
  }));
}

async function loadAndDrawTrends(pointId, hours) {
  const trend = await api(`/api/trends?dosing_point_id=${pointId}&hours=${hours}`);
  state.trendCache = trend;
  const tpKeys = ["TP_OUT", "PREDICT_TP"].filter((key) => Object.hasOwn(trend.series || {}, key));
  const pacKeys = ["PAC_ACTUAL", "RECOMMEND_PAC"].filter((key) => Object.hasOwn(trend.series || {}, key));
  renderLegend("tpLegend", tpKeys);
  renderLegend("pacLegend", pacKeys);
  drawChart(document.getElementById("tpChart"), trend.series, tpKeys, "tpTooltip");
  drawChart(document.getElementById("pacChart"), trend.series, pacKeys, "pacTooltip");
}

async function loadAndDrawSavings(pointId, start, end) {
  const data = await api(`/api/savings?dosing_point_id=${pointId}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`);
  state.savingsCache = data;
  const summary = document.getElementById("savingsSummary");
  if (summary) {
    const saved = data.total_savings || 0;
    const label = saved >= 0 ? "累计节省" : "累计多消耗";
    const color = saved >= 0 ? "#16a34a" : "#dc2626";
    summary.innerHTML = `<span class="savings-label">${label}</span><span class="savings-value" style="color:${color}">${fmtCompact(Math.abs(saved), 1)} L</span>`;
  }
  const series = { SAVINGS: { name: "节省流量差值", unit: "L/h", points: data.points || [] } };
  drawSavingsChart(document.getElementById("savingsChart"), series, ["SAVINGS"], "savingsTooltip");
}

function renderLegend(legendId, keys) {
  const legend = document.getElementById(legendId);
  if (!legend) return;
  legend.innerHTML = keys.length
    ? keys.map((key) => `<span class="legend-item"><span class="legend-line" style="background:${seriesStyle[key].color}"></span>${seriesStyle[key].label}</span>`).join("")
    : `<span class="muted">未配置可展示的数据源</span>`;
}

function drawSavingsChart(canvas, series, keys, tooltipId) {
  if (!canvas) return;
  // P2-6 修复：Canvas DPR 设置抽取到 setupChartCanvas
  const { ctx, w, h } = setupChartCanvas(canvas);
  const pad = { l: 50, r: 14, t: 12, b: 32 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  ctx.strokeStyle = "#e2e8f0";
  ctx.lineWidth = 1;
  ctx.font = "11px Microsoft YaHei UI, sans-serif";
  ctx.fillStyle = "#64748b";

  const allTimes = [];
  const allValues = [];
  keys.forEach((key) => {
    (series[key]?.points || []).forEach((p) => {
      allTimes.push(new Date(p.time).getTime());
      allValues.push(Number(p.value));
    });
  });

  if (!allTimes.length) {
    ctx.fillText("暂无数据", pad.l + 20, pad.t + 40);
    return;
  }

  const minT = Math.min(...allTimes);
  const maxT = Math.max(...allTimes);
  const minV = Math.min(0, Math.min(...allValues.filter(Number.isFinite)));
  const maxV = Math.max(0, Math.max(...allValues.filter(Number.isFinite)));
  const globalSpan = Math.max(maxV - minV, 0.0001);

  for (let i = 0; i <= 5; i++) {
    const y = pad.t + (plotH / 5) * i;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(w - pad.r, y);
    ctx.stroke();
    const val = maxV - (globalSpan / 5) * i;
    ctx.fillText(fmtCompact(val, 2), 4, y + 4);
  }

  const zeroY = pad.t + plotH - ((0 - minV) / globalSpan) * plotH;
  ctx.strokeStyle = "#94a3b8";
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.moveTo(pad.l, zeroY);
  ctx.lineTo(w - pad.r, zeroY);
  ctx.stroke();
  ctx.setLineDash([]);

  const chartPoints = [];
  keys.forEach((key) => {
    const points = (series[key]?.points || [])
      .map((point) => ({ time: point.time, t: new Date(point.time).getTime(), value: Number(point.value) }))
      .filter((point) => Number.isFinite(point.t) && Number.isFinite(point.value));
    if (!points.length) return;
    ctx.strokeStyle = "#2563eb";
    ctx.lineWidth = 1.7;
    ctx.beginPath();
    points.forEach((p, idx) => {
      const x = pad.l + ((p.t - minT) / Math.max(maxT - minT, 1)) * plotW;
      const y = pad.t + plotH - ((p.value - minV) / globalSpan) * plotH;
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    if (points.length > 1) ctx.stroke();

    ctx.fillStyle = "#2563eb";
    const markerStep = Math.max(1, Math.ceil(points.length / MARKER_MAX_COUNT));
    points.forEach((p, idx) => {
      if (idx % markerStep !== 0 && idx !== points.length - 1) return;
      const x = pad.l + ((p.t - minT) / Math.max(maxT - minT, 1)) * plotW;
      const y = pad.t + plotH - ((p.value - minV) / globalSpan) * plotH;
      const isLatest = idx === points.length - 1;
      ctx.beginPath();
      ctx.arc(x, y, isLatest ? 3.6 : 2.5, 0, Math.PI * 2);
      ctx.fill();
      chartPoints.push({ x, y, key, time: p.time, value: p.value, color: "#2563eb", label: "节省差值 (L/h)" });
    });
  });

  const labels = [minT, minT + (maxT - minT) / 3, minT + (maxT - minT) * 2 / 3, maxT];
  labels.forEach((t) => {
    const x = pad.l + ((t - minT) / Math.max(maxT - minT, 1)) * plotW;
    const d = new Date(t);
    ctx.fillText(`${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`, x - 16, h - 10);
  });

  wireChartTooltip(canvas, tooltipId, chartPoints, (p) => p.label || "节省差值 (L/h)");
}

function drawChart(canvas, series, keys, tooltipId) {
  if (!canvas) return;
  // P2-6 修复：Canvas DPR 设置抽取到 setupChartCanvas
  const { ctx, w, h } = setupChartCanvas(canvas);
  const pad = { l: 50, r: 14, t: 12, b: 32 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  ctx.strokeStyle = "#e2e8f0";
  ctx.lineWidth = 1;
  ctx.font = "11px Microsoft YaHei UI, sans-serif";
  ctx.fillStyle = "#64748b";

  const allTimes = [];
  const allValues = [];
  keys.forEach((key) => {
    (series[key]?.points || []).forEach((p) => {
      allTimes.push(new Date(p.time).getTime());
      allValues.push(Number(p.value));
    });
  });

  if (!allTimes.length) {
    ctx.fillText("暂无趋势数据", pad.l + 20, pad.t + 40);
    return;
  }

  const minT = Math.min(...allTimes);
  const maxT = Math.max(...allTimes);
  const globalMinV = Math.min(...allValues.filter(Number.isFinite));
  const globalMaxV = Math.max(...allValues.filter(Number.isFinite));
  const globalSpan = Math.max(globalMaxV - globalMinV, 0.0001);

  for (let i = 0; i <= 5; i++) {
    const y = pad.t + (plotH / 5) * i;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(w - pad.r, y);
    ctx.stroke();
    const val = globalMaxV - (globalSpan / 5) * i;
    ctx.fillText(fmtCompact(val, 2), 4, y + 4);
  }

  const chartPoints = [];
  keys.forEach((key) => {
    const points = (series[key]?.points || [])
      .map((point) => ({ time: point.time, t: new Date(point.time).getTime(), value: Number(point.value) }))
      .filter((point) => Number.isFinite(point.t) && Number.isFinite(point.value));
    if (!points.length) return;
    ctx.strokeStyle = seriesStyle[key].color;
    ctx.lineWidth = key === "PREDICT_TP" || key === "RECOMMEND_PAC" ? 2 : 1.7;
    ctx.setLineDash(key === "PREDICT_TP" || key === "RECOMMEND_PAC" ? [5, 3] : []);
    ctx.beginPath();
    points.forEach((p, idx) => {
      const x = pad.l + ((p.t - minT) / Math.max(maxT - minT, 1)) * plotW;
      const y = pad.t + plotH - ((p.value - globalMinV) / globalSpan) * plotH;
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    if (points.length > 1) ctx.stroke();
    ctx.setLineDash([]);

    const markerStep = Math.max(1, Math.ceil(points.length / MARKER_MAX_COUNT));
    ctx.fillStyle = seriesStyle[key].color;
    points.forEach((p, idx) => {
      if (idx % markerStep !== 0 && idx !== points.length - 1) return;
      const x = pad.l + ((p.t - minT) / Math.max(maxT - minT, 1)) * plotW;
      const y = pad.t + plotH - ((p.value - globalMinV) / globalSpan) * plotH;
      const isLatest = idx === points.length - 1;
      ctx.beginPath();
      ctx.arc(x, y, isLatest ? 3.6 : 2.5, 0, Math.PI * 2);
      ctx.fill();
      chartPoints.push({ x, y, key, time: p.time, value: p.value, color: seriesStyle[key].color });
    });
  });

  const labels = [minT, minT + (maxT - minT) / 3, minT + (maxT - minT) * 2 / 3, maxT];
  labels.forEach((t) => {
    const x = pad.l + ((t - minT) / Math.max(maxT - minT, 1)) * plotW;
    const d = new Date(t);
    ctx.fillText(`${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`, x - 16, h - 10);
  });

  wireChartTooltip(canvas, tooltipId, chartPoints, (p) => p.label || seriesStyle[p.key]?.label || p.key);
}

// P2-6 修复：wireChartTooltip 已移至 format.js，通过 labelFor 回调适配不同标签来源。

function toDateTimeLocal(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function selectedPoint() {
  return state.points.find((p) => p.id === state.selectedPointId) || state.points[0];
}

function selectedCollectionGroupId() {
  return state.selectedCollectionGroupId || PUBLIC_COLLECTION_GROUP_ID;
}

function collectionQuery(groupId = selectedCollectionGroupId()) {
  return groupId === PUBLIC_COLLECTION_GROUP_ID ? "scope=public" : `dosing_point_id=${encodeURIComponent(groupId)}`;
}

function selectedCollectionPoint(points = state.points) {
  const groupId = selectedCollectionGroupId();
  if (groupId === PUBLIC_COLLECTION_GROUP_ID) return null;
  return points.find((p) => String(p.id) === String(groupId)) || null;
}

function pointSelector() {
  return `<select id="pointSelector">${state.points.map((p) => `<option value="${p.id}" ${p.id === state.selectedPointId ? "selected" : ""}>${htmlEscape(p.name)}</option>`).join("")}</select>`;
}

function wirePointSelector(after) {
  document.getElementById("pointSelector")?.addEventListener("change", async (event) => {
    state.selectedPointId = Number(event.target.value);
    if (after) await after();
    else await renderPage();
  });
}
