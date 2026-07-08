function initModelHelpTooltips(container) {
  let tooltip = document.getElementById("modelGlobalTooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.id = "modelGlobalTooltip";
    document.body.appendChild(tooltip);
  }
  container.querySelectorAll(".model-help").forEach((el) => {
    el.addEventListener("mouseenter", () => {
      const text = el.getAttribute("data-help");
      if (!text) return;
      tooltip.textContent = text;
      tooltip.style.opacity = "0";
      tooltip.style.left = "-9999px";
      tooltip.style.top = "-9999px";
      const rect = el.getBoundingClientRect();
      const th = tooltip.offsetHeight || 60;
      const spaceAbove = rect.top;
      const spaceBelow = window.innerHeight - rect.bottom;
      let top;
      if (spaceAbove >= th + 12 || spaceAbove > spaceBelow) {
        top = rect.top - th - 8;
      } else {
        top = rect.bottom + 8;
      }
      tooltip.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - 340 - 8)) + "px";
      tooltip.style.top = top + "px";
      tooltip.style.opacity = "1";
    });
    el.addEventListener("mouseleave", () => { tooltip.style.opacity = "0"; });
  });
}

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
    const detail = await api(`/api/models/${selected.id}?compact=1`);
    state.modelSelectedSampleIds = [];
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
  return modelStatusLabel(model.status);
}

function modelDisplayStatusClass(model) {
  return modelStatusClass(model.status);
}

function modelKindLabel(model) {
  return "智能PAC双任务预测";
}

