async function renderModels(main) {
  const data = await api("/api/models");
  state.models = data.models || [];
  const points = data.points || [];
  if (!state.editingNewModel && (!state.selectedModelId || !state.models.some((model) => model.id === state.selectedModelId))) {
    state.selectedModelId = state.models[0]?.id || null;
  }
  const selected = state.models.find((model) => model.id === state.selectedModelId);
  const rows = state.models.length ? state.models.map((model) => `
    <button class="list-card model-list-card ${!state.editingNewModel && model.id === state.selectedModelId ? "active" : ""}" data-model-select="${model.id}" type="button">
      <span class="model-list-name">${htmlEscape(model.name)}</span>
      <span class="muted">${htmlEscape(model.dosing_point_name)}</span>
      <span class="model-list-meta"><span>${modelKindLabel(model)} · ${model.sample_count || 0} 条样本</span><span class="status-tag status-${modelDisplayStatusClass(model)}">${modelDisplayStatusLabel(model)}</span></span>
    </button>
  `).join("") : '<div class="empty">还没有训练模型，请先新建。</div>';

  main.innerHTML = `
    <section class="page-grid model-page-grid">
      <aside class="panel model-list-panel">
        <div class="panel-header"><div class="panel-title">训练模型</div><button class="btn ghost" id="newModelBtn" type="button">新建</button></div>
        <div class="panel-body"><div class="model-list">${rows}</div></div>
      </aside>
      <article class="panel model-workspace-panel">
        ${state.editingNewModel || !selected ? renderNewModelWorkspace(points) : '<div class="panel-body" id="modelWorkspaceLoading">正在加载模型数据</div>'}
      </article>
    </section>
  `;
  document.getElementById("newModelBtn")?.addEventListener("click", async () => {
    state.editingNewModel = true;
    await renderPage();
  });
  document.querySelectorAll("[data-model-select]").forEach((node) => node.addEventListener("click", async () => {
    state.selectedModelId = Number(node.dataset.modelSelect);
    state.editingNewModel = false;
    state.modelSelectedSampleIds = [];
    await renderPage();
  }));
  document.getElementById("newModelForm")?.addEventListener("submit", createModelProject);
  document.getElementById("cancelNewModelBtn")?.addEventListener("click", async () => {
    state.editingNewModel = false;
    await renderPage();
  });
  if (!selected || state.editingNewModel) return;

  try {
    const query = new URLSearchParams();
    if (state.modelSampleStart) query.set("start", state.modelSampleStart);
    if (state.modelSampleEnd) query.set("end", state.modelSampleEnd);
    const detail = await api(`/api/models/${selected.id}${query.size ? `?${query}` : ""}`);
    state.modelSelectedSampleIds = state.modelSelectedSampleIds.filter((id) => detail.samples.some((sample) => sample.id === id));
    const workspace = document.querySelector(".model-workspace-panel");
    if (!workspace || state.activePage !== "models" || state.selectedModelId !== selected.id) return;
    workspace.innerHTML = renderModelWorkspace(detail);
    wireModelWorkspace(detail);
  } catch (err) {
    const loading = document.getElementById("modelWorkspaceLoading");
    if (loading) loading.innerHTML = `<div class="empty">模型数据加载失败：${htmlEscape(err.message)}</div>`;
  }
}

function modelStatusLabel(status) {
  return { draft: "待导入", recording: "待导入", ready: "已训练", published: "已投用" }[status] || localizedStatus(status);
}

function modelStatusClass(status) {
  if (status === "published") return "fresh";
  if (status === "recording") return "delayed";
  return "manual";
}

function modelDisplayStatusLabel(model) {
  return modelStatusLabel(model.status);
}

function modelDisplayStatusClass(model) {
  return modelStatusClass(model.status);
}

function modelKindLabel(model) {
  return "出水TP预测";
}

function renderNewModelWorkspace(points) {
  const defaultName = `${points[0]?.name || "投加点"}训练模型`;
  return `
    <div class="panel-header"><div class="panel-title">新建训练模型</div></div>
    <div class="panel-body model-empty-workspace">
      <form id="newModelForm" class="model-create-form">
        <div class="form-grid">
          ${field("name", "模型名称", defaultName, "text")}
          ${selectField("dosing_point_id", "训练投加点", points.map((point) => ({ value: String(point.id), label: `${point.name} (${point.code})` })), String(points[0]?.id || ""))}
          <input name="model_kind" type="hidden" value="tp_out_response">
          <input name="sample_interval_minutes" type="hidden" value="5">
        </div>
        <div class="btn-row"><button class="btn primary" type="submit">创建并配置样本</button><button class="btn" id="cancelNewModelBtn" type="button">取消</button></div>
      </form>
    </div>
  `;
}

