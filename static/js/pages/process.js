async function renderProcess(main) {
  const modelsData = await api("/api/models");
  const trainedModels = (modelsData.models || []).filter((model) => model.trained_at);
  const processParameterGroups = await api("/api/process-parameter-groups");
  const rows = state.points.map((p) => `
    <div class="list-card ${!state.editingNewPoint && p.id === state.selectedPointId ? "active" : ""}" data-point-select="${p.id}">
      <div class="process-point-card-main">
        <div class="process-point-card-name">${htmlEscape(p.name)}</div>
        <div class="process-point-card-code">${htmlEscape(p.code)}</div>
      </div>
      <span class="status-tag status-${p.enabled ? "fresh" : "stale"}">${p.enabled ? "启用" : "停用"}</span>
    </div>
  `).join("");
  const p = state.editingNewPoint ? defaultNewPoint() : selectedPoint();
  main.innerHTML = `
    <section class="page-grid process-page-grid">
      <aside class="panel">
        <div class="panel-header"><div class="panel-title">投加点</div><button id="newPointBtn" class="btn ghost" type="button">新增</button></div>
        <div class="panel-body process-point-list">${rows}</div>
      </aside>
      <article class="panel">
        <div class="panel-header">
          <div class="panel-title">${state.editingNewPoint ? "新增投加点" : "投加点配置"}</div>
          ${state.editingNewPoint ? "" : `<button id="deletePointBtn" class="btn" type="button">删除投加点</button>`}
        </div>
        <div class="panel-body">
          <form id="pointForm">
            <div class="form-grid">
              ${field("name", "投加点名称", p.name, "text")}
              ${field("code", "投加点编码", p.code, "text")}
              ${selectField("enabled", "启用状态", [{ value: "true", label: "启用" }, { value: "false", label: "停用" }], String(Boolean(p.enabled)))}
              ${selectField("process_parameter_group_id", "工艺参数组", processParameterGroups.map((group) => ({ value: String(group.id), label: group.name })), p.process_parameter_group_id == null ? "" : String(p.process_parameter_group_id))}
              ${selectField("tp_model_id", "出水TP预测模型", modelSelectOptions(trainedModels, "tp_out_response"), p.tp_model_id == null ? "" : String(p.tp_model_id))}
              ${selectField("pac_flow_model_id", "加药流量预测模型", modelSelectOptions(trainedModels, "pac_flow_predict"), p.pac_flow_model_id == null ? "" : String(p.pac_flow_model_id))}
            </div>
            <div class="process-source-title">数据来源配置</div>
            <div class="form-grid process-source-grid">
              ${numberField("in_flow_weight", "进水流量权重", p.in_flow_weight ?? 1, "0", null, "0.01")}
              ${processSourceFields.map(([name, label]) => processSourceSelect(name, label, p)).join("")}
            </div>
            <div class="btn-row">
              <button class="btn primary" type="submit">${icon("i-save")}${state.editingNewPoint ? "创建投加点" : "保存属性"}</button>
              ${state.editingNewPoint ? `<button id="cancelNewPointBtn" class="btn" type="button">取消</button>` : ""}
              <span class="muted">选择“无”表示该工艺没有该变量，后续逻辑和模型计算不会使用该变量。</span>
            </div>
          </form>
        </div>
      </article>
    </section>
  `;
  document.getElementById("newPointBtn").addEventListener("click", async () => {
    state.editingNewPoint = true;
    await renderPage();
  });
  document.getElementById("cancelNewPointBtn")?.addEventListener("click", async () => {
    state.editingNewPoint = false;
    await renderPage();
  });
  document.querySelectorAll("[data-point-select]").forEach((node) => node.addEventListener("click", async () => {
    state.selectedPointId = Number(node.dataset.pointSelect);
    state.editingNewPoint = false;
    await renderPage();
  }));
  document.getElementById("pointForm").addEventListener("submit", saveDosingPoint);
  document.getElementById("deletePointBtn")?.addEventListener("click", deleteSelectedPoint);
}

