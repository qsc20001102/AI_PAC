async function renderModels(main) {
  const data = await api("/api/models");
  state.models = data.models || [];
  if (!state.editingNewModel && (!state.selectedModelId || !state.models.some((model) => model.id === state.selectedModelId))) {
    state.selectedModelId = state.models[0]?.id || null;
  }
  const selected = state.models.find((model) => model.id === state.selectedModelId);
  const rows = state.models.length ? state.models.map((model) => `
    <button class="list-card model-list-card ${!state.editingNewModel && model.id === state.selectedModelId ? "active" : ""}" data-model-select="${model.id}" type="button">
      <span class="model-list-name">${htmlEscape(model.name)}</span>
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
        ${state.editingNewModel || !selected ? renderNewModelWorkspace() : '<div class="panel-body" id="modelWorkspaceLoading">正在加载模型数据</div>'}
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
  return { draft: "待导入", recording: "待导入", ready: "已训练", published: "已训练" }[status] || localizedStatus(status);
}

function modelStatusClass(status) {
  if (status === "published") return "fresh";
  if (status === "recording") return "delayed";
  return "manual";
}

function modelDisplayStatusLabel(model) {
  if (model?.recording_enabled) return "记录中";
  return modelStatusLabel(model.status);
}

function modelDisplayStatusClass(model) {
  if (model?.recording_enabled) return "delayed";
  return modelStatusClass(model.status);
}

function modelKindLabel(model) {
  return model?.model_kind === "pac_flow_predict" ? "加药流量预测" : "下次出水TP预测";
}

function renderNewModelWorkspace() {
  const defaultName = "训练模型";
  return `
    <div class="panel-header"><div class="panel-title">新建训练模型</div></div>
    <div class="panel-body model-empty-workspace">
      <form id="newModelForm" class="model-create-form">
        <div class="form-grid">
          ${field("name", "模型名称", defaultName, "text")}
          ${selectField("model_kind", "模型类型", [
            { value: "tp_out_response", label: "下次出水TP预测" },
            { value: "pac_flow_predict", label: "加药流量预测" },
          ], "tp_out_response")}
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
  const sampleTargetLabel = modelTargetLabel(model);
  const canRecordRealtime = model.dosing_point_id != null;
  const deployHintText = model.model_kind === "pac_flow_predict"
    ? "选择后进入正常模式：模型直接预测实际加药流量，并按工艺参数上下限限幅。"
    : "选择后仅显示预测TP值：用于查看下一次出水TP检测数据，不直接替代加药流量推荐。";
  return `
    <div class="panel-header">
      <div><div class="panel-title">${htmlEscape(model.name)}</div><div class="muted">类型：${modelKindLabel(model)}　状态：<span class="status-tag status-${modelDisplayStatusClass(model)}">${modelDisplayStatusLabel(model)}</span></div></div>
      <button class="btn" id="deleteModelBtn" type="button">删除模型</button>
    </div>
    <div class="panel-body model-workspace-body">
      ${renderModelTrainingConfig(model, columns)}

      <section class="model-step model-sample-step">
        <div class="model-step-title"><span>2</span><div>导入训练样本</div><small>展示 ${samples.length} / ${model.sample_count || 0} 条</small></div>
        <div class="model-step-actions">
          <button class="btn ghost" id="refreshModelSamplesBtn" type="button">刷新样本</button>
          <button class="btn ghost" id="exportModelSamplesBtn" type="button">导出 CSV</button>
          <label class="btn primary file-button" for="modelCsvInput">导入 CSV</label><input id="modelCsvInput" type="file" accept=".csv,text/csv" hidden>
        </div>
        <div class="model-recording-row">
          <label>记录周期(min)<input id="modelRecordInterval" type="number" min="1" max="1440" step="1" value="${htmlEscape(model.sample_interval_minutes || 5)}"></label>
          <button class="btn ghost" id="recordModelSampleBtn" type="button" ${canRecordRealtime ? "" : "disabled"}>记录当前样本</button>
          <button class="btn ${model.recording_enabled ? "" : "primary"}" id="toggleModelRecordingBtn" type="button" ${canRecordRealtime ? "" : "disabled"}>${model.recording_enabled ? "关闭实时记录" : "开启实时记录"}</button>
          <span class="muted">${canRecordRealtime ? (model.recording_enabled ? `实时记录中，上次记录：${dateMinute(model.last_record_at)}` : "实时记录未开启") : "未绑定投加点，请导入 CSV 样本"}</span>
        </div>
        <div class="muted model-sampling-note">${htmlEscape(modelKindLabel(model))}使用${htmlEscape(sampleTargetLabel)}作为标签，标签不会进入输入特征。</div>
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
        <div class="model-step-title"><span>3</span><div>训练模型</div><small>${model.trained_at ? `最近训练：${dateMinute(model.trained_at)}` : "尚未训练"}</small></div>
        <div class="model-step-actions"><button class="btn primary" id="trainModelBtn" type="button" ${samples.length < 2 ? "disabled" : ""}>开始训练</button>${model.trained_at ? '<button class="btn ghost" id="downloadModelArtifactBtn" type="button">下载模型文件</button>' : ""}</div>
        ${model.trained_at ? `<div class="model-metrics"><span>LightGBM</span><span>训练样本 ${metrics.samples ?? 0}</span><span>R² ${fmtCompact(metrics.R2, 4)}</span><span>MAE ${fmtCompact(metrics.MAE, 4)}</span><span>有效特征 ${metrics.feature_count ?? 0}</span><span>${htmlEscape(artifact.file_name || "模型文件已生成")}</span></div>` : '<div class="muted">样本数达到 2 条且覆盖变化工况后可开始 LightGBM 训练。</div>'}
      </section>

      <section class="model-step">
        <div class="model-step-title"><span>4</span><div>使用配置</div><small>在工艺配置中选择</small></div>
        <div class="muted">${deployHintText} 已训练模型可在工艺配置的投加点配置中选择；也可以选择“无”表示不投用模型。</div>
      </section>
    </div>
  `;
}

function renderModelTrainingConfig(model, columns) {
  const config = modelTrainingConfig(model, columns);
  return `
    <section class="model-step model-config-step">
      <form id="modelConfigForm">
        <div class="model-step-title"><span>1</span><div>模型参数配置</div><small>${htmlEscape(modelTargetLabel(model))}</small></div>
        <div class="model-config-name-row">
          ${field("name", "模型名称", model.name, "text")}
          <input name="sample_interval_minutes" type="hidden" value="${htmlEscape(model.sample_interval_minutes || 5)}">
          <input name="target_column" type="hidden" value="${htmlEscape(modelTrainingTargetKey(model))}">
          <div class="field model-help" data-help="${modelHelpAttr("target_column", model)}"><label>target_column</label><input type="text" value="${htmlEscape(modelTargetLabel(model))}" disabled></div>
        </div>
        <div class="model-feature-config">
          <div class="model-config-subtitle model-help" data-help="${modelHelpAttr("feature_columns", model)}">feature_columns</div>
          <div class="model-feature-grid">
            ${columns.map((column) => `
              <label class="model-feature-option model-help" data-help="${modelHelpAttr("feature_columns", model)}">
                <input data-model-feature-column="${htmlEscape(column.key)}" type="checkbox" ${config.feature_columns.includes(column.key) ? "checked" : ""}>
                <span>${htmlEscape(column.label)}</span>
              </label>
            `).join("")}
          </div>
        </div>
        <div class="model-param-grid">
          ${modelNumberField("prediction_step", config.prediction_step, 0, 24, "1", model)}
          ${modelNumberField("valid_ratio", config.valid_ratio, 0.05, 0.5, "0.01", model)}
          ${modelSelectField("split_method", [
            { value: "time", label: "time" },
            { value: "random", label: "random" },
          ], config.split_method, model)}
          ${modelSelectField("objective", [
            { value: "huber", label: "huber" },
            { value: "regression_l2", label: "regression_l2" },
            { value: "regression_l1", label: "regression_l1" },
          ], config.objective, model)}
          ${modelNumberField("learning_rate", config.learning_rate, 0.001, 1, "0.001", model)}
          ${modelNumberField("num_boost_round", config.num_boost_round, 10, 2000, "1", model)}
          ${modelNumberField("early_stopping_rounds", config.early_stopping_rounds, 0, 300, "1", model)}
          ${modelNumberField("num_leaves", config.num_leaves, 2, 255, "1", model)}
          ${modelNumberField("max_depth", config.max_depth, -1, 32, "1", model)}
          ${modelNumberField("min_data_in_leaf", config.min_data_in_leaf, 1, 10000, "1", model)}
          ${modelNumberField("lambda_l2", config.lambda_l2, 0, 1000, "0.01", model)}
          ${modelNumberField("feature_fraction", config.feature_fraction, 0.1, 1, "0.01", model)}
          ${modelNumberField("bagging_fraction", config.bagging_fraction, 0.1, 1, "0.01", model)}
          ${modelNumberField("bagging_freq", config.bagging_freq, 0, 100, "1", model)}
          ${modelSelectField("sample_weight_rule", [
            { value: "none", label: "none" },
            { value: "high_target", label: "high_target" },
          ], config.sample_weight_rule, model)}
        </div>
        <div class="model-feature-config">
          <div class="model-config-subtitle model-help" data-help="${modelHelpAttr("monotone_constraints", model)}">monotone_constraints</div>
          <div class="model-constraint-grid">
            ${columns.map((column) => `
              <label class="model-constraint-row model-help" data-help="${modelHelpAttr("monotone_constraints", model)}">
                <span>${htmlEscape(column.label)}</span>
                <select data-model-monotone="${htmlEscape(column.key)}">
                  ${[-1, 0, 1].map((value) => `<option value="${value}" ${Number(config.monotone_constraints[column.key] || 0) === value ? "selected" : ""}>${value}</option>`).join("")}
                </select>
              </label>
            `).join("")}
          </div>
        </div>
        <div class="btn-row"><button class="btn ghost" type="submit">保存模型参数</button><span class="muted">模型不绑定投加点；训练完成后到工艺配置中按投加点选择使用。</span></div>
      </form>
    </section>
  `;
}

function modelNumberField(name, value, min, max, step, model) {
  const minAttr = min == null ? "" : ` min="${htmlEscape(min)}"`;
  const maxAttr = max == null ? "" : ` max="${htmlEscape(max)}"`;
  return `
    <div class="field model-help" data-help="${modelHelpAttr(name, model)}">
      <label for="${name}">${name}</label>
      <input id="${name}" name="${name}" type="number"${minAttr}${maxAttr} step="${htmlEscape(step)}" value="${htmlEscape(value)}">
    </div>
  `;
}

function modelSelectField(name, options, value, model) {
  return `
    <div class="field model-help" data-help="${modelHelpAttr(name, model)}">
      <label for="${name}">${name}</label>
      <select id="${name}" name="${name}">
        ${options.map((opt) => `<option value="${htmlEscape(opt.value)}" ${String(opt.value) === String(value) ? "selected" : ""}>${htmlEscape(opt.label)}</option>`).join("")}
      </select>
    </div>
  `;
}

function modelHelpAttr(name, model) {
  return htmlEscape(modelParamHelp(name, model)).replaceAll("\n", "&#10;");
}

function modelParamHelp(name, model) {
  const targetDefault = modelTargetLabel(model);
  const featureDefault = "默认勾选当前模型全部输入字段";
  const helps = {
    target_column: `作用：预测目标列\\A建议默认值：${targetDefault}\\A调整建议：不同模型类型必须对应不同目标列，页面会按模型类型自动固定。`,
    feature_columns: `作用：输入字段\\A建议默认值：${featureDefault}\\A调整建议：不同数据表字段变化时调整；至少保留 1 个有变化的数值字段。`,
    prediction_step: "作用：预测步长\\A建议默认值：1\\A调整建议：填 0 表示直接预测当前条数据；2小时数据预测下一次检测就填 1。",
    valid_ratio: "作用：验证集比例\\A建议默认值：0.2\\A调整建议：数据少用 0.2，数据多可调到 0.15。",
    split_method: "作用：划分方式\\A建议默认值：time\\A调整建议：工业时序数据必须按时间切分；只在明确要随机抽样验证时用 random。",
    objective: "作用：损失函数\\A建议默认值：huber\\A调整建议：异常点多用 huber，数据平稳可用 regression_l2。",
    learning_rate: "作用：学习率\\A建议默认值：0.03\\A调整建议：数据少不要太大；训练波动大时降低。",
    num_boost_round: "作用：最大树数量\\A建议默认值：300~500，当前默认 500\\A调整建议：配合 early_stopping 使用，数据多可适当增加。",
    early_stopping_rounds: "作用：早停轮数\\A建议默认值：30~50，当前默认 50\\A调整建议：数据少用 30，数据多用 50。",
    num_leaves: "作用：树复杂度\\A建议默认值：7 或 15，当前默认 7\\A调整建议：数据少用 7，数据多且欠拟合时可调到 15。",
    max_depth: "作用：树最大深度\\A建议默认值：3 或 4，当前默认 3\\A调整建议：数据少用 3，欠拟合时再尝试 4。",
    min_data_in_leaf: "作用：每个叶子最少样本\\A建议默认值：20\\A调整建议：数据越少越要大；过拟合时调大。",
    lambda_l2: "作用：L2正则\\A建议默认值：1~5，当前默认 3\\A调整建议：过拟合时调大，欠拟合明显时调小。",
    feature_fraction: "作用：每棵树使用多少特征\\A建议默认值：1.0\\A调整建议：特征很多时可用 0.8~0.9；当前特征不多建议 1.0。",
    bagging_fraction: "作用：每轮使用多少样本\\A建议默认值：0.85~0.9，当前默认 0.85\\A调整建议：数据多时可用，数据少不要太低。",
    bagging_freq: "作用：bagging 频率\\A建议默认值：1\\A调整建议：一般固定 1；设为 0 表示关闭 bagging。",
    monotone_constraints: "作用：单调约束\\A建议默认值：按字段配置，普通字段为 0\\A调整建议：PAC、加药单耗等字段可设 -1，表示该字段越大预测TP只能下降或不变。",
    sample_weight_rule: "作用：样本权重规则\\A建议默认值：none\\A调整建议：高TP样本少时可选 high_target，提高高目标值样本权重。",
  };
  return (helps[name] || "").replaceAll("\\A", "\n");
}

function modelTrainingTargetKey(model) {
  return model?.model_kind === "pac_flow_predict" ? "_training_target_pac_actual" : "_training_target_tp_out_next";
}

function modelTrainingConfig(model, columns) {
  const keys = columns.map((column) => column.key);
  const raw = model.training_config || {};
  const featureColumns = Array.isArray(raw.feature_columns) ? raw.feature_columns.filter((key) => keys.includes(key)) : keys;
  const rawConstraints = raw.monotone_constraints && typeof raw.monotone_constraints === "object" ? raw.monotone_constraints : {};
  const constraints = Object.fromEntries(keys.map((key) => [key, [-1, 0, 1].includes(Number(rawConstraints[key])) ? Number(rawConstraints[key]) : 0]));
  return {
    target_column: modelTrainingTargetKey(model),
    feature_columns: featureColumns.length ? featureColumns : keys,
    prediction_step: raw.prediction_step ?? 1,
    valid_ratio: raw.valid_ratio ?? 0.2,
    split_method: raw.split_method || "time",
    objective: raw.objective || "huber",
    learning_rate: raw.learning_rate ?? 0.03,
    num_boost_round: raw.num_boost_round ?? 500,
    early_stopping_rounds: raw.early_stopping_rounds ?? 50,
    num_leaves: raw.num_leaves ?? 7,
    max_depth: raw.max_depth ?? 3,
    min_data_in_leaf: raw.min_data_in_leaf ?? 20,
    lambda_l2: raw.lambda_l2 ?? 3,
    feature_fraction: raw.feature_fraction ?? 1,
    bagging_fraction: raw.bagging_fraction ?? 0.85,
    bagging_freq: raw.bagging_freq ?? 1,
    monotone_constraints: constraints,
    sample_weight_rule: raw.sample_weight_rule || "none",
  };
}

function modelProjectPayload(form, model, columns) {
  const payload = formObject(form);
  payload.name = String(payload.name || "").trim();
  payload.sample_interval_minutes = Number(payload.sample_interval_minutes || 5);
  const featureColumns = [...form.querySelectorAll("[data-model-feature-column]:checked")].map((node) => node.dataset.modelFeatureColumn);
  if (!featureColumns.length) return null;
  const monotoneConstraints = {};
  form.querySelectorAll("[data-model-monotone]").forEach((node) => {
    monotoneConstraints[node.dataset.modelMonotone] = Number(node.value);
  });
  payload.training_config = {
    target_column: modelTrainingTargetKey(model),
    feature_columns: featureColumns,
    prediction_step: Number(payload.prediction_step),
    valid_ratio: Number(payload.valid_ratio),
    split_method: payload.split_method,
    objective: payload.objective,
    learning_rate: Number(payload.learning_rate),
    num_boost_round: Number(payload.num_boost_round),
    early_stopping_rounds: Number(payload.early_stopping_rounds),
    num_leaves: Number(payload.num_leaves),
    max_depth: Number(payload.max_depth),
    min_data_in_leaf: Number(payload.min_data_in_leaf),
    lambda_l2: Number(payload.lambda_l2),
    feature_fraction: Number(payload.feature_fraction),
    bagging_fraction: Number(payload.bagging_fraction),
    bagging_freq: Number(payload.bagging_freq),
    monotone_constraints: monotoneConstraints,
    sample_weight_rule: payload.sample_weight_rule,
  };
  [
    "target_column",
    "feature_columns",
    "prediction_step",
    "valid_ratio",
    "split_method",
    "objective",
    "learning_rate",
    "num_boost_round",
    "early_stopping_rounds",
    "num_leaves",
    "max_depth",
    "min_data_in_leaf",
    "lambda_l2",
    "feature_fraction",
    "bagging_fraction",
    "bagging_freq",
    "monotone_constraints",
    "sample_weight_rule",
  ].forEach((key) => { delete payload[key]; });
  return payload;
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
  const targetHeaders = [sampleTargetLabel];
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
  const key = state.models.find((model) => model.id === state.selectedModelId)?.model_kind === "pac_flow_predict"
    ? "_training_target_pac_actual"
    : "_training_target_tp_out_next";
  return [key]
    .map((key) => `<td>${modelSampleValue(sample.values?.[key], 4)}</td>`)
    .join("");
}

function modelTargetLabel(model) {
  return model?.model_kind === "pac_flow_predict" ? "实际加药流量" : "下一次出水TP检测数据";
}

function wireModelWorkspace(detail) {
  const model = detail.model;
  document.getElementById("modelConfigForm")?.addEventListener("submit", (event) => saveModelProject(event, model, detail.columns));
  document.getElementById("deleteModelBtn")?.addEventListener("click", () => deleteModelProject(model));
  document.getElementById("refreshModelSamplesBtn")?.addEventListener("click", async () => { await renderPage(); });
  document.getElementById("exportModelSamplesBtn")?.addEventListener("click", () => { window.location.href = `/api/models/${model.id}/samples.csv`; });
  document.getElementById("modelCsvInput")?.addEventListener("change", (event) => importModelSamples(model.id, event));
  document.getElementById("recordModelSampleBtn")?.addEventListener("click", () => recordModelSample(model.id));
  document.getElementById("toggleModelRecordingBtn")?.addEventListener("click", () => toggleModelRecording(model));
  document.getElementById("trainModelBtn")?.addEventListener("click", () => trainModelProject(model.id));
  document.getElementById("downloadModelArtifactBtn")?.addEventListener("click", () => { window.location.href = `/api/models/${model.id}/artifact`; });
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
  payload.sample_interval_minutes = Number(payload.sample_interval_minutes || 5);
  payload.model_kind = payload.model_kind === "pac_flow_predict" ? "pac_flow_predict" : "tp_out_response";
  try {
    const res = await api("/api/models", { method: "POST", body: JSON.stringify(payload) });
    state.selectedModelId = res.model.id;
    state.editingNewModel = false;
    showToast("训练模型已创建，可开始导入样本");
    await renderPage();
  } catch (err) { showToast(`创建失败：${err.message}`); }
}

async function saveModelProject(event, model, columns) {
  event.preventDefault();
  const payload = modelProjectPayload(event.currentTarget, model, columns);
  if (!payload) {
    showToast("至少需要选择 1 个输入字段");
    return;
  }
  try {
    await api(`/api/models/${model.id}`, { method: "PUT", body: JSON.stringify(payload) });
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

function modelRecordInterval() {
  return Math.min(1440, Math.max(1, Number(document.getElementById("modelRecordInterval")?.value || 5)));
}

async function recordModelSample(modelId) {
  try {
    const res = await api(`/api/models/${modelId}/samples/record`, { method: "POST" });
    showToast(`已记录 1 条训练样本${res.backfilled ? `，回填 ${res.backfilled} 条标签` : ""}`);
    await renderPage();
  } catch (err) { showToast(`记录失败：${err.message}`); }
}

async function toggleModelRecording(model) {
  const enabled = Boolean(model.recording_enabled);
  try {
    const url = `/api/models/${model.id}/recording/${enabled ? "stop" : "start"}`;
    const options = enabled
      ? { method: "POST" }
      : { method: "POST", body: JSON.stringify({ sample_interval_minutes: modelRecordInterval() }) };
    await api(url, options);
    showToast(enabled ? "实时记录已关闭" : "实时记录已开启");
    await renderPage();
  } catch (err) { showToast(`${enabled ? "关闭" : "开启"}失败：${err.message}`); }
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
