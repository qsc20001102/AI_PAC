async function renderOverview(main) {
  const recs = state.dashboard.recommendations;
  const selected = recs.find((item) => item.dosing_point_id === state.selectedPointId) || recs[0];
  if (selected) state.selectedPointId = selected.dosing_point_id;
  main.innerHTML = `
    <section class="overview-card-scroll"><div class="grid overview-grid">${recs.map(metricCard).join("")}</div></section>
    <div class="overview-row-scroll" style="margin-top:14px">
      <section class="grid overview-row overview-second-row">
      <article class="panel overview-fixed-panel overview-explain-panel">
        <div class="panel-header"><div class="panel-title">推荐解释</div></div>
        <div class="panel-body overview-scroll-body">${explainBlock(selected)}</div>
      </article>
      <article class="panel overview-fixed-panel overview-chart-panel">
        <div class="panel-header">
          <div class="panel-title">历史趋势</div>
          <div class="chart-toolbar">
            ${[3, 6, 12].map((h) => `<button class="seg ${state.trendHours === h ? "active" : ""}" data-hours="${h}" type="button">${h}h</button>`).join("")}
          </div>
        </div>
        <div class="panel-body">
          <div id="overviewLegend" class="legend"></div>
          <div class="chart-wrap overview-chart-wrap"><canvas id="overviewChart"></canvas><div id="overviewTooltip" class="chart-tooltip"></div></div>
        </div>
      </article>
      ${dataQualityPanel()}
      </section>
    </div>
    <div class="overview-row-scroll" style="margin-top:14px">
      <section class="grid overview-row overview-third-row">
      <article class="panel overview-fixed-panel overview-alarm-panel">
        <div class="panel-header">
          <div class="panel-title">报警事件</div>
          <button class="btn ghost" id="ackAllOverview" type="button">全部确认</button>
        </div>
        <div class="panel-body overview-scroll-body">${alarmList(state.dashboard.alarms, 8)}</div>
      </article>
      ${plcSmallPanel()}
      ${modelSmallPanel()}
      </section>
    </div>
  `;
  document.querySelectorAll(".metric-card").forEach((card) => {
    card.addEventListener("click", async () => {
      state.selectedPointId = Number(card.dataset.pointId);
      state.overviewQualityGroupId = String(state.selectedPointId);
      await renderPage();
    });
  });
  document.querySelectorAll("[data-hours]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      state.trendHours = Number(btn.dataset.hours);
      await renderPage();
    });
  });
  document.getElementById("ackAllOverview")?.addEventListener("click", ackAll);
  document.getElementById("overviewQualityGroup")?.addEventListener("change", async (event) => {
    state.overviewQualityGroupId = event.target.value;
    await refreshOverviewDataQuality();
  });
  wireJumpButtons();
  await Promise.all([
    loadAndDrawTrend("overviewChart", "overviewLegend", state.selectedPointId, state.trendHours),
    refreshOverviewDataQuality(),
  ]);
}

function metricCard(rec) {
  const data = rec.data || {};
  const mode = rec.mode === "conservative" && data.TP_OUT?.status === "stale" ? "stale" : rec.mode;
  const configured = [data.Q, data.IN_Q, data.PO4_P, data.TP_BEFORE, data.TP_OUT, data.PAC_ACTUAL].filter(Boolean);
  const latest = configured
    .filter((item) => item.sample_time)
    .sort((a, b) => new Date(b.sample_time) - new Date(a.sample_time))[0];
  const time = latest?.source === "manual" ? "手动" : dateSecond(latest?.sample_time || rec.recommend_time);
  return `
    <article class="panel metric-card ${rec.dosing_point_id === state.selectedPointId ? "selected" : ""}" data-point-id="${rec.dosing_point_id}">
      <div class="card-top">
        <div class="point-name">${htmlEscape(rec.dosing_point_name)}</div>
        <span class="mode-tag mode-${mode}">${localizedStatus(mode)}</span>
      </div>
      <div class="metric-value">${fmt(rec.final_l_h, 1)}<small>L/h</small></div>
      <table class="mini-table">
        <thead><tr><th>参与流量</th><th>进水流量</th><th>正磷酸盐</th><th>出水TP</th><th>加药流量</th></tr></thead>
        <tbody><tr>
          <td>${fmtCompact(data.Q?.value, 0)}</td>
          <td>${fmtCompact(data.IN_Q?.value, 0)}</td>
          <td>${fmtCompact(data.PO4_P?.value, 2)}</td>
          <td>${fmtCompact(data.TP_OUT?.value, 2)}</td>
          <td>${fmtCompact(data.PAC_ACTUAL?.value, 1)}</td>
        </tr></tbody>
      </table>
      <div class="data-time">数据时间：${time}${latest?.age_minutes > 10 ? `（${fmtCompact(latest.age_minutes, 0)} min 前）` : ""}</div>
    </article>
  `;
}