async function renderProcessParams(main) {
  const groups = await api("/api/process-parameter-groups");
  if (!groups.length) {
    main.innerHTML = `<div class="empty">暂无工艺参数组</div>`;
    return;
  }
  if (!groups.some((group) => group.id === state.selectedProcessParameterGroupId)) {
    state.selectedProcessParameterGroupId = groups[0].id;
  }
  const current = groups.find((group) => group.id === state.selectedProcessParameterGroupId) || groups[0];
  const curve = normalizeCurve(current.unit_dose_curve);
  main.innerHTML = `
    <section class="page-grid process-page-grid">
      <aside class="panel">
        <div class="panel-header"><div class="panel-title">参数组</div><button id="newProcessParamGroupBtn" class="btn ghost" type="button">新增</button></div>
        <div class="panel-body process-point-list">
          ${groups.map((group) => `
            <div class="list-card ${group.id === current.id ? "active" : ""}" data-process-param-group="${group.id}">
              <div style="font-weight:800">${htmlEscape(group.name)}</div>
            </div>
          `).join("")}
        </div>
      </aside>
      <article class="panel">
        <div class="panel-header"><div class="panel-title">工艺参数</div><button id="deleteProcessParamGroupBtn" class="btn" type="button">删除参数组</button></div>
        <div class="panel-body">
          <form id="processParamGroupForm">
            <div class="form-grid">
              ${field("name", "参数组名称", current.name, "text")}
              ${numberField("tp_target_mg_l", "目标TP", current.tp_target_mg_l, "0", "5", "0.001")}
              ${numberField("tp_upper_mg_l", "出水TP上限", current.tp_upper_mg_l ?? current.tp_limit_mg_l, "0", "10", "0.001")}
              ${numberField("pac_density_kg_l", "药剂密度(kg/L)", current.pac_density_kg_l ?? 1.2, "0.01", "2", "0.001")}
              ${numberField("pac_min_l_h", "最小 L/h", current.pac_min_l_h, "0", "500", "0.01")}
              ${numberField("pac_max_l_h", "最大 L/h", current.pac_max_l_h, "0", "1000", "0.01")}
              ${numberField("calculation_interval_seconds", "计算周期(s)", current.calculation_interval_seconds, "5", "86400", "1")}
            </div>
            <div class="process-source-title">单耗配置曲线</div>
            ${unitDoseCurveEditor(curve)}
            <div class="btn-row">
              <button class="btn primary" type="submit">${icon("i-save")}保存工艺参数</button>
            </div>
          </form>
        </div>
      </article>
    </section>
  `;
  document.querySelectorAll("[data-process-param-group]").forEach((node) => node.addEventListener("click", async () => {
    state.selectedProcessParameterGroupId = Number(node.dataset.processParamGroup);
    await renderPage();
  }));
  document.getElementById("newProcessParamGroupBtn").addEventListener("click", createProcessParameterGroup);
  document.getElementById("deleteProcessParamGroupBtn").addEventListener("click", deleteProcessParameterGroup);
  wireUnitDoseCurveEditor();
  document.getElementById("processParamGroupForm").addEventListener("submit", saveProcessParameterGroup);
}

function defaultCurve() {
  return [{ tp_mg_l: 0, dose_mg_l: 0 }, { tp_mg_l: 0.3, dose_mg_l: 30 }, { tp_mg_l: 0.5, dose_mg_l: 60 }, { tp_mg_l: 1, dose_mg_l: 100 }];
}

let activeCurveDragBounds = null;

function normalizeCurve(curve) {
  const points = (Array.isArray(curve) && curve.length >= 2 ? curve : defaultCurve())
    .map((point) => ({
      tp_mg_l: clampNumber(point.tp_mg_l, 0, 20, 0),
      dose_mg_l: clampNumber(point.dose_mg_l, 0, 10000, 0),
    }))
    .filter((point) => Number.isFinite(point.tp_mg_l) && Number.isFinite(point.dose_mg_l));
  return sortedUniqueCurve(points.length >= 2 ? points : defaultCurve());
}

