async function renderProcess(main) {
  const [chemicalGroups, processParameterGroups] = await Promise.all([
    api("/api/chemical-groups"),
    api("/api/process-parameter-groups"),
  ]);
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
        <div class="panel-header">
          <div class="panel-title">投加点</div>
          <button id="newPointBtn" class="btn ghost" type="button">新增</button>
        </div>
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
            </div>
            <div class="process-source-title">关联参数组</div>
            <div class="form-grid">
              ${selectField("chemical_group_id", "药剂组", chemicalGroups.map((group) => ({ value: String(group.id), label: group.batch_id })), p.chemical_group_id == null ? "" : String(p.chemical_group_id))}
              ${selectField("process_parameter_group_id", "工艺参数组", processParameterGroups.map((group) => ({ value: String(group.id), label: group.name })), p.process_parameter_group_id == null ? "" : String(p.process_parameter_group_id))}
            </div>
            <div class="process-source-title">数据来源配置</div>
            <div class="form-grid process-source-grid">
              ${numberField("in_flow_weight", "进水流量权重", p.in_flow_weight ?? 1, "0", "1", "0.01")}
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

async function renderChemical(main) {
  const groups = await api("/api/chemical-groups");
  if (!groups.length) {
    main.innerHTML = `<div class="empty">暂无药剂组</div>`;
    return;
  }
  if (!groups.some((group) => group.id === state.selectedChemicalGroupId)) {
    state.selectedChemicalGroupId = groups[0].id;
  }
  const current = groups.find((group) => group.id === state.selectedChemicalGroupId) || groups[0];
  main.innerHTML = `
    <section class="page-grid process-page-grid">
      <aside class="panel">
        <div class="panel-header">
          <div class="panel-title">药剂组</div>
          <button id="newChemicalGroupBtn" class="btn ghost" type="button">新增</button>
        </div>
        <div class="panel-body process-point-list">
          ${groups.map((group) => `
            <div class="list-card ${group.id === current.id ? "active" : ""}" data-chemical-group="${group.id}">
              <div style="font-weight:800">${htmlEscape(group.batch_id)}</div>
            </div>
          `).join("")}
        </div>
      </aside>
      <article class="panel">
        <div class="panel-header">
          <div class="panel-title">药剂参数</div>
          <button id="deleteChemicalGroupBtn" class="btn" type="button">删除药剂组</button>
        </div>
        <div class="panel-body">
          <form id="chemicalGroupForm">
            <div class="form-grid">
              ${field("batch_id", "药剂批次", current.batch_id, "text")}
              ${numberField("pac_density_kg_l", "PAC密度", current.pac_density_kg_l, "0.01", "2", "0.001")}
              ${numberField("al_p_ratio", "摩尔比", current.al_p_ratio, "0.1", "8", "0.01")}
              ${numberField("effective_factor", "系数", current.effective_factor, "0.01", "1.5", "0.01")}
            </div>
            <div class="btn-row"><button class="btn primary" type="submit">${icon("i-save")}保存药剂参数</button><span class="muted">保存后会重新计算关联投加点的建议值。</span></div>
          </form>
        </div>
      </article>
    </section>
  `;
  document.querySelectorAll("[data-chemical-group]").forEach((node) => node.addEventListener("click", async () => {
    state.selectedChemicalGroupId = Number(node.dataset.chemicalGroup);
    await renderPage();
  }));
  document.getElementById("newChemicalGroupBtn").addEventListener("click", createChemicalGroup);
  document.getElementById("deleteChemicalGroupBtn").addEventListener("click", deleteChemicalGroup);
  document.getElementById("chemicalGroupForm").addEventListener("submit", saveChemicalGroup);
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
  main.innerHTML = `
    <section class="page-grid process-page-grid">
      <aside class="panel">
        <div class="panel-header">
          <div class="panel-title">参数组</div>
          <button id="newProcessParamGroupBtn" class="btn ghost" type="button">新增</button>
        </div>
        <div class="panel-body process-point-list">
          ${groups.map((group) => `
            <div class="list-card ${group.id === current.id ? "active" : ""}" data-process-param-group="${group.id}">
              <div style="font-weight:800">${htmlEscape(group.name)}</div>
            </div>
          `).join("")}
        </div>
      </aside>
      <article class="panel">
        <div class="panel-header">
          <div class="panel-title">工艺参数</div>
          <button id="deleteProcessParamGroupBtn" class="btn" type="button">删除参数组</button>
        </div>
        <div class="panel-body">
          <form id="processParamGroupForm">
            <div class="form-grid">
              ${field("name", "参数组名称", current.name, "text")}
              ${numberField("tp_target_mg_l", "目标TP <", current.tp_target_mg_l, "0", "5", "0.001")}
              ${numberField("tp_limit_mg_l", "出水限制", current.tp_limit_mg_l, "0", "10", "0.001")}
              ${numberField("pac_min_l_h", "最小 L/h", current.pac_min_l_h, "0", "500", "0.01")}
              ${numberField("pac_max_l_h", "最大 L/h", current.pac_max_l_h, "0", "1000", "0.01")}
              ${numberField("calculation_interval_seconds", "计算周期(s)", current.calculation_interval_seconds, "5", "86400", "1")}
            </div>
            <div class="process-source-title">反馈参数</div>
            <div class="form-grid">
              ${numberField("lag_minutes", "滞后分钟", current.lag_minutes, "0", "360", "1")}
              ${numberField("feedback_kp", "反馈Kp", current.feedback_kp, "0", "2", "0.01")}
              ${numberField("feedback_min", "反馈下限", current.feedback_min, "0.1", "2", "0.01")}
              ${numberField("feedback_max", "反馈上限", current.feedback_max, "0.1", "2", "0.01")}
              ${numberField("feedback_window_minutes", "反馈窗口分钟", current.feedback_window_minutes, "5", "720", "1")}
            </div>
            <div class="btn-row"><button class="btn primary" type="submit">${icon("i-save")}保存工艺参数</button><span class="muted">这些参数会影响建议值上下限、超限保护和滞后反馈修正。</span></div>
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
  document.getElementById("processParamGroupForm").addEventListener("submit", saveProcessParameterGroup);
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
    phosphorus_source: "po4_priority",
    feedback_source: "line_out",
    in_flow_tag_id: null,
    in_tp_tag_id: null,
    out_flow_tag_id: null,
    out_tp_tag_id: null,
    zone_flow_tag_id: null,
    in_flow_weight: 1,
    reflux_flow_1_tag_id: null,
    reflux_flow_2_tag_id: null,
    po4_tag_id: null,
    pac_flow_tag_id: null,
    chemical_group_id: null,
    process_parameter_group_id: null,
    source_tags: [],
    manual_contribution_factor: 1,
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

function pointBackendSummary(p) {
  const rec = p.latest_recommendation;
  return `
    <hr style="border:0;border-top:1px solid var(--line-soft);margin:18px 0">
    <div class="kv">
      <div class="kv-label">当前建议</div><div>${fmt(rec?.final_l_h, 2)} L/h · ${htmlEscape(rec?.mode || "未计算")}</div>
      <div class="kv-label">PAC批次</div><div>${htmlEscape(p.pac_config?.batch_id || "未配置")}</div>
      <div class="kv-label">目标TP</div><div>${fmtCompact(p.control_config?.tp_target_mg_l, 3)} mg/L</div>
    </div>
  `;
}

function pointFormPayload(form) {
  const payload = formObject(form);
  payload.enabled = payload.enabled === "true";
  payload.code = String(payload.code || "").trim();
  payload.name = String(payload.name || "").trim();
  payload.in_flow_weight = Math.max(0, Math.min(1, Number(payload.in_flow_weight ?? 1)));
  processSourceFields.forEach(([name]) => {
    payload[name] = payload[name] == null ? null : Number(payload[name]);
  });
  ["chemical_group_id", "process_parameter_group_id"].forEach((name) => {
    payload[name] = payload[name] == null ? null : Number(payload[name]);
  });
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
  return `<div class="field"><label for="${name}">${label}</label><input id="${name}" name="${name}" type="number" min="${min}" max="${max}" step="${step}" value="${htmlEscape(value)}"></div>`;
}

function formObject(form) {
  const out = {};
  new FormData(form).forEach((value, key) => {
    out[key] = value === "" ? null : (Number.isFinite(Number(value)) && !String(key).includes("batch") ? Number(value) : value);
  });
  return out;
}

async function saveConfig(event, type) {
  event.preventDefault();
  try {
    const payload = formObject(event.currentTarget);
    const path = type === "pac" ? "pac-config" : "control-config";
    await api(`/api/dosing-points/${state.selectedPointId}/${path}`, { method: "PUT", body: JSON.stringify(payload) });
    showToast("配置已保存并重新计算");
    await refreshAll();
  } catch (err) {
    showToast(`保存失败：${err.message}`);
  }
}

function chemicalGroupPayload(form) {
  return {
    batch_id: String(form.elements.batch_id.value || "").trim(),
    pac_density_kg_l: Number(form.elements.pac_density_kg_l.value),
    al_p_ratio: Number(form.elements.al_p_ratio.value),
    effective_factor: Number(form.elements.effective_factor.value),
  };
}

function processParameterGroupPayload(form) {
  return {
    name: String(form.elements.name.value || "").trim(),
    tp_target_mg_l: Number(form.elements.tp_target_mg_l.value),
    tp_limit_mg_l: Number(form.elements.tp_limit_mg_l.value),
    pac_min_l_h: Number(form.elements.pac_min_l_h.value),
    pac_max_l_h: Number(form.elements.pac_max_l_h.value),
    calculation_interval_seconds: Number(form.elements.calculation_interval_seconds.value),
    lag_minutes: Number(form.elements.lag_minutes.value),
    feedback_kp: Number(form.elements.feedback_kp.value),
    feedback_min: Number(form.elements.feedback_min.value),
    feedback_max: Number(form.elements.feedback_max.value),
    feedback_window_minutes: Number(form.elements.feedback_window_minutes.value),
  };
}

async function createChemicalGroup() {
  try {
    const suffix = Date.now().toString().slice(-6);
    const group = await api("/api/chemical-groups", {
      method: "POST",
      body: JSON.stringify({
        batch_id: `新药剂批次${suffix}`,
        pac_density_kg_l: 1.2,
        al_p_ratio: 2.5,
        effective_factor: 0.9,
      }),
    });
    state.selectedChemicalGroupId = group.id;
    showToast("药剂组已新增");
    await refreshAll();
  } catch (err) {
    showToast(`新增失败：${err.message}`);
  }
}

async function saveChemicalGroup(event) {
  event.preventDefault();
  try {
    await api(`/api/chemical-groups/${state.selectedChemicalGroupId}`, {
      method: "PUT",
      body: JSON.stringify(chemicalGroupPayload(event.currentTarget)),
    });
    showToast("药剂参数已保存并重新计算");
    await refreshAll();
  } catch (err) {
    showToast(`保存失败：${err.message}`);
  }
}

async function deleteChemicalGroup() {
  const groups = await api("/api/chemical-groups");
  const current = groups.find((group) => group.id === state.selectedChemicalGroupId);
  if (!current || !window.confirm(`确认删除药剂组「${current.batch_id}」？其关联投加点会自动切换到保留的药剂组。`)) return;
  try {
    await api(`/api/chemical-groups/${current.id}`, { method: "DELETE" });
    state.selectedChemicalGroupId = null;
    showToast("药剂组已删除，关联投加点已自动重分配");
    await refreshAll();
  } catch (err) {
    showToast(`删除失败：${err.message}`);
  }
}

async function createProcessParameterGroup() {
  try {
    const suffix = Date.now().toString().slice(-6);
    const group = await api("/api/process-parameter-groups", {
      method: "POST",
      body: JSON.stringify({
        name: `工艺参数${suffix}`,
        tp_target_mg_l: 0.18,
        tp_limit_mg_l: 0.3,
        pac_min_l_h: 0,
        pac_max_l_h: 60,
        calculation_interval_seconds: 60,
        lag_minutes: 60,
        feedback_kp: 0.25,
        feedback_min: 0.8,
        feedback_max: 1.3,
        feedback_window_minutes: 120,
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
