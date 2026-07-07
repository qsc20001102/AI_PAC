function dataTypeLength(type) {
  if (type === "BOOL") return "1位";
  if (type === "INT") return "2字节";
  return "4字节";
}

function collectionQualityText(tag) {
  const quality = tag.last_quality || tag.sample_quality || "unknown";
  if (quality === "good") return "正常";
  if (quality === "bad") return "异常";
  return "未读取";
}

function collectionQualityClass(tag) {
  const quality = tag.last_quality || tag.sample_quality || "unknown";
  if (quality === "good") return "fresh";
  if (quality === "bad") return "bad";
  return "manual";
}

function optionList(options, value) {
  return options.map((opt) => `<option value="${htmlEscape(opt.value)}" ${String(opt.value) === String(value ?? "") ? "selected" : ""}>${htmlEscape(opt.label)}</option>`).join("");
}

function collectionTagRow(tag, deviceOptions) {
  const dataType = tag.data_type || "REAL";
  const realtime = tag.last_value_text ?? (tag.value == null ? "—" : fmtCompact(tag.value, 4));
  return `
    <tr class="collection-row" data-tag-id="${tag.id}">
      <td><input class="compact-input" name="tag_code" value="${htmlEscape(tag.tag_code)}"></td>
      <td>
        <select class="compact-input" name="data_type">
          ${optionList([{ value: "REAL", label: `REAL / ${dataTypeLength("REAL")}` }, { value: "BOOL", label: `BOOL / ${dataTypeLength("BOOL")}` }, { value: "INT", label: `INT / ${dataTypeLength("INT")}` }], dataType)}
        </select>
      </td>
      <td><select class="compact-input" name="plc_device_id">${optionList(deviceOptions, tag.plc_device_id == null ? "" : String(tag.plc_device_id))}</select></td>
      <td><input class="compact-input address-input" name="data_address" value="${htmlEscape(tag.data_address || "")}" placeholder="M1.0 / DB2.1186.0"></td>
      <td><input class="compact-input number-input" name="poll_interval_seconds" type="number" min="1" max="60" step="1" value="${tag.poll_interval_seconds || 5}"></td>
      <td>
        <select class="compact-input" name="history_enabled" data-history-select>
          ${optionList([{ value: "true", label: "启用" }, { value: "false", label: "关闭" }], String(Boolean(tag.history_enabled)))}
        </select>
      </td>
      <td><input class="compact-input number-input" name="history_interval_minutes" type="number" min="1" max="60" step="1" value="${tag.history_interval_minutes || 5}"></td>
      <td><span class="status-tag status-${collectionQualityClass(tag)}" data-collection-quality>${collectionQualityText(tag)}</span></td>
      <td>
        <div class="realtime-value" data-collection-value>${htmlEscape(realtime)}</div>
        <div class="muted" data-collection-time>${dateMinute(tag.last_read_at || tag.sample_time)}</div>
        <div class="error-text" data-collection-error>${htmlEscape(tag.last_error || "")}</div>
      </td>
      <td>
        <div class="row-actions">
          <button class="btn ghost" data-save-collection="${tag.id}" type="button">${icon("i-save")}保存</button>
          <button class="btn danger" data-delete-collection="${tag.id}" data-tag-code="${htmlEscape(tag.tag_code)}" type="button">删除</button>
        </div>
      </td>
    </tr>
  `;
}

function collectionPayloadFromRow(row) {
  const get = (name) => row.querySelector(`[name="${name}"]`)?.value;
  return {
    tag_code: String(get("tag_code") || "").trim(),
    data_type: String(get("data_type") || "REAL"),
    plc_device_id: get("plc_device_id") ? Number(get("plc_device_id")) : null,
    data_address: String(get("data_address") || "").trim(),
    poll_interval_seconds: Number(get("poll_interval_seconds") || 5),
    history_enabled: get("history_enabled") === "true",
    history_interval_minutes: Number(get("history_interval_minutes") || 5),
    enabled: true,
  };
}