function renderModelWorkspace(detail) {
  const { model, columns, samples } = detail;
  const metrics = model.metrics || {};
  const artifact = model.artifact || {};
  const sampleTargetLabel = "未来出水TP";
  const deployText = "投用后进入正常模式：系统枚举PAC加药流量，用模型预测所选时长出水TP，并选择刚低于目标TP的最小加药量。";
  return `
    <div class="panel-header">
      <div><div class="panel-title">${htmlEscape(model.name)}</div><div class="muted">训练投加点：${htmlEscape(model.dosing_point_name)}　类型：${modelKindLabel(model)}　状态：<span class="status-tag status-${modelDisplayStatusClass(model)}">${modelDisplayStatusLabel(model)}</span></div></div>
      <button class="btn" id="deleteModelBtn" type="button">删除模型</button>
    </div>
    <div class="panel-body model-workspace-body">
      <form id="modelConfigForm" class="model-config-form">
        <div class="form-grid">
          ${field("name", "模型名称", model.name, "text")}
          <input name="sample_interval_minutes" type="hidden" value="${htmlEscape(model.sample_interval_minutes || 5)}">
        </div>
        <div class="btn-row"><button class="btn ghost" type="submit">保存模型参数</button><span class="muted">模型绑定投加点后不可修改，避免混入不同工艺条件的样本。</span></div>
      </form>

      <section class="model-step model-sample-step">
        <div class="model-step-title"><span>1</span><div>导入训练样本</div><small>展示 ${samples.length} / ${model.sample_count || 0} 条</small></div>
        <div class="model-step-actions">
          <button class="btn ghost" id="refreshModelSamplesBtn" type="button">刷新样本</button>
          <button class="btn ghost" id="exportModelSamplesBtn" type="button">导出 CSV</button>
          <label class="btn primary file-button" for="modelCsvInput">导入 CSV</label><input id="modelCsvInput" type="file" accept=".csv,text/csv" hidden>
        </div>
        <div class="muted model-sampling-note">出水TP预测模型使用未来30/60/120分钟出水TP作为标签，标签不会进入输入特征。</div>
        <div class="model-sample-query">
          <label>开始时间<input id="modelSampleStart" type="datetime-local" value="${htmlEscape(state.modelSampleStart || "")}"></label>
          <label>结束时间<input id="modelSampleEnd" type="datetime-local" value="${htmlEscape(state.modelSampleEnd || "")}"></label>
          <button class="btn ghost" id="queryModelSamplesBtn" type="button">查询</button>
          <button class="btn" id="resetModelSampleQueryBtn" type="button">重置</button>
          <button class="btn ghost" id="deleteSelectedModelSamplesBtn" type="button" ${state.modelSelectedSampleIds.length ? "" : "disabled"}>删除已选（${state.modelSelectedSampleIds.length}）</button>
          <button class="btn danger" id="clearAllModelSamplesBtn" type="button" ${model.sample_count ? "" : "disabled"}>清空全部</button>
        </div>
        ${renderModelSampleTable(columns, samples, sampleTargetLabel)}
      </section>

      <section class="model-step">
        <div class="model-step-title"><span>2</span><div>训练模型</div><small>${model.trained_at ? `最近训练：${dateMinute(model.trained_at)}` : "尚未训练"}</small></div>
        <div class="model-step-actions"><button class="btn primary" id="trainModelBtn" type="button" ${samples.length < 2 ? "disabled" : ""}>开始训练</button>${model.trained_at ? '<button class="btn ghost" id="downloadModelArtifactBtn" type="button">下载模型文件</button>' : ""}</div>
        ${model.trained_at ? `<div class="model-metrics"><span>LightGBM</span><span>训练样本 ${metrics.samples ?? 0}</span><span>R² ${fmtCompact(metrics.R2, 4)}</span><span>MAE ${fmtCompact(metrics.MAE, 4)} mg/L</span><span>有效特征 ${metrics.feature_count ?? 0}</span><span>${htmlEscape(artifact.file_name || "模型文件已生成")}</span></div>` : '<div class="muted">样本数达到 2 条且覆盖变化工况后可开始 LightGBM 训练。</div>'}
      </section>

      <section class="model-step">
        <div class="model-step-title"><span>3</span><div>投用</div><small>${model.published_at ? `投用时间：${dateMinute(model.published_at)}` : "未投用"}</small></div>
        <div class="model-step-actions"><button class="btn ${model.status === "published" ? "" : "primary"}" id="deployModelBtn" type="button" ${model.trained_at ? "" : "disabled"}>${model.status === "published" ? "停止投用" : "投用模型"}</button></div>
        <div class="muted">${deployText}</div>
      </section>
    </div>
  `;
}

