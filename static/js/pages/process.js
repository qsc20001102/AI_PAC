async function renderProcess(main) {
  const processParameterGroups = await api("/api/process-parameter-groups");
  const rows = state.points.map((p) => `
    <div class="list-card ${!state.editingNewPoint && p.id === state.selectedPointId ? "active" : ""}" data-point-select="${p.id}">
      <div style="font-weight:800">${htmlEscape(p.name)}</div>
      <div class="muted" style="margin-top:5px">${htmlEscape(p.code)}</div>
      <div style="margin-top:8px"><span class="status-tag status-${p.enabled ? "fresh" : "stale"}">${p.enabled ? "启用" : "停用"}</span></div>
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
              ${selectField("forecast_horizon_minutes", "出水TP预测时长(min)", [
                { value: "30", label: "30 分钟" },
                { value: "60", label: "60 分钟" },
                { value: "120", label: "120 分钟" },
              ], String(current.forecast_horizon_minutes ?? 120))}
            </div>
            <div class="process-source-title">单耗配置曲线</div>
            <div id="unitDoseCurveRows" class="curve-editor">
              ${curve.map((point, index) => curveRow(point, index)).join("")}
            </div>
            <div class="btn-row">
              <button id="addCurvePointBtn" class="btn ghost" type="button">增加关键点</button>
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
  document.getElementById("addCurvePointBtn").addEventListener("click", addCurvePoint);
  document.querySelectorAll("[data-curve-delete]").forEach((node) => node.addEventListener("click", deleteCurvePoint));
  document.getElementById("processParamGroupForm").addEventListener("submit", saveProcessParameterGroup);
}

function defaultCurve() {
  return [{ tp_mg_l: 0, dose_mg_l: 0 }, { tp_mg_l: 0.3, dose_mg_l: 30 }, { tp_mg_l: 0.5, dose_mg_l: 60 }, { tp_mg_l: 1, dose_mg_l: 100 }];
}

function normalizeCurve(curve) {
  return Array.isArray(curve) && curve.length >= 2 ? curve : defaultCurve();
}

function curveRow(point, index) {
  return `
    <div class="curve-row" data-curve-row>
      <label>出水TP<input name="curve_tp" type="number" min="0" max="20" step="0.001" value="${htmlEscape(point.tp_mg_l)}"></label>
      <label>设定单耗<input name="curve_dose" type="number" min="0" max="10000" step="0.001" value="${htmlEscape(point.dose_mg_l)}"></label>
      <button class="btn ghost" type="button" data-curve-delete="${index}">删除</button>
    </div>
  `;
}

function addCurvePoint() {
  const container = document.getElementById("unitDoseCurveRows");
  container.insertAdjacentHTML("beforeend", curveRow({ tp_mg_l: "", dose_mg_l: "" }, container.querySelectorAll("[data-curve-row]").length));
  container.querySelectorAll("[data-curve-delete]").forEach((node) => node.addEventListener("click", deleteCurvePoint));
}

function deleteCurvePoint(event) {
  const rows = document.querySelectorAll("[data-curve-row]");
  if (rows.length <= 2) {
    showToast("单耗曲线至少保留 2 个关键点");
    return;
  }
  event.currentTarget.closest("[data-curve-row]")?.remove();
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
    process_parameter_group_id: null,
    source_tags: [],
    display_order: next,
    write_enabled: false,
  };
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
  const curve = Array.from(form.querySelectorAll("[data-curve-row]")).map((row) => ({
    tp_mg_l: Number(row.querySelector('[name="curve_tp"]').value),
    dose_mg_l: Number(row.querySelector('[name="curve_dose"]').value),
  }));
  return {
    name: String(form.elements.name.value || "").trim(),
    tp_target_mg_l: Number(form.elements.tp_target_mg_l.value),
    tp_upper_mg_l: Number(form.elements.tp_upper_mg_l.value),
    pac_density_kg_l: Number(form.elements.pac_density_kg_l.value),
    pac_min_l_h: Number(form.elements.pac_min_l_h.value),
    pac_max_l_h: Number(form.elements.pac_max_l_h.value),
    calculation_interval_seconds: Number(form.elements.calculation_interval_seconds.value),
    forecast_horizon_minutes: Number(form.elements.forecast_horizon_minutes.value),
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
        forecast_horizon_minutes: 120,
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