function toggleHistoryInterval(select) {
  const row = select.closest(".collection-row");
  const input = row?.querySelector('[name="history_interval_minutes"]');
  if (input) input.disabled = select.value !== "true";
}

async function saveCollectionTag(event) {
  const row = event.currentTarget.closest(".collection-row");
  if (!row) return;
  const payload = collectionPayloadFromRow(row);
  try {
    await api(`/api/collection/tags/${row.dataset.tagId}`, { method: "PUT", body: JSON.stringify(payload) });
    showToast("采集点配置已保存");
    await renderPage();
  } catch (err) {
    showToast(`保存失败：${err.message}`);
  }
}

function defaultCollectionTagPayload(tags) {
  const point = selectedCollectionPoint();
  const prefix = point?.code || "PUBLIC";
  let index = tags.length + 1;
  let tagCode = `${prefix}_CUSTOM_${index}`;
  const existing = new Set(tags.map((tag) => tag.tag_code));
  while (existing.has(tagCode)) {
    index += 1;
    tagCode = `${prefix}_CUSTOM_${index}`;
  }
  return {
    tag_code: tagCode,
    tag_type: `CUSTOM_${index}`,
    unit: "",
    data_type: "REAL",
    plc_device_id: null,
    data_address: "",
    poll_interval_seconds: 5,
    history_enabled: true,
    history_interval_minutes: 5,
    enabled: true,
  };
}

async function createCollectionTag(tags) {
  try {
    const payload = defaultCollectionTagPayload(tags);
    const endpoint = selectedCollectionGroupId() === PUBLIC_COLLECTION_GROUP_ID
      ? "/api/collection/public/tags"
      : `/api/collection/points/${selectedCollectionGroupId()}/tags`;
    await api(endpoint, { method: "POST", body: JSON.stringify(payload) });
    showToast("采集点已新增");
    await renderPage();
  } catch (err) {
    showToast(`新增失败：${err.message}`);
  }
}

async function deleteCollectionTag(event) {
  const tagId = event.currentTarget.dataset.deleteCollection;
  const tagCode = event.currentTarget.dataset.tagCode;
  if (!window.confirm(`确认删除采集点「${tagCode}」？该点位的历史样本和人工样本会同步删除。`)) return;
  try {
    await api(`/api/collection/tags/${tagId}`, { method: "DELETE" });
    showToast("采集点已删除");
    await renderPage();
  } catch (err) {
    showToast(`删除失败：${err.message}`);
  }
}

function updateCollectionRealtimeCells(tags) {
  tags.forEach((tag) => {
    const row = document.querySelector(`.collection-row[data-tag-id="${tag.id}"]`);
    if (!row) return;
    const quality = row.querySelector("[data-collection-quality]");
    const value = row.querySelector("[data-collection-value]");
    const time = row.querySelector("[data-collection-time]");
    const error = row.querySelector("[data-collection-error]");
    if (quality) {
      quality.className = `status-tag status-${collectionQualityClass(tag)}`;
      quality.textContent = collectionQualityText(tag);
    }
    if (value) {
      const realtime = tag.last_value_text ?? (tag.value == null ? "—" : fmtCompact(tag.value, 4));
      value.textContent = realtime;
    }
    if (time) time.textContent = dateMinute(tag.last_read_at || tag.sample_time);
    if (error) error.textContent = tag.last_error || "";
  });
}

async function refreshCollectionRealtime() {
  if (state.activePage === "overview") {
    return;
  }
  if (state.activePage !== "data" || !document.querySelector(".collection-table")) return;
  try {
    const data = await api(`/api/collection?${collectionQuery()}`);
    updateCollectionRealtimeCells(data.tags || []);
  } catch (_) {
    // Avoid interrupting operators while they are editing collection settings.
  }
}