function modelSampleDigits(column) {
  const key = column?.key || "";
  if (key.includes("MLSS")) return 0;
  if (key.includes("ORP")) return 1;
  if (key.includes("Q") || key === "PAC_ACTUAL") return 2;
  if (key.includes("TP") || key.includes("DO")) return 4;
  return 4;
}

function modelSampleValue(value, digits = 4) {
  if (value === null || value === undefined || value === "") return "";
  return fmtCompact(value, digits);
}

function renderModelSampleTable(columns, samples, sampleTargetLabel) {
  const targetHeaders = ["未来30分钟出水TP", "未来60分钟出水TP", "未来120分钟出水TP"];
  return `
    <div class="model-sample-table-wrap">
      <table class="table model-sample-table">
        <thead><tr><th><input id="selectAllModelSamples" type="checkbox" aria-label="全选查询结果" ${samples.length && state.modelSelectedSampleIds.length === samples.length ? "checked" : ""}></th><th>时间</th>${columns.map((column) => `<th>${htmlEscape(column.label)}<div class="muted">${htmlEscape(column.tag_code || "")}</div></th>`).join("")}${targetHeaders.map((label) => `<th>${htmlEscape(label)}</th>`).join("")}<th>来源</th><th>操作</th></tr></thead>
        <tbody>${samples.length ? samples.map((sample) => `<tr>
          <td><input class="model-sample-select" data-model-sample-select="${sample.id}" type="checkbox" aria-label="选择样本 ${sample.id}" ${state.modelSelectedSampleIds.includes(sample.id) ? "checked" : ""}></td>
          <td>${dateMinute(sample.sample_time)}</td>
          ${columns.map((column) => `<td>${modelSampleValue(sample.values?.[column.key], modelSampleDigits(column))}</td>`).join("")}
          ${renderModelSampleTargets(sample)}
          <td>CSV</td>
          <td><button class="btn ghost model-delete-sample" data-model-sample-delete="${sample.id}" type="button">删除</button></td>
        </tr>`).join("") : `<tr><td colspan="${columns.length + targetHeaders.length + 4}" class="muted">当前查询范围内没有训练样本。</td></tr>`}</tbody>
      </table>
    </div>
  `;
}

function renderModelSampleTargets(sample) {
  return ["_training_target_tp_out_30", "_training_target_tp_out_60", "_training_target_tp_out_120"]
    .map((key) => `<td>${modelSampleValue(sample.values?.[key], 4)}</td>`)
    .join("");
}

function wireModelWorkspace(detail) {
  const model = detail.model;
  document.getElementById("modelConfigForm")?.addEventListener("submit", (event) => saveModelProject(event, model.id));
  document.getElementById("deleteModelBtn")?.addEventListener("click", () => deleteModelProject(model));
  document.getElementById("refreshModelSamplesBtn")?.addEventListener("click", async () => { await renderPage(); });
  document.getElementById("exportModelSamplesBtn")?.addEventListener("click", () => { window.location.href = `/api/models/${model.id}/samples.csv`; });
  document.getElementById("modelCsvInput")?.addEventListener("change", (event) => importModelSamples(model.id, event));
  document.getElementById("trainModelBtn")?.addEventListener("click", () => trainModelProject(model.id));
  document.getElementById("downloadModelArtifactBtn")?.addEventListener("click", () => { window.location.href = `/api/models/${model.id}/artifact`; });
  document.getElementById("deployModelBtn")?.addEventListener("click", () => deployModelProject(model));
  document.querySelectorAll("[data-model-sample-delete]").forEach((button) => button.addEventListener("click", () => deleteModelSample(model.id, Number(button.dataset.modelSampleDelete))));
  document.getElementById("queryModelSamplesBtn")?.addEventListener("click", async () => {
    state.modelSampleStart = document.getElementById("modelSampleStart")?.value || null;
    state.modelSampleEnd = document.getElementById("modelSampleEnd")?.value || null;
    state.modelSelectedSampleIds = [];
    await renderPage();
  });
  document.getElementById("resetModelSampleQueryBtn")?.addEventListener("click", async () => {
    state.modelSampleStart = null;
    state.modelSampleEnd = null;
    state.modelSelectedSampleIds = [];
    await renderPage();
  });
  document.getElementById("selectAllModelSamples")?.addEventListener("change", (event) => {
    state.modelSelectedSampleIds = event.target.checked ? detail.samples.map((sample) => sample.id) : [];
    updateModelSampleSelectionAction();
  });
  document.querySelectorAll("[data-model-sample-select]").forEach((input) => input.addEventListener("change", () => {
    state.modelSelectedSampleIds = [...document.querySelectorAll("[data-model-sample-select]:checked")].map((node) => Number(node.dataset.modelSampleSelect));
    updateModelSampleSelectionAction();
  }));
  document.getElementById("deleteSelectedModelSamplesBtn")?.addEventListener("click", () => deleteSelectedModelSamples(model.id));
  document.getElementById("clearAllModelSamplesBtn")?.addEventListener("click", () => clearAllModelSamples(model.id, model.sample_count));
}