function explainBlock(rec) {
  if (!rec) return `<div class="empty">暂无推荐结果</div>`;
  return `
    <div class="formula">
      <div class="formula-box"><div class="formula-label">机理基础值</div><div class="formula-number">${fmt(rec.base_l_h, 1)}</div><div class="formula-unit">L/h</div></div>
      <div class="operator">×</div>
      <div class="formula-box"><div class="formula-label">K_feedback</div><div class="formula-number">${fmt(rec.k_feedback, 2)}</div></div>
      <div class="operator">×</div>
      <div class="formula-box"><div class="formula-label">K_ai</div><div class="formula-number">${fmt(rec.k_ai, 2)}</div></div>
      <div class="operator">→</div>
      <div class="formula-box"><div class="formula-label">限幅后</div><div class="formula-number">${fmt(rec.final_l_h, 1)}</div><div class="formula-unit">L/h</div></div>
    </div>
    <div class="muted" style="font-weight:700;margin-bottom:10px">推荐理由</div>
    <div class="reason-tags">${rec.reasons.slice(0, 6).map((reason) => `<span class="reason">${icon("i-check")}${htmlEscape(reason)}</span>`).join("")}</div>
  `;
}

function overviewQualityScope() {
  return String(state.overviewQualityGroupId || PUBLIC_COLLECTION_GROUP_ID);
}

function overviewQualityRows(rows) {
  if (!rows.length) return `<tr><td class="overview-quality-empty" colspan="3">当前分组暂无采集点</td></tr>`;
  return rows.map((tag) => {
    const timestamp = tag.last_read_at || tag.sample_time;
    return `
      <tr data-overview-quality-tag="${tag.id}">
        <td><div class="overview-tag-code">${htmlEscape(tag.tag_code || tag.name)}</div></td>
        <td><span class="status-tag status-${collectionQualityClass(tag)}">${collectionQualityText(tag)}</span></td>
        <td>${dateMinute(timestamp)}</td>
      </tr>
    `;
  }).join("");
}

function dashboardQualityRowsForScope() {
  const scope = overviewQualityScope();
  return (state.dashboard.data_quality || []).filter((tag) => (
    scope === PUBLIC_COLLECTION_GROUP_ID ? tag.dosing_point_id == null : String(tag.dosing_point_id) === scope
  ));
}

function dataQualityPanel() {
  const scope = overviewQualityScope();
  const options = [
    { value: PUBLIC_COLLECTION_GROUP_ID, label: "公共数据" },
    ...state.points.map((point) => ({ value: String(point.id), label: point.name })),
  ];
  return `
    <article class="panel overview-fixed-panel overview-quality-panel">
      <div class="panel-header"><div class="panel-title">数据质量</div><select id="overviewQualityGroup" class="overview-panel-select" aria-label="数据质量投加点选择">${optionList(options, scope)}</select></div>
      <div class="panel-body overview-scroll-body overview-quality-body">
        <table class="table overview-quality-table">
          <thead><tr><th>采集点名称</th><th>质量</th><th>更新时间</th></tr></thead>
          <tbody id="overviewDataQualityRows">${overviewQualityRows(dashboardQualityRowsForScope())}</tbody>
        </table>
      </div>
    </article>
  `;
}