function unitDoseCurveEditor(curve) {
  const points = normalizeCurve(curve);
  return `
    <div class="curve-editor" id="unitDoseCurveEditor">
      <input id="unitDoseCurveData" name="curve_data" type="hidden" value="${htmlEscape(JSON.stringify(points))}">
      <input id="unitDoseCurveSelected" type="hidden" value="0">
      <div class="unit-dose-chart-wrap">
        <svg id="unitDoseCurveSvg" class="unit-dose-chart" viewBox="0 0 760 320" role="img" aria-label="单耗配置曲线"></svg>
      </div>
      <div class="unit-dose-control-row">
        <button class="btn ghost" id="addCurvePointBtn" type="button">增加关键点</button>
        <button class="btn ghost" id="deleteCurvePointBtn" type="button">删除选中点</button>
        <label>出水TP X<input id="curvePointTpInput" type="number" min="0" max="20" step="0.001"></label>
        <label>设定单耗 Y<input id="curvePointDoseInput" type="number" min="0" max="10000" step="0.001"></label>
        <span class="muted">点击图面增加关键点，拖动关键点或输入 X/Y 后折线会实时更新。</span>
      </div>
      <div id="unitDosePointList" class="unit-dose-point-list"></div>
    </div>
  `;
}

function clampNumber(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, number));
}

function sortedUniqueCurve(points) {
  const unique = new Map();
  points.forEach((point) => {
    const tp = Number(point.tp_mg_l.toFixed(3));
    unique.set(String(tp), { tp_mg_l: tp, dose_mg_l: Number(point.dose_mg_l.toFixed(3)) });
  });
  return [...unique.values()].sort((a, b) => a.tp_mg_l - b.tp_mg_l);
}

function curveEditorPoints() {
  try {
    return normalizeCurve(JSON.parse(document.getElementById("unitDoseCurveData")?.value || "[]"));
  } catch {
    return defaultCurve();
  }
}

function setCurveEditorPoints(points, selectedIndex = null) {
  const normalized = normalizeCurve(points);
  const data = document.getElementById("unitDoseCurveData");
  if (data) data.value = JSON.stringify(normalized);
  const selected = document.getElementById("unitDoseCurveSelected");
  if (selected) {
    const current = selectedIndex == null ? Number(selected.value || 0) : selectedIndex;
    selected.value = String(Math.min(normalized.length - 1, Math.max(0, current)));
  }
  renderUnitDoseCurve();
}

function selectedCurvePointIndex() {
  const points = curveEditorPoints();
  return Math.min(points.length - 1, Math.max(0, Number(document.getElementById("unitDoseCurveSelected")?.value || 0)));
}

function setSelectedCurvePoint(index) {
  const selected = document.getElementById("unitDoseCurveSelected");
  if (selected) selected.value = String(index);
  renderUnitDoseCurve();
}

function curveChartBounds(points) {
  const maxX = Math.max(1, ...points.map((point) => point.tp_mg_l));
  const maxY = Math.max(100, ...points.map((point) => point.dose_mg_l));
  return {
    width: 760,
    height: 320,
    left: 56,
    right: 20,
    top: 18,
    bottom: 42,
    maxX: Math.min(20, Math.ceil(maxX * 1.15 * 1000) / 1000),
    maxY: Math.min(10000, Math.ceil(maxY * 1.15 / 10) * 10),
  };
}

function curvePointToSvg(point, bounds) {
  const plotWidth = bounds.width - bounds.left - bounds.right;
  const plotHeight = bounds.height - bounds.top - bounds.bottom;
  return {
    x: bounds.left + (point.tp_mg_l / bounds.maxX) * plotWidth,
    y: bounds.top + plotHeight - (point.dose_mg_l / bounds.maxY) * plotHeight,
  };
}

function clientPointToSvg(svg, event) {
  const matrix = svg.getScreenCTM();
  if (matrix && typeof svg.createSVGPoint === "function") {
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const transformed = point.matrixTransform(matrix.inverse());
    return { x: transformed.x, y: transformed.y };
  }
  const rect = svg.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) / rect.width) * 760,
    y: ((event.clientY - rect.top) / rect.height) * 320,
  };
}