function updateModelSampleSelectionAction() {
  const button = document.getElementById("deleteSelectedModelSamplesBtn");
  if (!button) return;
  const count = state.modelSelectedSampleIds.length;
  button.disabled = count === 0;
  button.textContent = `删除已选（${count}）`;
}

async function createModelProject(event) {
  event.preventDefault();
  const payload = formObject(event.currentTarget);
  payload.name = String(payload.name || "").trim();
  payload.dosing_point_id = Number(payload.dosing_point_id);
  payload.sample_interval_minutes = Number(payload.sample_interval_minutes || 5);
  payload.model_kind = "tp_out_response";
  try {
    const res = await api("/api/models", { method: "POST", body: JSON.stringify(payload) });
    state.selectedModelId = res.model.id;
    state.editingNewModel = false;
    showToast("训练模型已创建，可开始采集样本");
    await renderPage();
  } catch (err) { showToast(`创建失败：${err.message}`); }
}

async function saveModelProject(event, modelId) {
  event.preventDefault();
  const payload = formObject(event.currentTarget);
  payload.sample_interval_minutes = Number(payload.sample_interval_minutes);
  try {
    await api(`/api/models/${modelId}`, { method: "PUT", body: JSON.stringify(payload) });
    showToast("模型参数已保存");
    await renderPage();
  } catch (err) { showToast(`保存失败：${err.message}`); }
}

async function deleteModelProject(model) {
  if (!window.confirm(`确认删除训练模型「${model.name}」及其全部训练样本？`)) return;
  try {
    await api(`/api/models/${model.id}`, { method: "DELETE" });
    state.selectedModelId = null;
    showToast("训练模型已删除");
    await renderPage();
  } catch (err) { showToast(`删除失败：${err.message}`); }
}

async function importModelSamples(modelId, event) {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    const chunkSize = 0x8000;
    for (let index = 0; index < bytes.length; index += chunkSize) {
      binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
    }
    const res = await api(`/api/models/${modelId}/samples/import`, { method: "POST", body: JSON.stringify({ csv_base64: btoa(binary) }) });
    showToast(`已导入 ${res.written} 条训练样本`);
    await renderPage();
  } catch (err) { showToast(`导入失败：${err.message}`); }
}

async function deleteModelSample(modelId, sampleId) {
  if (!window.confirm("确认删除这条训练样本？")) return;
  try {
    await api(`/api/models/${modelId}/samples/${sampleId}`, { method: "DELETE" });
    showToast("训练样本已删除");
    await renderPage();
  } catch (err) { showToast(`删除失败：${err.message}`); }
}

async function deleteSelectedModelSamples(modelId) {
  const sampleIds = [...state.modelSelectedSampleIds];
  if (!sampleIds.length || !window.confirm(`确认删除选中的 ${sampleIds.length} 条训练样本？`)) return;
  try {
    const res = await api(`/api/models/${modelId}/samples/bulk-delete`, { method: "POST", body: JSON.stringify({ sample_ids: sampleIds }) });
    state.modelSelectedSampleIds = [];
    showToast(`已删除 ${res.deleted} 条训练样本`);
    await renderPage();
  } catch (err) { showToast(`删除失败：${err.message}`); }
}

async function clearAllModelSamples(modelId, count) {
  if (!window.confirm(`确认清空该模型全部 ${count} 条训练样本？此操作不可恢复。`)) return;
  try {
    const res = await api(`/api/models/${modelId}/samples`, { method: "DELETE" });
    state.modelSelectedSampleIds = [];
    showToast(`已清空 ${res.deleted} 条训练样本`);
    await renderPage();
  } catch (err) { showToast(`清空失败：${err.message}`); }
}

async function trainModelProject(modelId) {
  try {
    await api(`/api/models/${modelId}/train`, { method: "POST" });
    showToast("LightGBM 训练完成，已生成模型文件");
    await renderPage();
  } catch (err) { showToast(`训练失败：${err.message}`); }
}

async function deployModelProject(model) {
  try {
    await api(`/api/models/${model.id}/deploy`, { method: "POST", body: JSON.stringify({ enabled: model.status !== "published", actor: "local" }) });
    showToast(model.status === "published" ? "模型已停止投用" : `模型已投用：${modelKindLabel(model)}`);
    await refreshAll();
  } catch (err) { showToast(`投用失败：${err.message}`); }
}