function overviewQualityQuery() {
  const scope = overviewQualityScope();
  return scope === PUBLIC_COLLECTION_GROUP_ID ? "scope=public" : `dosing_point_id=${encodeURIComponent(scope)}`;
}

async function refreshOverviewDataQuality() {
  const body = document.getElementById("overviewDataQualityRows");
  if (!body || state.activePage !== "overview") return;
  try {
    const data = await api(`/api/collection?${overviewQualityQuery()}`);
    body.innerHTML = overviewQualityRows(data.tags || []);
  } catch (_) {
    // Keep the last rendered values visible if a short polling request fails.
  }
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
              <div class="plc-status-card-identity">
                <span class="plc-status-card-name" title="${htmlEscape(device.name || "未命名设备")}">${htmlEscape(device.name || "未命名设备")}</span>
                <span class="plc-status-card-ip" title="${htmlEscape(device.ip_address || "未配置 IP")}">${htmlEscape(device.ip_address || "未配置 IP")}</span>
              </div>
              <span class="status-tag status-${plcStatusClass(device.status)}">${plcStatusLabel(device.status)}</span>
            </div>
          `).join("") : '<div class="empty">未配置 PLC 设备</div>'}
        </div>
      </div>
    </article>
  `;
}

function modelSmallPanel() {
  const models = state.dashboard.training_models || [];
  const publishedCount = models.filter((model) => model.status === "published").length;
  const trained = models.filter((model) => ["ready", "published"].includes(model.status)).length;
  return `
    <article class="panel">
      <div class="panel-header"><div class="panel-title">模型管理</div><button class="btn ghost" data-jump="models" type="button">管理模型</button></div>
      <div class="panel-body model-overview-body">
        <div class="model-overview-summary"><span>训练模型 <strong>${models.length}</strong></span><span>已训练 <strong>${trained}</strong></span><span>已投用 <strong>${publishedCount}</strong></span></div>
        ${models.length ? `<div class="model-overview-list">${models.map((model) => {
          const metrics = model.metrics || {};
          return `<div class="model-overview-item">
            <div class="model-overview-name" title="${htmlEscape(model.name)}">${htmlEscape(model.name)}</div>
            <span class="status-tag status-${modelDisplayStatusClass(model)}">${modelDisplayStatusLabel(model)}</span>
            <div class="model-overview-meta">${htmlEscape(model.dosing_point_name)} · ${model.sample_count || 0} 条</div>
            <div class="model-overview-meta">R² ${fmtCompact(metrics.R2, 4)} · MAE ${fmtCompact(metrics.MAE, 4)} · K_AI ${fmtCompact(model.output_min, 2)}~${fmtCompact(model.output_max, 2)}</div>
          </div>`;
        }).join("")}</div>` : '<div class="empty">暂无训练模型</div>'}
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

async function loadAndDrawTrend(canvasId, legendId, pointId, hours) {
  const trend = await api(`/api/trends?dosing_point_id=${pointId}&hours=${hours}`);
  state.trendCache = trend;
  const keys = ["TP_BEFORE", "TP_OUT", "PO4_P"].filter((key) => Object.hasOwn(trend.series || {}, key));
  state.trendKeys = keys;
  const legend = document.getElementById(legendId);
  if (legend) legend.innerHTML = keys.length
    ? keys.map((key) => `<span class="legend-item"><span class="legend-line" style="background:${seriesStyle[key].color}"></span>${seriesStyle[key].label}</span>`).join("")
    : `<span class="muted">未配置可展示的数据源</span>`;
  const canvas = document.getElementById(canvasId);
  drawChart(canvas, trend.series, keys);
  wireOverviewTooltip(canvas);
}

function drawChart(canvas, series, keys) {
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const w = canvas.width / dpr;
  const h = canvas.height / dpr;
  ctx.clearRect(0, 0, w, h);
  const pad = { l: 44, r: 26, t: 12, b: 32 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  ctx.strokeStyle = "#e2e8f0";
  ctx.lineWidth = 1;
  ctx.font = "12px Microsoft YaHei UI, sans-serif";
  ctx.fillStyle = "#64748b";
  for (let i = 0; i <= 5; i++) {
    const y = pad.t + (plotH / 5) * i;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(w - pad.r, y);
    ctx.stroke();
  }
  const allTimes = [];
  keys.forEach((key) => (series[key]?.points || []).forEach((p) => allTimes.push(new Date(p.time).getTime())));
  if (!allTimes.length) {
    ctx.fillText("暂无趋势数据", pad.l + 20, pad.t + 40);
    return;
  }
  const minT = Math.min(...allTimes);
  const maxT = Math.max(...allTimes);
  state.overviewChartPoints = [];
  keys.forEach((key) => {
    const points = (series[key]?.points || [])
      .map((point) => ({ time: point.time, t: new Date(point.time).getTime(), value: Number(point.value) }))
      .filter((point) => Number.isFinite(point.t) && Number.isFinite(point.value));
    if (!points.length) return;
    const values = points.map((p) => Number(p.value)).filter(Number.isFinite);
    const minV = Math.min(...values);
    const maxV = Math.max(...values);
    const span = Math.max(maxV - minV, 0.0001);
    ctx.strokeStyle = seriesStyle[key].color;
    ctx.lineWidth = key === "PAC_SUGGEST" ? 2 : 1.7;
    ctx.beginPath();
    points.forEach((p, idx) => {
      const x = pad.l + ((new Date(p.time).getTime() - minT) / Math.max(maxT - minT, 1)) * plotW;
      const y = pad.t + plotH - ((Number(p.value) - minV) / span) * plotH;
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    if (points.length > 1) ctx.stroke();

    // Sensor history is stored less frequently than recommendations. Keep those
    // stored points visually prominent while limiting markers on dense ranges.
    const markerStep = Math.max(1, Math.ceil(points.length / 24));
    ctx.fillStyle = seriesStyle[key].color;
    points.forEach((p, idx) => {
      if (idx % markerStep !== 0 && idx !== points.length - 1) return;
      const x = pad.l + ((p.t - minT) / Math.max(maxT - minT, 1)) * plotW;
      const y = pad.t + plotH - ((p.value - minV) / span) * plotH;
      const isLatest = idx === points.length - 1;
      ctx.beginPath();
      ctx.arc(x, y, isLatest ? 3.6 : 2.5, 0, Math.PI * 2);
      ctx.fill();
      state.overviewChartPoints.push({ x, y, key, time: p.time, value: p.value, color: seriesStyle[key].color });
    });
  });
  const labels = [minT, minT + (maxT - minT) / 3, minT + (maxT - minT) * 2 / 3, maxT];
  labels.forEach((t) => {
    const x = pad.l + ((t - minT) / Math.max(maxT - minT, 1)) * plotW;
    const d = new Date(t);
    ctx.fillText(`${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`, x - 16, h - 10);
  });
}

function wireOverviewTooltip(canvas) {
  const tooltip = document.getElementById("overviewTooltip");
  if (!canvas || !tooltip) return;
  canvas.onmousemove = (event) => {
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    let nearest = null;
    let best = 13;
    state.overviewChartPoints.forEach((point) => {
      const distance = Math.hypot(point.x - x, point.y - y);
      if (distance < best) {
        best = distance;
        nearest = point;
      }
    });
    if (!nearest) {
      tooltip.classList.remove("show");
      return;
    }
    tooltip.innerHTML = `<b>${htmlEscape(seriesStyle[nearest.key].label)}</b><br>${dateMinute(nearest.time)}<br>${fmtCompact(nearest.value, 4)}`;
    tooltip.style.left = `${Math.min(x + 12, rect.width - 170)}px`;
    tooltip.style.top = `${Math.max(y - 62, 6)}px`;
    tooltip.classList.add("show");
  };
  canvas.onmouseleave = () => tooltip.classList.remove("show");
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