function svgToCurvePoint(x, y, bounds) {
  const plotWidth = bounds.width - bounds.left - bounds.right;
  const plotHeight = bounds.height - bounds.top - bounds.bottom;
  const px = clampNumber(x, bounds.left, bounds.width - bounds.right, bounds.left);
  const py = clampNumber(y, bounds.top, bounds.height - bounds.bottom, bounds.height - bounds.bottom);
  return {
    tp_mg_l: Number((((px - bounds.left) / plotWidth) * bounds.maxX).toFixed(3)),
    dose_mg_l: Number((((bounds.top + plotHeight - py) / plotHeight) * bounds.maxY).toFixed(3)),
  };
}

function renderUnitDoseCurve() {
  const svg = document.getElementById("unitDoseCurveSvg");
  if (!svg) return;
  const points = curveEditorPoints();
  const selectedIndex = selectedCurvePointIndex();
  const bounds = activeCurveDragBounds || curveChartBounds(points);
  const svgPoints = points.map((point) => curvePointToSvg(point, bounds));
  const xTicks = [0, bounds.maxX / 2, bounds.maxX];
  const yTicks = [0, bounds.maxY / 2, bounds.maxY];
  svg.innerHTML = `
    <rect class="unit-dose-plot-bg" x="${bounds.left}" y="${bounds.top}" width="${bounds.width - bounds.left - bounds.right}" height="${bounds.height - bounds.top - bounds.bottom}"></rect>
    ${xTicks.map((tick) => {
      const x = curvePointToSvg({ tp_mg_l: tick, dose_mg_l: 0 }, bounds).x;
      return `<line class="unit-dose-grid" x1="${x}" y1="${bounds.top}" x2="${x}" y2="${bounds.height - bounds.bottom}"></line><text class="unit-dose-axis-text" x="${x}" y="${bounds.height - 16}" text-anchor="middle">${fmtCompact(tick, 3)}</text>`;
    }).join("")}
    ${yTicks.map((tick) => {
      const y = curvePointToSvg({ tp_mg_l: 0, dose_mg_l: tick }, bounds).y;
      return `<line class="unit-dose-grid" x1="${bounds.left}" y1="${y}" x2="${bounds.width - bounds.right}" y2="${y}"></line><text class="unit-dose-axis-text" x="${bounds.left - 10}" y="${y + 4}" text-anchor="end">${fmtCompact(tick, 1)}</text>`;
    }).join("")}
    <polyline class="unit-dose-line" points="${svgPoints.map((point) => `${point.x},${point.y}`).join(" ")}"></polyline>
    ${svgPoints.map((point, index) => `
      <g class="unit-dose-point ${index === selectedIndex ? "selected" : ""}" data-curve-point="${index}" transform="translate(${point.x} ${point.y})">
        <circle r="${index === selectedIndex ? 8 : 6}"></circle>
        <text y="-12" text-anchor="middle">${fmtCompact(points[index].tp_mg_l, 3)}, ${fmtCompact(points[index].dose_mg_l, 1)}</text>
      </g>
    `).join("")}
    <text class="unit-dose-axis-label" x="${bounds.width / 2}" y="${bounds.height - 2}" text-anchor="middle">出水TP (mg/L)</text>
    <text class="unit-dose-axis-label" x="14" y="${bounds.height / 2}" text-anchor="middle" transform="rotate(-90 14 ${bounds.height / 2})">单耗 (mg/L)</text>
  `;
  renderCurvePointControls(points[selectedIndex], points, selectedIndex);
  wireCurvePointEvents();
}

function renderCurvePointControls(point, points, selectedIndex) {
  const tpInput = document.getElementById("curvePointTpInput");
  const doseInput = document.getElementById("curvePointDoseInput");
  if (tpInput && document.activeElement !== tpInput) tpInput.value = point ? point.tp_mg_l : "";
  if (doseInput && document.activeElement !== doseInput) doseInput.value = point ? point.dose_mg_l : "";
  const deleteButton = document.getElementById("deleteCurvePointBtn");
  if (deleteButton) deleteButton.disabled = points.length <= 2;
  const list = document.getElementById("unitDosePointList");
  if (list) {
    list.innerHTML = points.map((item, index) => `
      <button class="unit-dose-point-chip ${index === selectedIndex ? "active" : ""}" data-curve-chip="${index}" type="button">
        X ${fmtCompact(item.tp_mg_l, 3)} / Y ${fmtCompact(item.dose_mg_l, 1)}
      </button>
    `).join("");
    list.querySelectorAll("[data-curve-chip]").forEach((node) => node.addEventListener("click", () => setSelectedCurvePoint(Number(node.dataset.curveChip))));
  }
}