function renderNewModelWorkspace() {
  const defaultName = "训练模型";
  return `
    <div class="panel-header"><div class="panel-title">新建训练模型</div></div>
    <div class="panel-body model-empty-workspace">
      <form id="newModelForm" class="model-create-form">
        <div class="form-grid">
          ${field("name", "模型名称", defaultName, "text")}
          ${hiddenField("model_kind", "ai_pac_dual_task")}
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
  const deployHintText = "选择后进入双任务AI模式：模型同时预测PAC加药流量和下次出水TP变化量，并自动计算推荐加药流量。";
  const trainMetricsHtml = model.trained_at
    ? `<div class="model-metrics">
        <span>LightGBM 双任务</span>
        <span>任务1样本 ${metrics.task1?.samples ?? 0}</span>
        <span>任务1特征 ${metrics.task1?.feature_count ?? 0}</span>
        <span>任务2样本 ${metrics.task2?.samples ?? 0}</span>
        <span>任务2特征 ${metrics.task2?.feature_count ?? 0}</span>
      </div>
      <div class="model-metrics">
        <span>标签模式：${artifact.label_mode === "fixed_hrt" ? "固定HRT" : artifact.label_mode === "auto_detected" ? "自动推断" : "未知"}</span>
        <span>使用延迟行数：${artifact.used_lag_rows ?? "-"}</span>
        <span>HRT(分钟)：${artifact.hrt_minutes ?? "自动"}</span>
        <span>采样间隔(分钟)：${artifact.sample_interval_minutes ?? 5}</span>
      </div>
      ${renderDualTaskEvalMetrics(metrics)}`
    : '<div class="muted">样本数达到 40 条后可开始双任务 LightGBM 训练。</div>';
  return `
    <div class="panel-header">
      <div><div class="panel-title">${htmlEscape(model.name)}</div><div class="muted">类型：${modelKindLabel(model)}　状态：<span class="status-tag status-${modelDisplayStatusClass(model)}">${modelDisplayStatusLabel(model)}</span></div></div>
      <button class="btn" id="deleteModelBtn" type="button">删除模型</button>
    </div>
    <div class="panel-body model-workspace-body" style="align-content:start;">
      ${renderModelTrainingConfig(model, columns)}

      <section class="model-step model-sample-step" style="align-self:start;">
        <div class="model-step-title"><span>2</span><div>导入训练样本</div></div>
        <div class="model-step-actions">
          <button class="btn ghost" id="refreshModelSamplesBtn" type="button">刷新样本</button>
          <button class="btn ghost" id="exportModelSamplesBtn" type="button">导出 CSV</button>
          ${model.sample_count ? '<button class="btn ghost" id="exportModelFeaturesBtn" type="button">导出处理后特征</button>' : ""}
          <label class="btn primary file-button" for="modelCsvInput">导入 CSV</label><input id="modelCsvInput" type="file" accept=".csv,text/csv" hidden>
          <button class="btn danger" id="clearAllModelSamplesBtn" type="button" ${model.sample_count ? "" : "disabled"}>清空全部样本</button>
        </div>
        <div class="muted model-sampling-note">已导入 <strong>${model.sample_count || 0}</strong> 条训练样本。使用13个原始传感器字段，系统自动完成特征工程（滞后、滚动窗口、差分等）。</div>
      </section>

      <section class="model-step" style="align-self:start;">
        <div class="model-step-title"><span>3</span><div>训练模型</div><small>${model.trained_at ? `最近训练：${dateMinute(model.trained_at)}` : "尚未训练"}</small></div>
        <div class="model-step-actions"><button class="btn primary" id="trainModelBtn" type="button" ${(model.sample_count || 0) < (model.model_kind === "ai_pac_dual_task" ? 40 : 2) ? "disabled" : ""}>开始训练</button>${model.trained_at ? '<button class="btn ghost" id="downloadModelArtifactBtn" type="button">下载模型文件</button>' : ""}</div>
        ${trainMetricsHtml}
      </section>

      <section class="model-step" style="align-self:start;">
        <div class="model-step-title"><span>4</span><div>使用配置</div><small>在工艺配置中选择</small></div>
        <div class="muted">${deployHintText} 已训练模型可在工艺配置的投加点配置中选择；也可以选择“无”表示不投用模型。</div>
      </section>
    </div>
  `;
}

function renderModelTrainingConfig(model, columns) {
  const config = modelTrainingConfig(model, columns);
  if (config.is_dual_task) {
    return renderDualTaskTrainingConfig(model, config);
  }
  return `
    <section class="model-step model-config-step" style="align-self:start;">
      <form id="modelConfigForm">
        <div class="model-step-title"><span>1</span><div>模型参数配置</div><small>${htmlEscape(modelTargetLabel(model))}</small></div>
        <div class="model-config-name-row">
          ${field("name", "模型名称", model.name, "text")}
          <input name="target_column" type="hidden" value="${htmlEscape(modelTrainingTargetKey(model))}">
          <div class="field model-help" data-help="${modelHelpAttr("target_column", model)}"><label>目标列</label><input type="text" value="${htmlEscape(modelTargetLabel(model))}" disabled></div>
        </div>

        <div class="model-param-group expanded" data-model-group>
          <div class="model-param-group-header">数据选择</div>
          <div class="model-param-group-body"><div class="model-param-group-body-inner">
            <div class="model-feature-config">
              <div class="model-config-subtitle model-help" data-help="${modelHelpAttr("feature_columns", model)}">输入特征列</div>
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
              ${modelNumberField("valid_ratio", config.valid_ratio, 0.05, 0.5, "0.01", model)}
              ${modelSelectField("split_method", [
                { value: "time", label: "time（按时间切分）" },
                { value: "random", label: "random（随机切分）" },
              ], config.split_method, model)}
            </div>
          </div></div>
        </div>

        <div class="model-param-group expanded" data-model-group>
          <div class="model-param-group-header">任务与评价参数</div>
          <div class="model-param-group-body"><div class="model-param-group-body-inner">
            <div class="model-param-grid">
              ${modelSelectField("objective", [
                { value: "regression_l2", label: "regression_l2（均方误差，数据平稳）" },
                { value: "regression_l1", label: "regression_l1（绝对误差，异常点多）" },
                { value: "huber", label: "huber（混合损失，推荐）" },
              ], config.objective, model)}
              ${modelCheckboxGroup("metric", [
                { value: "rmse", label: "rmse（对大误差敏感）" },
                { value: "mae", label: "mae（看平均误差）" },
                { value: "mse", label: "mse（均方误差）" },
              ], config.metric, model)}
              ${modelSelectField("boosting_type", [
                { value: "gbdt", label: "gbdt（最稳定，推荐）" },
                { value: "dart", label: "dart（泛化可能更好）" },
                { value: "rf", label: "rf（随机森林）" },
              ], config.boosting_type, model)}
              ${modelNumberField("learning_rate", config.learning_rate, 0.001, 1, "0.001", model)}
              ${modelNumberField("num_boost_round", config.num_boost_round, 10, 2000, "1", model)}
              ${modelNumberField("early_stopping_rounds", config.early_stopping_rounds, 0, 300, "1", model)}
            </div>
          </div></div>
        </div>

        <div class="model-param-group" data-model-group>
          <div class="model-param-group-header">树结构复杂度参数</div>
          <div class="model-param-group-body"><div class="model-param-group-body-inner">
            <div class="model-param-grid">
              ${modelNumberField("num_leaves", config.num_leaves, 2, 255, "1", model)}
              ${modelNumberField("max_depth", config.max_depth, -1, 32, "1", model)}
              ${modelNumberField("min_data_in_leaf", config.min_data_in_leaf, 1, 10000, "1", model)}
              ${modelNumberField("min_sum_hessian_in_leaf", config.min_sum_hessian_in_leaf, 0, 10, "0.001", model)}
              ${modelNumberField("max_delta_step", config.max_delta_step, 0, 100, "0.1", model)}
            </div>
          </div></div>
        </div>

        <div class="model-param-group" data-model-group>
          <div class="model-param-group-header">分箱参数</div>
          <div class="model-param-group-body"><div class="model-param-group-body-inner">
            <div class="model-param-grid">
              ${modelNumberField("max_bin", config.max_bin, 2, 255, "1", model)}
              ${modelNumberField("min_data_in_bin", config.min_data_in_bin, 1, 100, "1", model)}
              ${modelNumberField("bin_construct_sample_cnt", config.bin_construct_sample_cnt, 100, 1000000, "1", model)}
            </div>
          </div></div>
        </div>

        <div class="model-param-group" data-model-group>
          <div class="model-param-group-header">正则化参数</div>
          <div class="model-param-group-body"><div class="model-param-group-body-inner">
            <div class="model-param-grid">
              ${modelNumberField("lambda_l1", config.lambda_l1, 0, 1000, "0.1", model)}
              ${modelNumberField("lambda_l2", config.lambda_l2, 0, 1000, "0.1", model)}
              ${modelNumberField("min_gain_to_split", config.min_gain_to_split, 0, 10, "0.001", model)}
              ${modelNumberField("path_smooth", config.path_smooth, 0, 100, "0.1", model)}
              ${modelNumberField("linear_lambda", config.linear_lambda, 0, 1000, "0.1", model)}
            </div>
          </div></div>
        </div>

        <div class="model-param-group" data-model-group>
          <div class="model-param-group-header">采样参数</div>
          <div class="model-param-group-body"><div class="model-param-group-body-inner">
            <div class="model-param-grid">
              ${modelNumberField("feature_fraction", config.feature_fraction, 0.1, 1, "0.01", model)}
              ${modelNumberField("feature_fraction_bynode", config.feature_fraction_bynode, 0.1, 1, "0.01", model)}
              ${modelNumberField("bagging_fraction", config.bagging_fraction, 0.1, 1, "0.01", model)}
              ${modelNumberField("bagging_freq", config.bagging_freq, 0, 100, "1", model)}
              ${modelSelectField("extra_trees", [
                { value: "false", label: "关闭" },
                { value: "true", label: "开启" },
              ], String(Boolean(config.extra_trees)), model)}
            </div>
          </div></div>
        </div>

        <div class="model-param-group" data-model-group>
          <div class="model-param-group-header">单调约束参数</div>
          <div class="model-param-group-body"><div class="model-param-group-body-inner">
            <div class="model-feature-config">
              <div class="model-config-subtitle model-help" data-help="${modelHelpAttr("monotone_constraints", model)}">单调约束</div>
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
          </div></div>
        </div>

        <div class="model-param-group" data-model-group>
          <div class="model-param-group-header">随机性与复现参数</div>
          <div class="model-param-group-body"><div class="model-param-group-body-inner">
            <div class="model-param-grid">
              ${modelNumberField("seed", config.seed, 0, 999999, "1", model)}
              ${modelNumberField("feature_fraction_seed", config.feature_fraction_seed, 0, 999999, "1", model)}
              ${modelNumberField("bagging_seed", config.bagging_seed, 0, 999999, "1", model)}
              ${modelNumberField("data_random_seed", config.data_random_seed, 0, 999999, "1", model)}
              ${modelNumberField("extra_seed", config.extra_seed, 0, 999999, "1", model)}
              ${modelSelectField("deterministic", [
                { value: "true", label: "开启" },
                { value: "false", label: "关闭" },
              ], String(Boolean(config.deterministic)), model)}
            </div>
          </div></div>
        </div>

        <div class="btn-row"><button class="btn ghost" type="submit">保存模型参数</button><span class="muted">模型不绑定投加点；训练完成后到工艺配置中按投加点选择使用。</span></div>
      </form>
    </section>
  `;
}

function renderDualTaskTrainingConfig(model, config) {
  const taskFields = (prefix, task) => `
    <div class="model-param-grid">
      ${modelNumberField(`${prefix}_num_leaves`, task.num_leaves, 2, 255, "1", model)}
      ${modelNumberField(`${prefix}_max_depth`, task.max_depth, -1, 32, "1", model)}
      ${modelNumberField(`${prefix}_min_data_in_leaf`, task.min_data_in_leaf, 1, 10000, "1", model)}
      ${modelNumberField(`${prefix}_min_sum_hessian_in_leaf`, task.min_sum_hessian_in_leaf, 0, 10, "0.001", model)}
      ${modelNumberField(`${prefix}_learning_rate`, task.learning_rate, 0.001, 1, "0.001", model)}
      ${modelNumberField(`${prefix}_feature_fraction`, task.feature_fraction, 0.1, 1, "0.01", model)}
      ${modelNumberField(`${prefix}_bagging_fraction`, task.bagging_fraction, 0.1, 1, "0.01", model)}
      ${modelNumberField(`${prefix}_bagging_freq`, task.bagging_freq, 0, 100, "1", model)}
      ${modelNumberField(`${prefix}_lambda_l1`, task.lambda_l1, 0, 1000, "0.1", model)}
      ${modelNumberField(`${prefix}_lambda_l2`, task.lambda_l2, 0, 1000, "0.1", model)}
      ${modelNumberField(`${prefix}_num_boost_round`, task.num_boost_round, 10, 5000, "1", model)}
      ${modelNumberField(`${prefix}_early_stopping_rounds`, task.early_stopping_rounds, 0, 500, "1", model)}
    </div>
  `;
  return `
    <section class="model-step model-config-step" style="align-self:start;">
      <form id="modelConfigForm">
        <div class="model-step-title"><span>1</span><div>模型参数配置</div><small>智能PAC双任务预测（特征工程自动完成）</small></div>
        <div class="model-config-name-row">
          ${field("name", "模型名称", model.name, "text")}
        </div>

        <div class="model-param-group expanded" data-model-group>
          <div class="model-param-group-header">数据切分</div>
          <div class="model-param-group-body"><div class="model-param-group-body-inner">
            <div class="model-param-grid">
              ${modelNumberField("train_ratio", config.train_ratio, 0.1, 0.9, "0.01", model)}
              ${modelNumberField("val_ratio", config.val_ratio, 0.05, 0.5, "0.01", model)}
              ${modelNumberField("tp_hrt_minutes", config.tp_hrt_minutes ?? "", 1, 1440, "1", model)}
              ${modelNumberField("sample_interval_minutes", config.sample_interval_minutes ?? "", 1, 1440, "1", model)}
            </div>
            <div class="muted" style="margin-top:8px;">
              投加点到出水TP检查点时间：设置后用固定延迟构建标签；不填则自动推断最佳延迟。<br>
              采样间隔：设置后使用固定值；不填则从数据中自动推断。
            </div>
          </div></div>
        </div>

        <div class="model-param-group expanded" data-model-group>
          <div class="model-param-group-header">任务1：PAC加药量预测</div>
          <div class="model-param-group-body"><div class="model-param-group-body-inner">
            ${taskFields("task1", config.task1)}
          </div></div>
        </div>

        <div class="model-param-group expanded" data-model-group>
          <div class="model-param-group-header">任务2：出水TP变化量预测</div>
          <div class="model-param-group-body"><div class="model-param-group-body-inner">
            ${taskFields("task2", config.task2)}
          </div></div>
        </div>

        <div class="model-param-group" data-model-group>
          <div class="model-param-group-header">随机种子</div>
          <div class="model-param-group-body"><div class="model-param-group-body-inner">
            <div class="model-param-grid">
              ${modelNumberField("seed", config.seed, 0, 999999, "1", model)}
            </div>
          </div></div>
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

function modelCheckboxGroup(name, options, values, model) {
  const selected = Array.isArray(values) ? values : [String(values)];
  return `
    <div class="field model-help" data-help="${modelHelpAttr(name, model)}">
      <label>${name}</label>
      <div class="model-checkbox-group">
        ${options.map((opt) => `
          <label>
            <input type="checkbox" name="${name}" value="${htmlEscape(opt.value)}" ${selected.includes(opt.value) ? "checked" : ""}>
            <span>${htmlEscape(opt.label)}</span>
          </label>
        `).join("")}
      </div>
    </div>
  `;
}

function modelHelpAttr(name, model) {
  return htmlEscape(modelParamHelp(name, model)).replaceAll("\n", "&#10;");
}

function modelParamHelp(name, model) {
  const helps = {
    target_column: "预测目标列。不同模型类型对应不同目标列，页面会按模型类型自动固定。",
    feature_columns: "输入特征列。选择用于训练模型的输入变量，至少保留1个有变化的数值字段。",
    valid_ratio: "验证集比例（0.05~0.5）。数据少用0.2，数据多可调到0.15。",
    split_method: "划分方式。工业时序数据建议按time时间切分；random用于随机抽样验证。",
    objective: "损失函数。普通连续值预测用regression_l2；异常值多用regression_l1或huber。预测PAC投加量用regression_l2；仪表异常点多用huber。",
    metric: "评价指标。rmse对大误差敏感，适合看TP超标风险；mae看平均误差。",
    boosting_type: "提升方式。gbdt最稳定；dart泛化可能更好但不稳定；rf类似随机森林。小样本水厂数据建议先用gbdt。",
    learning_rate: "学习率（0.001~1.0）。越小越稳但需要更多轮数。默认0.05；模型波动大改0.03；数据多可用0.05~0.08。",
    num_boost_round: "最大训练轮数（10~2000）。learning_rate=0.05时可设300；0.03时可设500。",
    early_stopping_rounds: "早停轮数（0~300）。验证集指标连续N轮不改善则停止。数据少用30，数据多用50。",
    num_leaves: "每棵树最多叶子数（2~255）。直接控制模型复杂度。过拟合调小，欠拟合调大。小样本设5~15；数据多可设31。",
    max_depth: "树最大深度（-1~32）。-1表示无限制。过拟合调小；关系复杂时调大。小样本设2~4；模型太钝可设5。",
    min_data_in_leaf: "叶子最少样本数（1~10000）。过拟合调大，欠拟合调小。几百条数据设6~20；几千条设20~50。",
    min_sum_hessian_in_leaf: "叶子最小权重和（0~10）。更细的复杂度限制。一般不动；过拟合严重可调大。默认0.001。",
    max_delta_step: "叶子输出最大变化限制（0~100）。预测值跳变大时设置。默认0不限制；PAC建议值跳太猛可试1~5。",
    max_bin: "每个特征最多分箱数（2~255）。值大更精细但容易过拟合。小样本建议63或127；数据多可用255。",
    min_data_in_bin: "每个分箱最少样本数（1~100）。过拟合调大；数据少不要太大。默认3；仪表噪声多可设5~10。",
    bin_construct_sample_cnt: "构建分箱用样本数（100~1000000）。数据量不大一般不用改。默认200000。",
    lambda_l1: "L1正则（0~1000）。让模型更稀疏。过拟合调大；欠拟合调小。默认可设0.3；过拟合试1~5。",
    lambda_l2: "L2正则（0~1000）。让模型更平滑。小样本建议偏大；模型太钝则调小。默认可设20；预测不灵敏可降到5~10。",
    min_gain_to_split: "最小分裂收益（0~10）。节点继续分裂所需的最小收益。过拟合调大；欠拟合调小。默认0.02；过拟合试0.05~0.1。",
    path_smooth: "路径平滑（0~100）。让叶子节点输出更平滑。默认0；PAC投加量跳动明显可试1~5。",
    linear_lambda: "线性树正则（0~1000）。普通gbdt基本不用。默认0即可。",
    feature_fraction: "特征采样比例（0.1~1.0）。每轮随机使用一部分特征。特征多、过拟合时调小。默认0.9；过拟合可设0.7~0.8。",
    feature_fraction_bynode: "节点特征采样比例（0.1~1.0）。更细粒度的特征采样，一般不动。默认1.0。",
    bagging_fraction: "样本采样比例（0.1~1.0）。每轮随机使用一部分样本。过拟合时调小。默认0.9；过拟合可设0.7~0.8。",
    bagging_freq: "Bagging频率（0~100）。每隔多少轮执行一次样本采样。0表示关闭；建议1表示每轮都采样。",
    extra_trees: "使用更随机的分裂方式。泛化可能更好，但结果会更随机。默认关闭；过拟合严重可开启。",
    monotone_constraints: "单调约束。每个字段可选-1/0/1。PAC、加药单耗等字段可设-1，表示该字段越大预测值只能下降或不变。",
    seed: "总随机种子（0~999999）。固定值方便复现实验。推荐42。",
    feature_fraction_seed: "特征采样随机种子（0~999999）。一般和seed保持一致。",
    bagging_seed: "样本采样随机种子（0~999999）。一般和seed保持一致。",
    data_random_seed: "数据分箱随机种子（0~999999）。一般不用单独改。",
    extra_seed: "extra_trees使用的随机种子（0~999999）。只有开启extra_trees时明显。",
    deterministic: "尽量保证相同数据训练结果一致。工程系统建议开启。",
  };
  return helps[name] || "";
}

function renderDualTaskEvalMetrics(metrics) {
  const t1 = metrics?.task1?.eval || {};
  const t2 = metrics?.task2?.eval || {};
  if (!Object.keys(t1).length && !Object.keys(t2).length) return "";
  const fmt = (v) => v == null ? "—" : fmtCompact(v, 4);
  const row = (label, data) => {
    const train = data?.train || {};
    const val = data?.val || {};
    const test = data?.test || {};
    if (data?.train?.delta) {
      // task2 有 delta/abs 双层结构
      const dTrain = train.delta || {};
      const dVal = val.delta || {};
      const dTest = test.delta || {};
      const aTrain = train.abs || {};
      const aVal = val.abs || {};
      const aTest = test.abs || {};
      return `<tr><td>${label}(delta)</td><td>${fmt(dTrain.rmse)}</td><td>${fmt(dTrain.mae)}</td><td>${fmt(dTrain.r2)}</td><td>—</td><td>${fmt(dVal.rmse)}</td><td>${fmt(dVal.mae)}</td><td>${fmt(dVal.r2)}</td><td>—</td><td>${fmt(dTest.rmse)}</td><td>${fmt(dTest.mae)}</td><td>${fmt(dTest.r2)}</td><td>—</td></tr>
              <tr><td>${label}(绝对TP)</td><td>${fmt(aTrain.rmse)}</td><td>${fmt(aTrain.mae)}</td><td>—</td><td>${fmt(aTrain.mape)}%</td><td>${fmt(aVal.rmse)}</td><td>${fmt(aVal.mae)}</td><td>—</td><td>${fmt(aVal.mape)}%</td><td>${fmt(aTest.rmse)}</td><td>${fmt(aTest.mae)}</td><td>—</td><td>${fmt(aTest.mape)}%</td></tr>`;
    }
    return `<tr><td>${label}</td><td>${fmt(train.rmse)}</td><td>${fmt(train.mae)}</td><td>${fmt(train.r2)}</td><td>${fmt(train.mape)}%</td><td>${fmt(val.rmse)}</td><td>${fmt(val.mae)}</td><td>${fmt(val.r2)}</td><td>${fmt(val.mape)}%</td><td>${fmt(test.rmse)}</td><td>${fmt(test.mae)}</td><td>${fmt(test.r2)}</td><td>${fmt(test.mape)}%</td></tr>`;
  };
  return `
    <div class="model-eval-table-wrap">
      <table class="table model-eval-table">
        <thead><tr><th>任务</th><th colspan="4">训练集</th><th colspan="4">验证集</th><th colspan="4">测试集</th></tr>
        <tr><th></th><th>RMSE</th><th>MAE</th><th>R²</th><th>MAPE</th><th>RMSE</th><th>MAE</th><th>R²</th><th>MAPE</th><th>RMSE</th><th>MAE</th><th>R²</th><th>MAPE</th></tr></thead>
        <tbody>${row("任务1：PAC加药量", t1)}${row("任务2：出水TP", t2)}</tbody>
      </table>
    </div>
  `;
}

function modelTrainingTargetKey(model) {
  return model?.model_kind === "pac_flow_predict" ? "_training_target_pac_actual" : "_training_target_tp_out_next";
}

function modelTrainingConfig(model, columns) {
  const raw = model.training_config || {};
  if (model?.model_kind === "ai_pac_dual_task") {
    const taskDefaults = {
      num_leaves: 31, max_depth: 6, min_data_in_leaf: 50, min_sum_hessian_in_leaf: 0.001,
      learning_rate: 0.05, feature_fraction: 0.8, bagging_fraction: 0.8, bagging_freq: 5,
      lambda_l1: 0.1, lambda_l2: 1.0, num_boost_round: 2000, early_stopping_rounds: 100,
    };
    const makeTask = (t) => ({
      num_leaves: raw[t]?.num_leaves ?? taskDefaults.num_leaves,
      max_depth: raw[t]?.max_depth ?? taskDefaults.max_depth,
      min_data_in_leaf: raw[t]?.min_data_in_leaf ?? taskDefaults.min_data_in_leaf,
      min_sum_hessian_in_leaf: raw[t]?.min_sum_hessian_in_leaf ?? taskDefaults.min_sum_hessian_in_leaf,
      learning_rate: raw[t]?.learning_rate ?? taskDefaults.learning_rate,
      feature_fraction: raw[t]?.feature_fraction ?? taskDefaults.feature_fraction,
      bagging_fraction: raw[t]?.bagging_fraction ?? taskDefaults.bagging_fraction,
      bagging_freq: raw[t]?.bagging_freq ?? taskDefaults.bagging_freq,
      lambda_l1: raw[t]?.lambda_l1 ?? taskDefaults.lambda_l1,
      lambda_l2: raw[t]?.lambda_l2 ?? taskDefaults.lambda_l2,
      num_boost_round: raw[t]?.num_boost_round ?? taskDefaults.num_boost_round,
      early_stopping_rounds: raw[t]?.early_stopping_rounds ?? taskDefaults.early_stopping_rounds,
    });
    return {
      is_dual_task: true,
      task1: makeTask("task1"),
      task2: makeTask("task2"),
      train_ratio: raw.split?.train_ratio ?? 0.7,
      val_ratio: raw.split?.val_ratio ?? 0.15,
      seed: raw.seed ?? 42,
      tp_hrt_minutes: raw.tp_hrt_minutes ?? null,
      sample_interval_minutes: model.sample_interval_minutes ?? null,
    };
  }
  const keys = columns.map((column) => column.key);
  const featureColumns = Array.isArray(raw.feature_columns) ? raw.feature_columns.filter((key) => keys.includes(key)) : keys;
  const rawConstraints = raw.monotone_constraints && typeof raw.monotone_constraints === "object" ? raw.monotone_constraints : {};
  const constraints = Object.fromEntries(keys.map((key) => [key, [-1, 0, 1].includes(Number(rawConstraints[key])) ? Number(rawConstraints[key]) : 0]));
  return {
    target_column: modelTrainingTargetKey(model),
    feature_columns: featureColumns.length ? featureColumns : keys,
    valid_ratio: raw.valid_ratio ?? 0.2,
    split_method: raw.split_method || "time",
    objective: raw.objective || "huber",
    metric: Array.isArray(raw.metric) && raw.metric.length ? raw.metric : (raw.metric ? [String(raw.metric)] : ["rmse"]),
    boosting_type: raw.boosting_type || "gbdt",
    learning_rate: raw.learning_rate ?? 0.05,
    num_boost_round: raw.num_boost_round ?? 300,
    early_stopping_rounds: raw.early_stopping_rounds ?? 50,
    num_leaves: raw.num_leaves ?? 15,
    max_depth: raw.max_depth ?? 4,
    min_data_in_leaf: raw.min_data_in_leaf ?? 20,
    min_sum_hessian_in_leaf: raw.min_sum_hessian_in_leaf ?? 0.001,
    max_delta_step: raw.max_delta_step ?? 0,
    max_bin: raw.max_bin ?? 255,
    min_data_in_bin: raw.min_data_in_bin ?? 3,
    bin_construct_sample_cnt: raw.bin_construct_sample_cnt ?? 200000,
    lambda_l1: raw.lambda_l1 ?? 0.3,
    lambda_l2: raw.lambda_l2 ?? 20,
    min_gain_to_split: raw.min_gain_to_split ?? 0.02,
    path_smooth: raw.path_smooth ?? 0,
    linear_lambda: raw.linear_lambda ?? 0,
    feature_fraction: raw.feature_fraction ?? 0.9,
    feature_fraction_bynode: raw.feature_fraction_bynode ?? 1.0,
    bagging_fraction: raw.bagging_fraction ?? 0.9,
    bagging_freq: raw.bagging_freq ?? 1,
    extra_trees: raw.extra_trees ?? false,
    monotone_constraints: constraints,
    seed: raw.seed ?? 42,
    feature_fraction_seed: raw.feature_fraction_seed ?? 42,
    bagging_seed: raw.bagging_seed ?? 42,
    data_random_seed: raw.data_random_seed ?? 42,
    extra_seed: raw.extra_seed ?? 42,
    deterministic: raw.deterministic ?? true,
  };
}

function modelProjectPayload(form, model, columns) {
  const payload = formObject(form);
  payload.name = String(payload.name || "").trim();
  if (model?.model_kind === "ai_pac_dual_task") {
    const taskKeys = ["num_leaves", "max_depth", "min_data_in_leaf", "min_sum_hessian_in_leaf",
      "learning_rate", "feature_fraction", "bagging_fraction", "bagging_freq",
      "lambda_l1", "lambda_l2", "num_boost_round", "early_stopping_rounds"];
    const makeTask = (prefix) => Object.fromEntries(taskKeys.map((k) => [k, Number(payload[`${prefix}_${k}`])]));
    const hrtVal = payload.tp_hrt_minutes;
    const intervalVal = payload.sample_interval_minutes;
    payload.training_config = {
      task1: makeTask("task1"),
      task2: makeTask("task2"),
      split: { train_ratio: Number(payload.train_ratio), val_ratio: Number(payload.val_ratio) },
      seed: Number(payload.seed),
      tp_hrt_minutes: hrtVal && hrtVal !== "" ? Number(hrtVal) : null,
      sample_interval_minutes: intervalVal && intervalVal !== "" ? Number(intervalVal) : null,
    };
    taskKeys.forEach((k) => { delete payload[`task1_${k}`]; delete payload[`task2_${k}`]; });
    ["train_ratio", "val_ratio", "seed", "tp_hrt_minutes", "sample_interval_minutes"].forEach((k) => { delete payload[k]; });
    return payload;
  }
  const featureColumns = [...form.querySelectorAll("[data-model-feature-column]:checked")].map((node) => node.dataset.modelFeatureColumn);
  if (!featureColumns.length) return null;
  const monotoneConstraints = {};
  form.querySelectorAll("[data-model-monotone]").forEach((node) => {
    monotoneConstraints[node.dataset.modelMonotone] = Number(node.value);
  });
  const metricValues = [...form.querySelectorAll('input[name="metric"]:checked')].map((node) => node.value);
  payload.training_config = {
    target_column: modelTrainingTargetKey(model),
    feature_columns: featureColumns,
    valid_ratio: Number(payload.valid_ratio),
    split_method: payload.split_method,
    objective: payload.objective,
    metric: metricValues.length ? metricValues : ["rmse"],
    boosting_type: payload.boosting_type,
    learning_rate: Number(payload.learning_rate),
    num_boost_round: Number(payload.num_boost_round),
    early_stopping_rounds: Number(payload.early_stopping_rounds),
    num_leaves: Number(payload.num_leaves),
    max_depth: Number(payload.max_depth),
    min_data_in_leaf: Number(payload.min_data_in_leaf),
    min_sum_hessian_in_leaf: Number(payload.min_sum_hessian_in_leaf),
    max_delta_step: Number(payload.max_delta_step),
    max_bin: Number(payload.max_bin),
    min_data_in_bin: Number(payload.min_data_in_bin),
    bin_construct_sample_cnt: Number(payload.bin_construct_sample_cnt),
    lambda_l1: Number(payload.lambda_l1),
    lambda_l2: Number(payload.lambda_l2),
    min_gain_to_split: Number(payload.min_gain_to_split),
    path_smooth: Number(payload.path_smooth),
    linear_lambda: Number(payload.linear_lambda),
    feature_fraction: Number(payload.feature_fraction),
    feature_fraction_bynode: Number(payload.feature_fraction_bynode),
    bagging_fraction: Number(payload.bagging_fraction),
    bagging_freq: Number(payload.bagging_freq),
    extra_trees: payload.extra_trees === "true",
    monotone_constraints: monotoneConstraints,
    seed: Number(payload.seed),
    feature_fraction_seed: Number(payload.feature_fraction_seed),
    bagging_seed: Number(payload.bagging_seed),
    data_random_seed: Number(payload.data_random_seed),
    extra_seed: Number(payload.extra_seed),
    deterministic: payload.deterministic === "true",
  };
  [
    "target_column", "feature_columns", "valid_ratio", "split_method",
    "objective", "metric", "boosting_type", "learning_rate", "num_boost_round", "early_stopping_rounds",
    "num_leaves", "max_depth", "min_data_in_leaf", "min_sum_hessian_in_leaf", "max_delta_step",
    "max_bin", "min_data_in_bin", "bin_construct_sample_cnt",
    "lambda_l1", "lambda_l2", "min_gain_to_split", "path_smooth", "linear_lambda",
    "feature_fraction", "feature_fraction_bynode", "bagging_fraction", "bagging_freq", "extra_trees",
    "monotone_constraints",
    "seed", "feature_fraction_seed", "bagging_seed", "data_random_seed", "extra_seed", "deterministic",
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
  const workspace = document.querySelector(".model-workspace-body");
  if (workspace) initModelHelpTooltips(workspace);
  document.querySelectorAll("[data-model-group] .model-param-group-header").forEach((header) => {
    header.addEventListener("click", () => {
      header.closest("[data-model-group]").classList.toggle("expanded");
    });
  });
  document.getElementById("modelConfigForm")?.addEventListener("submit", (event) => saveModelProject(event, model, detail.columns));
  document.getElementById("deleteModelBtn")?.addEventListener("click", () => deleteModelProject(model));
  document.getElementById("refreshModelSamplesBtn")?.addEventListener("click", async () => { await renderPage(); });
  document.getElementById("exportModelSamplesBtn")?.addEventListener("click", () => { window.location.href = `/api/models/${model.id}/samples.csv`; });
  document.getElementById("exportModelFeaturesBtn")?.addEventListener("click", () => { window.location.href = `/api/models/${model.id}/features.csv`; });
  document.getElementById("modelCsvInput")?.addEventListener("change", (event) => importModelSamples(model.id, event));
  document.getElementById("trainModelBtn")?.addEventListener("click", () => trainModelProject(model.id));
  document.getElementById("downloadModelArtifactBtn")?.addEventListener("click", () => { window.location.href = `/api/models/${model.id}/artifact`; });
  document.getElementById("clearAllModelSamplesBtn")?.addEventListener("click", () => clearAllModelSamples(model.id, model.sample_count));
}

async function createModelProject(event) {
  event.preventDefault();
  const payload = formObject(event.currentTarget);
  payload.name = String(payload.name || "").trim();
  const validKinds = ["tp_out_response", "pac_flow_predict", "ai_pac_dual_task"];
  if (!validKinds.includes(payload.model_kind)) payload.model_kind = "tp_out_response";
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