async function renderData(main) {
  let data = await api(`/api/collection?${collectionQuery()}`);
  const tags = data.tags || [];
  const devices = data.devices || [];
  const points = data.points || state.points;
  if (selectedCollectionGroupId() !== PUBLIC_COLLECTION_GROUP_ID && !points.some((p) => String(p.id) === String(selectedCollectionGroupId()))) {
    state.selectedCollectionGroupId = PUBLIC_COLLECTION_GROUP_ID;
    data = await api(`/api/collection?${collectionQuery()}`);
  }
  const currentTags = data.tags || tags;
  const currentGroupId = selectedCollectionGroupId();
  const currentGroupName = currentGroupId === PUBLIC_COLLECTION_GROUP_ID
    ? "公共数据"
    : (points.find((p) => String(p.id) === String(currentGroupId))?.name || "投加点");
  const groups = [
    { id: PUBLIC_COLLECTION_GROUP_ID, name: "公共数据", code: "全系统共享", isPublic: true },
    ...points.map((point) => ({ id: String(point.id), name: point.name, code: point.code || "", isPublic: false })),
  ];
  const deviceOptions = [{ value: "", label: "未选择" }, ...devices.map((device) => ({ value: String(device.id), label: device.name }))];
  main.innerHTML = `
    <section class="page-grid">
      <aside class="panel">
        <div class="panel-header"><div class="panel-title">投加点分组</div></div>
        <div class="panel-body">
          <div class="collection-group-list">
            ${groups.map((point) => {
              return `
                <div class="list-card ${String(point.id) === String(currentGroupId) ? "active" : ""}" data-collection-group="${htmlEscape(point.id)}">
                  <div style="font-weight:800">${htmlEscape(point.name)}</div>
                  <div class="muted" style="margin-top:5px">${htmlEscape(point.code || "")}</div>
                </div>
              `;
            }).join("")}
          </div>
        </div>
      </aside>
      <article class="panel">
        <div class="panel-header">
          <div class="panel-title">${htmlEscape(currentGroupName)}采集点配置</div>
          <div class="btn-row compact-actions">
            <button id="newCollectionTagBtn" class="btn primary" type="button">新增采集点</button>
            <button id="pollCollectionBtn" class="btn ghost" type="button">${icon("i-refresh")}立即读取当前组</button>
          </div>
        </div>
        <div class="panel-body">
          <div class="collection-table-wrap">
            <table class="table collection-table">
              <thead>
                <tr>
                  <th>采集点名称</th>
                  <th>数据类型</th>
                  <th>数据源</th>
                  <th>数据地址</th>
                  <th>采集周期(s)</th>
                  <th>历史存储</th>
                  <th>存储周期(min)</th>
                  <th>质量戳</th>
                  <th>实时值</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                ${currentTags.length ? currentTags.map((tag) => collectionTagRow(tag, deviceOptions)).join("") : `<tr><td colspan="10" class="muted">当前分组还没有采集点</td></tr>`}
              </tbody>
            </table>
          </div>
          <div class="muted" style="margin-top:12px">地址示例：BOOL 使用 M1.0；REAL 使用 DB2.1186.0。DB 地址格式为 DB号.字节偏移.位偏移。</div>
        </div>
      </article>
    </section>
  `;
  document.querySelectorAll("[data-collection-group]").forEach((node) => node.addEventListener("click", async () => {
    state.selectedCollectionGroupId = node.dataset.collectionGroup;
    await renderPage();
  }));
  document.querySelectorAll("[data-save-collection]").forEach((button) => button.addEventListener("click", saveCollectionTag));
  document.querySelectorAll("[data-delete-collection]").forEach((button) => button.addEventListener("click", deleteCollectionTag));
  document.querySelectorAll("[data-history-select]").forEach((select) => {
    toggleHistoryInterval(select);
    select.addEventListener("change", () => toggleHistoryInterval(select));
  });
  document.getElementById("newCollectionTagBtn").addEventListener("click", () => createCollectionTag(currentTags));
  document.getElementById("pollCollectionBtn").addEventListener("click", async () => {
    try {
      const res = await api(`/api/collection/poll?${collectionQuery()}`, { method: "POST" });
      showToast(`读取完成：成功 ${res.read_ok}，失败 ${res.read_failed}`);
      await renderPage();
    } catch (err) {
      showToast(`读取失败：${err.message}`);
    }
  });
}