function wireCurvePointEvents() {
  document.querySelectorAll("[data-curve-point]").forEach((node) => {
    node.addEventListener("pointerdown", startCurvePointDrag);
    node.addEventListener("click", (event) => {
      event.stopPropagation();
      setSelectedCurvePoint(Number(node.dataset.curvePoint));
    });
  });
}

function updateSelectedCurvePoint(partial) {
  const points = curveEditorPoints();
  const index = selectedCurvePointIndex();
  points[index] = { ...points[index], ...partial };
  const targetPoint = points[index];
  const sorted = sortedUniqueCurve(points);
  const newIndex = sorted.findIndex((point) => point.tp_mg_l === Number(targetPoint.tp_mg_l.toFixed(3)));
  setCurveEditorPoints(sorted, newIndex < 0 ? index : newIndex);
}

function addCurvePoint() {
  const points = curveEditorPoints();
  const index = selectedCurvePointIndex();
  const left = points[index] || points[points.length - 1];
  const right = points[index + 1] || null;
  const newPoint = right
    ? { tp_mg_l: (left.tp_mg_l + right.tp_mg_l) / 2, dose_mg_l: (left.dose_mg_l + right.dose_mg_l) / 2 }
    : { tp_mg_l: Math.min(20, left.tp_mg_l + 0.1), dose_mg_l: left.dose_mg_l };
  const sorted = sortedUniqueCurve([...points, newPoint]);
  const newIndex = sorted.findIndex((point) => point.tp_mg_l === Number(newPoint.tp_mg_l.toFixed(3)));
  setCurveEditorPoints(sorted, newIndex < 0 ? sorted.length - 1 : newIndex);
}

function addCurvePointFromSvg(event) {
  if (event.target.closest("[data-curve-point]")) return;
  const svg = document.getElementById("unitDoseCurveSvg");
  if (!svg) return;
  const { x, y } = clientPointToSvg(svg, event);
  const points = curveEditorPoints();
  const newPoint = svgToCurvePoint(x, y, curveChartBounds(points));
  const sorted = sortedUniqueCurve([...points, newPoint]);
  const newIndex = sorted.findIndex((point) => point.tp_mg_l === Number(newPoint.tp_mg_l.toFixed(3)));
  setCurveEditorPoints(sorted, newIndex < 0 ? sorted.length - 1 : newIndex);
}

function deleteCurvePoint() {
  const points = curveEditorPoints();
  if (points.length <= 2) {
    showToast("单耗曲线至少保留 2 个关键点");
    return;
  }
  const index = selectedCurvePointIndex();
  points.splice(index, 1);
  setCurveEditorPoints(points, Math.min(index, points.length - 1));
}

function startCurvePointDrag(event) {
  event.preventDefault();
  const svg = document.getElementById("unitDoseCurveSvg");
  if (!svg) return;
  const index = Number(event.currentTarget.dataset.curvePoint);
  const dragBounds = curveChartBounds(curveEditorPoints());
  activeCurveDragBounds = dragBounds;
  setSelectedCurvePoint(index);
  const move = (moveEvent) => {
    const { x, y } = clientPointToSvg(svg, moveEvent);
    updateSelectedCurvePoint(svgToCurvePoint(x, y, dragBounds));
  };
  const finish = () => {
    activeCurveDragBounds = null;
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", finish);
    window.removeEventListener("pointercancel", finish);
    renderUnitDoseCurve();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", finish);
  window.addEventListener("pointercancel", finish);
}

function wireUnitDoseCurveEditor() {
  renderUnitDoseCurve();
  document.getElementById("unitDoseCurveSvg")?.addEventListener("click", addCurvePointFromSvg);
  document.getElementById("addCurvePointBtn")?.addEventListener("click", addCurvePoint);
  document.getElementById("deleteCurvePointBtn")?.addEventListener("click", deleteCurvePoint);
  document.getElementById("curvePointTpInput")?.addEventListener("input", (event) => {
    updateSelectedCurvePoint({ tp_mg_l: clampNumber(event.target.value, 0, 20, 0) });
  });
  document.getElementById("curvePointDoseInput")?.addEventListener("input", (event) => {
    updateSelectedCurvePoint({ dose_mg_l: clampNumber(event.target.value, 0, 10000, 0) });
  });
}

function metricMini(p) {
  const rec = p.latest_recommendation;
  return `<div class="list-card ${p.id === state.selectedPointId ? "active" : ""}" data-point-select="${p.id}"><b>${htmlEscape(p.name)}</b><div class="muted">${fmt(rec?.final_l_h, 1)} L/h · ${htmlEscape(rec?.mode || "")}</div></div>`;
}

function defaultNewPoint() {
  const next = state.points.length + 1;
  return {
    name: `新建PAC投加点${next}`,
    code: `PAC_NEW_${next}`,
    enabled: true,
    flow_source: "line",
    in_flow_tag_id: null,
    in_tp_tag_id: null,
    in_ph_tag_id: null,
    out_flow_tag_id: null,
    out_tp_tag_id: null,
    in_flow_weight: 1,
    reflux_flow_1_tag_id: null,
    reflux_flow_2_tag_id: null,
    pac_flow_tag_id: null,
    bio_orp1_tag_id: null,
    bio_orp2_tag_id: null,
    bio_orp3_tag_id: null,
    bio_orp4_tag_id: null,
    bio_do1_tag_id: null,
    bio_do2_tag_id: null,
    bio_mlss1_tag_id: null,
    bio_mlss2_tag_id: null,
    tp_model_id: null,
    pac_flow_model_id: null,
    process_parameter_group_id: null,
    source_tags: [],
    display_order: next,
    write_enabled: false,
  };
}

function modelSelectOptions(models, kind) {
  return [
    { value: "", label: "无" },
    ...models
      .filter((model) => model.model_kind === kind)
      .map((model) => ({ value: String(model.id), label: `${model.name}（${dateMinute(model.trained_at)}）` })),
  ];
}

function processSourceSelect(name, label, point) {
  const options = [{ value: "", label: "无" }, ...(point.source_tags || []).map((tag) => ({
    value: String(tag.id),
    label: `${tag.dosing_point_id == null ? "公共数据" : point.name} / ${tag.tag_code}`,
  }))];
  return selectField(name, label, options, point[name] == null ? "" : String(point[name]));
}

function selectField(name, label, options, value) {
  return `
    <div class="field">
      <label for="${name}">${label}</label>
      <select id="${name}" name="${name}">
        ${options.map((opt) => `<option value="${htmlEscape(opt.value)}" ${String(opt.value) === String(value) ? "selected" : ""}>${htmlEscape(opt.label)}</option>`).join("")}
      </select>
    </div>
  `;
}

function pointFormPayload(form) {
  const payload = formObject(form);
  payload.enabled = payload.enabled === "true";
  payload.code = String(payload.code || "").trim();
  payload.name = String(payload.name || "").trim();
  payload.in_flow_weight = Math.max(0, Number(payload.in_flow_weight ?? 1));
  processSourceFields.forEach(([name]) => {
    payload[name] = payload[name] == null ? null : Number(payload[name]);
  });
  payload.tp_model_id = payload.tp_model_id == null ? null : Number(payload.tp_model_id);
  payload.pac_flow_model_id = payload.pac_flow_model_id == null ? null : Number(payload.pac_flow_model_id);
  payload.process_parameter_group_id = payload.process_parameter_group_id == null ? null : Number(payload.process_parameter_group_id);
  return payload;
}

async function saveDosingPoint(event) {
  event.preventDefault();
  const payload = pointFormPayload(event.currentTarget);
  try {
    if (state.editingNewPoint) {
      const res = await api("/api/dosing-points", { method: "POST", body: JSON.stringify(payload) });
      state.selectedPointId = res.id;
      state.editingNewPoint = false;
      showToast("投加点已创建，关联配置和标签已生成");
    } else {
      await api(`/api/dosing-points/${state.selectedPointId}`, { method: "PUT", body: JSON.stringify(payload) });
      showToast("投加点属性已保存");
    }
    await refreshAll();
  } catch (err) {
    showToast(`保存失败：${err.message}`);
  }
}

async function deleteSelectedPoint() {
  const p = selectedPoint();
  if (!p) return;
  if (!window.confirm(`确认删除「${p.name}」？关联样本、推荐结果、配置和标签会同步删除。`)) return;
  try {
    await api(`/api/dosing-points/${p.id}`, { method: "DELETE" });
    showToast("投加点已删除，后台关联数据已同步清理");
    state.editingNewPoint = false;
    state.selectedPointId = null;
    await refreshAll();
  } catch (err) {
    showToast(`删除失败：${err.message}`);
  }
}

function field(name, label, value, type = "number") {
  const step = type === "number" ? "step=\"any\"" : "";
  return `<div class="field"><label for="${name}">${label}</label><input id="${name}" name="${name}" type="${type}" ${step} value="${htmlEscape(value)}"></div>`;
}

function numberField(name, label, value, min, max, step = "any") {
  const minAttr = min == null ? "" : ` min="${htmlEscape(min)}"`;
  const maxAttr = max == null ? "" : ` max="${htmlEscape(max)}"`;
  return `<div class="field"><label for="${name}">${label}</label><input id="${name}" name="${name}" type="number"${minAttr}${maxAttr} step="${step}" value="${htmlEscape(value)}"></div>`;
}

function formObject(form) {
  const out = {};
  new FormData(form).forEach((value, key) => {
    out[key] = value === "" ? null : (Number.isFinite(Number(value)) ? Number(value) : value);
  });
  return out;
}

function processParameterGroupPayload(form) {
  const curve = curveEditorPoints();
  return {
    name: String(form.elements.name.value || "").trim(),
    tp_target_mg_l: Number(form.elements.tp_target_mg_l.value),
    tp_upper_mg_l: Number(form.elements.tp_upper_mg_l.value),
    pac_density_kg_l: Number(form.elements.pac_density_kg_l.value),
    pac_min_l_h: Number(form.elements.pac_min_l_h.value),
    pac_max_l_h: Number(form.elements.pac_max_l_h.value),
    calculation_interval_seconds: Number(form.elements.calculation_interval_seconds.value),
    unit_dose_curve: curve,
  };
}

async function createProcessParameterGroup() {
  try {
    const suffix = Date.now().toString().slice(-6);
    const group = await api("/api/process-parameter-groups", {
      method: "POST",
      body: JSON.stringify({
        name: `工艺参数${suffix}`,
        tp_target_mg_l: 0.18,
        tp_upper_mg_l: 0.3,
        pac_density_kg_l: 1.2,
        pac_min_l_h: 0,
        pac_max_l_h: 60,
        calculation_interval_seconds: 60,
        unit_dose_curve: defaultCurve(),
      }),
    });
    state.selectedProcessParameterGroupId = group.id;
    showToast("参数组已新增");
    await refreshAll();
  } catch (err) {
    showToast(`新增失败：${err.message}`);
  }
}

async function saveProcessParameterGroup(event) {
  event.preventDefault();
  try {
    await api(`/api/process-parameter-groups/${state.selectedProcessParameterGroupId}`, {
      method: "PUT",
      body: JSON.stringify(processParameterGroupPayload(event.currentTarget)),
    });
    showToast("工艺参数已保存并重新计算");
    await refreshAll();
  } catch (err) {
    showToast(`保存失败：${err.message}`);
  }
}

async function deleteProcessParameterGroup() {
  const groups = await api("/api/process-parameter-groups");
  const current = groups.find((group) => group.id === state.selectedProcessParameterGroupId);
  if (!current || !window.confirm(`确认删除参数组「${current.name}」？其关联投加点会自动切换到保留的参数组。`)) return;
  try {
    await api(`/api/process-parameter-groups/${current.id}`, { method: "DELETE" });
    state.selectedProcessParameterGroupId = null;
    showToast("参数组已删除，关联投加点已自动重分配");
    await refreshAll();
  } catch (err) {
    showToast(`删除失败：${err.message}`);
  }
}