function toDatetimeLocalValue(value) {
  const d = value ? new Date(value) : new Date();
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

function ensureHistoryRange() {
  if (!state.historyEnd) state.historyEnd = toDatetimeLocalValue(new Date());
  if (!state.historyStart) state.historyStart = toDatetimeLocalValue(new Date(Date.now() - 24 * 60 * 60 * 1000));
}

function historyColor(tagId) {
  if (state.historyColors[tagId]) return state.historyColors[tagId];
  const palette = ["#155cc3", "#d92828", "#16883c", "#8a3ffc", "#c76a00", "#008b8b", "#b21f66", "#4f6f00", "#7c3f00", "#0f766e", "#7f1d1d", "#4338ca"];
  const used = new Set(Object.values(state.historyColors));
  let color = palette.find((item) => !used.has(item));
  if (!color) {
    const hue = (Number(tagId) * 137.508) % 360;
    color = `hsl(${hue.toFixed(0)}, 72%, 38%)`;
  }
  state.historyColors[tagId] = color;
  return color;
}

function historyTree(points, tags) {
  const selected = new Set(state.historySelectedTagIds.map(Number));
  const groups = [
    { id: PUBLIC_COLLECTION_GROUP_ID, name: "公共数据" },
    ...points.map((point) => ({ id: String(point.id), name: point.name })),
  ];
  return groups.map((point) => {
    const children = point.id === PUBLIC_COLLECTION_GROUP_ID
      ? tags.filter((tag) => tag.dosing_point_id == null)
      : tags.filter((tag) => String(tag.dosing_point_id) === point.id);
    const checkedCount = children.filter((tag) => selected.has(tag.id)).length;
    const pointChecked = children.length > 0 && checkedCount === children.length;
    return `
      <div class="history-tree-point">
        <label class="tree-row tree-parent">
          <input type="checkbox" data-history-point="${point.id}" ${pointChecked ? "checked" : ""}>
          <span>${htmlEscape(point.name)}</span>
          <small>${checkedCount}/${children.length}</small>
        </label>
        <div class="tree-children">
          ${children.map((tag) => `
            <label class="tree-row tree-child">
              <input type="checkbox" data-history-tag="${tag.id}" data-point-id="${htmlEscape(point.id)}" ${selected.has(tag.id) ? "checked" : ""}>
              <span>${htmlEscape(tag.tag_code)}</span>
            </label>
          `).join("")}
        </div>
      </div>
    `;
  }).join("");
}

function historyGroupChildIds(tags, groupId) {
  return tags
    .filter((tag) => groupId === PUBLIC_COLLECTION_GROUP_ID ? tag.dosing_point_id == null : String(tag.dosing_point_id) === groupId)
    .map((tag) => tag.id);
}

async function loadHistoryData() {
  if (!state.historySelectedTagIds.length) return { series: [] };
  const params = new URLSearchParams({
    tag_ids: state.historySelectedTagIds.join(","),
    start_time: state.historyStart,
    end_time: state.historyEnd,
  });
  if (state.historyViewMode === "table" && state.historyTableIntervalMinutes) {
    params.set("interval_minutes", String(state.historyTableIntervalMinutes));
  }
  return api(`/api/history-data?${params.toString()}`);
}

function historyLegend(series) {
  return series.map((item) => `<span class="legend-item"><span class="legend-line" style="background:${historyColor(item.tag.id)}"></span>${htmlEscape(item.tag.tag_code)}</span>`).join("");
}

function historyTable(series) {
  if (!series.length) return `<div class="empty">请选择左侧采集点</div>`;
  const maxLen = Math.max(...series.map((item) => item.points.length));
  if (!maxLen) return `<div class="empty">所选时间范围内无历史数据</div>`;
  const timestamps = series[0].points.map((p) => p.sample_time);
  return `
    <div class="history-table-wrap">
      <table class="history-sample-table unified-table">
        <thead>
          <tr>
            <th>时间</th>
            ${series.map((item) => `<th>${htmlEscape(item.tag.tag_code)}${item.tag.unit ? ` (${htmlEscape(item.tag.unit)})` : ""}</th>`).join("")}
          </tr>
        </thead>
        <tbody>
          ${timestamps.map((ts, idx) => `
            <tr>
              <td>${dateMinute(ts)}</td>
              ${series.map((item) => {
                const point = item.points[idx];
                const val = point && point.value != null ? fmtCompact(point.value, 2) : "—";
                return `<td>${val}</td>`;
              }).join("")}
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function formatAxisTime(timestamp, spanMs) {
  const d = new Date(timestamp);
  const date = `${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  const time = spanMs > 48 * 60 * 60 * 1000 ? `${pad2(d.getHours())}:00` : `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  return `${date} ${time}`;
}

function drawHistoryChart(canvas, history) {
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(700, rect.width * dpr);
  canvas.height = Math.max(360, rect.height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const w = canvas.width / dpr;
  const h = canvas.height / dpr;
  ctx.clearRect(0, 0, w, h);
  const pad = { l: 64, r: 24, t: 18, b: 38 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  const startT = new Date(state.historyStart).getTime();
  const endT = new Date(state.historyEnd).getTime();
  const spanT = Math.max(endT - startT, 1);
  const values = [];
  (history.series || []).forEach((item) => item.points.forEach((point) => {
    const value = Number(point.value);
    if (Number.isFinite(value)) values.push(value);
  }));
  ctx.font = "12px Microsoft YaHei UI, sans-serif";
  ctx.fillStyle = "#64748b";
  ctx.strokeStyle = "#e2e8f0";
  ctx.lineWidth = 1;
  if (!values.length) {
    ctx.fillText(state.historySelectedTagIds.length ? "所选时间范围内无历史数据" : "请选择左侧采集点", pad.l + 18, pad.t + 42);
    state.historyChartPoints = [];
    return;
  }
  let minV = Math.min(...values);
  let maxV = Math.max(...values);
  if (minV === maxV) {
    minV -= 1;
    maxV += 1;
  } else {
    const padV = (maxV - minV) * 0.08;
    minV -= padV;
    maxV += padV;
  }
  for (let i = 0; i <= 5; i++) {
    const y = pad.t + (plotH / 5) * i;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(w - pad.r, y);
    ctx.stroke();
    const value = maxV - ((maxV - minV) / 5) * i;
    ctx.fillText(fmtCompact(value, 2), 8, y + 4);
  }
  for (let i = 0; i <= 5; i++) {
    const t = startT + (spanT / 5) * i;
    const x = pad.l + (plotW / 5) * i;
    ctx.fillText(formatAxisTime(t, spanT), x - 34, h - 12);
  }
  state.historyChartPoints = [];
  (history.series || []).forEach((item) => {
    const color = historyColor(item.tag.id);
    const points = item.points
      .map((point) => ({ time: point.sample_time, t: new Date(point.sample_time).getTime(), value: Number(point.value) }))
      .filter((point) => Number.isFinite(point.t) && Number.isFinite(point.value));
    if (!points.length) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    points.forEach((point, idx) => {
      const x = pad.l + ((point.t - startT) / spanT) * plotW;
      const y = pad.t + plotH - ((point.value - minV) / (maxV - minV)) * plotH;
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
      state.historyChartPoints.push({ x, y, tag: item.tag.tag_code, time: point.time, value: point.value, color });
    });
    ctx.stroke();
    ctx.fillStyle = color;
    points.forEach((point) => {
      const x = pad.l + ((point.t - startT) / spanT) * plotW;
      const y = pad.t + plotH - ((point.value - minV) / (maxV - minV)) * plotH;
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fill();
    });
  });
}

function wireHistoryTooltip(canvas) {
  const tooltip = document.getElementById("historyTooltip");
  if (!canvas || !tooltip) return;
  canvas.addEventListener("mousemove", (event) => {
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    let nearest = null;
    let best = 14;
    state.historyChartPoints.forEach((point) => {
      const dist = Math.hypot(point.x - x, point.y - y);
      if (dist < best) {
        best = dist;
        nearest = point;
      }
    });
    if (!nearest) {
      tooltip.classList.remove("show");
      return;
    }
    tooltip.innerHTML = `<b>${htmlEscape(nearest.tag)}</b><br>${dateMinute(nearest.time)}<br>${fmtCompact(nearest.value, 4)}`;
    tooltip.style.left = `${Math.min(x + 14, rect.width - 160)}px`;
    tooltip.style.top = `${Math.max(y - 58, 8)}px`;
    tooltip.classList.add("show");
  });
  canvas.addEventListener("mouseleave", () => tooltip.classList.remove("show"));
}

function exportHistoryTableCsv() {
  const history = state.historyCache;
  const series = history.series || [];
  if (!series.length) {
    showToast("没有可导出的数据");
    return;
  }
  const timestamps = series[0].points.map((p) => p.sample_time);
  let csv = "\ufeff";
  const headers = ["时间", ...series.map((item) => {
    const name = item.tag.tag_code;
    return item.tag.unit ? `${name}(${item.tag.unit})` : name;
  })];
  csv += headers.join(",") + "\n";
  timestamps.forEach((ts, idx) => {
    const row = [ts.replace("T", " ")];
    series.forEach((item) => {
      const point = item.points[idx];
      const val = point && point.value != null ? Number(point.value).toFixed(2) : "";
      row.push(val);
    });
    csv += row.join(",") + "\n";
  });
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  const startStr = (state.historyStart || "").replace("T", "_").replace(/:/g, "-");
  const endStr = (state.historyEnd || "").replace("T", "_").replace(/:/g, "-");
  link.href = URL.createObjectURL(blob);
  link.download = `历史数据_${startStr}_${endStr}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(link.href);
}

async function renderTrends(main) {
  ensureHistoryRange();
  const tree = await api("/api/collection");
  const allTagIds = new Set((tree.tags || []).map((tag) => tag.id));
  state.historySelectedTagIds = state.historySelectedTagIds.filter((id) => allTagIds.has(Number(id)));
  const history = await loadHistoryData();
  state.historyCache = history;
  main.innerHTML = `
    <section class="page-grid history-page-grid">
      <aside class="panel">
        <div class="panel-header"><div class="panel-title">采集点树</div></div>
        <div class="panel-body history-tree">${historyTree(tree.points || [], tree.tags || [])}</div>
      </aside>
      <article class="panel">
        <div class="panel-header">
          <div class="panel-title">历史数据</div>
          <div class="history-controls">
            <label>开始 <input id="historyStart" class="compact-input" type="datetime-local" value="${htmlEscape(state.historyStart)}"></label>
            <label>结束 <input id="historyEnd" class="compact-input" type="datetime-local" value="${htmlEscape(state.historyEnd)}"></label>
            ${state.historyViewMode === "table" ? `
              <label>间隔 <input id="historyInterval" class="compact-input history-days-input" type="number" min="1" max="1440" step="1" value="${htmlEscape(state.historyTableIntervalMinutes)}"> 分钟</label>
              <button id="exportTableBtn" class="btn ghost" type="button">${icon("i-download")}导出CSV</button>
            ` : ""}
            <label>清理 <input id="historyPurgeDays" class="compact-input history-days-input" type="number" min="1" max="3650" step="1" value="${htmlEscape(state.historyPurgeDays)}"> 天以前</label>
            <button id="purgeHistoryBtn" class="btn danger" type="button">清理历史</button>
            <button class="seg ${state.historyViewMode === "chart" ? "active" : ""}" data-history-mode="chart" type="button">曲线</button>
            <button class="seg ${state.historyViewMode === "table" ? "active" : ""}" data-history-mode="table" type="button">表格</button>
          </div>
        </div>
        <div class="panel-body history-display">
          ${state.historyViewMode === "chart" ? `
            <div id="historyLegend" class="legend">${historyLegend(history.series || [])}</div>
            <div class="history-chart-wrap"><canvas id="historyChart"></canvas><div id="historyTooltip" class="history-tooltip"></div></div>
          ` : historyTable(history.series || [])}
        </div>
      </article>
    </section>
  `;
  document.querySelectorAll("[data-history-point]").forEach((input) => {
    const childIds = historyGroupChildIds(tree.tags || [], input.dataset.historyPoint);
    const selected = new Set(state.historySelectedTagIds.map(Number));
    const selectedCount = childIds.filter((id) => selected.has(id)).length;
    input.indeterminate = selectedCount > 0 && selectedCount < childIds.length;
    input.addEventListener("change", async () => {
      const next = new Set(state.historySelectedTagIds.map(Number));
      childIds.forEach((id) => input.checked ? next.add(id) : next.delete(id));
      state.historySelectedTagIds = Array.from(next);
      await renderPage();
    });
  });
  document.querySelectorAll("[data-history-tag]").forEach((input) => input.addEventListener("change", async () => {
    const next = new Set(state.historySelectedTagIds.map(Number));
    const id = Number(input.dataset.historyTag);
    if (input.checked) next.add(id);
    else next.delete(id);
    state.historySelectedTagIds = Array.from(next);
    await renderPage();
  }));
  document.getElementById("historyStart").addEventListener("change", async (event) => {
    state.historyStart = event.target.value;
    await renderPage();
  });
  document.getElementById("historyEnd").addEventListener("change", async (event) => {
    state.historyEnd = event.target.value;
    await renderPage();
  });
  document.getElementById("historyPurgeDays").addEventListener("change", (event) => {
    state.historyPurgeDays = Math.max(1, Math.min(3650, Number(event.target.value || 30)));
    event.target.value = state.historyPurgeDays;
  });
  document.getElementById("purgeHistoryBtn").addEventListener("click", purgeHistoryData);
  if (state.historyViewMode === "table") {
    document.getElementById("historyInterval").addEventListener("change", async (event) => {
      state.historyTableIntervalMinutes = Math.max(1, Math.min(1440, Number(event.target.value || 60)));
      event.target.value = state.historyTableIntervalMinutes;
      await renderPage();
    });
    document.getElementById("exportTableBtn").addEventListener("click", exportHistoryTableCsv);
  }
  document.querySelectorAll("[data-history-mode]").forEach((button) => button.addEventListener("click", async () => {
    state.historyViewMode = button.dataset.historyMode;
    await renderPage();
  }));
  if (state.historyViewMode === "chart") {
    drawHistoryChart(document.getElementById("historyChart"), history);
    wireHistoryTooltip(document.getElementById("historyChart"));
  }
}

async function purgeHistoryData() {
  const input = document.getElementById("historyPurgeDays");
  const days = Math.max(1, Math.min(3650, Number(input?.value || state.historyPurgeDays || 30)));
  state.historyPurgeDays = days;
  const cutoff = toDatetimeLocalValue(new Date(Date.now() - days * 24 * 60 * 60 * 1000)).replace("T", " ");
  if (!window.confirm(`确认清理当前时间 ${days} 天以前的历史数据？\n早于 ${cutoff} 的采集历史记录将被删除，此操作不可恢复。`)) return;
  try {
    const res = await api("/api/history-data/purge", { method: "POST", body: JSON.stringify({ days }) });
    showToast(`已清理 ${res.sensor_samples_deleted} 条历史样本`);
    await renderPage();
  } catch (err) {
    showToast(`清理失败：${err.message}`);
  }
}
